"""Tests for the LLM-name → UUID prerequisite resolver in content ingestion.

The content-analysis prompt asks the LLM to emit prerequisites as concept
names (per ``prompts/content_analysis.md``). The ingestion worker has to
turn those names into ``Concept.prerequisites`` UUIDs so that the knowledge
graph endpoint can render edges. These tests pin the resolver's behaviour:

- happy path: names from the same analysis resolve to ids
- aliases also resolve (LLM occasionally refers by alias)
- unknown names are dropped silently
- self-references are skipped
- two-node cycles (A → B + B → A) are prevented
- re-running with new prereqs unions with the existing list
"""

from sqlalchemy import select

from app.db.models.concept import Concept
from app.services.content_analyzer import ExtractedConcept
from app.worker.tasks.content_ingestion import _resolve_concept_prerequisites


async def _seed_concept(db_session, name: str, aliases: list[str] | None = None) -> Concept:
    concept = Concept(
        name=name,
        description=f"description for {name}",
        category="algorithms",
        aliases=aliases or [],
        prerequisites=[],
    )
    db_session.add(concept)
    await db_session.flush()
    return concept


async def test_resolves_names_to_uuids(db_session):
    a = await _seed_concept(db_session, "binary_search")
    b = await _seed_concept(db_session, "sorted_array")
    c = await _seed_concept(db_session, "loop_invariant")

    ext_concepts = [
        ExtractedConcept(
            name="binary_search",
            description="An O(log n) algorithm.",
            prerequisites=["sorted_array", "loop_invariant"],
            category="algorithms",
        ),
        ExtractedConcept(name="sorted_array", description="...", prerequisites=[]),
        ExtractedConcept(name="loop_invariant", description="...", prerequisites=[]),
    ]
    concept_ids = [a.id, b.id, c.id]

    updated = await _resolve_concept_prerequisites(db_session, ext_concepts, concept_ids)

    assert updated == 1

    refreshed = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    assert set(map(str, refreshed.prerequisites)) == {str(b.id), str(c.id)}


async def test_aliases_resolve_to_canonical_concept(db_session):
    # The LLM sometimes refers to a prereq by its alias rather than the
    # canonical snake_case name (e.g. 中文 source mentions 二分查找).
    a = await _seed_concept(db_session, "quicksort", aliases=[])
    b = await _seed_concept(db_session, "binary_search", aliases=["二分查找"])

    ext_concepts = [
        ExtractedConcept(
            name="quicksort",
            description="...",
            prerequisites=["二分查找"],  # alias
        ),
        ExtractedConcept(name="binary_search", aliases=["二分查找"], prerequisites=[]),
    ]
    concept_ids = [a.id, b.id]

    await _resolve_concept_prerequisites(db_session, ext_concepts, concept_ids)

    refreshed = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    assert [str(p) for p in refreshed.prerequisites] == [str(b.id)]


async def test_unknown_prerequisite_names_are_dropped(db_session):
    a = await _seed_concept(db_session, "alpha")
    b = await _seed_concept(db_session, "beta")

    ext_concepts = [
        ExtractedConcept(
            name="alpha",
            description="...",
            prerequisites=["beta", "gamma_not_in_analysis"],
        ),
        ExtractedConcept(name="beta", description="...", prerequisites=[]),
    ]
    concept_ids = [a.id, b.id]

    await _resolve_concept_prerequisites(db_session, ext_concepts, concept_ids)

    refreshed = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    # Only the known name survived; the unknown one is silently dropped to
    # keep the graph free of dangling references.
    assert [str(p) for p in refreshed.prerequisites] == [str(b.id)]


async def test_self_reference_is_skipped(db_session):
    a = await _seed_concept(db_session, "fixed_point")

    ext_concepts = [
        ExtractedConcept(
            name="fixed_point",
            description="...",
            prerequisites=["fixed_point"],  # LLM hallucinates a self-loop
        ),
    ]
    await _resolve_concept_prerequisites(db_session, ext_concepts, [a.id])

    refreshed = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    assert refreshed.prerequisites == []


async def test_two_node_cycle_is_prevented(db_session):
    """If A's existing prereqs include B, we refuse to add A as B's prereq."""
    a = await _seed_concept(db_session, "node_a")
    b = await _seed_concept(db_session, "node_b")

    # Establish A -> B first.
    await _resolve_concept_prerequisites(
        db_session,
        [
            ExtractedConcept(name="node_a", description="...", prerequisites=["node_b"]),
            ExtractedConcept(name="node_b", description="...", prerequisites=[]),
        ],
        [a.id, b.id],
    )

    # Now a follow-up analysis claims B -> A. The resolver must refuse it.
    await _resolve_concept_prerequisites(
        db_session,
        [
            ExtractedConcept(name="node_a", description="...", prerequisites=[]),
            ExtractedConcept(name="node_b", description="...", prerequisites=["node_a"]),
        ],
        [a.id, b.id],
    )

    refreshed_a = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    refreshed_b = (
        await db_session.execute(select(Concept).where(Concept.id == b.id))
    ).scalar_one()
    assert [str(p) for p in refreshed_a.prerequisites] == [str(b.id)]
    assert refreshed_b.prerequisites == []


async def test_union_merge_with_existing_prereqs(db_session):
    a = await _seed_concept(db_session, "child")
    p1 = await _seed_concept(db_session, "parent_one")
    p2 = await _seed_concept(db_session, "parent_two")

    # First source learns child -> [parent_one].
    await _resolve_concept_prerequisites(
        db_session,
        [
            ExtractedConcept(name="child", description="...", prerequisites=["parent_one"]),
            ExtractedConcept(name="parent_one", description="...", prerequisites=[]),
        ],
        [a.id, p1.id],
    )

    # Second source mentions a different parent for the same concept.
    await _resolve_concept_prerequisites(
        db_session,
        [
            ExtractedConcept(name="child", description="...", prerequisites=["parent_two"]),
            ExtractedConcept(name="parent_two", description="...", prerequisites=[]),
        ],
        [a.id, p2.id],
    )

    refreshed = (
        await db_session.execute(select(Concept).where(Concept.id == a.id))
    ).scalar_one()
    # Union: both parents survive across the two ingestions.
    assert set(map(str, refreshed.prerequisites)) == {str(p1.id), str(p2.id)}


async def test_no_op_when_no_prereqs(db_session):
    a = await _seed_concept(db_session, "lone")
    updated = await _resolve_concept_prerequisites(
        db_session,
        [ExtractedConcept(name="lone", description="...", prerequisites=[])],
        [a.id],
    )
    assert updated == 0

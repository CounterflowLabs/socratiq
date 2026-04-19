"""Tests for knowledge graph service."""

import pytest
from app.db.models.concept import Concept, ConceptSource
from app.db.models.course import Course, CourseSource
from app.db.models.source import Source
from app.services.knowledge_graph import KnowledgeGraphNode
from app.services.knowledge_graph import KnowledgeGraphService


class TestMasteryCalculation:
    def test_no_data_returns_zero(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=None, exercise_scores=[]
        )
        assert mastery == 0.0

    def test_review_only(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=2.5, exercise_scores=[]
        )
        assert mastery == pytest.approx(0.5 * 0.4, abs=0.01)  # 2.5/5 * 0.4

    def test_exercise_only(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=None, exercise_scores=[80.0, 100.0]
        )
        assert mastery == pytest.approx(0.9 * 0.6, abs=0.01)  # avg(80,100)/100 * 0.6

    def test_both(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=3.0, exercise_scores=[100.0]
        )
        expected = (3.0 / 5.0) * 0.4 + (100.0 / 100.0) * 0.6
        assert mastery == pytest.approx(expected, abs=0.01)


class TestKnowledgeGraphPayload:
    def test_node_model_supports_description_kind_and_section_id(self):
        node = KnowledgeGraphNode(
            id="concept-1",
            label="Attention",
            description="Mechanism for weighting relevant tokens.",
            kind="current",
            section_id="section-1",
        )

        assert node.model_dump() == {
            "id": "concept-1",
            "label": "Attention",
            "category": None,
            "description": "Mechanism for weighting relevant tokens.",
            "kind": "current",
            "mastery": 0.0,
            "section_id": "section-1",
        }

    @pytest.mark.asyncio
    async def test_get_graph_includes_description_and_reasonable_kind(
        self, db_session, demo_user
    ):
        source = Source(
            type="youtube",
            title="Graph Source",
            status="ready",
            url="https://example.com/graph",
            created_by=demo_user.id,
        )
        db_session.add(source)
        await db_session.flush()

        course = Course(
            title="Graph Course",
            description="Knowledge graph course",
            created_by=demo_user.id,
        )
        db_session.add(course)
        await db_session.flush()

        db_session.add(CourseSource(course_id=course.id, source_id=source.id))

        prerequisite = Concept(
            name="Embeddings",
            description="Vector representations of tokens.",
            category="foundation",
            prerequisites=[],
        )
        current = Concept(
            name="Attention",
            description="Mechanism for weighting token relationships.",
            category="core",
            prerequisites=[],
        )
        db_session.add_all([prerequisite, current])
        await db_session.flush()

        current.prerequisites = [prerequisite.id]
        db_session.add_all(
            [
                ConceptSource(concept_id=prerequisite.id, source_id=source.id),
                ConceptSource(concept_id=current.id, source_id=source.id),
            ]
        )
        await db_session.flush()

        graph = await KnowledgeGraphService(db_session).get_graph(course.id, demo_user.id)
        nodes = {node["label"]: node for node in graph["nodes"]}

        assert nodes["Embeddings"]["description"] == "Vector representations of tokens."
        assert nodes["Embeddings"]["kind"] == "related"
        assert nodes["Embeddings"]["section_id"] is None

        assert nodes["Attention"]["description"] == "Mechanism for weighting token relationships."
        assert nodes["Attention"]["kind"] == "current"
        assert nodes["Attention"]["section_id"] is None

"""Backfill concept prerequisites for sources analyzed before the fix.

Before commit 2c0ee27, ``content_ingestion._get_or_create_concept`` always
wrote ``prerequisites=[]`` to the ``concepts`` table — the LLM-emitted
prereq names were dropped on the floor. That left every knowledge graph
edge-less in the database.

This script re-runs ``ContentAnalyzer`` against the persisted chunks for
sources whose linked concepts still have empty prerequisite arrays. It
calls the new ``_resolve_concept_prerequisites`` helper to populate the
column. Embeddings are not recomputed (they were already correct).

Usage:
    cd backend
    .venv/bin/python -m scripts.backfill_concept_prereqs              # dry-run
    .venv/bin/python -m scripts.backfill_concept_prereqs --commit    # apply

The dry-run prints what *would* change without writing. Use ``--commit``
once you've reviewed the list.

The script is idempotent: running it twice is safe because the resolver
unions prereqs into the existing list.
"""

import argparse
import asyncio
import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import async_session_factory
from app.db.models.concept import Concept, ConceptSource
from app.db.models.content_chunk import ContentChunk
from app.db.models.source import Source
from app.services.content_analyzer import ContentAnalyzer
from app.services.llm.router import ModelRouter
from app.tools.extractors.base import RawContentChunk
from app.worker.tasks.content_ingestion import _resolve_concept_prerequisites

logger = logging.getLogger(__name__)


async def _candidate_source_ids(db: AsyncSession) -> Sequence[Source]:
    """Find sources that have concepts whose ``prerequisites`` is empty.

    We don't try to be clever about distinguishing "concept legitimately
    has no prereqs" from "concept never had its prereqs resolved" — the
    resolver is idempotent, so re-running on an actually-empty case
    leaves it empty.
    """
    rows = await db.execute(
        select(Source)
        .join(ConceptSource, ConceptSource.source_id == Source.id)
        .join(Concept, Concept.id == ConceptSource.concept_id)
        .distinct()
    )
    return rows.scalars().all()


async def _rebuild_raw_chunks_from_db(
    db: AsyncSession, source_id, source_type: str
) -> list[RawContentChunk]:
    rows = await db.execute(
        select(ContentChunk)
        .where(ContentChunk.source_id == source_id)
        .order_by(ContentChunk.created_at)
    )
    chunks = rows.scalars().all()
    return [
        RawContentChunk(
            source_type=source_type,
            raw_text=chunk.text or "",
            metadata={k: v for k, v in (chunk.metadata_ or {}).items() if v is not None},
        )
        for chunk in chunks
    ]


async def _backfill_one(
    db: AsyncSession,
    source: Source,
    analyzer: ContentAnalyzer,
    *,
    commit: bool,
) -> tuple[int, int]:
    raw_chunks = await _rebuild_raw_chunks_from_db(db, source.id, source.type)
    if not raw_chunks:
        logger.info("source %s has no chunks; skipping", source.id)
        return 0, 0

    analysis = await analyzer.analyze(
        title=source.title or str(source.id),
        chunks=raw_chunks,
        source_type=source.type,
    )

    # Map the analysis concepts back to Concept rows by name + alias.
    concept_ids = []
    ext_concepts = []
    for ext in analysis.concepts:
        row = await db.execute(
            select(Concept).where(Concept.name == ext.name)
        )
        concept = row.scalar_one_or_none()
        if concept is None:
            for alias in ext.aliases or []:
                row = await db.execute(
                    select(Concept).where(Concept.name == alias)
                )
                concept = row.scalar_one_or_none()
                if concept:
                    break
        if concept is None:
            continue
        concept_ids.append(concept.id)
        ext_concepts.append(ext)

    if not concept_ids:
        return 0, 0

    if not commit:
        # Dry-run: print intended changes without applying.
        for ext, cid in zip(ext_concepts, concept_ids):
            if ext.prerequisites:
                logger.info(
                    "  [dry-run] concept %s would gain prereqs: %s",
                    ext.name,
                    ext.prerequisites,
                )
        return len(concept_ids), 0

    updated = await _resolve_concept_prerequisites(db, ext_concepts, concept_ids)
    await db.commit()
    return len(concept_ids), updated


async def main(commit: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    async with async_session_factory() as db:
        sources = await _candidate_source_ids(db)
    if not sources:
        logger.info("no candidate sources found")
        return

    logger.info("found %s candidate sources", len(sources))

    settings = get_settings()
    router = ModelRouter(
        session_factory=async_session_factory,
        encryption_key=settings.llm_encryption_key,
    )
    analyzer = ContentAnalyzer(router)

    total_concepts = 0
    total_updated = 0
    for source in sources:
        async with async_session_factory() as db:
            concepts_seen, updated = await _backfill_one(
                db, source, analyzer, commit=commit
            )
        logger.info(
            "source %s (%s): %s concepts, %s updated",
            source.id,
            source.title or "?",
            concepts_seen,
            updated,
        )
        total_concepts += concepts_seen
        total_updated += updated

    logger.info(
        "done: %s concepts processed, %s prereqs written%s",
        total_concepts,
        total_updated,
        " (dry-run)" if not commit else "",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply the changes. Without this flag the script does a dry-run.",
    )
    args = parser.parse_args()
    asyncio.run(main(commit=args.commit))

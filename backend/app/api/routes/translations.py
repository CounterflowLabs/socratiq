"""API routes for subtitle translation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Section
from app.db.models.translation import Translation
from app.db.models.user import User
from app.services.llm.router import ModelRouter, TaskType
from app.services.translation import TranslationService

router = APIRouter(prefix="/api/v1/sections", tags=["translations"])


@router.get("/{section_id}/translate/estimate")
async def estimate_translation(
    section_id: uuid.UUID,
    target: str = "zh",
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    user: Annotated[User, Depends(get_local_user)] = ...,
) -> dict:
    """Estimate translation cost for a section.

    Returns token and cost estimates, accounting for already-cached chunks.
    """
    section = await db.get(Section, section_id)
    if not section:
        raise HTTPException(404, "Section not found")

    # Fetch chunks belonging to this section's source (via source_id or section_id)
    if section.source_id:
        chunks_q = (
            select(ContentChunk)
            .where(
                (ContentChunk.section_id == section_id)
                | (ContentChunk.source_id == section.source_id)
            )
            .limit(50)
        )
    else:
        chunks_q = (
            select(ContentChunk)
            .where(ContentChunk.section_id == section_id)
            .limit(50)
        )

    result = await db.execute(chunks_q)
    chunks = result.scalars().all()

    texts = [c.text for c in chunks if c.text]
    service = TranslationService(None)  # type: ignore[arg-type]
    est_tokens = service.estimate_tokens(texts, target)

    # Count cached translations
    cached_count = 0
    for chunk in chunks:
        cached_result = await db.execute(
            select(Translation).where(
                Translation.chunk_id == chunk.id,
                Translation.target_lang == target,
            )
        )
        if cached_result.scalar_one_or_none():
            cached_count += 1

    chunks_total = len(chunks)
    chunks_to_translate = chunks_total - cached_count

    return {
        "chunks_total": chunks_total,
        "chunks_cached": cached_count,
        "chunks_to_translate": chunks_to_translate,
        "estimated_tokens": est_tokens,
        "estimated_cost_usd": round(est_tokens * 0.000003, 4),
    }


@router.post("/{section_id}/translate")
async def translate_section(
    section_id: uuid.UUID,
    target: str = "zh",
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    user: Annotated[User, Depends(get_local_user)] = ...,
    model_router: Annotated[ModelRouter, Depends(get_model_router)] = ...,
) -> dict:
    """Translate all chunks belonging to a section.

    Cached translations are returned immediately; uncached chunks are sent to
    the LLM and the results are stored in the *translations* table.
    """
    section = await db.get(Section, section_id)
    if not section:
        raise HTTPException(404, "Section not found")

    chunks_q = (
        select(ContentChunk)
        .where(ContentChunk.section_id == section_id)
        .limit(50)
    )
    result = await db.execute(chunks_q)
    chunks = result.scalars().all()

    # Fall back to source-level chunks when the section has no direct chunk links
    if not chunks and section.source_id:
        result = await db.execute(
            select(ContentChunk)
            .where(ContentChunk.source_id == section.source_id)
            .limit(50)
        )
        chunks = result.scalars().all()

    chunk_dicts = [{"id": c.id, "text": c.text} for c in chunks if c.text]

    provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
    service = TranslationService(provider, db)
    translations = await service.translate_section_chunks(chunk_dicts, target, user.id)

    return {"translations": translations, "total": len(translations)}

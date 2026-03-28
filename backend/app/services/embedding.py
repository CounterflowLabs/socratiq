"""Embedding computation service using the LLM abstraction layer."""

import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.concept import Concept as ConceptModel
from app.services.llm.base import LLMProvider
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Compute and store vector embeddings for content chunks and concepts."""

    BATCH_SIZE = 5  # Max texts per embedding API call (conservative for local models)

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    MAX_CHARS_PER_TEXT = 2000  # Conservative limit: ~2000 chars ≈ 4000-6000 tokens for CJK text

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of texts.

        Returns embeddings in the same order as input.
        """
        if not texts:
            return []

        # Truncate long texts to avoid exceeding embedding model context
        texts = [t[:self.MAX_CHARS_PER_TEXT] for t in texts]

        provider = await self._router.get_provider(TaskType.EMBEDDING)

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_embeddings = await self._embed_batch(provider, batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(
        self, provider: LLMProvider, texts: list[str]
    ) -> list[list[float]]:
        """Embed a single batch of texts using the provider's embed method."""
        try:
            return await provider.embed(texts)
        except NotImplementedError:
            logger.warning(
                "Provider %s does not support embeddings. "
                "Configure an OpenAI-compatible embedding model.",
                type(provider).__name__,
            )
            return [[0.0] * 1536 for _ in texts]

    async def embed_and_store_chunks(
        self, db: AsyncSession, chunk_ids: list[UUID], texts: list[str],
    ) -> None:
        """Compute embeddings and update content_chunks in the database."""
        if not chunk_ids:
            return

        embeddings = await self.embed_texts(texts)

        for chunk_id, embedding in zip(chunk_ids, embeddings):
            await db.execute(
                update(ContentChunkModel)
                .where(ContentChunkModel.id == chunk_id)
                .values(embedding=embedding)
            )

        await db.flush()
        logger.info(f"Embedded and stored {len(chunk_ids)} content chunks")

    async def embed_and_store_concepts(
        self, db: AsyncSession, concept_ids: list[UUID], texts: list[str],
    ) -> None:
        """Compute embeddings and update concepts in the database."""
        if not concept_ids:
            return

        embeddings = await self.embed_texts(texts)

        for concept_id, embedding in zip(concept_ids, embeddings):
            await db.execute(
                update(ConceptModel)
                .where(ConceptModel.id == concept_id)
                .values(embedding=embedding)
            )

        await db.flush()
        logger.info(f"Embedded and stored {len(concept_ids)} concepts")

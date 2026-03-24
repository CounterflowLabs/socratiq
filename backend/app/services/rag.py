"""RAG (Retrieval-Augmented Generation) service for knowledge search."""

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


class RAGService:
    """Vector similarity search over content chunks using pgvector."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def search(
        self,
        db: AsyncSession,
        query: str,
        course_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for content chunks similar to the query.

        Args:
            db: Database session.
            query: Natural language search query.
            course_id: Optional filter to a specific course.
            top_k: Number of results to return.

        Returns:
            List of dicts: [{"text": str, "metadata": dict, "score": float}]
        """
        # 1. Compute query embedding
        query_embedding = await self._embed_query(query)

        # 2. Build pgvector cosine similarity query
        # Using raw SQL for pgvector <=> operator
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        if course_id:
            # Filter by course via section → course relationship
            sql = text("""
                SELECT cc.id, cc.text, cc.metadata_, 
                       cc.embedding <=> :query_vec AS distance
                FROM content_chunks cc
                JOIN sections s ON cc.section_id = s.id
                WHERE s.course_id = :course_id
                  AND cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :query_vec
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {"query_vec": embedding_str, "course_id": str(course_id), "top_k": top_k},
            )
        else:
            sql = text("""
                SELECT cc.id, cc.text, cc.metadata_,
                       cc.embedding <=> :query_vec AS distance
                FROM content_chunks cc
                WHERE cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :query_vec
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {"query_vec": embedding_str, "top_k": top_k},
            )

        rows = result.all()

        return [
            {
                "text": row.text,
                "metadata": row.metadata_ if row.metadata_ else {},
                "score": 1 - row.distance,  # Convert distance to similarity
            }
            for row in rows
        ]

    async def _embed_query(self, query: str) -> list[float]:
        """Compute embedding for a search query."""
        from app.services.embedding import EmbeddingService

        embedding_service = EmbeddingService(self._router)
        embeddings = await embedding_service.embed_texts([query])
        return embeddings[0] if embeddings else [0.0] * 1536

"""RAG knowledge retrieval tool for the MentorAgent."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.services.rag import RAGService


class KnowledgeSearchTool(AgentTool):
    """Search the knowledge base for relevant content chunks.

    The MentorAgent uses this tool to retrieve context from ingested
    content (Bilibili transcripts, PDFs) when answering student questions.
    """

    def __init__(self, db: AsyncSession, rag_service: RAGService,
                 course_id: uuid.UUID | None = None) -> None:
        self._db = db
        self._rag = rag_service
        self._course_id = course_id

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the course knowledge base for relevant content. "
            "Use this when the student asks about a concept, needs an explanation, "
            "or when you need to reference specific content from the learning materials. "
            "Returns relevant text passages with source references (timestamps, page numbers)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Use natural language describing the concept or topic to search for.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, top_k: int = 5) -> str:
        top_k = min(top_k, 10)
        results = await self._rag.search(
            db=self._db,
            query=query,
            course_id=self._course_id,
            top_k=top_k,
        )
        if not results:
            return "No relevant content found in the knowledge base."

        # Format results for the LLM
        formatted = []
        citations = []
        for i, r in enumerate(results, 1):
            source_info = ""
            meta = r.get("metadata", {})
            if "start_time" in meta:
                source_info = f" [Video timestamp: {meta['start_time']}s - {meta.get('end_time', '?')}s]"
            elif "page_start" in meta:
                source_info = f" [PDF page: {meta['page_start']}]"
            formatted.append(f"[{i}]{source_info}\n{r['text']}")

            citation = {
                "chunk_id": r.get("chunk_id"),
                "source_id": r.get("source_id"),
                "source_title": r.get("source_title"),
                "source_type": r.get("source_type"),
                "source_url": r.get("source_url"),
                "text": r["text"][:200],
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
                "page_start": meta.get("page_start"),
            }
            citations.append(citation)

        text_output = "\n\n---\n\n".join(formatted)
        return f"{text_output}\n\n<!-- CITATIONS:{json.dumps(citations, ensure_ascii=False)}-->"

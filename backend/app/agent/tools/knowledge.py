"""RAG knowledge retrieval tool for the MentorAgent."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool, tool_error
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
            "Search the course knowledge base (ingested transcripts, PDFs, articles) "
            "for passages relevant to a query. Returns text passages with source "
            "references (video timestamps, PDF pages).\n\n"
            "## Use when\n"
            "- Student references a course-internal entity (\"section 3\", \"the lab on X\", \"the video about Y\")\n"
            "- Student asks \"what does the source/video/PDF say about Z?\"\n"
            "- About to make a factual claim about specific course content not already in this turn's context\n"
            "- Student's question is clearly about THIS course's framing of a topic, not the topic in general\n\n"
            "## Don't use when\n"
            "- General domain knowledge question (\"what is binary search?\", \"how does gradient descent work?\") — answer from your own knowledge\n"
            "- The fact you need is already grounded in a tool result earlier in this turn — don't re-fetch\n"
            "- The student is asking a meta-question about Socratiq itself, their progress, or their profile\n"
            "- You're about to ask a Socratic leading question — fetch only if the question itself needs course content\n\n"
            "## Example of misuse\n"
            "Student: \"What is recursion?\"\n"
            "Mentor: [calls search_knowledge with query=\"recursion\"]\n"
            "→ wrong; recursion is general CS knowledge. Answer directly, then if the student wants to see how the course treats it, then search."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language search query. Phrase it as the concept or "
                        "topic, not as a question. Good: \"attention mechanism in "
                        "transformers\". Avoid: \"what is attention?\" — strip the "
                        "interrogative wrapper."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of passages to return. Default 5, max 10. Use 3 for narrow lookups, 8-10 for broad survey.",
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
            return tool_error(
                message=f"No passages found for query: {query!r}",
                reason="no_results",
                suggestion=(
                    "The course material may not cover this topic, or the query "
                    "phrasing may not match the source language. Try a broader or "
                    "differently-phrased query, or answer from your own knowledge "
                    "and tell the student this isn't in the course materials."
                ),
            )

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

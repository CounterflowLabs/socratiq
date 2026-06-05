"""Tests for citation data in RAG results and KnowledgeSearchTool output."""

import json
import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.hooks import CitationHook
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.models.citation import Citation
from app.services.rag import RAGService


# ---------------------------------------------------------------------------
# RAG service: source metadata in results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_search_returns_source_fields():
    """RAG search results include chunk_id, source_id, and source metadata."""
    Row = namedtuple(
        "Row",
        ["id", "text", "metadata_", "source_id", "source_title", "source_type", "source_url", "distance"],
    )
    fake_row = Row(
        id=uuid.uuid4(),
        text="Some chunk text",
        metadata_={"start_time": 10.0, "end_time": 20.0},
        source_id=uuid.uuid4(),
        source_title="Intro to Python",
        source_type="bilibili",
        source_url="https://bilibili.com/video/123",
        distance=0.2,
    )

    mock_router = MagicMock()
    rag = RAGService(model_router=mock_router)

    # Mock _embed_query to avoid real embedding call
    rag._embed_query = AsyncMock(return_value=[0.0] * 1536)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    results = await rag.search(db=mock_db, query="python basics", top_k=3)

    assert len(results) == 1
    r = results[0]
    assert r["chunk_id"] == str(fake_row.id)
    assert r["source_id"] == str(fake_row.source_id)
    assert r["source_title"] == "Intro to Python"
    assert r["source_type"] == "bilibili"
    assert r["source_url"] == "https://bilibili.com/video/123"
    assert r["text"] == "Some chunk text"
    assert r["score"] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_rag_search_handles_null_source():
    """RAG search gracefully handles rows with no source_id."""
    Row = namedtuple(
        "Row",
        ["id", "text", "metadata_", "source_id", "source_title", "source_type", "source_url", "distance"],
    )
    fake_row = Row(
        id=uuid.uuid4(),
        text="Orphan chunk",
        metadata_={},
        source_id=None,
        source_title=None,
        source_type=None,
        source_url=None,
        distance=0.5,
    )

    mock_router = MagicMock()
    rag = RAGService(model_router=mock_router)
    rag._embed_query = AsyncMock(return_value=[0.0] * 1536)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    results = await rag.search(db=mock_db, query="test")
    r = results[0]
    assert r["source_id"] is None
    assert r["chunk_id"] == str(fake_row.id)


# ---------------------------------------------------------------------------
# KnowledgeSearchTool: citation JSON block in output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_knowledge_tool_emits_citations_block():
    """KnowledgeSearchTool output contains a hidden CITATIONS JSON block."""
    chunk_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())

    mock_rag = AsyncMock(spec=RAGService)
    mock_rag.search.return_value = [
        {
            "chunk_id": chunk_id,
            "source_id": source_id,
            "source_title": "Intro Video",
            "source_type": "youtube",
            "source_url": "https://youtube.com/watch?v=abc",
            "text": "Python is a programming language.",
            "metadata": {"start_time": 5.0, "end_time": 15.0},
            "score": 0.9,
        }
    ]

    mock_db = AsyncMock()
    tool = KnowledgeSearchTool(db=mock_db, rag_service=mock_rag, course_id=uuid.uuid4())

    output = await tool.execute(query="what is python")

    assert "<!-- CITATIONS:" in output
    assert "-->" in output

    # Extract and parse citations JSON
    marker = "<!-- CITATIONS:"
    start = output.index(marker) + len(marker)
    end = output.index("-->", start)
    citations = json.loads(output[start:end])

    assert len(citations) == 1
    c = citations[0]
    assert c["chunk_id"] == chunk_id
    assert c["source_id"] == source_id
    assert c["source_title"] == "Intro Video"
    assert c["source_type"] == "youtube"
    assert c["source_url"] == "https://youtube.com/watch?v=abc"
    assert c["start_time"] == 5.0
    assert c["end_time"] == 15.0
    assert len(c["text"]) <= 200


@pytest.mark.asyncio
async def test_knowledge_tool_no_results():
    """KnowledgeSearchTool returns a structured tool_error payload when empty.

    The new shape carries `error`, `reason`, and `suggestion` so the agent
    loop can plan a recovery instead of just stuffing the empty result back
    into the model context.
    """
    import json

    mock_rag = AsyncMock(spec=RAGService)
    mock_rag.search.return_value = []

    mock_db = AsyncMock()
    tool = KnowledgeSearchTool(db=mock_db, rag_service=mock_rag)

    output = await tool.execute(query="something obscure")
    payload = json.loads(output)
    assert payload["reason"] == "no_results"
    assert "something obscure" in payload["error"]
    assert payload["suggestion"]  # non-empty
    assert "CITATIONS" not in output


@pytest.mark.asyncio
async def test_knowledge_tool_truncates_citation_text():
    """Citation text is truncated to 200 characters."""
    long_text = "A" * 500
    mock_rag = AsyncMock(spec=RAGService)
    mock_rag.search.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "source_id": None,
            "source_title": None,
            "source_type": None,
            "source_url": None,
            "text": long_text,
            "metadata": {},
            "score": 0.7,
        }
    ]

    mock_db = AsyncMock()
    tool = KnowledgeSearchTool(db=mock_db, rag_service=mock_rag)

    output = await tool.execute(query="test")

    marker = "<!-- CITATIONS:"
    start = output.index(marker) + len(marker)
    end = output.index("-->", start)
    citations = json.loads(output[start:end])

    assert len(citations[0]["text"]) == 200


# ---------------------------------------------------------------------------
# Citation Pydantic model
# ---------------------------------------------------------------------------

def test_citation_model_from_dict():
    """Citation schema validates and parses a citation dict."""
    data = {
        "chunk_id": str(uuid.uuid4()),
        "source_id": str(uuid.uuid4()),
        "source_title": "Test Source",
        "source_type": "youtube",
        "source_url": "https://example.com",
        "text": "Some text",
        "start_time": 10.5,
        "end_time": 20.0,
        "page_start": None,
    }
    citation = Citation(**data)
    assert citation.chunk_id == data["chunk_id"]
    assert citation.start_time == 10.5
    assert citation.page_start is None


# ---------------------------------------------------------------------------
# CitationHook.extract: strip markers & collect citations
# ---------------------------------------------------------------------------

class TestCitationHookExtract:
    """CitationHook.extract parses and strips the CITATIONS markers."""

    def test_extracts_single_citation_block(self):
        citations = [{"chunk_id": "abc", "title": "Intro", "score": 0.92}]
        raw = f"Some result text<!-- CITATIONS:{json.dumps(citations)}-->"

        cleaned, parsed = CitationHook.extract(raw)

        assert cleaned == "Some result text"
        assert parsed == citations

    def test_extracts_multiple_citation_blocks(self):
        c1 = [{"chunk_id": "a"}]
        c2 = [{"chunk_id": "b"}, {"chunk_id": "c"}]
        raw = f"Part1<!-- CITATIONS:{json.dumps(c1)}-->Part2<!-- CITATIONS:{json.dumps(c2)}-->"

        cleaned, parsed = CitationHook.extract(raw)

        assert cleaned == "Part1Part2"
        assert len(parsed) == 3

    def test_no_citations_returns_unchanged(self):
        raw = "Just a plain tool result with no markers."

        cleaned, parsed = CitationHook.extract(raw)

        assert cleaned == raw
        assert parsed == []

    def test_malformed_json_is_skipped(self):
        cleaned, parsed = CitationHook.extract("Result<!-- CITATIONS:not valid json-->rest")

        assert cleaned == "Resultrest"
        assert parsed == []

    def test_non_list_json_is_skipped(self):
        raw = f'Result<!-- CITATIONS:{json.dumps({"key": "value"})}-->rest'

        cleaned, parsed = CitationHook.extract(raw)

        assert cleaned == "Resultrest"
        assert parsed == []

    def test_multiline_citation_json(self):
        citations = [{"chunk_id": "x", "title": "A long title"}]
        raw = f"Result<!-- CITATIONS:\n{json.dumps(citations, indent=2)}\n-->done"

        cleaned, parsed = CitationHook.extract(raw)

        assert cleaned == "Resultdone"
        assert parsed == citations

    @pytest.mark.asyncio
    async def test_after_tool_call_attaches_citations_and_strips(self):
        from app.agentcore.tools.base import ToolCall, ToolContext, ToolResult

        citations = [{"chunk_id": "abc"}]
        result = ToolResult(content=f"text<!-- CITATIONS:{json.dumps(citations)}-->")
        out = await CitationHook().after_tool_call(
            ToolCall(id="t", name="search", input={}), result, ToolContext()
        )
        assert out.content == "text"
        assert out.citations == citations

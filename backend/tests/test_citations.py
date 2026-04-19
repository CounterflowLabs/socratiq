"""Tests for citation data in RAG results and KnowledgeSearchTool output."""

import json
import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.mentor import MentorAgent
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.models.citation import Citation
from app.services.rag import RAGService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> MentorAgent:
    """Create a MentorAgent with minimal state for unit testing."""
    agent = object.__new__(MentorAgent)
    agent._collected_citations = []
    return agent


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
    """KnowledgeSearchTool returns plain message when no results found."""
    mock_rag = AsyncMock(spec=RAGService)
    mock_rag.search.return_value = []

    mock_db = AsyncMock()
    tool = KnowledgeSearchTool(db=mock_db, rag_service=mock_rag)

    output = await tool.execute(query="something obscure")
    assert "No relevant content found" in output
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
# MentorAgent._extract_citations: strip markers & collect citations
# ---------------------------------------------------------------------------

class TestMentorExtractCitations:
    """Test that MentorAgent._extract_citations parses and strips citation markers."""

    def test_extracts_single_citation_block(self):
        agent = _make_agent()
        citations = [{"chunk_id": "abc", "title": "Intro", "score": 0.92}]
        raw = f"Some result text<!-- CITATIONS:{json.dumps(citations)}-->"

        cleaned = agent._extract_citations(raw)

        assert cleaned == "Some result text"
        assert agent._collected_citations == citations

    def test_extracts_multiple_citation_blocks(self):
        agent = _make_agent()
        c1 = [{"chunk_id": "a"}]
        c2 = [{"chunk_id": "b"}, {"chunk_id": "c"}]
        raw = f"Part1<!-- CITATIONS:{json.dumps(c1)}-->Part2<!-- CITATIONS:{json.dumps(c2)}-->"

        cleaned = agent._extract_citations(raw)

        assert cleaned == "Part1Part2"
        assert len(agent._collected_citations) == 3

    def test_no_citations_returns_unchanged(self):
        agent = _make_agent()
        raw = "Just a plain tool result with no markers."

        cleaned = agent._extract_citations(raw)

        assert cleaned == raw
        assert agent._collected_citations == []

    def test_malformed_json_is_skipped(self):
        agent = _make_agent()
        raw = "Result<!-- CITATIONS:not valid json-->rest"

        cleaned = agent._extract_citations(raw)

        assert cleaned == "Resultrest"
        assert agent._collected_citations == []

    def test_non_list_json_is_skipped(self):
        agent = _make_agent()
        raw = f'Result<!-- CITATIONS:{json.dumps({"key": "value"})}-->rest'

        cleaned = agent._extract_citations(raw)

        assert cleaned == "Resultrest"
        assert agent._collected_citations == []

    def test_citations_accumulate_across_calls(self):
        agent = _make_agent()
        c1 = [{"chunk_id": "first"}]
        c2 = [{"chunk_id": "second"}]

        agent._extract_citations(f"<!-- CITATIONS:{json.dumps(c1)}-->")
        agent._extract_citations(f"<!-- CITATIONS:{json.dumps(c2)}-->")

        assert len(agent._collected_citations) == 2
        assert agent._collected_citations[0]["chunk_id"] == "first"
        assert agent._collected_citations[1]["chunk_id"] == "second"

    def test_multiline_citation_json(self):
        agent = _make_agent()
        citations = [{"chunk_id": "x", "title": "A long title"}]
        raw = f"Result<!-- CITATIONS:\n{json.dumps(citations, indent=2)}\n-->done"

        cleaned = agent._extract_citations(raw)

        assert cleaned == "Resultdone"
        assert agent._collected_citations == citations

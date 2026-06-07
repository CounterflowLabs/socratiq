"""Unit tests for the arXiv reference fetcher (offline, fixture-parsed)."""

import pytest

from app.services.reference_fetcher import (
    ArxivReferenceFetcher,
    MultiSourceReferenceFetcher,
    _parse_arxiv_atom,
    build_reference_fetcher,
)

_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <published>2017-06-12T00:00:00Z</published>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models are based on complex
    recurrent or convolutional neural networks. We propose the Transformer,
    based solely on attention mechanisms.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <author><name>Niki Parmar</name></author>
    <author><name>Jakob Uszkoreit</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1409.0473v7</id>
    <published>2014-09-01T00:00:00Z</published>
    <title>Neural Machine Translation by Jointly Learning to Align and Translate</title>
    <summary>We conjecture that the use of a fixed-length vector is a bottleneck.</summary>
    <author><name>Dzmitry Bahdanau</name></author>
  </entry>
</feed>"""


def test_parse_arxiv_atom_maps_to_research_cards():
    cards = _parse_arxiv_atom(_SAMPLE_ATOM, concepts=["attention", "transformer"])
    assert len(cards) == 2
    c0 = cards[0]
    assert c0.title == "Attention Is All You Need"
    assert c0.url == "http://arxiv.org/abs/1706.03762v5"  # real, citable URL
    assert c0.source_type == "paper"
    assert c0.use_as == "further_reading"
    assert c0.published_at == "2017-06-12"
    assert "Vaswani" in c0.source_title and "et al" in c0.source_title  # 4 authors → et al.
    assert c0.relevance  # abstract snippet, non-empty
    assert c0.concepts == ["attention", "transformer"]
    # Single-author paper formats without "et al.".
    assert cards[1].source_title == "Dzmitry Bahdanau (arXiv)"


def test_parse_handles_garbage():
    assert _parse_arxiv_atom("not xml at all", []) == []
    assert _parse_arxiv_atom("<feed xmlns='http://www.w3.org/2005/Atom'></feed>", []) == []


@pytest.mark.asyncio
async def test_arxiv_fetch_empty_query_skips_network():
    # Empty query must not hit the network.
    assert await ArxivReferenceFetcher().fetch("   ") == []


@pytest.mark.asyncio
async def test_multisource_dedupes_by_url():
    class _Stub:
        def __init__(self, cards):
            self._cards = cards

        async def fetch(self, query, *, concepts=None, max_results=6):
            return self._cards

    cards = _parse_arxiv_atom(_SAMPLE_ATOM, [])
    # Two sources returning overlapping URLs → merged, de-duped.
    multi = MultiSourceReferenceFetcher([_Stub(cards), _Stub(cards)])
    out = await multi.fetch("x")
    urls = [c.url for c in out]
    assert len(urls) == len(set(urls)) == 2


@pytest.mark.asyncio
async def test_multisource_isolates_a_failing_source():
    class _Boom:
        async def fetch(self, query, *, concepts=None, max_results=6):
            raise RuntimeError("provider down")

    class _Ok:
        async def fetch(self, query, *, concepts=None, max_results=6):
            return _parse_arxiv_atom(_SAMPLE_ATOM, [])

    multi = MultiSourceReferenceFetcher([_Boom(), _Ok()])
    out = await multi.fetch("x")
    assert len(out) == 2  # the good source still contributes


def test_build_reference_fetcher_flag():
    assert build_reference_fetcher(enabled=False) is None
    assert build_reference_fetcher(enabled=True) is not None


# --- Semantic Scholar parsing (offline) ------------------------------------

_S2_SAMPLE = {
    "total": 3,
    "data": [
        {"title": "Less cited", "year": 2022, "citationCount": 10,
         "externalIds": {"DOI": "10.1234/abc"}, "authors": [{"name": "Solo"}],
         "abstract": "lower impact", "venue": "ICML"},
        {"title": "Attention Is All You Need", "year": 2017, "citationCount": 100000,
         "externalIds": {"ArXiv": "1706.03762"},
         "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}, {"name": "Parmar"}, {"name": "Uszkoreit"}],
         "abstract": "The Transformer...", "venue": "NeurIPS"},
        {"title": "No locator", "year": 2020, "citationCount": 50,
         "externalIds": {}, "authors": [], "url": None},
    ],
}


def test_parse_semantic_scholar_citation_ranked_and_urls():
    from app.services.reference_fetcher import _parse_semantic_scholar

    cards = _parse_semantic_scholar(_S2_SAMPLE, ["attention"], max_results=6)
    # The no-locator paper (no ArXiv/DOI/url) is dropped; 2 remain.
    titles = [c.title for c in cards]
    assert titles == ["Attention Is All You Need", "Less cited"]  # citation-ranked
    attn = cards[0]
    assert attn.url == "https://arxiv.org/abs/1706.03762"  # arXiv id → real url
    assert "et al." in attn.source_title and "(NeurIPS)" in attn.source_title
    assert attn.concepts == ["attention"]
    assert cards[1].url == "https://doi.org/10.1234/abc"  # DOI → real url


def test_parse_semantic_scholar_handles_garbage():
    from app.services.reference_fetcher import _parse_semantic_scholar

    assert _parse_semantic_scholar({}, [], 5) == []
    assert _parse_semantic_scholar({"data": "nope"}, [], 5) == []


def test_build_reference_fetcher_adds_s2_only_with_key():
    from app.services.reference_fetcher import (
        MultiSourceReferenceFetcher,
        build_reference_fetcher,
    )

    no_key = build_reference_fetcher(enabled=True)
    with_key = build_reference_fetcher(enabled=True, semantic_scholar_api_key="k")
    assert isinstance(no_key, MultiSourceReferenceFetcher)
    assert isinstance(with_key, MultiSourceReferenceFetcher)
    assert len(no_key._fetchers) == 1  # arXiv only
    assert len(with_key._fetchers) == 2  # S2 (first) + arXiv

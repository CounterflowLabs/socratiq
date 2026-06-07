"""Live reference fetching for lesson enrichment.

Turns a section's topic/concepts into a handful of REAL, citable references
(``ResearchCard`` with a real URL), so the lesson's ``further_reading`` block
cites fetched sources instead of the model's (hallucination-prone) memory.

Design:
  - ``ReferenceFetcher`` is a small protocol so sources are pluggable. Today
    only ``ArxivReferenceFetcher`` is wired (free, no API key, reproducible);
    Exa / Tavily / a web search can be added later behind the same protocol and
    composed via ``MultiSourceReferenceFetcher``.
  - Fetching runs at INGESTION (see content_ingestion) and the cards are cached
    on the source, so course generation reuses them: reproducible, and the
    network cost is paid once per source rather than per regeneration.
  - Every failure degrades to ``[]`` — references are an enhancement, never a
    reason to fail ingestion or block a course.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Protocol, runtime_checkable

import httpx

from app.models.research import ResearchCard

logger = logging.getLogger(__name__)

__all__ = [
    "ReferenceFetcher",
    "ArxivReferenceFetcher",
    "SemanticScholarReferenceFetcher",
    "MultiSourceReferenceFetcher",
    "build_reference_fetcher",
    "ReferenceRanker",
]

_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
_S2_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_FIELDS = "title,year,citationCount,url,externalIds,abstract,authors,venue"


@runtime_checkable
class ReferenceFetcher(Protocol):
    async def fetch(
        self, query: str, *, concepts: list[str] = ..., max_results: int = ...
    ) -> list[ResearchCard]:
        """Return real, citable references for ``query`` (best-effort)."""
        ...


class ArxivReferenceFetcher:
    """Fetch references from the arXiv API (Atom feed, stdlib-parsed).

    No API key required. Results are real papers with real abstract URLs, so a
    downstream ``further_reading`` block can cite them with a verified ``url``.
    """

    def __init__(self, *, timeout_s: float = 12.0) -> None:
        self._timeout = timeout_s

    async def fetch(
        self, query: str, *, concepts: list[str] | None = None, max_results: int = 6
    ) -> list[ResearchCard]:
        # Normalize: internal concept labels are snake_case (e.g.
        # "self_attention"), which as a quoted arXiv phrase matches almost
        # nothing. Turn them into space-separated terms so arXiv ANDs them.
        q = (query or "").replace("_", " ").strip()
        if not q:
            return []
        params = {
            "search_query": f"all:{q}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        # arXiv rate-limits rapid successive requests, so one transient failure
        # is common — retry once after a polite delay before giving up.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(_ARXIV_ENDPOINT, params=params)
                    resp.raise_for_status()
                    return _parse_arxiv_atom(resp.text, concepts or [])
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(3.0)
                    continue
                logger.warning("ArxivReferenceFetcher failed for %r: %s", q, exc)
                return []
        return []


class SemanticScholarReferenceFetcher:
    """Fetch references from Semantic Scholar, ranked by citation count.

    This fixes arXiv's recall weakness: S2 indexes the seminal literature and
    exposes ``citationCount``, so sorting candidates by citations surfaces the
    foundational works (and high-impact frontier ones) that arXiv relevance
    search misses. Keyless access is heavily rate-limited (429), so an API key
    is strongly recommended. URLs come from arXiv id / DOI / the S2 page — all
    real, so they survive the verified-url enforcement downstream.
    """

    def __init__(self, *, api_key: str = "", timeout_s: float = 12.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_s

    async def fetch(
        self, query: str, *, concepts: list[str] | None = None, max_results: int = 6
    ) -> list[ResearchCard]:
        q = (query or "").replace("_", " ").strip()
        if not q:
            return []
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        params = {
            "query": q,
            # over-fetch, then keep the most-cited locally
            "limit": max(max_results * 2, 10),
            "fields": _S2_FIELDS,
        }
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(_S2_ENDPOINT, params=params, headers=headers)
                    resp.raise_for_status()
                    return _parse_semantic_scholar(
                        resp.json(), concepts or [], max_results
                    )
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    await asyncio.sleep(3.0)
                    continue
                logger.warning(
                    "SemanticScholarReferenceFetcher failed for %r: %s", q, exc
                )
                return []
        return []


class MultiSourceReferenceFetcher:
    """Fan a query across several fetchers and merge, de-duped by URL.

    Pluggable: pass any list of ``ReferenceFetcher``. Each source's failure is
    isolated (it contributes ``[]``), so one bad provider can't sink the rest.
    """

    def __init__(self, fetchers: list[ReferenceFetcher]) -> None:
        self._fetchers = fetchers

    async def fetch(
        self, query: str, *, concepts: list[str] | None = None, max_results: int = 6
    ) -> list[ResearchCard]:
        if not self._fetchers:
            return []
        results = await asyncio.gather(
            *(
                f.fetch(query, concepts=concepts, max_results=max_results)
                for f in self._fetchers
            ),
            return_exceptions=True,
        )
        merged: list[ResearchCard] = []
        seen: set[str] = set()
        for r in results:
            if isinstance(r, BaseException):
                continue
            for card in r:
                key = (card.url or card.title).strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(card)
        return merged


_RANKER_SYSTEM = """\
你在为一门课筛选「延伸阅读」参考文献。给定课程主题和若干**候选论文**（来自 arXiv \
搜索，含噪声、可能跨领域离题），从中挑出**真正与该主题相关、且对学习者有价值/有权威性**\
的论文（奠基性的经典，或有代表性的前沿），**丢弃离题、低质、或仅表面词面相关的**。

判断标准：这篇论文真的能帮助学这个主题的人加深理解吗？只是标题里有相同词、实则属于\
别的领域（例如把"注意力机制"误配到神经科学/物理论文）的，一律丢弃。**宁缺毋滥**：\
如果候选里没有真正合适的，就返回空列表。

对每篇保留的论文，给出 `kind`（"classic" 经典奠基 / "frontier" 近期前沿）和一句\
{target_language} 的相关性说明（为什么值得读、和本主题什么关系）。

只输出一个 JSON 对象：{"keep": [{"index": <候选序号>, "kind": "classic|frontier", \
"note": "..."}]}。不要 markdown，不要多余文字。最多保留 {keep} 篇。
"""


class ReferenceRanker:
    """LLM precision pass over noisy fetched candidates.

    arXiv search is high-recall / low-precision (it surfaces unrelated recent
    papers). This ranks candidates against the actual course topic, keeps only
    the genuinely relevant + authoritative ones, tags classic/frontier, and
    writes a topic-specific relevance note. On any failure it returns ``[]``
    (no references beats noisy ones), so the lesson falls back to the model's
    own well-known classics.
    """

    def __init__(self, provider, *, target_language: str = "zh-CN") -> None:
        from app.services.llm.runtime import AgentRuntime

        self._provider = provider
        self._runtime = AgentRuntime()
        self._target_language = target_language

    async def rank(
        self, *, topic: str, candidates: list[ResearchCard], keep: int = 6
    ) -> list[ResearchCard]:
        if not candidates:
            return []
        from app.services.llm.base import UnifiedMessage
        from app.services.llm.runtime import LLMError, LLMValidationError, ValidationFailed

        listing = "\n".join(
            f"[{i}] {c.title} ({c.published_at or 'n.d.'}) — {(c.relevance or '')[:200]}"
            for i, c in enumerate(candidates)
        )
        system = _RANKER_SYSTEM.replace("{target_language}", self._target_language).replace(
            "{keep}", str(keep)
        )
        messages = [
            UnifiedMessage(role="system", content=system),
            UnifiedMessage(role="user", content=f"课程主题：{topic}\n\n候选论文：\n{listing}"),
        ]

        def _validate(text: str) -> list[ResearchCard]:
            import json as _json

            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                parsed = _json.loads(cleaned)
            except (ValueError, TypeError) as exc:
                raise ValidationFailed("ranker_json_parse_failed") from exc
            kept_raw = parsed.get("keep") if isinstance(parsed, dict) else None
            if not isinstance(kept_raw, list):
                raise ValidationFailed("ranker_missing_keep")
            out: list[ResearchCard] = []
            for entry in kept_raw:
                if not isinstance(entry, dict):
                    continue
                try:
                    idx = int(entry.get("index"))
                except (TypeError, ValueError):
                    continue
                if not (0 <= idx < len(candidates)):
                    continue
                card = candidates[idx]
                note = entry.get("note")
                if isinstance(note, str) and note.strip():
                    card = card.model_copy(update={"relevance": note.strip()})
                out.append(card)
            return out[:keep]

        try:
            result = await self._runtime.call(
                messages,
                primary=self._provider,
                max_tokens=1200,
                temperature=0.0,
                phase="reference_ranker.rank",
                validator=_validate,
                max_validation_retries=1,
            )
            return result.parsed
        except (LLMValidationError, LLMError) as exc:
            logger.warning("ReferenceRanker failed (%s); dropping fetched references", exc)
            return []


def _parse_arxiv_atom(xml_text: str, concepts: list[str]) -> list[ResearchCard]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("arXiv: could not parse Atom response: %s", exc)
        return []
    cards: list[ResearchCard] = []
    for entry in root.findall("a:entry", _ATOM):
        title_el = entry.find("a:title", _ATOM)
        id_el = entry.find("a:id", _ATOM)
        if title_el is None or id_el is None or not (id_el.text or "").strip():
            continue
        title = " ".join((title_el.text or "").split())
        url = (id_el.text or "").strip()
        published = (entry.findtext("a:published", default="", namespaces=_ATOM) or "")[:10]
        authors = [
            (a.findtext("a:name", default="", namespaces=_ATOM) or "").strip()
            for a in entry.findall("a:author", _ATOM)
        ]
        authors = [a for a in authors if a]
        summary = " ".join(
            (entry.findtext("a:summary", default="", namespaces=_ATOM) or "").split()
        )
        cards.append(
            ResearchCard(
                type="further_reading",
                title=title or "(untitled)",
                source_title=_format_authors(authors, "(arXiv)"),
                url=url,
                published_at=published or None,
                source_type="paper",
                relevance=(summary[:240] or "arXiv paper relevant to this topic."),
                use_as="further_reading",
                concepts=list(concepts),
                confidence=0.7,
            )
        )
    return cards


def _format_authors(authors: list[str], suffix: str = "") -> str:
    if not authors:
        return suffix.strip("() ") or "Unknown"
    if len(authors) == 1:
        names = authors[0]
    elif len(authors) <= 3:
        names = ", ".join(authors)
    else:
        names = f"{authors[0]} et al."
    return f"{names} {suffix}".strip()


def _parse_semantic_scholar(
    payload: object, concepts: list[str], max_results: int
) -> list[ResearchCard]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    # Citation-rank: the most-cited matches are the seminal/high-impact works.
    data = sorted(data, key=lambda p: (p.get("citationCount") or 0), reverse=True)
    cards: list[ResearchCard] = []
    for p in data[:max_results]:
        if not isinstance(p, dict):
            continue
        title = (p.get("title") or "").strip()
        if not title:
            continue
        ext = p.get("externalIds") or {}
        if ext.get("ArXiv"):
            url = f"https://arxiv.org/abs/{ext['ArXiv']}"
        elif ext.get("DOI"):
            url = f"https://doi.org/{ext['DOI']}"
        else:
            url = p.get("url")
        if not url:
            continue
        authors = [
            a.get("name")
            for a in (p.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        venue = (p.get("venue") or "").strip()
        cites = p.get("citationCount")
        rel = (p.get("abstract") or "").strip()[:240] or (
            f"被引 {cites} 次的相关论文" if cites else "相关论文"
        )
        cards.append(
            ResearchCard(
                type="further_reading",
                title=title,
                source_title=_format_authors(authors, f"({venue})" if venue else ""),
                url=url,
                published_at=str(p["year"]) if p.get("year") else None,
                source_type="paper",
                relevance=rel,
                use_as="further_reading",
                concepts=list(concepts),
                confidence=0.8,
            )
        )
    return cards


def build_reference_fetcher(
    *, enabled: bool = True, semantic_scholar_api_key: str = ""
) -> ReferenceFetcher | None:
    """Construct the configured reference fetcher, or ``None`` when disabled.

    Composes the available sources via ``MultiSourceReferenceFetcher``:
      - Semantic Scholar FIRST when an API key is configured — it's the strong
        recall source (citation-ranked → seminal works). Keyless S2 is omitted
        because it 429s, which would just add latency for nothing.
      - arXiv always, as the keyless fallback / extra recall.
    Add Exa / Tavily / a web-search tool here and they fan in automatically.
    """
    if not enabled:
        return None
    fetchers: list[ReferenceFetcher] = []
    if semantic_scholar_api_key:
        fetchers.append(
            SemanticScholarReferenceFetcher(api_key=semantic_scholar_api_key)
        )
    fetchers.append(ArxivReferenceFetcher())
    return MultiSourceReferenceFetcher(fetchers)

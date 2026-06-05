"""LLM-powered content analysis service."""

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.prompt_template import load_prompt
from app.services.llm.base import LLMProvider, UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    ValidationFailed,
)
from app.tools.extractors.base import RawContentChunk

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "content_analysis.md")


# --- Pydantic models for analysis results ---

class ExtractedConcept(BaseModel):
    """A concept extracted from content analysis."""
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    category: str = ""


class AnalyzedChunk(BaseModel):
    """Analysis result for a single content chunk."""
    topic: str
    summary: str = ""
    raw_text: str = ""
    concepts: list[str] = Field(default_factory=list)
    difficulty: int = Field(default=3, ge=1, le=5)
    key_terms: list[str] = Field(default_factory=list)
    has_code: bool = False
    has_formula: bool = False
    metadata: dict = Field(default_factory=dict)


class AnalysisResult(BaseModel):
    """Complete analysis result for a source."""
    source_title: str
    overall_summary: str = ""
    overall_difficulty: int = Field(default=3, ge=1, le=5)
    concepts: list[ExtractedConcept] = Field(default_factory=list)
    chunks: list[AnalyzedChunk] = Field(default_factory=list)
    suggested_prerequisites: list[str] = Field(default_factory=list)
    estimated_study_minutes: int = 0


class ContentAnalyzer:
    """Analyzes raw content chunks using LLM for structured understanding."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router
        self._runtime = AgentRuntime(router=model_router)

    async def analyze(
        self,
        title: str,
        chunks: list[RawContentChunk],
        source_type: str,
        user_directive: str = "",
    ) -> AnalysisResult:
        """Analyze extracted content chunks."""
        system_prompt = _PROMPT.render(user_directive=user_directive)

        total_text = "\n\n---\n\n".join(c.raw_text for c in chunks)

        if len(total_text) < 8000:
            return await self._analyze_single(system_prompt, title, chunks, source_type)
        else:
            return await self._analyze_batched(system_prompt, title, chunks, source_type)

    async def _analyze_single(
        self, system_prompt: str, title: str,
        chunks: list[RawContentChunk], source_type: str,
    ) -> AnalysisResult:
        content_text = self._format_chunks_for_llm(chunks, source_type)
        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            UnifiedMessage(
                role="user",
                content=f'Analyze the following content from a {source_type} source titled "{title}":\n\n{content_text}',
            ),
        ]

        # Validator parses JSON + builds the structured result. On JSON parse
        # failure the runtime gets one corrective retry; on exhaustion we fall
        # back to a degenerate result rather than raising — keeps the upstream
        # ingestion pipeline robust to a single bad LLM response.
        try:
            result = await self._runtime.call(
                messages,
                primary=TaskType.CONTENT_ANALYSIS,
                max_tokens=4096,
                temperature=0.3,
                phase="content_analyzer.single",
                validator=lambda text: _build_analysis_from_text(text, title, chunks),
            )
            return result.parsed  # type: ignore[no-any-return]
        except LLMValidationError:
            logger.warning("ContentAnalyzer: validator exhausted, using degenerate fallback")
            return _degenerate_analysis_result(title, chunks)

    async def _analyze_batched(
        self, system_prompt: str, title: str,
        chunks: list[RawContentChunk], source_type: str,
    ) -> AnalysisResult:
        BATCH_CHAR_LIMIT = 6000
        batches: list[list[RawContentChunk]] = []
        current_batch: list[RawContentChunk] = []
        current_chars = 0

        for chunk in chunks:
            chunk_len = len(chunk.raw_text)
            if current_chars + chunk_len > BATCH_CHAR_LIMIT and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(chunk)
            current_chars += chunk_len

        if current_batch:
            batches.append(current_batch)

        batch_results: list[AnalysisResult] = []
        for i, batch in enumerate(batches):
            content_text = self._format_chunks_for_llm(batch, source_type)
            messages = [
                UnifiedMessage(role="system", content=system_prompt),
                UnifiedMessage(
                    role="user",
                    content=f'Analyze part {i + 1}/{len(batches)} of a {source_type} source titled "{title}":\n\n{content_text}',
                ),
            ]
            try:
                result = await self._runtime.call(
                    messages,
                    primary=TaskType.CONTENT_ANALYSIS,
                    max_tokens=4096,
                    temperature=0.3,
                    phase=f"content_analyzer.batch[{i + 1}/{len(batches)}]",
                    validator=lambda text, b=batch: _build_analysis_from_text(text, title, b),
                )
                batch_results.append(result.parsed)
            except LLMValidationError:
                logger.warning(
                    "ContentAnalyzer: batch %d/%d validator exhausted, using fallback",
                    i + 1, len(batches),
                )
                batch_results.append(_degenerate_analysis_result(title, batch))

        return self._merge_batch_results(title, batch_results)

    @staticmethod
    def _format_chunks_for_llm(chunks: list[RawContentChunk], source_type: str) -> str:
        parts = []
        for i, chunk in enumerate(chunks):
            header = f"--- Chunk {i + 1} ---"
            if source_type == "bilibili":
                start = chunk.metadata.get("start_time", 0)
                end = chunk.metadata.get("end_time", 0)
                header += f" [Video timestamp: {start:.0f}s - {end:.0f}s]"
            elif source_type == "pdf":
                page_start = chunk.metadata.get("page_start", "?")
                heading = chunk.metadata.get("heading", "")
                header += f" [Page: {page_start}]"
                if heading:
                    header += f" [Heading: {heading}]"
            parts.append(f"{header}\n{chunk.raw_text}")
        return "\n\n".join(parts)

    # NB: ``_parse_analysis_response`` was split into the module-level
    # ``_build_analysis_from_text`` (validator-friendly, raises
    # ``ValidationFailed`` on bad JSON) and ``_degenerate_analysis_result``
    # (the soft fallback used when the runtime exhausts retries).

    @staticmethod
    def _merge_batch_results(title: str, results: list[AnalysisResult]) -> AnalysisResult:
        all_concepts: dict[str, ExtractedConcept] = {}
        all_chunks: list[AnalyzedChunk] = []
        all_prereqs: set[str] = set()
        total_minutes = 0
        difficulties: list[int] = []

        for result in results:
            for concept in result.concepts:
                if concept.name not in all_concepts:
                    all_concepts[concept.name] = concept
            all_chunks.extend(result.chunks)
            all_prereqs.update(result.suggested_prerequisites)
            total_minutes += result.estimated_study_minutes
            difficulties.append(result.overall_difficulty)

        # Each batch numbers its own fallback topics (``Section 1``, ``Section 2``
        # …) starting at 1, so merged chunks end up with duplicate generic
        # topics across batches. Renumber generic topics globally so per-chunk
        # section titles stay distinct.
        generic_pat = re.compile(r"^(Section|Part|Chunk)\s*\d+$", re.IGNORECASE)
        for i, ch in enumerate(all_chunks):
            if not ch.topic or generic_pat.match(ch.topic.strip()):
                ch.topic = f"Section {i + 1}"

        avg_difficulty = round(sum(difficulties) / len(difficulties)) if difficulties else 3
        summaries = [r.overall_summary for r in results if r.overall_summary]
        combined_summary = " ".join(summaries) if summaries else f"Content from: {title}"

        return AnalysisResult(
            source_title=title,
            overall_summary=combined_summary,
            overall_difficulty=avg_difficulty,
            concepts=list(all_concepts.values()),
            chunks=all_chunks,
            suggested_prerequisites=list(all_prereqs),
            estimated_study_minutes=total_minutes,
        )


# --- parsing helpers -------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _build_analysis_from_text(
    response_text: str, title: str, chunks: list[RawContentChunk]
) -> AnalysisResult:
    """Parse a single LLM response into an ``AnalysisResult``.

    Used as an ``AgentRuntime`` validator. Raises ``ValidationFailed`` on
    JSON parse failure so the runtime can issue a corrective retry. The
    caller falls back to ``_degenerate_analysis_result`` on retry exhaustion.
    """
    text = _strip_json_fences(response_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(
            f"invalid_json: {exc}",
            hint="Reply with a single JSON object only — no prose, no fences.",
        ) from exc

    if not isinstance(data, dict):
        raise ValidationFailed(
            "response was valid JSON but not an object",
            hint="Wrap the analysis fields in a top-level `{...}` object.",
        )

    concepts = [ExtractedConcept(**c) for c in data.get("concepts", [])]
    analyzed_chunks = []
    raw_chunks = data.get("chunks", [])
    # Truncate any overshoot up-front — the prompt requires `chunks` to match
    # the input length, but an over-generous LLM that emits an extra entry
    # would otherwise produce an AnalyzedChunk with empty raw_text/metadata
    # that has no real input chunk behind it.
    for i, chunk_data in enumerate(raw_chunks[: len(chunks)]):
        raw_text = chunks[i].raw_text
        metadata = chunks[i].metadata
        analyzed_chunks.append(
            AnalyzedChunk(
                topic=chunk_data.get("topic", f"Section {i + 1}"),
                summary=chunk_data.get("summary", ""),
                raw_text=raw_text,
                concepts=chunk_data.get("concepts", []),
                difficulty=chunk_data.get("difficulty", 3),
                key_terms=chunk_data.get("key_terms", []),
                has_code=chunk_data.get("has_code", False),
                has_formula=chunk_data.get("has_formula", False),
                metadata=metadata,
            )
        )

    # Enforce the analyzer's length contract: the output ``chunks`` array
    # must line up 1:1 with the extractor's input chunks. When the LLM
    # under-returns we pad with degenerate entries (preserving raw_text +
    # extractor metadata so downstream stages still see every chunk); when
    # it over-returns the slice above already truncated. Without this,
    # SectionPlanner's length check (see services/section_planner.py:164)
    # short-circuits to Layer 4 per-chunk fallback and the course becomes
    # one-section-per-chunk.
    if len(analyzed_chunks) != len(chunks):
        logger.warning(
            "ContentAnalyzer: LLM returned %d chunks for %d input chunks; "
            "padding to match",
            len(raw_chunks),
            len(chunks),
        )
        for i in range(len(analyzed_chunks), len(chunks)):
            analyzed_chunks.append(
                AnalyzedChunk(
                    topic=f"Section {i + 1}",
                    summary="",
                    raw_text=chunks[i].raw_text,
                    metadata=chunks[i].metadata,
                )
            )

    return AnalysisResult(
        source_title=data.get("source_title", title),
        overall_summary=data.get("overall_summary", ""),
        overall_difficulty=data.get("overall_difficulty", 3),
        concepts=concepts,
        chunks=analyzed_chunks,
        suggested_prerequisites=data.get("suggested_prerequisites", []),
        estimated_study_minutes=data.get("estimated_study_minutes", 0),
    )


def _degenerate_analysis_result(
    title: str, chunks: list[RawContentChunk]
) -> AnalysisResult:
    """Soft fallback when the LLM never returns valid JSON.

    Preserves the pre-runtime behavior of ``_parse_analysis_response`` —
    upstream ingestion gets a usable result instead of an exception.
    """
    return AnalysisResult(
        source_title=title,
        overall_summary=f"Content from: {title}",
        overall_difficulty=3,
        concepts=[],
        chunks=[
            AnalyzedChunk(
                topic=f"Section {i + 1}",
                summary=c.raw_text[:200],
                raw_text=c.raw_text,
                concepts=[],
                difficulty=3,
                metadata=c.metadata,
            )
            for i, c in enumerate(chunks)
        ],
    )

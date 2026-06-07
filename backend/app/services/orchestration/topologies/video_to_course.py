"""video→course topology (Phase 3): plan-coherent-outline → critic → fill.

The video→course path has a rich source (a full transcript already chunked and
analyzed), so unlike sentence→course it does NOT need ReAct exploration to
invent structure. It needs the opposite: to *consolidate* an over-segmented
chunk stream into a small, coherent outline.

``SectionPlanner`` (run at ingestion) already proposes a bucketing, but its
floor can be coarse and it carries no difficulty / knowledge-point structure —
and on LLM outage it used to degrade to one-section-per-chunk. So here the
``OutlinePlannerNode`` takes the analyzed chunks (and SectionPlanner's buckets
as a *warm start*) and produces the critic-checkable outline shape:

    sections = [{
        "title", "difficulty" (1-5), "knowledge_points": [str],
        "has_practice": bool, "source_chunk_indices": [int],
    }]

A ``CriticGate`` then validates difficulty progression / KP coverage / quiz
coverage / duplicate titles (``RuleCritic``); on failure it backtracks to the
planner with feedback (bounded by ``GraphState.backtrack_budget``). The
``source_chunk_indices`` partition lets the downstream fill phase map each
section back to its chunks and reuse the existing lesson/lab generation.

This module wires the outline half concretely. The fill/assemble back half
reuses course generation and is wired by the worker (``CourseGenerator``
decomposition), the same way ``sentence_to_course.OutlineToPlanNode`` hands a
frozen outline to that path.
"""

from __future__ import annotations

import json
import logging

from app.services.llm.base import LLMError
from app.services.llm.runtime import LLMValidationError, ValidationFailed
from app.services.orchestration.critic import CriticGate, RuleCritic
from app.services.orchestration.graph import CourseGraph, GateDecision, GraphState

logger = logging.getLogger(__name__)

__all__ = [
    "SECTIONS_KEY",
    "CHUNK_SUMMARIES_KEY",
    "WARM_START_KEY",
    "RECUT_RESULT_KEY",
    "OutlinePlannerNode",
    "OutlineInspectTool",
    "RecutGate",
    "build_recut_node",
    "build_video_course_graph",
    "build_chunk_summaries",
    "build_warm_start_buckets",
    "plan_video_outline",
    "split_oversized_sections",
]

SECTIONS_KEY = "sections"
# state.data inputs the worker populates before running the graph:
CHUNK_SUMMARIES_KEY = "chunk_summaries"   # [{idx, topic, summary, size_hint}]
WARM_START_KEY = "warm_start_buckets"     # [{topic, chunk_indices: [int]}] | None
TITLE_KEY = "title"
# state.data key the ReAct re-cut node writes its verdict under:
RECUT_RESULT_KEY = "recut_decision"       # {"decision": "accept"|"recut", "reason": str}
# Name of the planner node the re-cut gate backtracks to (must match the planner
# node's ``name`` so ``CourseGraph`` can resolve + replay feedback into it).
PLAN_NODE_NAME = "plan_outline"

# Outline size ceiling. A coherent course from a single source is a handful of
# sections, not dozens — this is the hard anti-fragmentation guard enforced in
# the validator (so the planner self-corrects) on top of the critic gate.
_DEFAULT_MAX_SECTIONS = 12
_MIN_SECTIONS = 1


# ``{target_language}`` is filled per course so section titles match the
# learner's language. ``knowledge_points`` stay canonical English
# ``lower_snake_case`` regardless (they link to the knowledge graph) — see
# ``services/prompts/lesson_generation.md`` for the same convention.
_PLANNER_SYSTEM_TEMPLATE = """\
你是课程大纲规划师。输入是一个已被切片并分析过的视频/长文转写（每个 chunk 带 \
topic + summary），你要把这些**碎片整合成一份连贯的课程大纲**。

核心要求：
1. **合并而非罗列**。相邻、同主题的 chunk 必须归入同一节。一份好的大纲是个位数到十几节，\
绝不是一个 chunk 一节。
2. 每一节给出：`title`（具体、点明本节内容，不要 "第N节"/"Introduction" 这类空标题）、\
`difficulty`（1-5 的整数）、`knowledge_points`（1-5 个核心知识点，规范英文 lower_snake_case）、\
`source_chunk_indices`（本节覆盖的 chunk 序号列表）。
3. **难度单调不降**：靠前的节难度不高于靠后的节。
4. **标题不重复**。
5. **完整且不重叠地覆盖所有 chunk**：每个 chunk 序号必须恰好属于一节，按原顺序连续切分\
（一节的 chunk 序号是一段连续区间）。
6. **语言**：每一节的 `title` 必须用 {target_language} 书写（自然语言文本）；\
但 `knowledge_points` 必须保持规范英文 lower_snake_case，**不要翻译**——它们要对接知识图谱。

只输出一个 JSON 对象，形如：
{{"sections": [{{"title": "...", "difficulty": 1, "knowledge_points": ["..."], \
"source_chunk_indices": [0,1,2]}}]}}
不要 markdown 代码块，不要任何额外文字。最后一个字符必须是 `}}`。
"""


def _coerce_int(v, default: int = 1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class OutlinePlannerNode:
    """Consolidate analyzed chunks into a coherent, critic-checkable outline.

    A deterministic graph ``Node`` (single structured LLM call with a
    validator) rather than a ReAct loop — the structure is already present in
    the source, so this is consolidation, not exploration. On a critic
    backtrack the gate's feedback (``state.feedback[name]``) is replayed into
    the prompt so the re-plan is informed.
    """

    def __init__(
        self,
        *,
        name: str = "plan_outline",
        llm,
        max_sections: int = _DEFAULT_MAX_SECTIONS,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        target_language: str = "zh-CN",
    ) -> None:
        self.name = name
        self._llm = llm
        self._max_sections = max_sections
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._target_language = target_language

    async def run(self, state: GraphState, *, bus=None) -> GraphState:
        chunk_summaries = list(state.data.get(CHUNK_SUMMARIES_KEY) or [])
        n = len(chunk_summaries)
        if n == 0:
            state.data[SECTIONS_KEY] = []
            return state
        # n == 1 has no consolidation to do — one section, skip the LLM.
        if n == 1:
            cs = chunk_summaries[0]
            state.data[SECTIONS_KEY] = [
                {
                    "title": cs.get("topic") or state.data.get(TITLE_KEY) or "Section 1",
                    "difficulty": 1,
                    "knowledge_points": [],
                    "has_practice": True,
                    "source_chunk_indices": [0],
                }
            ]
            return state

        messages = self._build_messages(state, chunk_summaries, n)
        try:
            result = await self._llm.complete(
                messages,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                validator=lambda text: self._validate(text, n),
                max_validation_retries=1,
                phase=f"{self.name}.plan",
            )
            sections = result.parsed
        except (LLMValidationError, LLMError) as exc:
            # Planner exhausted: fall back to the warm-start buckets (or a
            # single coarse section) so the graph still produces an outline
            # rather than aborting. The critic gate still runs on it.
            logger.warning("OutlinePlannerNode failed (%s); using warm-start floor", exc)
            sections = self._warm_start_floor(state, n)

        state.data[SECTIONS_KEY] = sections
        return state

    # --- prompt -----------------------------------------------------------

    def _build_messages(self, state: GraphState, chunk_summaries, n: int):
        from app.services.llm.base import UnifiedMessage

        title = state.data.get(TITLE_KEY) or "Untitled"
        payload = {
            "title": title,
            "chunk_count": n,
            "max_sections": self._max_sections,
            "chunks": [
                {
                    "idx": _coerce_int(cs.get("idx", i), i),
                    "topic": cs.get("topic") or "",
                    "summary": (cs.get("summary") or "")[:400],
                }
                for i, cs in enumerate(chunk_summaries)
            ],
        }
        warm = state.data.get(WARM_START_KEY)
        if warm:
            payload["warm_start_buckets"] = warm

        user_parts = [
            f"课程标题：{title}",
            f"共 {n} 个 chunk，请整合成不超过 {self._max_sections} 节的大纲。",
            "Chunks (JSON):",
            json.dumps(payload, ensure_ascii=False),
        ]
        # Pin section titles to the course language; knowledge_points stay
        # canonical English lower_snake_case (restated in the user message so
        # the directive survives even if the system prompt is summarized).
        user_parts.append(
            f"语言要求：每节 `title` 用 {self._target_language} 书写；"
            "`knowledge_points` 保持英文 lower_snake_case，不要翻译。"
        )
        feedback = state.feedback.get(self.name, "")
        if feedback:
            user_parts.insert(
                0,
                f"上一版大纲被质检驳回，问题：{feedback}\n请针对性修正后重新规划。",
            )
        return [
            UnifiedMessage(
                role="system",
                content=_PLANNER_SYSTEM_TEMPLATE.format(
                    target_language=self._target_language
                ),
            ),
            UnifiedMessage(role="user", content="\n".join(user_parts)),
        ]

    # --- validation -------------------------------------------------------

    def _validate(self, text: str, n: int) -> list[dict]:
        """Parse + structurally validate the outline.

        Raises ``ValidationFailed`` (→ one corrective retry) on: unparseable
        JSON, missing/empty sections, section count over the cap (the
        anti-fragmentation guard), or a chunk partition that doesn't cover
        ``range(n)`` exactly once. Difficulty progression / duplicate titles
        are left to the ``RuleCritic`` gate so they drive a *backtrack* with
        feedback rather than a blind in-call retry.
        """
        parsed = _parse_json(text)
        if not isinstance(parsed, dict):
            raise ValidationFailed(
                "outline_not_object",
                hint='Reply with a single JSON object: {"sections": [...]}.',
            )
        raw_sections = parsed.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValidationFailed(
                "outline_no_sections",
                hint="`sections` must be a non-empty array.",
            )
        if len(raw_sections) > self._max_sections:
            raise ValidationFailed(
                f"too_many_sections: {len(raw_sections)} > {self._max_sections}",
                hint=(
                    f"Merge adjacent same-topic chunks — produce at most "
                    f"{self._max_sections} sections, not one per chunk."
                ),
            )

        covered: set[int] = set()
        sections: list[dict] = []
        for s in raw_sections:
            if not isinstance(s, dict):
                raise ValidationFailed("section_not_object")
            title = str(s.get("title") or "").strip()
            if not title:
                raise ValidationFailed(
                    "section_missing_title",
                    hint="Every section needs a specific, non-empty title.",
                )
            indices = s.get("source_chunk_indices")
            if not isinstance(indices, list) or not indices:
                raise ValidationFailed(
                    f"section_missing_chunks: {title}",
                    hint="Each section must list its `source_chunk_indices`.",
                )
            idx_ints: list[int] = []
            for raw_idx in indices:
                idx = _coerce_int(raw_idx, -1)
                if idx < 0 or idx >= n:
                    raise ValidationFailed(
                        f"chunk_index_out_of_range: {raw_idx}",
                        hint=f"Chunk indices must be within 0..{n - 1}.",
                    )
                if idx in covered:
                    raise ValidationFailed(
                        f"chunk_index_reused: {idx}",
                        hint="Each chunk belongs to exactly one section.",
                    )
                covered.add(idx)
                idx_ints.append(idx)
            kps = s.get("knowledge_points")
            kp_list = [str(k).strip() for k in kps if str(k).strip()] if isinstance(kps, list) else []
            sections.append(
                {
                    "title": title,
                    "difficulty": max(1, min(5, _coerce_int(s.get("difficulty", 1), 1))),
                    "knowledge_points": kp_list,
                    "has_practice": True,
                    "source_chunk_indices": sorted(idx_ints),
                }
            )

        missing = set(range(n)) - covered
        if missing:
            raise ValidationFailed(
                f"chunks_uncovered: {sorted(missing)[:10]}",
                hint="Cover every chunk index exactly once across all sections.",
            )
        # Each section must be a CONTIGUOUS range of chunk indices. Combined
        # with full coverage + no reuse this makes the outline an ordered
        # segmentation of [0, n) — exactly what the downstream bucket-mode fill
        # (consecutive chunks sharing a bucket) expects, so sections map 1:1 to
        # section_bucket ids without splitting.
        for s in sections:
            idxs = s["source_chunk_indices"]
            if idxs[-1] - idxs[0] + 1 != len(idxs):
                raise ValidationFailed(
                    f"section_chunks_not_contiguous: {s['title']}",
                    hint=(
                        "Each section must cover a contiguous run of chunks "
                        "(e.g. [3,4,5]), not a scattered set."
                    ),
                )
        # Keep the outline in source order so difficulty progression and the
        # downstream fill align with the transcript.
        sections.sort(key=lambda s: s["source_chunk_indices"][0])
        return sections

    # --- warm-start floor -------------------------------------------------

    def _warm_start_floor(self, state: GraphState, n: int) -> list[dict]:
        """Outline from SectionPlanner's buckets when the LLM planner fails.

        Reuses the (already coarsened) warm-start grouping; difficulty ramps
        gently and KPs are empty (the critic will flag, but a coarse outline
        beats none). Falls back to a single section if no warm start exists.
        """
        warm = state.data.get(WARM_START_KEY)
        if warm:
            sections: list[dict] = []
            total = len(warm)
            for i, b in enumerate(warm):
                indices = sorted(
                    _coerce_int(x, -1) for x in (b.get("chunk_indices") or [])
                )
                indices = [x for x in indices if 0 <= x < n]
                if not indices:
                    continue
                sections.append(
                    {
                        "title": b.get("topic") or f"Section {i + 1}",
                        "difficulty": 1 + min(4, (i * 4) // max(1, total - 1)) if total > 1 else 1,
                        "knowledge_points": [],
                        "has_practice": True,
                        "source_chunk_indices": indices,
                    }
                )
            if sections:
                sections.sort(key=lambda s: s["source_chunk_indices"][0])
                return sections
        return [
            {
                "title": state.data.get(TITLE_KEY) or "Section 1",
                "difficulty": 1,
                "knowledge_points": [],
                "has_practice": True,
                "source_chunk_indices": list(range(n)),
            }
        ]


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("OutlinePlannerNode: response is not valid JSON: %s", cleaned[:200])
        return None


# --- ReAct re-cut judgment (optional, opt-in) -----------------------------
#
# The ``RuleCritic`` is structural and local: it sees difficulty regression,
# missing knowledge points, quiz coverage, duplicate titles — but it CANNOT see
# *semantic boundary* problems, because it never reads chunk content. Two
# adjacent sections that are really one topic, or a single section that
# conflates two distinct topics, both pass the rule critic cleanly. The re-cut
# node closes that gap: a bounded ReAct loop that inspects the outline (and the
# chunk topics/summaries behind it) and decides whether the *cut points* are
# right. It's wired AFTER the critic gate (so it only ever judges a
# structurally-valid outline) and is opt-in/off-by-default (one extra LLM call).


# Chinese, consistent with ``_PLANNER_SYSTEM_TEMPLATE`` above. The judge reads
# the outline + chunk topics with the inspect tool, then ``finish``es with
# accept | recut. It is told to lean toward ``accept`` — a false re-cut costs a
# whole re-plan — and to recut ONLY for a clear boundary defect.
_RECUT_SYSTEM_TEMPLATE = """\
你是课程大纲的「切分质检员」。规则质检已经通过（难度递进、知识点、标题不重复都没问题），\
你只负责判断一件规则质检看不到的事：**章节的切分边界是否合理**。

你可以调用 `inspect_outline` 工具查看当前大纲，每一节都带有 \
`title`/`difficulty`/`knowledge_points`/`source_chunk_indices`，以及它覆盖的各 chunk 的 \
`topic` 与 `summary` 摘录。先 inspect，再判断。

只在出现**明确的边界缺陷**时才要求重切（recut），典型情形：
1. **一节混了两个不相干的主题**——应当拆分。
2. **相邻两节其实是同一个主题**——应当合并。
3. **节奏明显失衡**——某节塞了大半内容、其余节寥寥几句。

如果切分基本合理（哪怕不完美），就 `accept`。**宁可放过，不要误杀**：一次错误的 recut \
会触发整份大纲重规划，代价很高。

判断完成后，调用一次 `finish`：
- `decision="recut"` 时，`reason` 必须**具体**说明哪一节该拆/哪两节该合，以及为什么，\
这段话会原样反馈给规划师，请写成可直接执行的修改指令（用{target_language}书写）。
- `decision="accept"` 时，`reason` 可简短。
"""


class OutlineInspectTool:
    """Read-only window onto the current outline for the re-cut judge.

    The ReAct judge cannot otherwise see ``state.data`` — this tool projects the
    structurally-validated ``sections`` (with each section's covered chunk
    ``topic``/``summary`` excerpts, which carry the *semantic* signal the rule
    critic ignores) into a compact JSON the model can reason over. Read-only: it
    never mutates state, so it can't break course generation.
    """

    name = "inspect_outline"
    description = (
        "查看当前课程大纲：返回每一节的 title/difficulty/knowledge_points/"
        "source_chunk_indices，以及该节覆盖的 chunk 的 topic 与 summary 摘录。"
        "用它来判断切分边界是否合理。无参数。"
    )
    parameters = {"type": "object", "properties": {}}

    def to_tool_definition(self):
        from app.services.llm.base import ToolDefinition

        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def run(self, ctx, **params):  # noqa: ARG002
        from app.agentcore.tools.base import ToolResult

        state = (ctx.extras or {}).get("state")
        sections = list((getattr(state, "data", {}) or {}).get(SECTIONS_KEY) or [])
        chunk_summaries = list(
            (getattr(state, "data", {}) or {}).get(CHUNK_SUMMARIES_KEY) or []
        )
        by_idx = {
            _coerce_int(cs.get("idx", i), i): cs
            for i, cs in enumerate(chunk_summaries)
        }
        view = []
        for s in sections:
            idxs = list(s.get("source_chunk_indices") or [])
            view.append(
                {
                    "title": s.get("title"),
                    "difficulty": s.get("difficulty"),
                    "knowledge_points": s.get("knowledge_points", []),
                    "source_chunk_indices": idxs,
                    "chunk_count": len(idxs),
                    "chunks": [
                        {
                            "idx": i,
                            "topic": (by_idx.get(i, {}).get("topic") or "")[:120],
                            "summary": (by_idx.get(i, {}).get("summary") or "")[:240],
                        }
                        for i in idxs
                    ],
                }
            )
        return ToolResult(
            content=json.dumps(
                {"section_count": len(view), "sections": view}, ensure_ascii=False
            )
        )


def _recut_context_builder(state: GraphState) -> str:
    sections = list(state.data.get(SECTIONS_KEY) or [])
    titles = [s.get("title") for s in sections]
    return (
        f"课程标题：{state.data.get(TITLE_KEY) or 'Untitled'}\n"
        f"当前大纲共 {len(sections)} 节：{titles}\n"
        "请先调用 inspect_outline 查看每节覆盖的 chunk 主题与摘要，"
        "再判断切分边界，最后调用 finish(decision, reason)。"
    )


class _SafeReActNode:
    """Wrap a ``ReActNode`` so a raised loop (LLM outage/timeout) defaults to
    ``"accept"`` instead of aborting the graph.

    ``ReActNode``/``AgentLoop`` don't catch exceptions from ``llm.stream`` — an
    outage would propagate out of the graph and block course generation. This
    wrapper is the safety boundary the spec requires: on ANY error it writes an
    ``accept`` verdict to ``state.data[result_key]`` (so the ``RecutGate`` reads
    a benign decision and continues) and swallows the error. The node ``name`` is
    proxied so ``CourseGraph`` can key the gate on it.
    """

    def __init__(self, inner, *, result_key: str, default_decision: str = "accept") -> None:
        self._inner = inner
        self.name = inner.name
        self._result_key = result_key
        self._default = default_decision

    async def run(self, state: GraphState, *, bus=None) -> GraphState:
        try:
            return await self._inner.run(state, bus=bus)
        except Exception:  # noqa: BLE001 — never let a judge error block generation
            logger.warning(
                "recut node %s failed; defaulting to %r", self.name, self._default,
                exc_info=True,
            )
            state.data[self._result_key] = {"decision": self._default, "reason": "recut_node_error"}
            return state


def build_recut_node(recut_llm, *, target_language: str = "zh-CN"):
    """Build the (error-safe) ReAct re-cut judgment node.

    ``recut_llm`` is an agentcore ``LLMClient`` (a ``.stream(...)``-capable
    client — NOT the ``.complete``-only planner stub); the node runs a bounded
    ``ReActNode`` loop ending in ``finish(decision in {accept, recut})``. The
    node is wrapped in ``_SafeReActNode`` so that on ANY error/timeout — or if
    the model simply never calls ``finish`` — it defaults to ``"accept"`` and
    can never block course generation.
    """
    from app.services.orchestration.react_node import ReActNode

    inner = ReActNode(
        name="recut_judge",
        llm=recut_llm,
        system_prompt=_RECUT_SYSTEM_TEMPLATE.format(target_language=target_language),
        context_builder=_recut_context_builder,
        inspect_tools=(OutlineInspectTool(),),
        decisions=("accept", "recut"),
        default_decision="accept",
        max_iterations=4,
        result_key=RECUT_RESULT_KEY,
        temperature=0.2,
    )
    return _SafeReActNode(inner, result_key=RECUT_RESULT_KEY, default_decision="accept")


class RecutGate:
    """Adapt the re-cut node's verdict into a backtrack-to-planner decision.

    Reads ``state.data[RECUT_RESULT_KEY]`` (written by the ``ReActNode``). On
    ``"recut"`` it requests a backtrack to ``plan_outline`` carrying the judge's
    reason as feedback — ``CourseGraph`` then enforces ``backtrack_budget`` and
    replays the feedback into ``state.feedback["plan_outline"]`` so the planner
    re-plans WITH it. On ``"accept"`` (or any malformed/missing verdict) it
    continues — never blocking generation.
    """

    def __init__(self, *, target_node: str = PLAN_NODE_NAME) -> None:
        self._target = target_node

    async def evaluate(self, state: GraphState, *, bus=None) -> GateDecision:
        verdict = state.data.get(RECUT_RESULT_KEY) or {}
        decision = verdict.get("decision") if isinstance(verdict, dict) else None
        if decision != "recut":
            return GateDecision(action="continue")
        reason = (verdict.get("reason") or "").strip() if isinstance(verdict, dict) else ""
        feedback = (
            f"切分质检判定需要重切：{reason}"
            if reason
            else "切分质检判定章节边界不合理，请重新规划切分（拆分混合主题/合并同一主题/平衡节奏）。"
        )
        if bus is not None:
            from app.agentcore.events.types import custom

            await bus.emit(custom("recut_verdict", {"decision": "recut", "feedback": feedback}))
        return GateDecision(action="backtrack", target=self._target, feedback=feedback)


def build_video_course_graph(
    llm,
    *,
    max_sections: int = _DEFAULT_MAX_SECTIONS,
    target_language: str = "zh-CN",
    enable_recut: bool = False,
    recut_llm=None,
) -> CourseGraph:
    """Outline half of video→course: plan → critic gate (backtrack to plan).

    The worker populates ``state.data`` with ``chunk_summaries`` (+ optional
    ``warm_start_buckets`` and ``title``), runs the graph, then reads the
    frozen ``state.data["sections"]`` for the fill/assemble phase. The critic
    is ``RuleCritic`` (zero-LLM); swap in ``ModelCritic`` where a CRITIC route
    is provisioned. Backtrack depth is governed by
    ``GraphState.backtrack_budget`` on the state the worker passes in.

    When ``enable_recut`` is True, an OPTIONAL ReAct boundary-judgment node is
    appended AFTER the critic gate: it inspects the (already structurally-valid)
    outline for semantic boundary defects the rule critic can't see — a section
    conflating two topics, two adjacent sections that are one topic, lopsided
    pacing — and on a ``"recut"`` verdict its ``RecutGate`` backtracks to the
    planner (reusing the same ``backtrack_budget``), replaying the judge's
    feedback so the re-plan is informed. It is OFF by default (one extra LLM
    call); when omitted the graph is byte-for-byte the prior plan→critic graph.

    ``recut_llm`` (an agentcore ``.stream``-capable ``LLMClient``) is the model
    the re-cut node uses; it defaults to ``llm`` but is a separate parameter so
    callers/tests can inject a streaming client distinct from the planner's
    ``.complete``-only one. Ignored unless ``enable_recut`` is True.
    """
    planner = OutlinePlannerNode(
        llm=llm, max_sections=max_sections, target_language=target_language
    )
    gates: dict = {planner.name: CriticGate(RuleCritic(target_node=planner.name))}
    nodes: list = [planner]
    if enable_recut:
        recut = build_recut_node(recut_llm or llm, target_language=target_language)
        nodes.append(recut)
        gates[recut.name] = RecutGate(target_node=planner.name)
    return CourseGraph(nodes=nodes, gates=gates)


# --- worker glue: build graph inputs from persisted chunks ----------------


def _chunk_meta(chunk) -> dict:
    """Read a content chunk's metadata dict (ORM ``metadata_`` or duck-typed)."""
    meta = getattr(chunk, "metadata_", None)
    if meta is None:
        meta = getattr(chunk, "metadata", None)
    return meta or {}


def build_chunk_summaries(chunks) -> list[dict]:
    """Project ordered content chunks into the planner's ``chunk_summaries``.

    Reads the per-chunk ``topic`` + ``summary`` that ContentAnalyzer already
    persisted on chunk metadata at ingestion. ``idx`` is the chunk's position
    in the supplied (source-ordered) list.
    """
    summaries: list[dict] = []
    for i, chunk in enumerate(chunks):
        meta = _chunk_meta(chunk)
        summaries.append(
            {
                "idx": i,
                "topic": meta.get("topic") or "",
                "summary": meta.get("summary") or "",
            }
        )
    return summaries


def build_warm_start_buckets(chunks) -> list[dict] | None:
    """Group ordered chunks by their existing ``section_bucket`` (SectionPlanner
    output) into warm-start buckets ``[{topic, chunk_indices}]``.

    Returns ``None`` when no chunk carries a ``section_bucket`` (nothing to warm
    start from). Consecutive chunks sharing a bucket id are grouped together;
    the bucket's topic is the first non-empty ``section_bucket_topic``/``topic``.
    """
    from app.services.section_planner import (
        SECTION_BUCKET_KEY,
        SECTION_BUCKET_TOPIC_KEY,
    )

    groups: dict[int, list[int]] = {}
    topics: dict[int, str] = {}
    any_bucket = False
    for i, chunk in enumerate(chunks):
        meta = _chunk_meta(chunk)
        bid = meta.get(SECTION_BUCKET_KEY)
        if bid is None:
            continue
        any_bucket = True
        bid = _coerce_int(bid, 0)
        groups.setdefault(bid, []).append(i)
        if bid not in topics:
            topics[bid] = meta.get(SECTION_BUCKET_TOPIC_KEY) or meta.get("topic") or ""
    if not any_bucket:
        return None
    return [
        {"topic": topics.get(bid, ""), "chunk_indices": sorted(idxs)}
        for bid, idxs in sorted(groups.items())
    ]


async def plan_video_outline(
    llm,
    *,
    title: str,
    chunk_summaries: list[dict],
    warm_start_buckets: list[dict] | None = None,
    bus=None,
    max_sections: int = _DEFAULT_MAX_SECTIONS,
    backtrack_budget: int = 2,
    target_language: str = "zh-CN",
    enable_recut: bool = False,
    recut_llm=None,
) -> list[dict]:
    """Run the outline graph and return the frozen ``sections``.

    Convenience entry point for the worker: assembles the ``GraphState``,
    executes ``build_video_course_graph`` (emitting AG-UI step/critic/backtrack
    events on ``bus``), and returns ``state.data["sections"]`` — the ordered,
    critic-checked outline with ``source_chunk_indices`` for the fill phase.

    ``enable_recut`` (default False) appends the optional ReAct boundary-
    judgment node; ``recut_llm`` is the ``.stream``-capable client it uses
    (defaults to ``llm``). Both are passed straight through to
    ``build_video_course_graph``; with the default they have no effect and this
    is exactly the prior plan→critic behavior.
    """
    state = GraphState(
        data={
            CHUNK_SUMMARIES_KEY: chunk_summaries,
            WARM_START_KEY: warm_start_buckets,
            TITLE_KEY: title,
        },
        backtrack_budget=backtrack_budget,
    )
    graph = build_video_course_graph(
        llm,
        max_sections=max_sections,
        target_language=target_language,
        enable_recut=enable_recut,
        recut_llm=recut_llm,
    )
    state = await graph.execute(state, bus=bus)
    return list(state.data.get(SECTIONS_KEY) or [])


def split_oversized_sections(
    sections: list[dict],
    chunk_token_counts: list[int],
    cap_tokens: int,
) -> list[dict]:
    """Split any section whose chunks exceed the lesson input budget.

    The outline planner optimizes for *coherence* (few, topically-clean
    sections) and is blind to the downstream per-lesson token budget. A long,
    dense section can therefore exceed what LessonGenerator can ingest, which
    would silently truncate the section's tail. Mirroring SectionPlanner's
    ``_split_oversized_buckets``, we re-split such a section along chunk
    boundaries into contiguous parts that each fit ``cap_tokens`` — so every
    chunk reaches a lesson instead of being dropped. Parts inherit the
    section's difficulty + knowledge points and get a ``（第k/N部分）`` title
    suffix. Sections within budget pass through untouched.

    This runs AFTER the critic gate (it's a budget adaptation, not a structural
    decision), so a small amount of re-segmentation here doesn't undo the
    consolidation the critic approved.
    """
    if cap_tokens <= 0:
        return sections

    def _tok(i: int) -> int:
        return chunk_token_counts[i] if 0 <= i < len(chunk_token_counts) else 0

    out: list[dict] = []
    for s in sections:
        idxs = list(s.get("source_chunk_indices") or [])
        total = sum(_tok(i) for i in idxs)
        if len(idxs) <= 1 or total <= cap_tokens:
            out.append(s)
            continue
        # Greedy contiguous packing — each part carries ≥1 chunk even if that
        # single chunk alone exceeds the cap (LessonGenerator trims that case).
        parts: list[list[int]] = [[]]
        running = 0
        for i in idxs:
            t = _tok(i)
            if parts[-1] and running + t > cap_tokens:
                parts.append([])
                running = 0
            parts[-1].append(i)
            running += t
        n = len(parts)
        if n <= 1:
            out.append(s)
            continue
        for k, part in enumerate(parts):
            out.append(
                {
                    **s,
                    "title": f"{s.get('title', 'Section')}（第{k + 1}/{n}部分）",
                    "source_chunk_indices": part,
                }
            )
    out.sort(key=lambda x: (x.get("source_chunk_indices") or [0])[0])
    return out

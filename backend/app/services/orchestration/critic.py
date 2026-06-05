"""Critic — the independent self-check that drives re-plan / backtrack.

A course-generation pipeline needs a feedback signal: without it, Plan-and-
Execute runs blind and a ReAct loop never knows when to stop. ``RuleCritic`` is
the zero-LLM default — deterministic, fully testable, free — checking the
assembled outline for difficulty progression, knowledge-point coverage, quiz
coverage, and duplicate titles. ``ModelCritic`` (a single LLM judgment, routed
via ``TaskType.CRITIC``) lands in Phase 4 and falls back to ``RuleCritic``.

A ``Critic`` produces a ``CriticVerdict``; a ``CriticGate`` adapts that verdict
into a graph ``GateDecision`` (continue vs backtrack-to-node).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "CriticVerdict",
    "Critic",
    "RuleCritic",
    "CriticGate",
    "SECTIONS_KEY",
]

# State key under which the assembled sections live. Each section is a dict:
#   {"title": str, "difficulty": int|float,
#    "knowledge_points": list[str], "has_practice": bool}
SECTIONS_KEY = "sections"


@dataclass
class CriticVerdict:
    passed: bool
    action: Literal["accept", "revise", "backtrack"]
    feedback: str = ""
    target_node: str | None = None
    scores: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class Critic(Protocol):
    async def evaluate(self, state, *, bus=None) -> CriticVerdict: ...


class RuleCritic:
    """Deterministic, zero-LLM outline checker.

    Thresholds are tunable; defaults are intentionally lenient so the gate only
    fires on real problems (the cost of a false backtrack is wasted tokens).
    """

    def __init__(
        self,
        *,
        target_node: str | None = None,
        difficulty_threshold: float = 0.9,
        coverage_threshold: float = 0.8,
    ) -> None:
        self._target = target_node
        self._difficulty_threshold = difficulty_threshold
        self._coverage_threshold = coverage_threshold

    async def evaluate(self, state, *, bus=None) -> CriticVerdict:  # noqa: ARG002
        sections: list[dict[str, Any]] = list(_get(state, SECTIONS_KEY) or [])
        if not sections:
            return CriticVerdict(passed=True, action="accept", scores={})

        problems: list[str] = []

        # 1. Difficulty progression — non-decreasing across the sequence.
        diffs = [_num(s.get("difficulty", 1)) for s in sections]
        pairs = list(zip(diffs, diffs[1:]))
        ok_pairs = sum(1 for a, b in pairs if b >= a)
        difficulty_score = ok_pairs / len(pairs) if pairs else 1.0
        if difficulty_score < self._difficulty_threshold:
            regressions = [
                sections[i + 1].get("title", f"#{i + 1}")
                for i, (a, b) in enumerate(pairs)
                if b < a
            ]
            problems.append(f"难度未递进，回落于：{', '.join(regressions)}")

        # 2. Knowledge points — every section has at least one.
        with_kp = sum(1 for s in sections if s.get("knowledge_points"))
        kp_score = with_kp / len(sections)
        if kp_score < 1.0:
            empty = [s.get("title", "?") for s in sections if not s.get("knowledge_points")]
            problems.append(f"以下章节缺少知识点：{', '.join(empty)}")

        # 3. Quiz coverage — sections that have knowledge points should have a
        #    practice/quiz attached.
        need = [s for s in sections if s.get("knowledge_points")]
        covered = sum(1 for s in need if s.get("has_practice"))
        coverage_score = covered / len(need) if need else 1.0
        if coverage_score < self._coverage_threshold:
            uncovered = [s.get("title", "?") for s in need if not s.get("has_practice")]
            problems.append(f"以下章节知识点未被测验覆盖：{', '.join(uncovered)}")

        # 4. Duplicate titles.
        titles = [s.get("title", "") for s in sections]
        dupes = {t for t in titles if t and titles.count(t) > 1}
        if dupes:
            problems.append(f"重复章节标题：{', '.join(sorted(dupes))}")

        scores = {
            "difficulty_progression": round(difficulty_score, 3),
            "knowledge_points": round(kp_score, 3),
            "quiz_coverage": round(coverage_score, 3),
            "title_uniqueness": round(1.0 - len(dupes) / len(titles), 3) if titles else 1.0,
        }
        passed = not problems
        return CriticVerdict(
            passed=passed,
            action="accept" if passed else "backtrack",
            feedback="" if passed else " ；".join(problems),
            target_node=None if passed else self._target,
            scores=scores,
        )


class ModelCritic:
    """LLM-judged critic (Phase 4). Routes via ``TaskType.CRITIC`` and falls
    back to ``RuleCritic`` on any LLM/parse failure so it can never be worse
    than the deterministic check.

    ``llm`` is an object exposing ``async complete(messages, *, validator=...)``
    (e.g. ``RouterLLMClient`` bound to the CRITIC route). The validator parses
    the model's JSON verdict; a failure degrades to the rule verdict.
    """

    def __init__(self, llm, *, target_node: str | None = None) -> None:
        self._llm = llm
        self._rule = RuleCritic(target_node=target_node)
        self._target = target_node

    async def evaluate(self, state, *, bus=None) -> CriticVerdict:
        sections = list(_get(state, SECTIONS_KEY) or [])
        if not sections:
            return CriticVerdict(passed=True, action="accept", scores={})
        import json

        outline = json.dumps(
            [
                {
                    "title": s.get("title"),
                    "difficulty": s.get("difficulty"),
                    "knowledge_points": s.get("knowledge_points", []),
                    "has_practice": bool(s.get("has_practice")),
                }
                for s in sections
            ],
            ensure_ascii=False,
        )
        from app.services.llm.base import UnifiedMessage

        messages = [
            UnifiedMessage(
                role="system",
                content=(
                    "你是课程质量评审。审查大纲的：难度递进、每节知识点充分、"
                    "测验覆盖、标题无重复。只回 JSON："
                    '{"passed": bool, "feedback": str}。'
                ),
            ),
            UnifiedMessage(role="user", content=f"课程大纲(JSON)：\n{outline}"),
        ]

        def _validate(text: str) -> dict:
            from app.services.llm.runtime import ValidationFailed

            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                parsed = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValidationFailed("critic_json_parse_failed") from exc
            if "passed" not in parsed:
                raise ValidationFailed("critic_missing_passed")
            return parsed

        try:
            result = await self._llm.complete(
                messages, max_tokens=400, temperature=0.0,
                validator=_validate, phase="critic",
            )
            parsed = result.parsed
        except Exception:  # noqa: BLE001
            logger = __import__("logging").getLogger(__name__)
            logger.warning("ModelCritic failed; falling back to RuleCritic", exc_info=True)
            return await self._rule.evaluate(state, bus=bus)

        passed = bool(parsed.get("passed"))
        return CriticVerdict(
            passed=passed,
            action="accept" if passed else "backtrack",
            feedback="" if passed else str(parsed.get("feedback") or "critic rejected outline"),
            target_node=None if passed else self._target,
            scores={"model_passed": 1.0 if passed else 0.0},
        )


class CriticGate:
    """Adapt a ``Critic`` into a graph gate.

    On a failing verdict it requests a backtrack to ``critic.target_node``
    (carried in the verdict). The graph executor enforces the backtrack budget.
    """

    def __init__(self, critic: Critic) -> None:
        self._critic = critic

    async def evaluate(self, state, *, bus=None):
        from app.services.orchestration.graph import GateDecision

        verdict = await self._critic.evaluate(state, bus=bus)
        state.critic_history.append(verdict)
        if bus is not None:
            from app.agentcore.events.types import custom

            await bus.emit(custom("critic_verdict", {
                "passed": verdict.passed,
                "scores": verdict.scores,
                "feedback": verdict.feedback,
            }))
        if verdict.passed or verdict.action != "backtrack":
            return GateDecision(action="continue")
        return GateDecision(
            action="backtrack", target=verdict.target_node, feedback=verdict.feedback
        )


def _get(state, key: str):
    data = getattr(state, "data", None)
    if isinstance(data, dict):
        return data.get(key)
    return getattr(state, key, None)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

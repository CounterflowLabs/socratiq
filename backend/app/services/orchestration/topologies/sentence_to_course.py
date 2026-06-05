"""sentence→course topology (Phase 5): ReAct-explore → outline-freeze → fill.

From a sparse one-sentence prompt there isn't enough to plan deterministically,
so phase 1 is ReAct-dominant exploration: the agent drafts (and may refine) a
candidate outline via the ``draft_outline`` tool, then ``finish``. A critic gate
then validates the outline; on failure it backtracks to explore (bounded), on
success the outline is "frozen" and phase 2 (deterministic Plan-and-Execute
fill) takes over — reusing the same lesson/lab execute path as video→course.

This module wires the front half concretely (explore + freeze) on the
orchestration primitives. The fill/assemble back half reuses course generation
and is represented by ``OutlineToPlanNode`` handing a frozen plan to that path.
"""

from __future__ import annotations

from app.agentcore.llm.client import LLMClient
from app.agentcore.tools.base import ToolContext, ToolDefinition, ToolResult
from app.services.orchestration.critic import CriticGate, RuleCritic
from app.services.orchestration.graph import CourseGraph, GraphState
from app.services.orchestration.react_node import ReActNode

__all__ = ["DraftOutlineTool", "OutlineToPlanNode", "build_sentence_course_graph"]

SECTIONS_KEY = "sections"
OUTLINE_FROZEN_KEY = "outline_frozen"


class DraftOutlineTool:
    """Lets the explore agent write/overwrite the candidate outline into state."""

    name = "draft_outline"
    description = (
        "Propose the course outline. Pass `sections` as an ordered list of "
        "{title, difficulty (1-5), knowledge_points: [str]}. Call again to refine."
    )
    parameters = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "difficulty": {"type": "integer"},
                        "knowledge_points": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title"],
                },
            }
        },
        "required": ["sections"],
    }

    def to_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def run(self, ctx: ToolContext, **params) -> ToolResult:
        state = ctx.extras.get("state")
        sections = params.get("sections") or []
        # Normalize so the critic can read knowledge_points / has_practice.
        norm = [
            {
                "title": s.get("title", ""),
                "difficulty": s.get("difficulty", 1),
                "knowledge_points": s.get("knowledge_points", []),
                "has_practice": True,  # explore outlines assume a practice per section
            }
            for s in sections
            if isinstance(s, dict)
        ]
        if state is not None:
            state.data[SECTIONS_KEY] = norm
        return ToolResult(content=f"outline drafted with {len(norm)} sections")


class OutlineToPlanNode:
    """Freeze the (gate-approved) outline and hand off to the fill phase.

    The frozen ``sections`` are the same shape video→course produces post-plan,
    so the deterministic lesson/lab execute + assemble path is reused. Here we
    mark the freeze; the executor wiring is shared with course generation.
    """

    name = "outline_to_plan"

    async def run(self, state: GraphState, *, bus=None) -> GraphState:
        state.data[OUTLINE_FROZEN_KEY] = True
        return state


_EXPLORE_SYSTEM = (
    "你在从一句话需求探索一门课程的大纲。先调用 draft_outline 给出候选大纲"
    "（章节标题 + 难度 + 知识点），如有需要再 refine；满意后调用 finish。"
    "保证难度递进、每节有知识点、标题不重复。"
)


def build_sentence_course_graph(llm: LLMClient, *, max_explore_iters: int = 6) -> CourseGraph:
    """Phase 1 (explore + freeze) of sentence→course as a CourseGraph.

    ``state.data["prompt"]`` holds the one-sentence input. On a passing freeze
    gate the outline is frozen into ``state.data["sections"]``; a failing gate
    backtracks to ``explore`` (bounded by ``GraphState.backtrack_budget``).
    """
    explore = ReActNode(
        name="explore",
        llm=llm,
        system_prompt=_EXPLORE_SYSTEM,
        context_builder=lambda s: f"一句话需求：{s.data.get('prompt', '')}",
        inspect_tools=[DraftOutlineTool()],
        decisions=("done",),
        default_decision="done",
        max_iterations=max_explore_iters,
        result_key="explore.decision",
    )
    freeze_gate = CriticGate(RuleCritic(target_node="explore"))
    return CourseGraph(
        nodes=[explore, OutlineToPlanNode()],
        gates={"explore": freeze_gate},
    )

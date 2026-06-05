"""Phase-0 gate: the agentcore scaffold imports and its defaults behave.

Covers the six non-event layers (runtime/llm/tools/memory/policy/storage):
interfaces import, default implementations are sound, and ToolExecutor runs
calls with hooks/approval/policy/error-wrapping and optional event emission.
"""

from __future__ import annotations

import pytest

from app.agentcore.events import EventBus
from app.agentcore.llm import RouterLLMClient, TurnResult  # noqa: F401
from app.agentcore.memory import ContextWindowManager, NoopSummarizer, PassthroughMemory
from app.agentcore.policy import AllowAll, NoopRiskScanner
from app.agentcore.runtime import (
    AgentState,
    CancellationToken,
    LoopConfig,
    NoopCheckpointer,
    RunCancelled,
)
from app.agentcore.storage import (
    InMemoryCheckpointStore,
    InMemoryMessageStore,
    InMemoryStateStore,
)
from app.agentcore.tools import (
    AgentToolAdapter,
    ToolCall,
    ToolContext,
    ToolExecutor,
    ToolResult,
)
from app.agent.tools.base import AgentTool
from app.services.llm.base import UnifiedMessage


class EchoTool:
    name = "echo"
    description = "echo back"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def run(self, ctx: ToolContext, **params) -> ToolResult:
        return ToolResult(content=params.get("text", ""))

    def to_tool_definition(self):
        from app.services.llm.base import ToolDefinition

        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )


class CollectHook:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def before_tool_call(self, call, ctx):  # noqa: ARG002
        return call

    async def after_tool_call(self, call, result, ctx):  # noqa: ARG002
        self.seen.append(call.name)
        return result


async def test_tool_executor_runs_with_hooks_and_emits_result():
    captured = []

    class Sink:
        async def emit(self, ev):
            captured.append(ev)

    bus = EventBus.new(sinks=[Sink()])
    hook = CollectHook()
    ex = ToolExecutor([EchoTool()], hooks=[hook], parallel=True)
    out = await ex.run_all(
        [ToolCall(id="tc1", name="echo", input={"text": "hi"})],
        ToolContext(),
        bus=bus,
    )
    assert out == [("tc1", out[0][1])]
    assert out[0][1].content == "hi"
    assert hook.seen == ["echo"]
    assert any(e.type.value == "TOOL_CALL_RESULT" for e in captured)


async def test_tool_executor_unknown_tool_and_policy_and_approval():
    ex_unknown = ToolExecutor([EchoTool()])
    (_id, res) = (await ex_unknown.run_all([ToolCall(id="x", name="nope", input={})], ToolContext()))[0]
    assert res.is_error and "unknown_tool" in res.content

    class DenyPolicy:
        async def allowed(self, call, ctx):  # noqa: ARG002
            return False

    ex_policy = ToolExecutor([EchoTool()], policy=DenyPolicy())
    (_id, res) = (await ex_policy.run_all([ToolCall(id="x", name="echo", input={})], ToolContext()))[0]
    assert res.is_error and "policy_denied" in res.content

    class DenyApproval:
        async def check(self, call, ctx):  # noqa: ARG002
            return False

    ex_appr = ToolExecutor([EchoTool()], approval=DenyApproval())
    (_id, res) = (await ex_appr.run_all([ToolCall(id="x", name="echo", input={})], ToolContext()))[0]
    assert res.is_error and "approval_denied" in res.content


async def test_agent_tool_adapter_wraps_legacy_tool():
    class Legacy(AgentTool):
        @property
        def name(self):
            return "legacy"

        @property
        def description(self):
            return "d"

        @property
        def parameters(self):
            return {"type": "object", "properties": {}}

        async def execute(self, **params):
            return "legacy-result"

    adapted = AgentToolAdapter(Legacy())
    res = await adapted.run(ToolContext())
    assert res.content == "legacy-result" and not res.is_error
    assert adapted.to_tool_definition().name == "legacy"


def test_context_window_manager_trims_oldest_nonsystem():
    cwm = ContextWindowManager()
    msgs = [
        UnifiedMessage(role="system", content="S" * 4),
        UnifiedMessage(role="user", content="x" * 4000),
        UnifiedMessage(role="assistant", content="y" * 4000),
        UnifiedMessage(role="user", content="latest"),
    ]
    trimmed = cwm.trim(msgs, budget=50)
    assert trimmed[0].role == "system"  # system preserved
    assert trimmed[-1].content == "latest"  # most recent preserved
    assert len(trimmed) < len(msgs)


async def test_cancellation_token():
    tok = CancellationToken()
    await tok.raise_if_cancelled()  # no-op
    tok.cancel()
    with pytest.raises(RunCancelled):
        await tok.raise_if_cancelled()

    polled = CancellationToken(poll=lambda: _true())
    with pytest.raises(RunCancelled):
        await polled.raise_if_cancelled()


async def _true() -> bool:
    return True


async def test_defaults_are_instantiable():
    assert isinstance(LoopConfig().max_iterations, int)
    AgentState(thread_id="t", run_id="r")
    await PassthroughMemory().prepare([])
    assert await NoopSummarizer().summarize([]) is None
    assert await AllowAll().allowed(ToolCall(id="1", name="n", input={}), ToolContext())
    assert (await NoopRiskScanner().scan("x")).action == "allow"
    await NoopCheckpointer().save(AgentState(thread_id="t", run_id="r"))
    InMemoryStateStore(), InMemoryCheckpointStore(), InMemoryMessageStore()

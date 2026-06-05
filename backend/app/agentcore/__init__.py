"""agentcore — a layered, reusable agent runtime for Socratiq.

Ported from the *design* of ``pi-agent-core`` (not the PyPI ``pi-agent``
package) onto Socratiq's existing LLM stack. The provider layer
(``app.services.llm``: ``LLMProvider`` impls, ``ModelRouter``, token budgeting,
``UnifiedMessage``/``ContentBlock``/``ToolDefinition``/``StreamChunk``) is the
unchanged底座 — agentcore composes it, it does not re-implement it.

Layers (see plan ``~/.claude/plans/sleepy-whistling-marshmallow.md``):

  runtime/  AgentLoop, AgentState, AgentRunner, Cancellation, Checkpoint
  llm/      LLMClient interface + RouterLLMClient (wraps ModelRouter/AgentRuntime)
  tools/    ToolDefinition, ToolExecutor, ToolContext, ToolResult, Approval
  memory/   Memory, ContextWindowManager, Summarizer  (defaults are no-op)
  events/   AG-UI event standard: EventBus, EventSink, StateProjector
  policy/   PermissionPolicy, RiskScanner  (defaults are permissive)
  storage/  StateStore, CheckpointStore, MessageStore

The single event vocabulary across the chat loop AND long-running task
management is the **AG-UI** protocol (``ag-ui-protocol`` SDK), wrapped by
``agentcore.events`` so the 0.x SDK churn is contained in one place.
"""

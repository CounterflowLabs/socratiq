# LLM abstraction layer

Nothing in `backend/app/agent/*`, `backend/app/services/*` (except the LLM module itself), or `backend/app/worker/*` imports an LLM SDK. They go through `app.services.llm`, which normalizes:

- **Anthropic Messages API** (`AnthropicProvider`)
- **OpenAI-compatible APIs** (`OpenAICompatProvider`) — covers OpenAI, DeepSeek, Qwen via DashScope, SiliconFlow, Groq, Ollama, anything with a `/v1/chat/completions` endpoint
- **Codex SDK** (`CodexProvider`) — the official ChatGPT-CLI wrapper, lets a user sign in to ChatGPT and use their plan as the chat backend

All three implement the same `LLMProvider` abstract class. The agent layer never knows which one it's talking to.

## File map

```
backend/app/services/llm/
├── base.py              UnifiedMessage / ContentBlock / LLMProvider / errors
├── router.py            ModelRouter — task-type → provider mapping
├── config.py            ModelConfigManager — reads model_configs / model_routes
├── encryption.py        AES-GCM encryption for api_key column
├── anthropic.py         AnthropicProvider
├── openai_compat.py     OpenAICompatProvider (the catch-all)
├── codex_provider.py    CodexProvider (Codex CLI wrapper)
├── codex_auth.py        OAuth-style ChatGPT login flow for Codex
├── base_url.py          URL normalization (`host.docker.internal` rewriting)
└── adapters/
    ├── tool_adapter.py    Anthropic tool_use ↔ OpenAI function_calling
    └── stream_adapter.py  SSE chunk normalization
```

## UnifiedMessage — the lingua franca

`backend/app/services/llm/base.py`:

```python
class ContentBlock(BaseModel):
    type: Literal["text", "image", "tool_use", "tool_result"]
    text: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_result_content: str | None = None
    is_error: bool = False

class UnifiedMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool_result"]
    content: str | list[ContentBlock]      # str for plain text; list for mixed content
    reasoning_content: str | None = None   # extended-thinking output (Anthropic / GPT-o1 style)

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema
```

This shape is closer to Anthropic's than OpenAI's because Anthropic's nested content blocks are strictly more expressive (and trivially flattenable to OpenAI's single string + tool_calls array). The adapters do the flattening on egress.

## The `LLMProvider` contract

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None, max_tokens=4096, temperature=0.7, **kwargs) -> LLMResponse: ...

    @abstractmethod
    async def chat_stream(self, messages, tools=None, max_tokens=4096, temperature=0.7, **kwargs) -> AsyncIterator[StreamChunk]: ...

    @property
    def supports_tool_use(self) -> bool: ...

    @property
    def supports_streaming(self) -> bool: ...

    @property
    def model_id(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Every concrete provider must implement these. The async iterator returned by `chat_stream` yields `StreamChunk(type="text_delta" | "reasoning_delta" | "tool_use_start" | "tool_use_delta" | "tool_use_end" | "message_end")`.

## ModelRouter — TaskType → provider

`backend/app/services/llm/router.py:TaskType`:

| TaskType | Used by | Typical model |
|---|---|---|
| `MENTOR_CHAT` | `MentorAgent.process()`, `/chat` SSE | Smart-tier — Claude Sonnet / GPT-4.x / DeepSeek-V3 |
| `CONTENT_ANALYSIS` | `ContentAnalyzer`, `LessonGenerator`, course assembly | Smart-tier |
| `EVALUATION` | `ExerciseEvalTool`, diagnostic scoring | Smart-tier (could be a cheaper tier) |
| `EMBEDDING` | `EmbeddingService` | Embedding model only (validation enforced) |

Routing decisions are persisted in the `model_routes` table. Users edit them from `/settings` → "Model routing" (which I redesigned as a section rail; see [Frontend layout](./frontend-layout.md#settings)).

```python
class ModelRouter:
    async def get_provider(self, task_type: TaskType) -> LLMProvider:
        # 1. Look up route in model_routes
        # 2. Look up model_configs by name
        # 3. Validate model_type matches the task (embedding vs chat)
        # 4. Decrypt api_key
        # 5. Instantiate the right provider (with 5-min in-memory cache)
        # 6. Return it
```

The cache key is `route:{task_type}` or `name:{model_name}` with a TTL — so a settings change takes effect within five minutes without restart. `invalidate_cache()` is also called when the settings UI saves a route change so changes appear instantly.

Errors raised:

| Error | When |
|---|---|
| `LLMError("No model configured for task type ...")` | The route row is missing |
| `LLMError("Model '...' not found")` | The route points to a deleted model |
| `LLMError("Model '...' is not active")` | Model was paused via settings |
| `LLMError("Embedding route is configured to chat model ...")` | Misconfiguration guard |
| `LLMError("Route '...' is configured to embedding model ...")` | Symmetric guard |

These bubble up to the FastAPI route handler, which returns 500 with the message. The frontend's settings page catches that and shows a red banner under the offending route.

## The tool-use adapter

`backend/app/services/llm/adapters/tool_adapter.py` handles the impedance mismatch between Anthropic's nested `tool_use` blocks and OpenAI's flat `function_calling` payloads.

Anthropic:
```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Let me check that..."},
    {"type": "tool_use", "id": "tu_01", "name": "search", "input": {"q": "..."}}
  ]
}
```

OpenAI:
```json
{
  "role": "assistant",
  "content": "Let me check that...",
  "tool_calls": [{"id": "tu_01", "type": "function", "function": {"name": "search", "arguments": "..."}}]
}
```

The adapter:
- **Egress (UnifiedMessage → provider format)**: flattens nested blocks into OpenAI's flat shape for `OpenAICompatProvider`; passes through unchanged for `AnthropicProvider`.
- **Ingress (provider response → UnifiedMessage)**: parses both shapes back into `ContentBlock[]`.

For providers with `supports_tool_use=False` (like CodexProvider, or older Ollama models), there's a **prompt-injection fallback**: tool definitions get appended to the system prompt with strict-format instructions, and the response is parsed with a regex looking for `[TOOL_CALL: name {json}]` markers. Not ideal, but lets the agent loop function on any backend.

## Adding a provider

```python
# 1. Subclass LLMProvider
class MyProvider(LLMProvider):
    def __init__(self, model: str, api_key: str | None, ...):
        ...

    async def chat(self, messages, ...) -> LLMResponse: ...
    async def chat_stream(self, messages, ...) -> AsyncIterator[StreamChunk]: ...

# 2. Register in router.py:ModelRouter._create_provider
elif provider_type == "my_provider":
    return MyProvider(model=model_id, api_key=api_key, ...)

# 3. Add to providerPresets in frontend/src/app/settings/page.tsx
# 4. Optional: add a Whisper preset if the provider also offers ASR
```

Provider rows in `model_configs` carry: `provider_type`, `model_id`, `base_url`, `api_key` (encrypted), `supports_tool_use`, `supports_streaming`, `max_tokens_limit`, `model_type` ("chat" | "embedding").

## SSE streaming

The mentor chat endpoint (`POST /api/v1/chat`) streams Server-Sent Events:

```
event: text_delta\ndata: {"text": "Hello"}\n\n
event: tool_start\ndata: {"name": "search"}\n\n
event: citations\ndata: {"citations": [...]}\n\n
event: message_end\ndata: {"conversation_id": "..."}\n\n
```

The frontend consumer (`frontend/src/lib/sse.ts` + `frontend/src/lib/api.ts:streamChat`) yields typed events to the chat composer. The TutorDrawer / MentorPanel append `text_delta` chunks to the last assistant message in the Zustand store as they arrive.

Provider streams arrive as their native chunk shape; `stream_adapter.py` normalizes them into the unified `StreamChunk` enum types listed above before the route handler emits them as SSE.

## Encryption

`backend/app/services/llm/encryption.py` uses AES-GCM with a key derived from `LLM_ENCRYPTION_KEY` env var. Every `model_configs.api_key` is encrypted at write; decrypted only when instantiating a provider, in-memory.

The Settings page displays `api_key_masked` (last 4 chars) — the decrypted value is never sent to the client.

## Token usage logging

Every `chat` / `chat_stream` response carries a `TokenUsage(input_tokens, output_tokens)`. Where the call site cares to track it, it writes a `LLMUsageLog` row tied to the conversation or to the source/task that triggered the call. Used for the future "cost dashboard"; currently just persisted.

## Codex provider quirks

`CodexProvider` (`codex_provider.py`) wraps the official `codex` CLI binary. It:
- Does not support streaming or tool use (CodexCLI is one-shot).
- Authenticates via `codex login` once per container (OAuth-ish PKCE flow handled in `codex_auth.py`); the session token lives in a `codexhome` volume so it survives container restarts.
- Tool calls degenerate to the prompt-injection fallback path.

If a user routes `MENTOR_CHAT` to Codex, the mentor still works — just slower and without streaming. The frontend gracefully shows the full message at once instead of token-by-token.

## Adjacent docs

- [Architecture](./architecture.md) for where the LLM layer sits in the system
- [Content pipeline](./content-pipeline.md) for what `CONTENT_ANALYSIS` calls look like in context
- [Frontend layout](./frontend-layout.md#settings) for the settings UI that drives `model_routes`

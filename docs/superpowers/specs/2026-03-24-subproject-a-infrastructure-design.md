# Sub-project A: Infrastructure Layer Design

**Date**: 2026-03-24
**Status**: Approved
**Scope**: Docker Compose + FastAPI skeleton + DB schema + LLM abstraction layer + Celery async tasks

---

## 1. Overview

Sub-project A builds the foundation layer for Socratiq MVP. Everything else (content ingestion, agent core, frontend) depends on this layer being solid.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Project decomposition | 3 sub-projects: A (infra) → B (content) → C (agent+frontend) | Independent spec/plan/implement cycles |
| Package manager | uv | Fast, mature, native pyproject.toml |
| Auth | Skip for MVP | Single user / small beta; user_id preserved for multi-tenant readiness |
| Content sources | Bilibili + PDF | B站学习区 is core scenario; PDF covers papers/books |
| Bilibili extraction | bilibili-api-python | Active community, handles wbi auth/signatures |
| Dev environment | Local dev + Docker for DB/Redis | Fast hot-reload; DB/Redis containerized |
| LLM abstraction | Full implementation (SDK direct wrapper) | Complete control, no black-box dependencies |
| LLM implementation | Anthropic SDK + OpenAI SDK, self-built adapters | Matches CLAUDE.md architecture exactly |
| Model config storage | Database (not .env) | Runtime configurable via API, future UI page |

---

## 2. Project Skeleton

### Directory Structure

```
socratiq/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI entry point
│   │   ├── config.py                # Pydantic Settings (env vars)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py              # Dependency injection (db session, llm router)
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── health.py        # GET /health
│   │   │       ├── models.py        # LLM model config CRUD
│   │   │       ├── model_routes.py  # LLM routing config
│   │   │       └── tasks.py         # GET /tasks/{id}/status
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py          # async engine + session factory
│   │   │   └── models/
│   │   │       ├── __init__.py
│   │   │       ├── base.py          # declarative base + BaseMixin (id, timestamps)
│   │   │       ├── user.py
│   │   │       ├── source.py
│   │   │       ├── course.py
│   │   │       ├── concept.py
│   │   │       ├── content_chunk.py
│   │   │       ├── lab.py
│   │   │       ├── exercise.py
│   │   │       ├── learning_record.py
│   │   │       ├── conversation.py
│   │   │       ├── message.py
│   │   │       └── model_config.py  # LLM model + route configs
│   │   ├── models/                  # Pydantic schemas (API layer)
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   └── llm/                 # LLM abstraction layer
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── anthropic.py
│   │   │       ├── openai_compat.py
│   │   │       ├── router.py
│   │   │       ├── config.py
│   │   │       ├── encryption.py    # API key encryption (Fernet)
│   │   │       └── adapters/
│   │   │           ├── __init__.py
│   │   │           ├── tool_adapter.py
│   │   │           └── stream_adapter.py
│   │   └── worker/
│   │       ├── __init__.py
│   │       ├── celery_app.py        # Celery instance config
│   │       └── tasks/
│   │           └── __init__.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_health.py
│   │   ├── test_models_api.py
│   │   └── services/
│   │       └── llm/
│   │           ├── test_anthropic.py
│   │           ├── test_openai_compat.py
│   │           ├── test_tool_adapter.py
│   │           ├── test_stream_adapter.py
│   │           └── test_router.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── alembic.ini
│   └── pyproject.toml
├── docker-compose.yml
├── .env.example
└── .gitignore
```

### Docker Compose

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: socratiq
      POSTGRES_PASSWORD: socratiq
      POSTGRES_DB: socratiq
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

### FastAPI Entry Point (main.py)

- CORS middleware (allow localhost:3000 in dev)
- Lifespan: init/close DB connection pool
- Mount route modules: health, models, model_routes, tasks
- `/health` checks DB + Redis connectivity

### Configuration (config.py)

```python
class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://socratiq:socratiq@localhost:5432/socratiq"
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Security
    llm_encryption_key: str  # Fernet key for API key encryption

    model_config = SettingsConfigDict(env_file=".env")
```

---

## 3. Database Schema

### Base Mixin

```python
class BaseMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
```

### Tables (15 total)

**Core domain tables (13):**

1. **users** — id, email, name, student_profile (JSONB), created_at, updated_at
2. **sources** — id, type (bilibili|pdf|markdown|url), url, title, raw_content, metadata (JSONB), status (pending|processing|ready|error), created_by → users
3. **courses** — id, title, description, created_by → users
4. **course_sources** — course_id → courses, source_id → sources (M2M join table)
5. **sections** — id, course_id → courses, title, order_index, source_id → sources, source_start, source_end, content (JSONB), difficulty (1-5)
6. **concepts** — id, name (UNIQUE), description, category, aliases (JSONB), prerequisites (UUID[]), embedding vector(1536)
7. **concept_sources** — concept_id → concepts, source_id → sources, context
8. **content_chunks** — id, source_id → sources, section_id → sections (nullable), text, embedding vector(1536), metadata (JSONB)
9. **labs** — id, section_id → sections, title, description, difficulty, estimated_minutes, starter_code, solution, test_cases (JSONB), hints (JSONB)
10. **exercises** — id, section_id → sections, type (mcq|code|open), question, options (JSONB), answer, explanation, difficulty, concepts (UUID[])
11. **learning_records** — id, user_id → users, course_id → courses, section_id → sections (nullable), type, data (JSONB), created_at
12. **conversations** — id, user_id → users, course_id → courses (nullable), mode, created_at, updated_at
13. **messages** — id, conversation_id → conversations, role, content (TEXT), tool_calls (JSONB nullable), metadata (JSONB), created_at

**LLM configuration tables (2):**

14. **model_configs** — id, name (UNIQUE), provider_type, model_id, api_key_encrypted, base_url, supports_tool_use, supports_streaming, max_tokens_limit, is_active
15. **model_route_configs** — id, task_type (UNIQUE), model_name → model_configs.name

### Design Adjustments from Original Schema

| Change | Original | Updated | Reason |
|--------|----------|---------|--------|
| Course-source relation | `courses.source_ids UUID[]` | `course_sources` join table | Proper M2M, better query support |
| Concept aliases | `concepts.name UNIQUE` only | Added `aliases JSONB` | Synonym/multilingual support |
| Conversations | `conversations.messages JSONB` | Separate `messages` table | Scalability; enables pagination and RAG over chat history |
| Timestamps | Some tables missing `updated_at` | All tables have `updated_at` via mixin | Consistency |
| Model config | Environment variables | `model_configs` + `model_route_configs` tables | Runtime configurable, future UI page |

### Migration Strategy

- Alembic with async engine (asyncpg)
- Initial migration includes `CREATE EXTENSION IF NOT EXISTS vector`
- Autogenerate for initial schema, manual for subsequent changes

---

## 4. LLM Abstraction Layer

### Architecture

```
Agent / Service layer
        ↓
    ModelRouter  ←→  DB (model_configs + model_route_configs)
        ↓
    LLMProvider (abstract)
    ├── AnthropicProvider (anthropic SDK)
    └── OpenAICompatProvider (openai SDK, base_url switching)
        ↓
    Adapters
    ├── ToolAdapter (unified ↔ provider-specific tool format)
    └── StreamAdapter (provider SSE → unified StreamChunk)
```

### Unified Message Format (base.py)

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
    content: str | list[ContentBlock]

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

class LLMResponse(BaseModel):
    content: list[ContentBlock]
    model: str
    usage: TokenUsage | None = None
    stop_reason: str | None = None

class StreamChunk(BaseModel):
    type: Literal["text_delta", "tool_use_start", "tool_use_delta", "tool_use_end", "message_end"]
    text: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input_delta: str | None = None
    usage: TokenUsage | None = None
```

### Abstract Base Class (base.py)

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self, messages: list[UnifiedMessage], *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096, temperature: float = 0.7,
        **kwargs
    ) -> LLMResponse: ...

    @abstractmethod
    async def chat_stream(
        self, messages: list[UnifiedMessage], *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096, temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    def supports_tool_use(self) -> bool: ...

    @abstractmethod
    def supports_streaming(self) -> bool: ...

    @abstractmethod
    def model_id(self) -> str: ...
```

### Tool Adapter (adapters/tool_adapter.py)

Three conversion strategies:

| Scenario | Tool Definition → | Response ← | Strategy |
|----------|-------------------|-------------|----------|
| Anthropic | Anthropic `tools` param | `tool_use` content block → ContentBlock | Direct mapping |
| OpenAI | OpenAI `tools` param (function calling) | `tool_calls` in message → ContentBlock | Schema transform |
| No tool support | System prompt injection (serialize tool schemas) | Parse JSON from LLM output → ContentBlock | Prompt injection fallback |

### Stream Adapter (adapters/stream_adapter.py)

```python
async def normalize_anthropic_stream(raw_stream) -> AsyncIterator[StreamChunk]:
    # content_block_start → tool_use_start
    # content_block_delta → text_delta / tool_use_delta
    # message_stop → message_end

async def normalize_openai_stream(raw_stream) -> AsyncIterator[StreamChunk]:
    # choices[0].delta.content → text_delta
    # choices[0].delta.tool_calls → tool_use_start/delta
    # choices[0].finish_reason → message_end
```

### Model Configuration (DB-backed)

```python
# DB tables
class ModelConfig(Base):
    name: str                      # Unique alias, e.g. "claude-sonnet"
    provider_type: str             # "anthropic" | "openai_compatible"
    model_id: str                  # Actual model ID
    api_key_encrypted: str | None  # Fernet encrypted
    base_url: str | None           # OpenAI-compatible endpoint
    supports_tool_use: bool = True
    supports_streaming: bool = True
    max_tokens_limit: int = 4096
    is_active: bool = True

class ModelRouteConfig(Base):
    task_type: str                 # "mentor_chat" | "content_analysis" | "evaluation" | "embedding"
    model_name: str                # → ModelConfig.name
```

### Model Router (router.py)

```python
class TaskType(str, Enum):
    MENTOR_CHAT = "mentor_chat"
    CONTENT_ANALYSIS = "content_analysis"
    EVALUATION = "evaluation"
    EMBEDDING = "embedding"

class ModelRouter:
    def __init__(self, db_session):
        self._cache: dict[str, LLMProvider] = {}
        self._cache_ttl = 300  # 5 min

    async def get_provider(self, task_type: TaskType) -> LLMProvider:
        # task_type → model_name (from route config) → Provider instance (cached)

    async def get_provider_by_name(self, name: str) -> LLMProvider:
        # Direct lookup by alias (for user-specified model)

    async def invalidate_cache(self):
        # Called when model config is updated via API
```

### API Endpoints for Model Management

```
POST   /api/models              # Add model config
GET    /api/models              # List all models
PUT    /api/models/{name}       # Update model config
DELETE /api/models/{name}       # Delete model
POST   /api/models/{name}/test  # Test connectivity (send simple prompt)

GET    /api/model-routes        # Get route mappings
PUT    /api/model-routes        # Update route mappings
```

### API Key Security

- Encrypted with `cryptography.fernet` before DB storage
- Encryption key from env var `LLM_ENCRYPTION_KEY`
- API responses show masked keys only (`sk-ant-***xxx`)

### Error Handling

```python
class LLMError(Exception): ...
class LLMRateLimitError(LLMError): ...
class LLMAuthError(LLMError): ...
class LLMTimeoutError(LLMError): ...

# Retry: exponential backoff, rate limit respects retry-after header
# Timeout: 60s default, configurable per provider
# Max retries: 3
```

### Provider Implementation Notes

**AnthropicProvider:**
- Uses `anthropic.AsyncAnthropic` SDK
- chat: `client.messages.create(stream=False)`
- chat_stream: `client.messages.stream()` → normalize_anthropic_stream
- Native tool use and streaming support
- SDK built-in timeout (60s) and retry (3x)

**OpenAICompatProvider:**
- Uses `openai.AsyncOpenAI` SDK with `base_url` switching
- Single implementation covers OpenAI / DeepSeek / Qwen / Ollama etc.
- chat: `client.chat.completions.create(stream=False)`
- chat_stream: `client.chat.completions.create(stream=True)` → normalize_openai_stream
- Tool use support depends on model; `supports_tool_use()` flag from DB config
- Auto-fallback to prompt injection when tool use not supported

---

## 5. Async Task Infrastructure

### Structure

```
backend/app/worker/
├── __init__.py
├── celery_app.py        # Celery instance, broker=redis/1, backend=redis/2
└── tasks/
    └── __init__.py      # Empty; Sub-project B adds task definitions here
```

### Configuration

- Broker: Redis DB 1 (separate from main cache DB 0)
- Result backend: Redis DB 2
- Serialization: JSON
- Task timeout: configurable per task
- Retry: configurable per task

### Task Status API

```
GET /api/tasks/{task_id}/status → { "state": "PENDING|STARTED|SUCCESS|FAILURE", "result": ... }
```

### Local Development

No Celery worker container in Docker Compose. Start manually:
```bash
celery -A app.worker.celery_app worker --loglevel=info
```

---

## 6. Testing Strategy

### Test Infrastructure (conftest.py)

- `test_db`: testcontainers for real PostgreSQL with pgvector
- `test_redis`: fakeredis or testcontainers
- `test_client`: httpx.AsyncClient + FastAPI TestClient
- `mock_anthropic`: mock anthropic SDK responses
- `mock_openai`: mock openai SDK responses

### Test Matrix

| Module | Type | What |
|--------|------|------|
| FastAPI skeleton | Integration | `/health` returns 200 + DB/Redis status |
| DB Models | Unit | Each ORM model CRUD; migration up/down |
| LLM base types | Unit | UnifiedMessage / ToolDefinition / StreamChunk serde |
| AnthropicProvider | Unit | Mock SDK; verify unified ↔ Anthropic format conversion |
| OpenAICompatProvider | Unit | Mock SDK; verify unified ↔ OpenAI format conversion |
| Tool Adapter | Unit | 3 scenarios (Anthropic/OpenAI/prompt injection) bidirectional |
| Stream Adapter | Unit | Mock SSE events → StreamChunk normalization |
| ModelRouter | Unit | task_type → correct Provider; cache hit/invalidation |
| Model Config API | Integration | CRUD + API key encryption/masking |
| Celery | Unit | Task submit + status query (mock broker) |

### Tools

- pytest + pytest-asyncio
- testcontainers-python (PostgreSQL)
- All LLM tests mock SDK — no real API calls

---

## 7. Dependencies

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    # Web framework
    "fastapi>=0.115",
    "uvicorn[standard]",

    # Database
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "pgvector",

    # LLM SDKs
    "anthropic>=0.40",
    "openai>=1.50",

    # Async tasks
    "celery[redis]",
    "redis",

    # Security
    "cryptography",

    # Utils
    "pydantic>=2.0",
    "pydantic-settings",
    "httpx",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "testcontainers[postgres]",
    "fakeredis",
    "httpx",  # for TestClient
]
```

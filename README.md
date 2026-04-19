# Socratiq

**Turn any YouTube / Bilibili video into an interactive AI-tutored course.**

Self-hosted. Supports Ollama, Claude, GPT, DeepSeek, and any OpenAI-compatible backend. Your data stays yours.

## Features

- **Video → Course** — Paste a URL, get a structured course with chapters, concepts, and learning path
- **AI Mentor** — Socratic teaching method: guides your thinking instead of giving answers
- **5-Layer Memory** — The AI remembers your learning history, strengths, and gaps across sessions
- **Exercises & Evaluation** — Auto-generated practice with AI-powered feedback
- **Spaced Repetition** — SM-2 algorithm schedules reviews for long-term retention
- **Knowledge Graph** — Visualize concept relationships with interactive D3.js graph
- **Citation Cards** — Every AI answer shows its sources with video timestamps or page numbers
- **Cold-Start Diagnostic** — Adaptive assessment to understand your level before you start
- **Multi-LLM** — Ollama (free/local), Claude, GPT, DeepSeek, Qwen, and more

## Quick Start

```bash
git clone https://github.com/catundercar/socratiq.git
cd socratiq
cp .env.example .env      # Ollama works out of the box
docker compose up
```

Open [http://localhost:3000](http://localhost:3000). The setup page will guide you through LLM configuration.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- One LLM backend:
  - **Ollama** (recommended for getting started): [Install Ollama](https://ollama.ai), then `ollama pull qwen2.5`
  - **API key** for OpenAI, Anthropic, or DeepSeek

## Supported LLM Providers

| Provider | Type | Models | Notes |
|----------|------|--------|-------|
| Ollama | Local | Qwen 2.5, Llama 3, Mistral, etc. | Free, private, no API key needed |
| Anthropic | Cloud | Claude Sonnet, Haiku, Opus | Best tool-use support |
| OpenAI | Cloud | GPT-4o, GPT-4o-mini | Widely available |
| DeepSeek | Cloud | DeepSeek V3, Chat | Affordable, strong Chinese |
| Any OpenAI-compatible | Cloud/Local | Qwen, GLM, Moonshot, Groq, etc. | Via custom base URL |

## Architecture

```
┌──────────────────────────────────────────┐
│  Frontend (Next.js + React)              │
│  ┌─────────┐ ┌────────┐ ┌────────────┐  │
│  │ Courses  │ │ Mentor │ │ Knowledge  │  │
│  │ & Learn  │ │  Chat  │ │   Graph    │  │
│  └────┬─────┘ └───┬────┘ └─────┬──────┘  │
│       └───────────┼────────────┘         │
└───────────────────┼──────────────────────┘
                    │ SSE / REST
┌───────────────────┼──────────────────────┐
│  Backend (FastAPI)│                      │
│  ┌────────────────┴────────────────┐     │
│  │        MentorAgent              │     │
│  │   ┌─────┐ ┌─────┐ ┌─────────┐  │     │
│  │   │ RAG │ │ SRS │ │ Memory  │  │     │
│  │   │ +   │ │     │ │ (5-layer│  │     │
│  │   │ Cite│ │     │ │  system)│  │     │
│  │   └──┬──┘ └─────┘ └─────────┘  │     │
│  └──────┼──────────────────────────┘     │
│         │                                │
│  ┌──────┴──────┐  ┌──────────────────┐   │
│  │  pgvector   │  │  LLM Router      │   │
│  │  (embeddings│  │  Anthropic/OpenAI │   │
│  │   + search) │  │  /Ollama/DeepSeek│   │
│  └─────────────┘  └──────────────────┘   │
└──────────────────────────────────────────┘
     PostgreSQL 16        Redis 7
```

## Development

### Local development (without Docker)

```bash
# Start infrastructure
docker compose up -d db redis

# Backend
cd backend
uv sync --extra dev
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

### Running tests

```bash
# Backend
cd backend && .venv/bin/pytest

# Frontend
cd frontend && npm test
```

## Roadmap

- [x] YouTube + Bilibili video ingestion
- [x] AI course generation
- [x] Socratic mentor chat (SSE streaming)
- [x] 5-layer memory system
- [x] Exercises with AI evaluation
- [x] Spaced repetition (SM-2)
- [x] Knowledge graph visualization
- [x] Multi-LLM backend support
- [x] Citation cards
- [ ] PDF / URL / Markdown content sources
- [ ] Gamification (streaks, achievements)
- [ ] Code sandbox (online execution)
- [ ] Multi-user auth (SaaS)
- [ ] Mobile responsive design

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding conventions, and PR guidelines.

## License

[AGPL-3.0](LICENSE) — free to use, modify, and self-host. If you build a hosted service on Socratiq, it must also be open source.

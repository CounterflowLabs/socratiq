# Contributing to Socratiq

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+ with [uv](https://github.com/astral-sh/uv)
- Node.js 22+
- Docker and Docker Compose
- PostgreSQL 16 with pgvector (or use Docker)
- Redis 7 (or use Docker)

### Getting started

```bash
# Clone the repo
git clone https://github.com/catundercar/socratiq.git
cd socratiq

# Start infrastructure
docker compose up -d db redis

# Backend
cd backend
uv sync --extra dev
cp ../.env.example ../.env  # Edit .env with your LLM config
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Running tests

```bash
cd backend && .venv/bin/pytest       # Backend tests
cd frontend && npm test              # Frontend tests
cd frontend && npm run lint          # Lint check
```

## Code Conventions

### Python (Backend)
- Async/await everywhere
- Type annotations required
- Pydantic v2 for validation
- pytest with `asyncio_mode = "auto"`

### TypeScript (Frontend)
- Strict mode enabled
- `@/*` path alias for `./src/*`
- kebab-case for component files
- Zustand for state management

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass
4. Keep PRs focused — one feature or fix per PR
5. Write a clear PR description explaining what and why

## Architecture

See [docs/architecture.md](docs/architecture.md) for system architecture details.

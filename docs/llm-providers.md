# LLM Provider Configuration

Socratiq supports multiple LLM backends through a unified abstraction layer.

## Quick Setup

The easiest way to configure your LLM is through the Setup page at `http://localhost:3000/setup` after launching Socratiq.

Alternatively, edit `.env` before starting:

## Ollama (Recommended for Getting Started)

Free, local, private. No API key needed.

1. Install: https://ollama.ai
2. Pull a model: `ollama pull qwen2.5`
3. Set in `.env`:
   ```
   OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
   ```

Recommended models:
- `qwen2.5` — Good all-around, strong Chinese support
- `llama3.1` — Strong English, good reasoning
- `mistral` — Fast, good for lighter tasks

## Anthropic (Claude)

Best tool-use support, recommended for production quality.

```
ANTHROPIC_API_KEY=sk-ant-xxx
```

Recommended: Claude Sonnet for mentor chat, Claude Haiku for content analysis.

## OpenAI

```
OPENAI_API_KEY=sk-xxx
```

Recommended: GPT-4o for mentor chat, GPT-4o-mini for light tasks.

## DeepSeek

Affordable, strong Chinese language support.

```
DEEPSEEK_API_KEY=sk-xxx
```

## Custom OpenAI-Compatible Providers

Any provider implementing the OpenAI Chat Completions API works. Configure through the Settings page or use environment variables with custom base URLs.

## Model Routing

Socratiq routes different tasks to different models:

| Task | Default | Purpose |
|------|---------|---------|
| Mentor Chat | Primary model | Main tutoring interaction |
| Content Analysis | Light model | Course generation, summarization |
| Evaluation | Primary model | Exercise grading, diagnostics |
| Embedding | Embedding model | Vector search (RAG) |

Configure via environment variables:
```
LLM_PRIMARY_MODEL=anthropic/claude-sonnet-4-20250514
LLM_LIGHT_MODEL=anthropic/claude-haiku-4-20250414
LLM_EMBEDDING_MODEL=openai/text-embedding-3-small
```

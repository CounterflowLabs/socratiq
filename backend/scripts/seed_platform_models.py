"""Seed platform-managed `ModelConfig` rows (user_id = NULL) from environment.

In the SaaS / closed-beta deployment, the platform owns LLM API keys — users
never see model config UI. This script is idempotent: re-running it after a
key rotation simply rewrites the encrypted blob. Designed to run on every
deploy after ``alembic upgrade head``.

Environment variables consumed
==============================

API keys (set any subset — at least one chat model is required)::

    PLATFORM_ANTHROPIC_KEY              # Anthropic API key
    PLATFORM_OPENAI_KEY                 # OpenAI API key
    PLATFORM_DEEPSEEK_KEY               # DeepSeek API key
    PLATFORM_QWEN_KEY                   # Aliyun Qwen / DashScope key
    PLATFORM_OPENAI_EMBEDDING_KEY       # Embedding-only key (falls back to OPENAI)

Optional per-model overrides::

    PLATFORM_ANTHROPIC_MODEL_ID         # default: claude-sonnet-4-5
    PLATFORM_OPENAI_MODEL_ID            # default: gpt-4o
    PLATFORM_DEEPSEEK_MODEL_ID          # default: deepseek-chat
    PLATFORM_QWEN_MODEL_ID              # default: qwen-plus
    PLATFORM_EMBEDDING_MODEL_ID         # default: text-embedding-3-small

Routing overrides (`<task_type>` is the literal route name)::

    PLATFORM_ROUTE_MENTOR_CHAT=platform-anthropic
    PLATFORM_ROUTE_CONTENT_ANALYSIS=platform-anthropic
    PLATFORM_ROUTE_EVALUATION=platform-anthropic
    PLATFORM_ROUTE_STRUCTURE_PLANNING=platform-anthropic
    PLATFORM_ROUTE_EMBEDDING=platform-openai-embedding

If a routing override is unset, the script picks the first available chat
model (anthropic → openai → deepseek → qwen) and assigns it to every chat
task. EMBEDDING defaults to the dedicated embedding model.

Usage::

    uv run python -m scripts.seed_platform_models
    uv run python -m scripts.seed_platform_models --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

from app.config import get_settings
from app.db.database import async_session_factory
from app.services.llm.config import ModelConfigManager


CHAT_TASK_TYPES = (
    "mentor_chat",
    "content_analysis",
    "evaluation",
    "structure_planning",
)
EMBEDDING_TASK_TYPE = "embedding"


@dataclass(slots=True)
class _ModelSpec:
    name: str
    provider_type: str
    model_id: str
    api_key_env: str
    model_type: str = "chat"
    base_url: str | None = None
    supports_tool_use: bool = True
    supports_streaming: bool = True
    max_tokens_limit: int = 8192


def _chat_specs() -> list[_ModelSpec]:
    return [
        _ModelSpec(
            name="platform-anthropic",
            provider_type="anthropic",
            model_id=os.environ.get(
                "PLATFORM_ANTHROPIC_MODEL_ID", "claude-sonnet-4-5"
            ),
            api_key_env="PLATFORM_ANTHROPIC_KEY",
            max_tokens_limit=int(
                os.environ.get("PLATFORM_ANTHROPIC_MAX_TOKENS", "8192")
            ),
        ),
        _ModelSpec(
            name="platform-openai",
            provider_type="openai",
            model_id=os.environ.get("PLATFORM_OPENAI_MODEL_ID", "gpt-4o"),
            api_key_env="PLATFORM_OPENAI_KEY",
        ),
        _ModelSpec(
            name="platform-deepseek",
            provider_type="openai_compatible",
            model_id=os.environ.get("PLATFORM_DEEPSEEK_MODEL_ID", "deepseek-chat"),
            api_key_env="PLATFORM_DEEPSEEK_KEY",
            base_url="https://api.deepseek.com/v1",
        ),
        _ModelSpec(
            name="platform-qwen",
            provider_type="openai_compatible",
            model_id=os.environ.get("PLATFORM_QWEN_MODEL_ID", "qwen-plus"),
            api_key_env="PLATFORM_QWEN_KEY",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ]


def _embedding_spec() -> _ModelSpec:
    return _ModelSpec(
        name="platform-openai-embedding",
        provider_type="openai",
        model_id=os.environ.get(
            "PLATFORM_EMBEDDING_MODEL_ID", "text-embedding-3-small"
        ),
        api_key_env="PLATFORM_OPENAI_EMBEDDING_KEY",
        model_type="embedding",
        supports_tool_use=False,
        supports_streaming=False,
    )


async def _upsert(
    db, manager: ModelConfigManager, spec: _ModelSpec, api_key: str
) -> bool:
    existing = await manager.get_model_by_name(db, spec.name)
    if existing is None:
        model = await manager.create_model(
            db,
            name=spec.name,
            provider_type=spec.provider_type,
            model_id=spec.model_id,
            model_type=spec.model_type,
            api_key=api_key,
            base_url=spec.base_url,
            supports_tool_use=spec.supports_tool_use,
            supports_streaming=spec.supports_streaming,
            max_tokens_limit=spec.max_tokens_limit,
        )
        # Mark as platform-managed.
        model.user_id = None
        await db.flush()
        return True
    await manager.update_model(
        db,
        spec.name,
        provider_type=spec.provider_type,
        model_id=spec.model_id,
        model_type=spec.model_type,
        api_key=api_key,
        base_url=spec.base_url,
        supports_tool_use=spec.supports_tool_use,
        supports_streaming=spec.supports_streaming,
        max_tokens_limit=spec.max_tokens_limit,
        is_active=True,
    )
    existing.user_id = None
    await db.flush()
    return False


def _pick_default_chat_model(present: dict[str, _ModelSpec]) -> str | None:
    """Prefer Anthropic → OpenAI → DeepSeek → Qwen as the default chat route."""
    for name in (
        "platform-anthropic",
        "platform-openai",
        "platform-deepseek",
        "platform-qwen",
    ):
        if name in present:
            return name
    return None


async def _run(dry_run: bool) -> None:
    settings = get_settings()
    if not settings.llm_encryption_key:
        raise SystemExit(
            "LLM_ENCRYPTION_KEY is empty; refusing to seed platform keys. "
            "Set it in your env before running."
        )

    manager = ModelConfigManager(settings.llm_encryption_key)

    chat_specs = [s for s in _chat_specs() if os.environ.get(s.api_key_env)]
    if not chat_specs:
        raise SystemExit(
            "No PLATFORM_*_KEY chat env vars are set. At minimum, configure one of: "
            "PLATFORM_ANTHROPIC_KEY, PLATFORM_OPENAI_KEY, PLATFORM_DEEPSEEK_KEY, "
            "PLATFORM_QWEN_KEY."
        )

    emb_spec = _embedding_spec()
    embedding_key = (
        os.environ.get(emb_spec.api_key_env)
        or os.environ.get("PLATFORM_OPENAI_KEY")  # fall back to chat key
    )

    print(f"chat models to upsert: {[s.name for s in chat_specs]}")
    if embedding_key:
        print(f"embedding model: {emb_spec.name}")
    else:
        print("embedding model: SKIPPED (no key)")

    if dry_run:
        print("--dry-run set, exiting without DB writes.")
        return

    async with async_session_factory() as session:
        try:
            present: dict[str, _ModelSpec] = {}
            for spec in chat_specs:
                key = os.environ[spec.api_key_env]
                created = await _upsert(session, manager, spec, key)
                present[spec.name] = spec
                print(
                    f"  {'created' if created else 'updated'}: {spec.name} "
                    f"({spec.provider_type}:{spec.model_id})"
                )

            if embedding_key:
                created = await _upsert(session, manager, emb_spec, embedding_key)
                present[emb_spec.name] = emb_spec
                print(
                    f"  {'created' if created else 'updated'}: {emb_spec.name} "
                    f"({emb_spec.provider_type}:{emb_spec.model_id})"
                )

            default_chat = _pick_default_chat_model(present)
            for task in CHAT_TASK_TYPES:
                env_key = f"PLATFORM_ROUTE_{task.upper()}"
                target = os.environ.get(env_key) or default_chat
                if not target or target not in present:
                    print(f"  route {task}: SKIPPED (no model available)")
                    continue
                await manager.update_route_config(session, task, target)
                print(f"  route {task} -> {target}")

            if embedding_key and emb_spec.name in present:
                target = (
                    os.environ.get(
                        f"PLATFORM_ROUTE_{EMBEDDING_TASK_TYPE.upper()}"
                    )
                    or emb_spec.name
                )
                if target in present:
                    await manager.update_route_config(
                        session, EMBEDDING_TASK_TYPE, target
                    )
                    print(f"  route {EMBEDDING_TASK_TYPE} -> {target}")

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    print("done.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without touching the database.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()

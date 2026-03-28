"""API routes for content source management."""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.source import Source
from app.db.models.user import User
from app.models.source import SourceResponse, SourceListResponse
from app.services.content_key import extract_content_key
from celery import chain
from app.worker.tasks.content_ingestion import ingest_source, clone_source
from app.worker.tasks.course_generation import generate_course_task

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])



@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
    goal: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SourceResponse:
    """Submit a URL or upload a file for content ingestion."""
    if not url and not file:
        raise HTTPException(400, "Either 'url' or 'file' must be provided")

    metadata: dict = {}

    if file:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are supported")

        source_type = "pdf"
        title = title or file.filename

        upload_dir = Path(get_settings().upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_id = str(uuid.uuid4())
        file_path = upload_dir / f"{file_id}.pdf"

        content = await file.read()
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(413, "File too large (max 50MB)")
        file_path.write_bytes(content)

        metadata = {
            "file_path": f"{file_id}.pdf",
            "original_filename": file.filename,
            "file_size": len(content),
        }
    else:
        if not source_type:
            source_type = _detect_source_type(url)
        if source_type not in ("bilibili", "youtube"):
            raise HTTPException(400, f"Unsupported source type: {source_type}")

    # --- Validate required model tiers are correctly configured ---
    from app.services.llm.config import ModelConfigManager
    from app.db.models.model_config import ModelConfig as ModelConfigModel
    tier_manager = ModelConfigManager(get_settings().llm_encryption_key)
    existing_tiers = await tier_manager.get_tier_configs(db)
    configured_tiers = {c.tier: c.model_name for c in existing_tiers}
    problems = []
    if "light" not in configured_tiers:
        problems.append("轻量任务模型 (light) 未配置")
    if "embedding" not in configured_tiers:
        problems.append("向量计算模型 (embedding) 未配置")
    else:
        # Verify the embedding tier actually has an embedding-type model
        embed_model = (await db.execute(
            select(ModelConfigModel).where(ModelConfigModel.name == configured_tiers["embedding"])
        )).scalar_one_or_none()
        if embed_model and embed_model.model_type != "embedding":
            problems.append(f"向量计算 tier 绑定了对话模型 '{embed_model.name}'，请在设置页面更换为向量模型")
    # Verify that configured models have API keys (for remote providers)
    for tier_name, model_name in configured_tiers.items():
        model_obj = (await db.execute(
            select(ModelConfigModel).where(ModelConfigModel.name == model_name)
        )).scalar_one_or_none()
        if model_obj and model_obj.provider_type != "openai_compatible":
            # Non-local providers need API key
            if not model_obj.api_key_encrypted:
                tier_label = {"primary": "主交互", "light": "轻量任务", "strong": "复杂推理", "embedding": "向量计算"}.get(tier_name, tier_name)
                problems.append(f"{tier_label}模型 '{model_name}' 未配置 API Key")

    # For video sources, check Whisper ASR config
    if source_type in ("youtube", "bilibili"):
        from app.db.models.whisper_config import WhisperConfig as WhisperConfigModel
        whisper_result = await db.execute(
            select(WhisperConfigModel).where(WhisperConfigModel.user_id == user.id)
        )
        whisper_config = whisper_result.scalar_one_or_none()
        whisper_has_key = bool(whisper_config and whisper_config.api_key_encrypted)
        env_has_key = bool(get_settings().whisper_api_key and get_settings().whisper_api_key != "gsk_填入你的Groq_Key")
        if not whisper_has_key and not env_has_key:
            problems.append("语音识别 (Whisper) API Key 未配置，请在设置页面配置")

    if problems:
        raise HTTPException(400, f"配置问题: {'; '.join(problems)}")

    # --- Compute content_key ---
    file_content_bytes = content if file else None
    ck = extract_content_key(source_type, url=url, file_content=file_content_bytes)

    # --- Same-user dedup ---
    if ck:
        existing = (await db.execute(
            select(Source).where(
                Source.content_key == ck,
                Source.created_by == user.id,
                Source.status != "error",
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "该资源已导入或正在处理中",
                    "existing_source": _source_to_response(existing).model_dump(mode="json"),
                },
            )

    # --- Cross-user ref_source lookup ---
    ref_source = None
    if ck:
        ref_source = (await db.execute(
            select(Source).where(
                Source.content_key == ck,
                Source.status != "error",
                Source.created_by != user.id,
            ).order_by(Source.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    source = Source(
        type=source_type,
        url=url,
        title=title,
        status="waiting_donor" if ref_source else "pending",
        metadata_=metadata,
        created_by=user.id,
        content_key=ck,
        ref_source_id=ref_source.id if ref_source else None,
    )
    db.add(source)
    await db.flush()

    if ref_source and ref_source.status == "ready":
        pipeline = chain(
            clone_source.s(str(source.id), str(ref_source.id)),
            generate_course_task.s(goal=goal, user_id=str(user.id)),
        )
        result = pipeline.delay()
        source.celery_task_id = result.parent.id if result.parent else result.id
    elif ref_source:
        # Ref still processing — Redis subscriber will dispatch chain when ready
        source.metadata_ = {**source.metadata_, "pending_goal": goal, "pending_user_id": str(user.id)}
    else:
        pipeline = chain(
            ingest_source.s(str(source.id)),
            generate_course_task.s(goal=goal, user_id=str(user.id)),
        )
        result = pipeline.delay()
        source.celery_task_id = result.parent.id if result.parent else result.id

    await db.commit()
    await db.refresh(source)

    return _source_to_response(source)


@router.get("", response_model=SourceListResponse)
async def list_sources(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    skip: int = 0,
    limit: int = 20,
) -> SourceListResponse:
    """List all content sources with pagination."""
    result = await db.execute(
        select(Source)
        .where(Source.created_by == user.id)
        .order_by(Source.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    sources = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(Source).where(Source.created_by == user.id)
    )
    total = count_result.scalar()

    return SourceListResponse(
        items=[_source_to_response(s) for s in sources],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/active", response_model=list[SourceResponse])
async def list_active_sources(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> list[SourceResponse]:
    """List sources that are still being processed (not ready/error)."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    result = await db.execute(
        select(Source)
        .where(
            Source.created_by == user.id,
            Source.status.notin_(["ready", "error"]),
            Source.celery_task_id.is_not(None),
            Source.created_at > cutoff,
        )
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()
    return [_source_to_response(s) for s in sources]


@router.post("/{source_id}/cancel")
async def cancel_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SourceResponse:
    """Cancel an in-progress source ingestion."""
    from celery.result import AsyncResult
    from app.worker.celery_app import celery_app

    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.created_by == user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")
    if source.status in ("ready", "error"):
        raise HTTPException(400, "Source is not in progress")

    # Mark as cancelled in DB first (this is the source of truth)
    source.status = "error"
    source.metadata_ = {**source.metadata_, "error": "用户取消"}
    await db.commit()
    await db.refresh(source)

    # Best-effort revoke Celery task (non-blocking, non-critical)
    if source.celery_task_id:
        try:
            import asyncio
            task_id = source.celery_task_id
            await asyncio.to_thread(
                lambda: AsyncResult(task_id, app=celery_app).revoke(terminate=True)
            )
        except Exception:
            pass  # Task may already be done or lost

    return _source_to_response(source)


@router.post("/{source_id}/retry")
async def retry_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SourceResponse:
    """Retry a failed source ingestion."""
    # Validate required model tiers (same check as create_source)
    from app.services.llm.config import ModelConfigManager
    from app.db.models.model_config import ModelConfig as ModelConfigModel
    tier_manager = ModelConfigManager(get_settings().llm_encryption_key)
    existing_tiers = await tier_manager.get_tier_configs(db)
    configured_tiers = {c.tier: c.model_name for c in existing_tiers}
    problems = []
    if "light" not in configured_tiers:
        problems.append("轻量任务模型 (light) 未配置")
    if "embedding" not in configured_tiers:
        problems.append("向量计算模型 (embedding) 未配置")
    else:
        embed_model = (await db.execute(
            select(ModelConfigModel).where(ModelConfigModel.name == configured_tiers["embedding"])
        )).scalar_one_or_none()
        if embed_model and embed_model.model_type != "embedding":
            problems.append(f"向量计算 tier 绑定了对话模型 '{embed_model.name}'，请在设置页面更换为向量模型")
    if problems:
        raise HTTPException(400, f"模型配置问题: {'; '.join(problems)}")

    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.created_by == user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")
    if source.status != "error":
        raise HTTPException(400, "Only failed sources can be retried")

    # Reset status and clear error
    source.status = "pending"
    source.metadata_ = {k: v for k, v in source.metadata_.items() if k != "error"}

    # Re-dispatch pipeline
    goal = source.metadata_.get("pending_goal")
    user_id = str(user.id)

    pipeline = chain(
        ingest_source.s(str(source.id)),
        generate_course_task.s(goal=goal, user_id=user_id),
    )
    task_result = pipeline.delay()
    source.celery_task_id = task_result.id

    await db.commit()
    await db.refresh(source)
    return _source_to_response(source)


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SourceResponse:
    """Get a single source by ID."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.created_by == user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")
    return _source_to_response(source)


def _detect_source_type(url: str | None) -> str:
    if not url:
        raise HTTPException(400, "URL is required for non-file sources")
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    raise HTTPException(400, f"Cannot detect source type from URL: {url}")


def _source_to_response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        type=source.type,
        url=source.url,
        title=source.title,
        status=source.status,
        metadata_=source.metadata_,
        task_id=source.celery_task_id,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )

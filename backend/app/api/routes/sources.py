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
from app.worker.tasks.content_ingestion import ingest_source, clone_source

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])



@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
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
            "file_path": str(file_path.resolve()),
            "original_filename": file.filename,
            "file_size": len(content),
        }
    else:
        if not source_type:
            source_type = _detect_source_type(url)
        if source_type not in ("bilibili", "youtube"):
            raise HTTPException(400, f"Unsupported source type: {source_type}")

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
        task = clone_source.delay(str(source.id), str(ref_source.id))
        source.celery_task_id = task.id
    elif ref_source:
        # Ref still processing — Redis subscriber will dispatch clone when ready
        pass
    else:
        task = ingest_source.delay(str(source.id))
        source.celery_task_id = task.id

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
    result = await db.execute(
        select(Source)
        .where(
            Source.created_by == user.id,
            Source.status.notin_(["ready", "error"]),
            Source.celery_task_id.is_not(None),
        )
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()
    return [_source_to_response(s) for s in sources]


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

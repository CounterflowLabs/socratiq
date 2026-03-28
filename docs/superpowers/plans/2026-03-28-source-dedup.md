# Source Deduplication & Cross-User Content Clone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate ingestion of the same content by deduplicating via `content_key` (BV号/Video ID/MD5), and clone content from existing ready sources for cross-user imports.

**Architecture:** Each Source gets a `content_key` computed at creation time. Same-user duplicates are rejected (409). Cross-user duplicates either clone immediately (ref ready) or wait via Redis pub/sub (ref in-progress). The ingestion pipeline publishes completion/failure events; a subscriber thread in the Celery worker dispatches clone tasks or marks waiters as error.

**Tech Stack:** Python (FastAPI, Celery, SQLAlchemy, Redis pub/sub), Alembic, TypeScript (Next.js)

**Spec:** `docs/superpowers/specs/2026-03-28-source-dedup-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/db/models/source.py` | Modify | Add `content_key` + `ref_source_id` columns |
| `backend/alembic/versions/XXXX_add_content_key_ref_source_id.py` | Create | Migration |
| `backend/app/services/content_key.py` | Create | `extract_content_key()` function |
| `backend/tests/test_content_key.py` | Create | Tests for content_key extraction |
| `backend/app/api/routes/sources.py` | Modify | Dedup check + conditional dispatch |
| `backend/app/worker/tasks/content_ingestion.py` | Modify | `clone_source` task + Redis publish on complete/fail |
| `backend/app/worker/ref_subscriber.py` | Create | Redis subscriber background thread |
| `backend/app/worker/celery_app.py` | Modify | Register subscriber via `worker_ready` signal |
| `frontend/src/lib/api.ts` | Modify | `DuplicateSourceError` + 409 handling |
| `frontend/src/app/import/page.tsx` | Modify | Friendly error messages |
| `frontend/src/app/page.tsx` | Modify | `waiting_donor` state label |

---

### Task 1: Add `content_key` and `ref_source_id` columns to Source

**Files:**
- Modify: `backend/app/db/models/source.py`
- Create: Alembic migration (autogenerate)

- [ ] **Step 1: Add columns to ORM model**

In `backend/app/db/models/source.py`, add after `celery_task_id` (before `created_by`):

```python
content_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
ref_source_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("sources.id"), nullable=True
)
```

- [ ] **Step 2: Generate Alembic migration**

```bash
cd /home/tulip/project/socratiq/backend
uv run alembic revision --autogenerate -m "add content_key and ref_source_id to sources"
```

- [ ] **Step 3: Apply migration**

```bash
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/source.py backend/alembic/versions/*content_key*
git commit -m "feat: add content_key and ref_source_id columns to sources

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Create `content_key` extraction service

**Files:**
- Create: `backend/app/services/content_key.py`
- Create: `backend/tests/test_content_key.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_content_key.py`:

```python
"""Tests for content_key extraction."""

import pytest
from app.services.content_key import extract_content_key


class TestExtractContentKey:
    # --- Bilibili ---
    def test_bilibili_standard_url(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/video/BV1gZ4y1F7hS") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_short_url(self):
        assert extract_content_key("bilibili", url="https://b23.tv/BV1gZ4y1F7hS") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_with_query_params(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/video/BV1gZ4y1F7hS?p=1&t=30") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_invalid_url(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/some/other/page") is None

    # --- YouTube ---
    def test_youtube_standard_url(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/watch?v=kCc8FmEb1nY") == "youtube:kCc8FmEb1nY"

    def test_youtube_short_url(self):
        assert extract_content_key("youtube", url="https://youtu.be/kCc8FmEb1nY") == "youtube:kCc8FmEb1nY"

    def test_youtube_with_extra_params(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/watch?v=kCc8FmEb1nY&list=PLxxx&t=120") == "youtube:kCc8FmEb1nY"

    def test_youtube_invalid_url(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/channel/UCxxx") is None

    # --- PDF ---
    def test_pdf_md5(self):
        content = b"hello world pdf content"
        result = extract_content_key("pdf", file_content=content)
        assert result is not None
        assert result.startswith("pdf:")
        assert len(result) == 4 + 32  # "pdf:" + 32-char md5 hex

    def test_pdf_same_content_same_key(self):
        content = b"identical content"
        key1 = extract_content_key("pdf", file_content=content)
        key2 = extract_content_key("pdf", file_content=content)
        assert key1 == key2

    def test_pdf_different_content_different_key(self):
        key1 = extract_content_key("pdf", file_content=b"content A")
        key2 = extract_content_key("pdf", file_content=b"content B")
        assert key1 != key2

    # --- Edge cases ---
    def test_unknown_type(self):
        assert extract_content_key("markdown", url="https://example.com") is None

    def test_no_url_no_file(self):
        assert extract_content_key("bilibili") is None

    # --- content_key_hash ---
    def test_content_key_hash(self):
        from app.services.content_key import content_key_hash
        h = content_key_hash("bilibili:BV1gZ4y1F7hS")
        assert isinstance(h, str)
        assert len(h) == 16
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tulip/project/socratiq/backend
uv run pytest tests/test_content_key.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `content_key.py`**

Create `backend/app/services/content_key.py`:

```python
"""Content key extraction for source deduplication."""

import hashlib
import re


def extract_content_key(
    source_type: str,
    url: str | None = None,
    file_content: bytes | None = None,
) -> str | None:
    """Extract a unique content key for deduplication.

    Returns a string like "bilibili:BV1gZ4y1F7hS", "youtube:kCc8FmEb1nY",
    or "pdf:a1b2c3d4..." — or None if extraction fails.
    """
    if source_type == "bilibili" and url:
        match = re.search(r"(BV[a-zA-Z0-9]{10})", url)
        return f"bilibili:{match.group(1)}" if match else None

    elif source_type == "youtube" and url:
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return f"youtube:{match.group(1)}" if match else None

    elif source_type == "pdf" and file_content:
        md5 = hashlib.md5(file_content).hexdigest()
        return f"pdf:{md5}"

    return None


def content_key_hash(key: str) -> str:
    """Short hash of a content_key for use in Redis channel names."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_content_key.py -v
```

Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/content_key.py backend/tests/test_content_key.py
git commit -m "feat: add content_key extraction service for source dedup

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add dedup logic to source creation API

**Files:**
- Modify: `backend/app/api/routes/sources.py`

- [ ] **Step 1: Add imports**

At the top of `backend/app/api/routes/sources.py`, add:

```python
from app.services.content_key import extract_content_key
from app.worker.tasks.content_ingestion import ingest_source, clone_source
```

Replace the existing single import:
```python
from app.worker.tasks.content_ingestion import ingest_source
```

- [ ] **Step 2: Compute content_key and add dedup check in `create_source`**

After the `else` block that validates `source_type` (line 63) and before `source = Source(...)` (line 65), insert:

```python
    # --- Compute content_key ---
    file_content_bytes = content if file else None  # `content` is the PDF bytes read above
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
```

Note: for the PDF branch, the variable `content` (file bytes) is defined at line 49. For URL branches, `file_content_bytes` will be `None` and that's fine — `extract_content_key` uses `url` instead.

- [ ] **Step 3: Update Source creation to include new fields**

Replace the `source = Source(...)` block with:

```python
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
```

- [ ] **Step 4: Update task dispatch to handle clone vs ingest**

Replace the existing dispatch block:

```python
    task = ingest_source.delay(str(source.id))
    source.celery_task_id = task.id
    await db.commit()
    await db.refresh(source)
```

With:

```python
    if ref_source and ref_source.status == "ready":
        # Ref already done — clone immediately
        task = clone_source.delay(str(source.id), str(ref_source.id))
        source.celery_task_id = task.id
    elif ref_source:
        # Ref still processing — no task yet, Redis subscriber will dispatch
        pass
    else:
        # No ref — normal pipeline
        task = ingest_source.delay(str(source.id))
        source.celery_task_id = task.id

    await db.commit()
    await db.refresh(source)

    return _source_to_response(source)
```

- [ ] **Step 5: Verify syntax**

```bash
uv run python -c "from app.api.routes.sources import router; print('OK')"
```

Expected: `OK` (will fail until Task 4 creates `clone_source`, so skip this check for now — it will be verified in Task 7).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/sources.py
git commit -m "feat: add content_key dedup + cross-user ref_source matching to source creation

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Add `clone_source` task + Redis publish to ingestion pipeline

**Files:**
- Modify: `backend/app/worker/tasks/content_ingestion.py`

- [ ] **Step 1: Add `clone_source` Celery task**

After the `ingest_source` function (after line 25), add:

```python
@celery_app.task(
    bind=True,
    name="content_ingestion.clone_source",
    max_retries=1,
    default_retry_delay=10,
    soft_time_limit=60,
    time_limit=90,
)
def clone_source(self, source_id: str, ref_source_id: str) -> dict:
    """Clone content from a ready ref_source to a new source. No LLM calls."""
    import asyncio
    return asyncio.run(_clone_source_async(self, source_id, ref_source_id))
```

- [ ] **Step 2: Implement `_clone_source_async`**

Add after `clone_source`:

```python
async def _clone_source_async(task, source_id: str, ref_source_id: str) -> dict:
    """Async implementation of content cloning."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.concept import ConceptSource
    from app.config import get_settings

    settings = get_settings()
    worker_engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    worker_session_factory = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with worker_session_factory() as db:
            from uuid import UUID
            sid = UUID(source_id)
            ref_sid = UUID(ref_source_id)

            target = await db.get(Source, sid)
            ref = await db.get(Source, ref_sid)

            if not target or not ref or ref.status != "ready":
                if target:
                    target.status = "error"
                    target.metadata_ = {**target.metadata_, "error": "引用源不可用"}
                    await db.commit()
                return {"source_id": source_id, "status": "error", "reason": "ref_source not ready"}

            task.update_state(state="PROGRESS", meta={"stage": "cloning"})

            # Copy scalar fields
            target.title = target.title or ref.title
            target.raw_content = ref.raw_content
            target.metadata_ = {**ref.metadata_}
            await db.flush()

            # Clone ContentChunks
            result = await db.execute(
                select(ContentChunkModel).where(ContentChunkModel.source_id == ref_sid)
            )
            ref_chunks = result.scalars().all()
            chunk_count = 0
            for chunk in ref_chunks:
                new_chunk = ContentChunkModel(
                    source_id=sid,
                    text=chunk.text,
                    embedding=chunk.embedding,
                    metadata_=dict(chunk.metadata_),
                )
                db.add(new_chunk)
                chunk_count += 1
            await db.flush()

            # Clone ConceptSource links
            cs_result = await db.execute(
                select(ConceptSource).where(ConceptSource.source_id == ref_sid)
            )
            ref_concept_sources = cs_result.scalars().all()
            concept_count = 0
            for cs in ref_concept_sources:
                # Check if link already exists (unlikely but safe)
                existing = await db.execute(
                    select(ConceptSource).where(
                        ConceptSource.concept_id == cs.concept_id,
                        ConceptSource.source_id == sid,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(ConceptSource(
                        concept_id=cs.concept_id,
                        source_id=sid,
                        context=cs.context,
                    ))
                    concept_count += 1
            await db.flush()

            # Mark ready
            target.status = "ready"
            await db.commit()

            logger.info(f"Cloned source {source_id} from ref {ref_source_id}: {chunk_count} chunks, {concept_count} concepts")
            return {
                "source_id": source_id,
                "ref_source_id": ref_source_id,
                "chunks_cloned": chunk_count,
                "concepts_linked": concept_count,
                "status": "ready",
            }
    finally:
        await worker_engine.dispose()
```

- [ ] **Step 3: Add Redis publish at end of ingest pipeline**

In `_ingest_source_async`, at the end of the success path (after `await db.commit()`, before `return`), add:

```python
                # Notify waiting sources via Redis
                _publish_source_done(source, "ready")
```

In the except block (after `await db.commit()`, before `raise`), add:

```python
                _publish_source_done(source, "error")
```

- [ ] **Step 4: Implement `_publish_source_done` helper**

Add at module level (after the helper functions at the bottom):

```python
def _publish_source_done(source, status: str) -> None:
    """Publish source completion/failure event to Redis."""
    import json
    import redis
    from app.config import get_settings
    from app.services.content_key import content_key_hash

    if not source.content_key:
        return

    settings = get_settings()
    try:
        r = redis.Redis.from_url(settings.redis_url)
        channel = f"source:done:{content_key_hash(source.content_key)}"
        payload = json.dumps({"source_id": str(source.id), "status": status})
        r.publish(channel, payload)
        logger.info(f"Published {status} to {channel}")
    except Exception as e:
        logger.warning(f"Failed to publish source done event: {e}")
```

- [ ] **Step 5: Verify syntax**

```bash
uv run python -c "from app.worker.tasks.content_ingestion import ingest_source, clone_source; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/tasks/content_ingestion.py
git commit -m "feat: add clone_source task + Redis publish on ingestion complete/fail

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Create Redis subscriber for source completion events

**Files:**
- Create: `backend/app/worker/ref_subscriber.py`
- Modify: `backend/app/worker/celery_app.py`

- [ ] **Step 1: Create subscriber module**

Create `backend/app/worker/ref_subscriber.py`:

```python
"""Redis subscriber that listens for source completion events and triggers clone tasks."""

import json
import logging
import threading

import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)


def start_ref_subscriber() -> None:
    """Start the Redis subscriber in a daemon thread. Call from worker_ready signal."""
    thread = threading.Thread(target=_run_subscriber, daemon=True, name="ref-subscriber")
    thread.start()
    logger.info("Started ref_source subscriber thread")


def _run_subscriber() -> None:
    """Subscribe to source:done:* and handle events."""
    import asyncio

    settings = get_settings()
    r = redis.Redis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    pubsub.psubscribe("source:done:*")

    logger.info("Ref subscriber listening on source:done:*")
    for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        try:
            payload = json.loads(message["data"])
            source_id = payload["source_id"]
            status = payload["status"]
            logger.info(f"Ref subscriber received: source={source_id} status={status}")
            asyncio.run(_handle_source_done(source_id, status))
        except Exception as e:
            logger.error(f"Ref subscriber error handling message: {e}", exc_info=True)


async def _handle_source_done(ref_source_id: str, status: str) -> None:
    """Find waiting sources and dispatch clone or mark error."""
    from uuid import UUID
    from app.db.models.source import Source

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=5)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            ref_sid = UUID(ref_source_id)
            result = await db.execute(
                select(Source).where(
                    Source.ref_source_id == ref_sid,
                    Source.status == "waiting_donor",
                )
            )
            waiters = result.scalars().all()

            if not waiters:
                return

            logger.info(f"Found {len(waiters)} waiting sources for ref {ref_source_id}")

            if status == "ready":
                from app.worker.tasks.content_ingestion import clone_source
                for waiter in waiters:
                    task = clone_source.delay(str(waiter.id), ref_source_id)
                    waiter.celery_task_id = task.id
                    waiter.status = "pending"  # transition from waiting_donor to pending
                    logger.info(f"Dispatched clone_source for {waiter.id}")
            else:
                # ref failed — mark all waiters as error
                for waiter in waiters:
                    waiter.status = "error"
                    waiter.metadata_ = {**waiter.metadata_, "error": "引用源处理失败"}
                    logger.info(f"Marked waiter {waiter.id} as error (ref failed)")

            await db.commit()
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Register subscriber in celery_app.py**

In `backend/app/worker/celery_app.py`, add after the task imports (after line 28):

```python
from celery.signals import worker_ready

@worker_ready.connect
def on_worker_ready(**kwargs):
    from app.worker.ref_subscriber import start_ref_subscriber
    start_ref_subscriber()
```

- [ ] **Step 3: Verify syntax**

```bash
uv run python -c "from app.worker.celery_app import celery_app; print('OK')"
uv run python -c "from app.worker.ref_subscriber import start_ref_subscriber; print('OK')"
```

Expected: Both print `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/ref_subscriber.py backend/app/worker/celery_app.py
git commit -m "feat: add Redis subscriber for cross-user source clone events

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Frontend — 409 handling + waiting_donor state

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/import/page.tsx`
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Add `DuplicateSourceError` and 409 handling in `api.ts`**

In `frontend/src/lib/api.ts`, add before `createSourceFromURL` (before line 19):

```typescript
export class DuplicateSourceError extends Error {
  existingSource: SourceResponse | null;
  constructor(message: string, existingSource: SourceResponse | null) {
    super(message);
    this.name = "DuplicateSourceError";
    this.existingSource = existingSource;
  }
}
```

In `createSourceFromURL`, replace:

```typescript
  if (!res.ok) throw new Error(await res.text());
```

With:

```typescript
  if (res.status === 409) {
    const body = await res.json();
    throw new DuplicateSourceError(
      body.detail?.message || "该资源已导入或正在处理中",
      body.detail?.existing_source ?? null,
    );
  }
  if (!res.ok) throw new Error(await res.text());
```

Do the same replacement in `createSourceFromFile`.

- [ ] **Step 2: Handle `DuplicateSourceError` in import page**

In `frontend/src/app/import/page.tsx`, add import:

```typescript
import { createSourceFromURL, createSourceFromFile, DuplicateSourceError } from "@/lib/api";
```

Replace the existing import:
```typescript
import { createSourceFromURL, createSourceFromFile } from "@/lib/api";
```

Replace the catch block (line 66-69):

```typescript
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "导入失败，请检查链接或文件后重试");
      setLoading(false);
    }
```

With:

```typescript
    } catch (err) {
      if (err instanceof DuplicateSourceError) {
        const existing = err.existingSource;
        if (existing?.status === "ready") {
          setErrorMsg("该资源已导入完成，无需重复导入");
        } else {
          setErrorMsg("该资源正在导入中，请稍候查看");
        }
      } else {
        setErrorMsg(err instanceof Error ? err.message : "导入失败，请检查链接或文件后重试");
      }
      setLoading(false);
    }
```

- [ ] **Step 3: Add `waiting_donor` to Dashboard state labels**

In `frontend/src/app/page.tsx`, add to `taskStateLabel` labels object (after `embedding` line):

```typescript
    waiting_donor: "复用已有资源中...",
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/import/page.tsx frontend/src/app/page.tsx
git commit -m "feat: frontend 409 duplicate handling + waiting_donor state label

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Integration verification

- [ ] **Step 1: Run all backend tests**

```bash
cd /home/tulip/project/socratiq/backend
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All new tests pass. Pre-existing failures (health, smoke needing DB) are acceptable.

- [ ] **Step 2: Verify all imports**

```bash
uv run python -c "from app.api.routes.sources import router; print('sources OK')"
uv run python -c "from app.worker.tasks.content_ingestion import ingest_source, clone_source; print('tasks OK')"
uv run python -c "from app.worker.ref_subscriber import start_ref_subscriber; print('subscriber OK')"
uv run python -c "from app.worker.celery_app import celery_app; print('celery OK')"
```

Expected: All print OK.

- [ ] **Step 3: Test 409 with curl**

```bash
# Create a source
curl -s -X POST http://localhost:8000/api/v1/sources -F "url=https://www.bilibili.com/video/BV1gZ4y1F7hS" | python3 -m json.tool

# Try to create same source again — should get 409
curl -s -w "\n%{http_code}" -X POST http://localhost:8000/api/v1/sources -F "url=https://www.bilibili.com/video/BV1gZ4y1F7hS"
```

Expected: First call returns 201, second returns 409.

- [ ] **Step 4: Commit any fixups**

Only if integration tests revealed issues.

---

## Self-Review

**Spec coverage:**
- ✅ content_key extraction (Bilibili BV, YouTube ID, PDF MD5) — Task 2
- ✅ Same-user dedup (409) — Task 3
- ✅ Cross-user ref_source ready → clone — Task 3 + 4
- ✅ Cross-user ref_source in-progress → waiting_donor + Redis — Task 3 + 5
- ✅ Ref failure → waiters error — Task 5
- ✅ clone_source task — Task 4
- ✅ Redis publish on complete/fail — Task 4
- ✅ Redis subscriber thread — Task 5
- ✅ Frontend 409 handling — Task 6
- ✅ waiting_donor state label — Task 6

**Placeholder scan:** No TBD/TODO/placeholder found.

**Type consistency:** `extract_content_key` signature matches across Task 2 (implementation) and Task 3 (usage). `clone_source` matches Task 4 (definition) and Task 3/5 (dispatch). `content_key_hash` matches Task 2 (definition) and Task 4 (usage).

---

Plan complete and saved to `docs/superpowers/plans/2026-03-28-source-dedup.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
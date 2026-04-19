import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models.source import Source
from app.db.models.source_task import SourceTask


@pytest.mark.asyncio
async def test_create_source_persists_processing_task(client, db_session):
    with patch("app.api.routes.sources.ingest_source") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "fake-task-001"
        mock_task.delay.return_value = mock_result

        res = await client.post("/api/v1/sources", data={
            "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
        })

    assert res.status_code == 201
    source_id = uuid.UUID(res.json()["id"])
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source_id)
        )
    ).scalars().all()

    assert len(tasks) == 1
    assert tasks[0].task_type == "source_processing"
    assert tasks[0].status == "pending"
    assert tasks[0].celery_task_id == "fake-task-001"


@pytest.mark.asyncio
async def test_create_clone_source_persists_processing_task(client, db_session, demo_user):
    donor = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=donor",
        title="Donor source",
        status="ready",
        content_key="shared-key",
        created_by=demo_user.id,
    )
    db_session.add(donor)
    await db_session.flush()

    with patch("app.api.routes.sources.extract_content_key", return_value="shared-key"):
        with patch("app.api.routes.sources.clone_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-clone-task-001"
            mock_task.delay.return_value = mock_result

            res = await client.post("/api/v1/sources", data={
                "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            })

    assert res.status_code == 201
    source_id = uuid.UUID(res.json()["id"])
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source_id)
        )
    ).scalars().all()

    assert len(tasks) == 1
    assert tasks[0].task_type == "source_processing"
    assert tasks[0].status == "pending"
    assert tasks[0].celery_task_id == "fake-clone-task-001"

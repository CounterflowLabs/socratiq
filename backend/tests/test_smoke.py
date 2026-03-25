"""Backend smoke tests -- critical happy path verification for all API endpoints."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.db.models.source import Source
from app.db.models.content_chunk import ContentChunk
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.services.llm.base import ContentBlock, LLMResponse, StreamChunk


# --- Model Config Tests ---------------------------------------------------

class TestModelConfigCRUD:
    @pytest.mark.asyncio
    async def test_crud_lifecycle(self, client: AsyncClient):
        # Create
        res = await client.post("/api/models", json={
            "name": "smoke-claude", "provider_type": "anthropic",
            "model_id": "claude-sonnet-4-20250514", "api_key": "sk-test-key-123",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "smoke-claude"
        assert data["is_active"] is True
        assert data["api_key_masked"] is not None
        assert "sk-test-key-123" not in data["api_key_masked"]

        # List
        res = await client.get("/api/models")
        assert res.status_code == 200
        names = [m["name"] for m in res.json()]
        assert "smoke-claude" in names

        # Update
        res = await client.put("/api/models/smoke-claude", json={"max_tokens_limit": 8192})
        assert res.status_code == 200
        assert res.json()["max_tokens_limit"] == 8192

        # Delete
        res = await client.delete("/api/models/smoke-claude")
        assert res.status_code == 204

        # Verify gone
        res = await client.get("/api/models")
        names = [m["name"] for m in res.json()]
        assert "smoke-claude" not in names

        # 404 on update/delete of nonexistent
        res = await client.put("/api/models/nonexistent", json={"is_active": False})
        assert res.status_code == 404
        res = await client.delete("/api/models/nonexistent")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_returns_409(self, client: AsyncClient):
        await client.post("/api/models", json={
            "name": "dup-model", "provider_type": "anthropic", "model_id": "x",
        })
        res = await client.post("/api/models", json={
            "name": "dup-model", "provider_type": "anthropic", "model_id": "y",
        })
        assert res.status_code == 409


class TestModelRoutes:
    @pytest.mark.asyncio
    async def test_routes_crud(self, client: AsyncClient):
        # Create model first (FK dependency)
        await client.post("/api/models", json={
            "name": "route-model", "provider_type": "anthropic", "model_id": "x",
        })
        # Set route
        res = await client.put("/api/model-routes", json=[
            {"task_type": "mentor_chat", "model_name": "route-model"},
        ])
        assert res.status_code == 200
        assert res.json()[0]["model_name"] == "route-model"

        # Get routes
        res = await client.get("/api/model-routes")
        assert res.status_code == 200
        types = [r["task_type"] for r in res.json()]
        assert "mentor_chat" in types


# --- Source Tests ---------------------------------------------------------

class TestSources:
    @pytest.mark.asyncio
    async def test_create_url_source(self, client: AsyncClient):
        with patch("app.api.routes.sources.ingest_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-task-001"
            mock_task.delay.return_value = mock_result

            res = await client.post("/api/sources", data={
                "url": "https://www.bilibili.com/video/BV1gZ4y1F7hS",
            })
            assert res.status_code == 201
            data = res.json()
            assert data["type"] == "bilibili"
            assert data["status"] == "pending"
            assert data["task_id"] == "fake-task-001"
            source_id = data["id"]

            # List
            res = await client.get("/api/sources")
            assert res.status_code == 200
            assert res.json()["total"] >= 1

            # Get by ID
            res = await client.get(f"/api/sources/{source_id}")
            assert res.status_code == 200
            assert res.json()["id"] == source_id

    @pytest.mark.asyncio
    async def test_create_youtube_source(self, client: AsyncClient):
        with patch("app.api.routes.sources.ingest_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-yt-task"
            mock_task.delay.return_value = mock_result

            res = await client.post("/api/sources", data={
                "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            })
            assert res.status_code == 201
            data = res.json()
            assert data["type"] == "youtube"
            assert data["status"] == "pending"
            assert data["task_id"] == "fake-yt-task"

    @pytest.mark.asyncio
    async def test_no_input_returns_400(self, client: AsyncClient):
        res = await client.post("/api/sources", data={})
        assert res.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_pagination(self, client: AsyncClient):
        with patch("app.api.routes.sources.ingest_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-task"
            mock_task.delay.return_value = mock_result

            for i in range(3):
                await client.post("/api/sources", data={
                    "url": f"https://www.bilibili.com/video/BV{i}test",
                })

            res = await client.get("/api/sources?skip=0&limit=2")
            data = res.json()
            assert len(data["items"]) == 2
            assert data["total"] >= 3


# --- Course Tests ---------------------------------------------------------

class TestCourses:
    @pytest.mark.asyncio
    async def test_generation_happy_path(self, client: AsyncClient, db_session):
        from datetime import datetime
        from app.db.models.course import Course, CourseSource, Section

        # Create prerequisite: source with status=ready + content chunk
        source = Source(
            type="bilibili", title="Test Video", status="ready",
            url="https://www.bilibili.com/video/BV1test",
        )
        db_session.add(source)
        await db_session.flush()

        chunk = ContentChunk(
            source_id=source.id, text="This is about neural networks and backpropagation.",
            metadata_={},
        )
        db_session.add(chunk)
        await db_session.flush()

        # Mock the CourseGenerator.generate method to avoid server_default
        # lazy-load issues in async context.  We insert the Course, Section,
        # and CourseSource directly and return a fully-loaded ORM object.
        now = datetime.now()
        course = Course(title="Test Video", description="A course about neural networks.")
        # Manually set timestamps to avoid server_default lazy load
        course.created_at = now
        course.updated_at = now
        db_session.add(course)
        await db_session.flush()

        db_session.add(CourseSource(course_id=course.id, source_id=source.id))
        section = Section(
            course_id=course.id,
            title="Section 1",
            order_index=0,
            source_id=source.id,
            content={},
            difficulty=1,
        )
        section.created_at = now
        section.updated_at = now
        db_session.add(section)
        await db_session.flush()

        # Mock the generator to return our pre-built course
        async def mock_generate(db, source_ids, title=None, user_id=None):
            return course

        mock_router = AsyncMock()

        from app.api.deps import get_model_router
        from app.main import app as the_app
        the_app.dependency_overrides[get_model_router] = lambda: mock_router

        try:
            with patch("app.api.routes.courses.CourseGenerator") as MockGen:
                gen_instance = AsyncMock()
                gen_instance.generate = mock_generate
                MockGen.return_value = gen_instance

                res = await client.post("/api/courses/generate", json={
                    "source_ids": [str(source.id)],
                })
                assert res.status_code == 201
                data = res.json()
                assert "id" in data
                course_id = data["id"]

            # List courses
            res = await client.get("/api/courses")
            assert res.status_code == 200
            assert res.json()["total"] >= 1

            # Get course detail
            res = await client.get(f"/api/courses/{course_id}")
            assert res.status_code == 200
            detail = res.json()
            assert len(detail["sections"]) >= 1
            assert str(source.id) in detail["source_ids"]
        finally:
            del the_app.dependency_overrides[get_model_router]

    @pytest.mark.asyncio
    async def test_source_not_ready_returns_400(self, client: AsyncClient, db_session):
        source = Source(
            type="bilibili", title="Pending", status="pending",
            url="https://www.bilibili.com/video/BV1pending",
        )
        db_session.add(source)
        await db_session.flush()

        mock_router = AsyncMock()
        from app.api.deps import get_model_router
        from app.main import app as the_app
        the_app.dependency_overrides[get_model_router] = lambda: mock_router
        try:
            res = await client.post("/api/courses/generate", json={
                "source_ids": [str(source.id)],
            })
            assert res.status_code == 400
        finally:
            del the_app.dependency_overrides[get_model_router]

    @pytest.mark.asyncio
    async def test_source_not_found_returns_400(self, client: AsyncClient):
        mock_router = AsyncMock()
        from app.api.deps import get_model_router
        from app.main import app as the_app
        the_app.dependency_overrides[get_model_router] = lambda: mock_router
        try:
            res = await client.post("/api/courses/generate", json={
                "source_ids": ["00000000-0000-0000-0000-000000000099"],
            })
            assert res.status_code in (400, 404)
        finally:
            del the_app.dependency_overrides[get_model_router]

    @pytest.mark.asyncio
    async def test_empty_source_ids_returns_422(self, client: AsyncClient):
        """Pydantic validation rejects empty source_ids list."""
        mock_router = AsyncMock()
        from app.api.deps import get_model_router
        from app.main import app as the_app
        the_app.dependency_overrides[get_model_router] = lambda: mock_router
        try:
            res = await client.post("/api/courses/generate", json={
                "source_ids": [],
            })
            assert res.status_code == 422
        finally:
            del the_app.dependency_overrides[get_model_router]


# --- Chat & Conversation Tests --------------------------------------------

class TestChat:
    @pytest.mark.asyncio
    async def test_sse_streaming(self, client: AsyncClient, demo_user):
        """Test chat SSE streaming with mocked MentorAgent."""
        async def mock_process(**kwargs):
            yield StreamChunk(type="text_delta", text="Hello ")
            yield StreamChunk(type="text_delta", text="student!")
            yield StreamChunk(type="message_end")

        with patch("app.api.routes.chat.async_session_factory") as mock_sf, \
             patch("app.api.routes.chat.MentorAgent") as MockAgent, \
             patch("app.api.routes.chat.RAGService"), \
             patch("app.api.routes.chat.KnowledgeSearchTool"), \
             patch("app.api.routes.chat.ProfileReadTool"), \
             patch("app.api.routes.chat.ProgressTrackTool"):

            # Build a mock async session
            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=None)  # no existing conversation

            # Track objects added via db.add
            added_objects = []
            def _capture_add(obj):
                added_objects.append(obj)
                # Assign an id on flush if it looks like an ORM object
                if hasattr(obj, "id") and obj.id is None:
                    obj.id = uuid.uuid4()
            mock_session.add = MagicMock(side_effect=_capture_add)
            mock_session.flush = AsyncMock()
            mock_session.commit = AsyncMock()

            # Make execute return empty result for history query
            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
            mock_session.execute = AsyncMock(return_value=mock_result)

            # Mock async context manager for session factory
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_cm

            # Mock agent
            agent_instance = AsyncMock()
            agent_instance.process = mock_process
            MockAgent.return_value = agent_instance

            # Need to override model_router dependency too
            mock_router = AsyncMock()
            from app.api.deps import get_model_router
            from app.main import app as the_app
            the_app.dependency_overrides[get_model_router] = lambda: mock_router

            try:
                res = await client.post("/api/chat", json={
                    "message": "What is recursion?",
                })
                assert res.status_code == 200
                assert "text/event-stream" in res.headers.get("content-type", "")

                # Parse SSE events
                text = res.text
                events = []
                for line in text.split("\n"):
                    if line.startswith("data:"):
                        try:
                            events.append(json.loads(line[5:].strip()))
                        except json.JSONDecodeError:
                            pass

                # Should have text deltas
                text_events = [e for e in events if "text" in e]
                assert len(text_events) >= 1
            finally:
                del the_app.dependency_overrides[get_model_router]


class TestConversations:
    @pytest.mark.asyncio
    async def test_list_and_messages(self, client: AsyncClient, db_session, demo_user):
        # Insert conversation + messages directly
        conv = Conversation(
            user_id=demo_user.id, mode="qa",
        )
        db_session.add(conv)
        await db_session.flush()

        msg1 = Message(conversation_id=conv.id, role="user", content="Hello")
        msg2 = Message(conversation_id=conv.id, role="assistant", content="Hi there!")
        db_session.add_all([msg1, msg2])
        await db_session.flush()

        # List conversations
        res = await client.get("/api/conversations")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        conv_item = next(c for c in data["items"] if c["id"] == str(conv.id))
        assert conv_item["message_count"] == 2

        # Get messages
        res = await client.get(f"/api/conversations/{conv.id}/messages")
        assert res.status_code == 200
        msgs = res.json()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient, demo_user):
        fake_id = "00000000-0000-0000-0000-000000000099"
        res = await client.get(f"/api/conversations/{fake_id}/messages")
        assert res.status_code == 404


# --- Task Status Test -----------------------------------------------------

class TestTaskStatus:
    @pytest.mark.asyncio
    async def test_pending_task(self, client: AsyncClient):
        with patch("app.api.routes.tasks.AsyncResult") as MockResult:
            mock_result = MagicMock()
            mock_result.state = "PENDING"
            mock_result.result = None
            mock_result.info = None
            MockResult.return_value = mock_result

            res = await client.get("/api/tasks/fake-task-id/status")
            assert res.status_code == 200
            data = res.json()
            assert data["task_id"] == "fake-task-id"
            assert data["state"] == "PENDING"


# --- Model Test Connectivity ---------------------------------------------

class TestModelConnectivity:
    @pytest.mark.asyncio
    async def test_connectivity(self, client: AsyncClient):
        # Create a model first
        await client.post("/api/models", json={
            "name": "test-conn", "provider_type": "anthropic",
            "model_id": "claude-test", "api_key": "sk-fake",
        })

        # Mock the provider construction in the test endpoint
        with patch("app.services.llm.anthropic.AnthropicProvider") as MockProvider:
            mock_instance = AsyncMock()
            mock_instance.chat.return_value = LLMResponse(
                content=[ContentBlock(type="text", text="hello")],
                model="claude-test",
            )
            MockProvider.return_value = mock_instance

            res = await client.post("/api/models/test-conn/test")
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True

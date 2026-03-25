"""API routes for knowledge graph visualization."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.db.models.user import User
from app.services.knowledge_graph import KnowledgeGraphService

router = APIRouter(prefix="/api/v1/courses", tags=["knowledge-graph"])


@router.get("/{course_id}/knowledge-graph")
async def get_knowledge_graph(
    course_id: uuid.UUID,
    max_depth: int = 2,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    """Return the knowledge graph (nodes + edges) for a course.

    Args:
        course_id: UUID of the course.
        max_depth: Depth limit for prerequisite traversal (reserved).
        db: Async database session (injected).
        user: Authenticated user (injected).

    Returns:
        Dict with ``nodes`` and ``edges`` lists.
    """
    service = KnowledgeGraphService(db)
    return await service.get_graph(course_id, user.id, max_depth)

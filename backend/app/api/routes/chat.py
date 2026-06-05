"""API routes for mentor chat with AG-UI SSE streaming.

The chat stream now speaks the AG-UI protocol: each SSE ``data:`` frame is one
AG-UI event (``ag_ui.encoder.EventEncoder``), discriminated by its ``type``
field. The conversation id is carried as the run's ``threadId`` (RUN_STARTED).
"""

import uuid
from typing import Annotated

from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agentcore.events import EventType
from app.agentcore.events.types import run_error
from app.api.deps import get_db, get_local_user, get_model_router
from app.db.database import async_session_factory
from app.db.models.conversation import Conversation
from app.db.models.course import Section
from app.db.models.message import Message
from app.db.models.user import User
from app.models.chat import (
    ChatRequest,
    ConversationResponse,
    ConversationListResponse,
    MessageResponse,
)
from app.agent.mentor import MentorAgent
from app.agent.tools.exercise import ExerciseGenerateTool, ExerciseEvalTool
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.agent.tools.memory import EpisodicMemoryTool, MetacognitiveReflectTool
from app.agent.tools.profile import ProfileReadTool
from app.agent.tools.progress import ProgressTrackTool
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.services.rag import RAGService

router = APIRouter(tags=["chat"])


@router.post("/api/v1/chat")
async def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_local_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
):
    """Send a message to the MentorAgent and receive an SSE stream."""
    user_id = user.id

    encoder = EventEncoder()

    async def event_generator():
        async with async_session_factory() as db:
            try:
                # Get or create conversation
                if request.conversation_id:
                    conversation = await db.get(Conversation, request.conversation_id)
                    if not conversation or conversation.user_id != user_id:
                        yield encoder.encode(run_error(message="Conversation not found", code="not_found"))
                        return
                else:
                    conversation = Conversation(
                        user_id=user_id,
                        course_id=request.course_id,
                        mode="qa",
                    )
                    db.add(conversation)
                    await db.flush()

                # Save user message
                user_msg = Message(
                    conversation_id=conversation.id,
                    role="user",
                    content=request.message,
                )
                db.add(user_msg)
                await db.flush()

                # Load conversation history (last 20 messages)
                history_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .limit(20)
                )
                history_messages = list(reversed(history_result.scalars().all()))

                # Build history excluding latest user message
                conversation_history = []
                for msg in history_messages[:-1]:
                    role = msg.role if msg.role in ("user", "assistant") else "user"
                    conversation_history.append(UnifiedMessage(role=role, content=msg.content))

                # Set up agent
                rag_service = RAGService(model_router)
                provider = await model_router.get_provider(TaskType.MENTOR_CHAT)
                tools = [
                    KnowledgeSearchTool(db=db, rag_service=rag_service, course_id=request.course_id),
                    ProfileReadTool(db=db, user_id=user_id),
                    ProgressTrackTool(db=db, user_id=user_id),
                    ExerciseGenerateTool(db=db, provider=provider, user_id=user_id),
                    ExerciseEvalTool(db=db, provider=provider, user_id=user_id),
                    EpisodicMemoryTool(db=db, user_id=user_id),
                    MetacognitiveReflectTool(db=db, provider=provider, user_id=user_id),
                ]
                agent = MentorAgent(
                    model_router=model_router,
                    db=db,
                    user_id=user_id,
                    tools=tools,
                )

                # If section_id is provided, load section title for agent context
                section_context = ""
                if request.section_id:
                    section = await db.get(Section, request.section_id)
                    if section:
                        section_context = f"\n\nThe student is currently studying section: {section.title}"

                # Stream response as AG-UI events
                full_response = ""
                async for event in agent.process(
                    user_message=request.message,
                    conversation_history=conversation_history,
                    course_id=request.course_id,
                    system_prompt_extra=section_context,
                    conversation_id=conversation.id,
                ):
                    if event.type == EventType.TEXT_MESSAGE_CONTENT and event.delta:
                        full_response += event.delta
                    yield encoder.encode(event)

                # Save assistant message
                if full_response:
                    assistant_msg = Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=full_response,
                    )
                    db.add(assistant_msg)

                await db.commit()

            except Exception as e:
                yield encoder.encode(run_error(message=str(e)))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/conversations", response_model=ConversationListResponse)
async def list_conversations(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    skip: int = 0,
    limit: int = 20,
):
    """List conversations for the current user."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    conversations = result.scalars().all()

    items = []
    for conv in conversations:
        msg_count = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        )
        count = msg_count.scalar_one()
        items.append(ConversationResponse(
            id=conv.id,
            course_id=conv.course_id,
            mode=conv.mode,
            created_at=conv.created_at,
            message_count=count,
        ))

    # Fix total count
    count_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
    )
    total = count_result.scalar()
    return ConversationListResponse(items=items, total=total)


@router.get("/api/v1/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> list[MessageResponse]:
    """Get all messages in a conversation."""
    conversation = await db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(404, "Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return [
        MessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at,
        )
        for msg in messages
    ]

"""API routes for mentor chat with SSE streaming."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db, get_model_router
from app.db.database import async_session_factory
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.models.chat import (
    ChatRequest,
    ConversationResponse,
    ConversationListResponse,
    MessageResponse,
)
from app.agent.mentor import MentorAgent
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.agent.tools.profile import ProfileReadTool
from app.agent.tools.progress import ProgressTrackTool
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter
from app.services.rag import RAGService

router = APIRouter(tags=["chat"])

# Hardcoded demo user ID for MVP (auth will be added later)
DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/api/chat")
async def chat(
    request: ChatRequest,
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
):
    """Send a message to the MentorAgent and receive an SSE stream."""
    user_id = DEMO_USER_ID

    async def event_generator():
        async with async_session_factory() as db:
            try:
                # Get or create conversation
                if request.conversation_id:
                    conversation = await db.get(Conversation, request.conversation_id)
                    if not conversation:
                        yield {"event": "error", "data": json.dumps({"message": "Conversation not found"})}
                        return
                    if conversation.user_id != user_id:
                        yield {"event": "error", "data": json.dumps({"message": "Conversation not found"})}
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
                tools = [
                    KnowledgeSearchTool(db=db, rag_service=rag_service, course_id=request.course_id),
                    ProfileReadTool(db=db, user_id=user_id),
                    ProgressTrackTool(db=db, user_id=user_id),
                ]
                agent = MentorAgent(
                    model_router=model_router,
                    db=db,
                    user_id=user_id,
                    tools=tools,
                )

                # Stream response
                full_response = ""
                async for chunk in agent.process(
                    user_message=request.message,
                    conversation_history=conversation_history,
                    course_id=request.course_id,
                ):
                    if chunk.type == "text_delta" and chunk.text:
                        full_response += chunk.text
                        yield {"event": "text_delta", "data": json.dumps({"text": chunk.text})}
                    elif chunk.type == "tool_use_start":
                        yield {"event": "tool_start", "data": json.dumps({"tool": chunk.tool_name})}
                    elif chunk.type == "tool_use_end":
                        yield {"event": "tool_end", "data": "{}"}
                    elif chunk.type == "message_end":
                        yield {"event": "message_end", "data": json.dumps({"conversation_id": str(conversation.id)})}

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
                yield {"event": "error", "data": json.dumps({"message": str(e)})}

    return EventSourceResponse(event_generator())


@router.get("/api/conversations", response_model=ConversationListResponse)
async def list_conversations(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 20,
):
    """List conversations for the current user."""
    user_id = DEMO_USER_ID

    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
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
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )
    total = count_result.scalar()
    return ConversationListResponse(items=items, total=total)


@router.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MessageResponse]:
    """Get all messages in a conversation."""
    conversation = await db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != DEMO_USER_ID:
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

"""Student profile Pydantic model and database operations."""

import json
import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User

logger = logging.getLogger(__name__)


# --- Pydantic models matching system-design.md Section 1.4 ---

class LearningStyle(BaseModel):
    pace: str = "moderate"                       # slow | moderate | fast
    prefers_examples: bool = True
    prefers_code_first: bool = True
    attention_span: str = "medium"               # short | medium | long
    best_time: str = "evening"
    response_to_challenge: str = "motivated"     # frustrated | neutral | motivated

class Competency(BaseModel):
    programming: dict[str, str] = Field(default_factory=dict)     # {"python": "intermediate"}
    domains: dict[str, float] = Field(default_factory=dict)       # {"llm_basics": 0.7}
    weak_spots: list[str] = Field(default_factory=list)
    strong_spots: list[str] = Field(default_factory=list)

class LearningHistory(BaseModel):
    courses_completed: list[str] = Field(default_factory=list)
    courses_in_progress: list[str] = Field(default_factory=list)
    labs_completed: list[str] = Field(default_factory=list)
    questions_asked: list[str] = Field(default_factory=list)
    mistakes_pattern: list[str] = Field(default_factory=list)
    aha_moments: list[str] = Field(default_factory=list)
    total_study_hours: float = 0
    streak_days: int = 0

class MentorStrategy(BaseModel):
    current_approach: str = ""
    personality: str = "encouraging"             # encouraging | direct | socratic
    push_level: str = "gentle"                   # gentle | moderate | firm
    last_interaction_summary: str = ""
    next_suggested_action: str = ""

class StudentProfile(BaseModel):
    name: str = ""
    learning_goals: list[str] = Field(default_factory=list)
    motivation: str = ""
    preferred_language: str = "zh-CN"
    competency: Competency = Field(default_factory=Competency)
    learning_style: LearningStyle = Field(default_factory=LearningStyle)
    history: LearningHistory = Field(default_factory=LearningHistory)
    mentor_strategy: MentorStrategy = Field(default_factory=MentorStrategy)


# --- Database operations ---

async def load_profile(db: AsyncSession, user_id: uuid.UUID) -> StudentProfile:
    """Load student profile from users.student_profile JSONB field.

    Returns a default StudentProfile if the field is empty or missing.
    """
    stmt = select(User.student_profile).where(User.id == user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row and isinstance(row, dict) and row:
        return StudentProfile(**row)
    return StudentProfile()


async def save_profile(db: AsyncSession, user_id: uuid.UUID, profile: StudentProfile) -> None:
    """Save student profile to users.student_profile JSONB field."""
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(student_profile=profile.model_dump())
    )
    await db.execute(stmt)
    await db.flush()


async def apply_profile_updates(
    db: AsyncSession, user_id: uuid.UUID, llm_response_text: str
) -> None:
    """Parse LLM JSON response and apply profile updates.

    Expected format from LLM:
    {"observations": ["..."], "updates": {"field": "value"}}

    Args:
        db: Database session.
        user_id: User ID.
        llm_response_text: Raw text from LLM containing JSON.
    """
    try:
        # Try to extract JSON from the response
        text = llm_response_text.strip()
        # Handle responses wrapped in markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        parsed = json.loads(text)
        updates = parsed.get("updates", {})
        observations = parsed.get("observations", [])

        if observations:
            logger.debug(f"Profile observations for user {user_id}: {observations}")

        if not updates:
            return

        # Load current profile, deep merge updates, save
        profile = await load_profile(db, user_id)
        profile_dict = profile.model_dump()

        def _deep_merge(base: dict, updates_dict: dict) -> None:
            for key, value in updates_dict.items():
                if key not in base:
                    base[key] = value
                elif isinstance(base[key], dict) and isinstance(value, dict):
                    _deep_merge(base[key], value)
                elif isinstance(base[key], list) and isinstance(value, list):
                    for item in value:
                        if item not in base[key]:
                            base[key].append(item)
                else:
                    base[key] = value

        _deep_merge(profile_dict, updates)

        updated_profile = StudentProfile(**profile_dict)
        await save_profile(db, user_id, updated_profile)
        logger.info(f"Updated profile for user {user_id}: {list(updates.keys())}")

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to parse profile updates: {e}")

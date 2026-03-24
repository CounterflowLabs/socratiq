"""Student profile read/update tool for the MentorAgent."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.services.profile import load_profile


class ProfileReadTool(AgentTool):
    """Read the current student profile.

    The MentorAgent calls this at the start of conversations or when it
    needs to check specific profile data (e.g. weak_spots, learning_style).
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "read_student_profile"

    @property
    def description(self) -> str:
        return (
            "Read the current student profile including learning style, competency levels, "
            "weak spots, strong spots, learning history, and mentor strategy. "
            "Use this to personalize your teaching approach."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Optional: specific section to read ('competency', 'learning_style', 'history', 'mentor_strategy', or 'all'). Defaults to 'all'.",
                    "enum": ["all", "competency", "learning_style", "history", "mentor_strategy"],
                    "default": "all",
                },
            },
            "required": [],
        }

    async def execute(self, section: str = "all") -> str:
        profile = await load_profile(self._db, self._user_id)
        if section == "all":
            return profile.model_dump_json(indent=2)
        elif hasattr(profile, section):
            attr = getattr(profile, section)
            if hasattr(attr, "model_dump_json"):
                return attr.model_dump_json(indent=2)
            return str(attr)
        else:
            return f"Unknown profile section: {section}"

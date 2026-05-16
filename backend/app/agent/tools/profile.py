"""Student profile read/update tool for the MentorAgent."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool, tool_error
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
            "Read the persistent student profile: name, learning_style "
            "(pace, prefers_examples, prefers_code_first, attention_span), "
            "competency (weak_spots, strong_spots, domain mastery), learning "
            "history, and mentor_strategy (current personality + push level).\n\n"
            "## Use when\n"
            "- Starting a new topic and want to choose between code-first vs concept-first explanation\n"
            "- About to push the student harder and want to check their `response_to_challenge` and `push_level`\n"
            "- The student touched on a topic that may intersect a `weak_spot` you should be more thorough on\n"
            "- You need to verify your assumptions about the student before committing to an explanation strategy\n\n"
            "## Don't use when\n"
            "- The relevant profile fact is already in this turn's system prompt — it's already injected, don't re-fetch\n"
            "- You're calling at the start of every turn defensively — only call when you have a specific decision to make\n"
            "- You want learning event history (\"did they finish section 5?\") — that's `track_progress`, not profile\n\n"
            "## Example of misuse\n"
            "[turn 1]\n"
            "Mentor: [calls read_student_profile section=all]\n"
            "→ wrong; the system prompt already includes the profile summary. Re-reading just burns tokens."
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

    _VALID_SECTIONS = ("all", "competency", "learning_style", "history", "mentor_strategy")

    async def execute(self, section: str = "all") -> str:
        profile = await load_profile(self._db, self._user_id)
        if section == "all":
            return profile.model_dump_json(indent=2)
        if hasattr(profile, section):
            attr = getattr(profile, section)
            if hasattr(attr, "model_dump_json"):
                return attr.model_dump_json(indent=2)
            return str(attr)
        return tool_error(
            message=f"Unknown profile section: {section!r}",
            reason="invalid_section",
            suggestion=(
                "Valid section values are: " + ", ".join(self._VALID_SECTIONS)
                + ". Pass section='all' if unsure."
            ),
        )

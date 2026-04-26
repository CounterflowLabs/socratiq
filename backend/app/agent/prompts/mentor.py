"""System prompt builder for the MentorAgent.

The static template lives in ``mentor_system.md``. This module is responsible
for resolving the StudentProfile into the flat string variables the template
expects — all conditional logic stays in Python so the template stays
data-only (per Codex's prompt convention).
"""

import uuid
from pathlib import Path

from app.agent.tools.base import AgentTool
from app.prompt_template import load_prompt
from app.services.profile import StudentProfile

_PROMPT = load_prompt(Path(__file__).parent / "mentor_system.md")


def build_system_prompt(
    profile: StudentProfile,
    course_id: uuid.UUID | str | None = None,
    tools: list[AgentTool] | None = None,
) -> str:
    """Render the MentorAgent system prompt with profile-driven personalization."""

    strategy = profile.mentor_strategy
    personality = strategy.personality if strategy.personality else "encouraging"
    push_level = strategy.push_level if strategy.push_level else "gentle"
    current_approach = strategy.current_approach if strategy.current_approach else "adaptive"

    competency_lines: list[str] = []
    if profile.competency.weak_spots:
        competency_lines.append(f"Weak spots: {', '.join(profile.competency.weak_spots)}")
    if profile.competency.strong_spots:
        competency_lines.append(f"Strong spots: {', '.join(profile.competency.strong_spots)}")
    if profile.competency.domains:
        domains_str = ", ".join(
            f"{k}: {v:.0%}" for k, v in profile.competency.domains.items()
        )
        competency_lines.append(f"Domain mastery: {domains_str}")
    competency_section = "\n".join(f"- {line}" for line in competency_lines)

    return _PROMPT.render(
        name=profile.name or "(unset)",
        learning_goals=", ".join(profile.learning_goals) if profile.learning_goals else "(unset)",
        preferred_language=profile.preferred_language,
        pace=profile.learning_style.pace,
        prefers_examples="yes" if profile.learning_style.prefers_examples else "no",
        prefers_code_first="yes" if profile.learning_style.prefers_code_first else "no",
        attention_span=profile.learning_style.attention_span,
        response_to_challenge=profile.learning_style.response_to_challenge,
        competency_section=competency_section,
        personality=personality,
        push_level=push_level,
        current_approach=current_approach,
    )

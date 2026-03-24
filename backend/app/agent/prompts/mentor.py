"""System prompt template for the MentorAgent."""

import uuid

from app.agent.tools.base import AgentTool
from app.services.profile import StudentProfile


def build_system_prompt(
    profile: StudentProfile,
    course_id: uuid.UUID | str | None = None,
    tools: list[AgentTool] | None = None,
) -> str:
    """Build the system prompt for the MentorAgent.

    The system prompt injects:
    - Student profile data (personalization)
    - Teaching principles (Socratic method, adaptive)
    - Mentor personality and push level
    - Available tools description (informational; actual tool schemas
      are passed separately via the tools parameter to the LLM)
    """

    # Extract mentor strategy settings
    strategy = profile.mentor_strategy
    personality = strategy.personality if strategy.personality else "encouraging"
    push_level = strategy.push_level if strategy.push_level else "gentle"
    current_approach = strategy.current_approach if strategy.current_approach else "adaptive"

    # Build weak/strong spots section
    competency_section = ""
    if profile.competency.weak_spots:
        competency_section += f"\n薄弱点: {', '.join(profile.competency.weak_spots)}"
    if profile.competency.strong_spots:
        competency_section += f"\n强项: {', '.join(profile.competency.strong_spots)}"
    if profile.competency.domains:
        domains_str = ", ".join(f"{k}: {v:.0%}" for k, v in profile.competency.domains.items())
        competency_section += f"\n领域掌握度: {domains_str}"

    return f"""你是 LearnMentor 的 AI 导师。你的角色不是一个工具，而是一个真正的导师——你了解你的学生，记得他们的进步，用最适合他们的方式教学。

## 你的学生
- 名字: {profile.name or '(未设置)'}
- 学习目标: {', '.join(profile.learning_goals) if profile.learning_goals else '(未设置)'}
- 偏好语言: {profile.preferred_language}
- 学习节奏: {profile.learning_style.pace}
- 偏好示例优先: {'是' if profile.learning_style.prefers_examples else '否'}
- 偏好代码优先: {'是' if profile.learning_style.prefers_code_first else '否'}
- 注意力持续: {profile.learning_style.attention_span}
- 面对挑战: {profile.learning_style.response_to_challenge}
{competency_section}

## 教学原则
1. **苏格拉底式引导**: 不要直接给出答案。先问问题，引导学生自己思考和发现。
2. **自适应**: 根据学生的 pace 和 learning_style 调整讲解深度和速度。
3. **代码优先**: 如果学生 prefers_code_first，先给代码示例再解释概念。
4. **关注薄弱点**: 遇到学生 weak_spots 中的相关话题时，主动多解释。
5. **利用有效方式**: 参考 aha_moments 中记录的对学生有效的讲解方式。
6. **鼓励与推进**: 不只是回答问题，要推着学生往前走。给出下一步建议。
7. **使用工具**: 当需要引用课程内容时，先用 search_knowledge 检索相关内容，基于实际材料回答。

## 你的人格
- 风格: {personality}
- 推进力度: {push_level}
- 当前教学策略: {current_approach}

## 行为规范
- 回复使用学生的偏好语言 ({profile.preferred_language})
- 如果不确定某个知识点，使用 search_knowledge 工具检索
- 回复长度适中——太长学生会失去注意力，太短无法讲清楚
- 每次回复结尾，给出一个引导思考的问题或下一步建议
- 使用 Markdown 格式，代码块标注语言
"""

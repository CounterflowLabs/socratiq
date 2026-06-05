"""Teaching orchestration — Plan-and-Execute + ReAct judgment + Critic.

Sits on top of ``app.agentcore``. Expresses the course-generation topologies as
a ``CourseGraph`` of deterministic nodes, ReAct judgment nodes, and critic
gates with bounded backtrack. Phase 2 ships the primitives; the concrete
video→course / sentence→course topologies and the CourseGenerator decomposition
land in Phase 3.
"""

from app.services.orchestration.critic import (
    Critic,
    CriticGate,
    CriticVerdict,
    ModelCritic,
    RuleCritic,
    SECTIONS_KEY,
)
from app.services.orchestration.graph import (
    CourseGraph,
    Gate,
    GateDecision,
    GraphState,
    Node,
)
from app.services.orchestration.plan_execute import (
    Executor,
    Plan,
    Planner,
    PlanAndExecute,
)
from app.services.orchestration.react_node import FinishTool, ReActNode

__all__ = [
    "Critic",
    "CriticGate",
    "CriticVerdict",
    "RuleCritic",
    "SECTIONS_KEY",
    "CourseGraph",
    "Gate",
    "GateDecision",
    "GraphState",
    "Node",
    "Executor",
    "Plan",
    "Planner",
    "PlanAndExecute",
    "FinishTool",
    "ReActNode",
]

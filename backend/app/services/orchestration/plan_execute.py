"""PlanAndExecute — plan once, execute the batch (in parallel), critic, re-plan.

The primary pattern for video→course: a ``Planner`` fixes a deterministic list
of tasks, an ``Executor`` runs them (cheap models / pure code, parallel for
throughput), then an optional ``Critic`` decides whether to accept or re-plan.
Re-planning is bounded by ``max_replans`` so it can't loop forever.

This is a reusable engine; a ``CourseGraph`` can also express the same shape
when finer per-node gating/backtrack is needed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.services.orchestration.critic import Critic
from app.services.orchestration.graph import GraphState

logger = logging.getLogger(__name__)

__all__ = ["Plan", "Planner", "Executor", "PlanAndExecute"]


@dataclass
class Plan:
    tasks: list[Any] = field(default_factory=list)


@runtime_checkable
class Planner(Protocol):
    async def plan(self, state: GraphState, *, bus=None) -> Plan: ...


@runtime_checkable
class Executor(Protocol):
    async def execute(self, task: Any, state: GraphState, *, bus=None) -> Any: ...


class PlanAndExecute:
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        *,
        parallel: bool = True,
        concurrency: int = 4,
        critic: Critic | None = None,
        max_replans: int = 1,
        results_key: str = "results",
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._parallel = parallel
        self._sem = asyncio.Semaphore(concurrency)
        self._critic = critic
        self._max_replans = max_replans
        self._results_key = results_key

    async def run(self, state: GraphState, *, bus=None) -> list[Any]:
        from app.agentcore.events.types import custom, step_finished, step_started

        results: list[Any] = []
        for attempt in range(self._max_replans + 1):
            if bus is not None:
                await bus.emit(step_started("plan"))
            plan = await self._planner.plan(state, bus=bus)
            if bus is not None:
                await bus.emit(step_finished("plan"))

            if bus is not None:
                await bus.emit(step_started("execute"))
            results = await self._execute_all(plan.tasks, state, bus)
            state.data[self._results_key] = results
            if bus is not None:
                await bus.emit(step_finished("execute"))

            if self._critic is None:
                return results
            verdict = await self._critic.evaluate(state, bus=bus)
            state.critic_history.append(verdict)
            if verdict.passed or attempt >= self._max_replans:
                return results
            # Re-plan with the critic's feedback available to the planner.
            state.feedback["plan"] = verdict.feedback
            if bus is not None:
                await bus.emit(custom("replan", {
                    "attempt": attempt + 1, "feedback": verdict.feedback,
                }))
            logger.info("PlanAndExecute re-planning (attempt %d)", attempt + 1)
        return results

    async def _execute_all(
        self, tasks: Sequence[Any], state: GraphState, bus
    ) -> list[Any]:
        if self._parallel and len(tasks) > 1:
            async def _guarded(t):
                async with self._sem:
                    return await self._executor.execute(t, state, bus=bus)

            return list(await asyncio.gather(*(_guarded(t) for t in tasks)))
        return [await self._executor.execute(t, state, bus=bus) for t in tasks]

"""RiskScanner — inspect tool inputs/outputs (and model content) for risk.

The seam for prompt-injection / unsafe-content / data-exfiltration checks. A
scan returns a verdict the caller can act on (block, redact, warn). Default
``NoopRiskScanner`` flags nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = ["RiskVerdict", "RiskScanner", "NoopRiskScanner"]


@dataclass
class RiskVerdict:
    action: Literal["allow", "redact", "block"] = "allow"
    reason: str = ""
    redacted: str | None = None


@runtime_checkable
class RiskScanner(Protocol):
    async def scan(self, text: str, *, kind: str = "tool_output") -> RiskVerdict: ...


class NoopRiskScanner:
    """Default: everything is allowed."""

    async def scan(self, text: str, *, kind: str = "tool_output") -> RiskVerdict:  # noqa: ARG002
        return RiskVerdict(action="allow")

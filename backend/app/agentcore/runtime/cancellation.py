"""CancellationToken — cooperative cancellation for agent runs.

Replaces the ad-hoc ``cancel_check`` callback threaded through CourseGenerator.
A token can be cancelled directly (``cancel()``) or back an external signal via
a poll function — e.g. ARQ's ``job.abort()`` or a DB ``cancel_requested`` flag.
Nodes/loops call ``await token.raise_if_cancelled()`` at break points.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

__all__ = ["RunCancelled", "CancellationToken"]


class RunCancelled(Exception):
    """Raised at a cooperative cancellation checkpoint."""


class CancellationToken:
    def __init__(
        self, *, poll: Callable[[], Awaitable[bool]] | None = None
    ) -> None:
        self._cancelled = False
        self._poll = poll

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    async def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise RunCancelled()
        if self._poll is not None and await self._poll():
            self._cancelled = True
            raise RunCancelled()

"""Retry helpers for DTU Proxy HTTP polling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def async_retry_request[_T](
    operation: Callable[[], Awaitable[_T]],
    *,
    should_retry: Callable[[Exception], bool],
    delays: tuple[float, ...],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> _T:
    """Run an operation once plus one retry after each configured delay."""
    for attempt in range(len(delays) + 1):
        try:
            return await operation()
        except Exception as err:
            if not should_retry(err) or attempt == len(delays):
                raise
            await sleep(delays[attempt])

    raise RuntimeError("Unreachable retry state")


class FailedRunBackoff:
    """Apply a short bounded delay after an exhausted polling run."""

    __slots__ = ("failures", "initial_delay", "maximum_delay")

    def __init__(self, *, initial_delay: float, maximum_delay: float) -> None:
        self.failures = 0
        self.initial_delay = initial_delay
        self.maximum_delay = maximum_delay

    def record_failure(self) -> float:
        """Record one exhausted run and return its next-run delay."""
        self.failures += 1
        return self.initial_delay if self.failures == 1 else self.maximum_delay

    def record_success(self) -> None:
        """Reset the failure streak after any successful polling run."""
        self.failures = 0

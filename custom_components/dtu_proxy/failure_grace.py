"""Helpers for suppressing one-off polling failures."""

from __future__ import annotations

FAILURES_BEFORE_UNAVAILABLE = 2


class ConsecutiveFailureTracker:
    """Track failures and decide whether cached data may be retained."""

    __slots__ = ("failures",)

    def __init__(self) -> None:
        self.failures = 0

    def record_failure(self, *, has_cached_data: bool) -> bool:
        """Return whether the last good data should survive this failure."""
        self.failures += 1
        return has_cached_data and self.failures < FAILURES_BEFORE_UNAVAILABLE

    def record_success(self) -> None:
        """Reset the failure streak after a successful request."""
        self.failures = 0

    @property
    def retry_exponent(self) -> int:
        """Return the exponential-backoff exponent for an exposed failure."""
        return max(self.failures - FAILURES_BEFORE_UNAVAILABLE, 0)

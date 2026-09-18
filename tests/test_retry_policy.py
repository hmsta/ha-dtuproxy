"""Tests for bounded HTTP and failed-run retry behavior."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    path = Path("custom_components/dtu_proxy/retry_policy.py")
    spec = importlib.util.spec_from_file_location("retry_policy", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_succeeds_on_third_total_attempt() -> None:
    """Retryable failures should use the two configured retry delays."""
    module = _load_module()
    attempts = 0
    sleeps: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary")
        return "ok"

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    result = asyncio.run(
        module.async_retry_request(
            operation,
            should_retry=lambda err: isinstance(err, OSError),
            delays=(1.0, 2.0),
            sleep=fake_sleep,
        )
    )

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [1.0, 2.0]


def test_request_stops_after_three_total_attempts() -> None:
    """An exhausted batch must not continue hammering the HTTP endpoint."""
    module = _load_module()
    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("offline")

    async def fake_sleep(_delay: float) -> None:
        return None

    try:
        asyncio.run(
            module.async_retry_request(
                operation,
                should_retry=lambda err: isinstance(err, OSError),
                delays=(1.0, 2.0),
                sleep=fake_sleep,
            )
        )
    except OSError:
        pass
    else:
        raise AssertionError("Expected the exhausted request error")

    assert attempts == 3


def test_non_retryable_error_is_not_repeated() -> None:
    """Permanent errors should fail without consuming the retry budget."""
    module = _load_module()
    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("permanent")

    try:
        asyncio.run(
            module.async_retry_request(
                operation,
                should_retry=lambda err: isinstance(err, OSError),
                delays=(1.0, 2.0),
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected the permanent request error")

    assert attempts == 1


def test_failed_run_backoff_caps_at_sixty_seconds() -> None:
    """Exhausted polling runs should use 30 seconds, then 60 seconds."""
    tracker = _load_module().FailedRunBackoff(
        initial_delay=30.0,
        maximum_delay=60.0,
    )

    assert tracker.record_failure() == 30.0
    assert tracker.record_failure() == 60.0
    assert tracker.record_failure() == 60.0


def test_success_resets_failed_run_backoff() -> None:
    """Recovery should restore the initial failed-run delay."""
    tracker = _load_module().FailedRunBackoff(
        initial_delay=30.0,
        maximum_delay=60.0,
    )
    tracker.record_failure()
    tracker.record_failure()
    tracker.record_success()

    assert tracker.failures == 0
    assert tracker.record_failure() == 30.0

"""Tests for transient polling failure suppression."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    path = Path("custom_components/dtu_proxy/failure_grace.py")
    spec = importlib.util.spec_from_file_location("failure_grace", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_failure_retains_cached_data() -> None:
    """One failed poll should not expose a transient outage."""
    tracker = _load_module().ConsecutiveFailureTracker()

    assert tracker.record_failure(has_cached_data=True)
    assert tracker.failures == 1
    assert tracker.retry_exponent == 0


def test_second_failure_exposes_outage_and_backoff_grows() -> None:
    """Two consecutive failures should stop retaining stale data."""
    tracker = _load_module().ConsecutiveFailureTracker()

    assert tracker.record_failure(has_cached_data=True)
    assert not tracker.record_failure(has_cached_data=True)
    assert tracker.retry_exponent == 0
    assert not tracker.record_failure(has_cached_data=True)
    assert tracker.retry_exponent == 1


def test_success_resets_failure_grace() -> None:
    """A recovered request should grant a fresh one-failure grace period."""
    tracker = _load_module().ConsecutiveFailureTracker()
    tracker.record_failure(has_cached_data=True)
    tracker.record_success()

    assert tracker.failures == 0
    assert tracker.record_failure(has_cached_data=True)


def test_failure_without_cached_data_is_exposed_immediately() -> None:
    """Initial setup cannot suppress a failure when no prior payload exists."""
    tracker = _load_module().ConsecutiveFailureTracker()

    assert not tracker.record_failure(has_cached_data=False)

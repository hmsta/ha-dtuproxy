"""Behavioral tests for DTU Proxy HTTP retry batches."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any


def _install_aiohttp_stub() -> None:
    try:
        import aiohttp  # noqa: F401
    except ModuleNotFoundError:
        module = ModuleType("aiohttp")

        class ClientError(Exception):
            """Minimal aiohttp client exception stub."""

        class ClientSession:
            """Minimal aiohttp client session type stub."""

        class ClientTimeout:
            """Minimal aiohttp timeout value stub."""

            def __init__(self, *, total: float) -> None:
                self.total = total

        module.ClientError = ClientError
        module.ClientSession = ClientSession
        module.ClientTimeout = ClientTimeout
        sys.modules["aiohttp"] = module


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_api_module() -> ModuleType:
    _install_aiohttp_stub()
    root = Path("custom_components/dtu_proxy")
    package_name = f"_dtu_proxy_test_{uuid.uuid4().hex}"
    package = ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package
    const = ModuleType(f"{package_name}.const")
    const.DEFAULT_PORT = 80
    const.REQUEST_RETRY_DELAYS_SECONDS = (1.0, 2.0)
    const.REQUEST_TIMEOUT_SECONDS = 5
    const.SHARED_HOST_COOLDOWN_SECONDS = 30
    sys.modules[const.__name__] = const
    _load_module(f"{package_name}.retry_policy", root / "retry_policy.py")
    api = _load_module(f"{package_name}.api", root / "api.py")
    api.REQUEST_RETRY_DELAYS_SECONDS = (0.0, 0.0)
    return api


class _FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, *, content_type: None) -> Any:
        assert content_type is None
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def get(self, _url: str, *, timeout: Any) -> _FakeResponse:
        assert timeout.total == 5
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, payload = outcome
        return _FakeResponse(status, payload)


def test_api_succeeds_on_third_total_attempt() -> None:
    """Two connection failures should be retried before returning data."""
    api_module = _load_api_module()
    session = _FakeSession([TimeoutError(), TimeoutError(), (200, {"ok": True})])
    api = api_module.DtuProxyApi(session, "192.0.2.1")

    assert asyncio.run(api.async_status()) == {"ok": True}
    assert session.calls == 3


def test_api_does_not_retry_permanent_http_error() -> None:
    """A permanent HTTP response should fail after one request."""
    api_module = _load_api_module()
    session = _FakeSession([(404, {})])
    api = api_module.DtuProxyApi(session, "192.0.2.1")

    try:
        asyncio.run(api.async_status())
    except api_module.DtuProxyHttpError:
        pass
    else:
        raise AssertionError("Expected a permanent HTTP error")

    assert session.calls == 1


def test_exhausted_connection_batch_starts_shared_host_cooldown() -> None:
    """The other proxy endpoint must not launch a second retry batch."""
    api_module = _load_api_module()
    session = _FakeSession([TimeoutError(), TimeoutError(), TimeoutError()])
    api = api_module.DtuProxyApi(session, "192.0.2.1")

    try:
        asyncio.run(api.async_status())
    except api_module.DtuProxyConnectionError:
        pass
    else:
        raise AssertionError("Expected an exhausted connection error")

    try:
        asyncio.run(api.async_meter())
    except api_module.DtuProxyCooldownError:
        pass
    else:
        raise AssertionError("Expected the shared host cooldown")

    assert session.calls == 3


def test_invalid_json_retries_without_blocking_other_endpoint() -> None:
    """Endpoint-specific invalid JSON should not start the host cooldown."""
    api_module = _load_api_module()
    session = _FakeSession(
        [
            (200, ValueError("bad json")),
            (200, ValueError("bad json")),
            (200, ValueError("bad json")),
            (200, {"meterData": []}),
        ]
    )
    api = api_module.DtuProxyApi(session, "192.0.2.1")

    try:
        asyncio.run(api.async_status())
    except api_module.DtuProxyInvalidResponse:
        pass
    else:
        raise AssertionError("Expected an invalid JSON error")

    assert asyncio.run(api.async_meter()) == {"meterData": []}
    assert session.calls == 4

"""Regression tests for Home Assistant device registry metadata."""

from __future__ import annotations

import ast
from pathlib import Path


def test_linked_devices_reference_proxy_by_identifier() -> None:
    """Linked DeviceInfo entries must use HA's public via_device key."""
    source = Path("custom_components/dtu_proxy/entity.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    device_info_keywords = [
        {keyword.arg for keyword in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeviceInfo"
    ]

    assert all("via_device_id" not in keywords for keywords in device_info_keywords)
    assert sum("via_device" in keywords for keywords in device_info_keywords) == 2

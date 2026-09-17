"""Contract tests for the public meter payload."""

from __future__ import annotations

import json
from pathlib import Path


def _fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / "meter.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_meter_fixture_scaling() -> None:
    meter = _fixture()["meterData"][0]
    assert meter["phaseTotalPower"] == -20010
    assert meter["voltagePhaseA"] / 100 == 231.6
    assert meter["currentPhaseA"] / 1000 == 25.2
    assert meter["powerFactorTotal"] / 10 == -95.1
    assert meter["energyTotalPower"] == 9_399_000
    assert meter["energyTotalConsumed"] == 26_427_234


def test_meter_partial_availability_contract() -> None:
    meter = _fixture()["meterData"][0]
    power_fields = [
        "phaseTotalPower",
        "phaseAPower",
        "phaseBPower",
        "phaseCPower",
        "voltagePhaseA",
        "voltagePhaseB",
        "voltagePhaseC",
        "currentPhaseA",
        "currentPhaseB",
        "currentPhaseC",
        "powerFactorTotal",
        "powerFactorPhaseA",
        "powerFactorPhaseB",
        "powerFactorPhaseC",
    ]
    energy_fields = [key for key in meter if key.startswith("energy")]
    assert all(meter[key] is not None for key in power_fields)
    assert all(meter[key] is not None for key in energy_fields)

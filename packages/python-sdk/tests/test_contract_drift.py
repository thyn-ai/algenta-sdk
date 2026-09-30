# SPDX-License-Identifier: Apache-2.0
"""Contract-drift lane for the Python SDK.

Loads recorded engine response fixtures from ``tests/fixtures/`` and asserts that
parsing them through the SDK's Pydantic models produces a deterministic,
byte-stable round-trip. If a model or fixture change alters the serialized
output, the lane fails until the fixture is regenerated with
``scripts/update_contract_drift_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient
from decision_engine.models_contract import PlatformContractResult
from decision_engine.models_decision_memory import ExecutionReceiptResult

from .conftest import TEST_BASE_URL

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def _load_json_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name / f"{name}.fixture.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


_ModelT = PlatformContractResult | ExecutionReceiptResult


def _round_trip_matches(raw: dict[str, Any], parsed: _ModelT) -> None:
    """Assert that ``parsed.model_dump(mode='json')`` matches the raw fixture."""
    dumped = parsed.model_dump(mode="json")
    assert _canonical_json(dumped) == _canonical_json(raw), (
        "Parsed output no longer matches the recorded fixture. "
        "If the engine contract changed, run scripts/update_contract_drift_fixtures.py "
        "and commit the updated fixture."
    )


@pytest.mark.parametrize(
    ("payload_type", "model_class"),
    [
        ("contract", PlatformContractResult),
        ("receipt", ExecutionReceiptResult),
    ],
)
def test_fixture_parses_directly(payload_type: str, model_class: type[Any]) -> None:
    """Each recorded fixture validates through its SDK model and round-trips."""
    raw = _load_json_fixture(payload_type)
    parsed = model_class.model_validate(raw)
    _round_trip_matches(raw, parsed)


def test_contract_fixture_parses_through_client(
    client: AlgentaClient,
    mock_router: respx.Router,
) -> None:
    """The recorded contract payload survives parsing in the real client path."""
    raw = _load_json_fixture("contract")
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(return_value=Response(200, json=raw))

    parsed = client.get_contract()
    _round_trip_matches(raw, parsed)


def test_receipt_fixture_parses_through_client(
    client: AlgentaClient,
    mock_router: respx.Router,
) -> None:
    """The recorded execution receipt survives parsing in the real client path."""
    raw = _load_json_fixture("receipt")
    mock_router.post(f"{TEST_BASE_URL}/v1/decisions/dec_123/execute").mock(
        return_value=Response(200, json=raw)
    )

    parsed = client.execute_decision(
        "dec_123",
        webhook_url="https://hooks.example.test/algenta",
    )
    _round_trip_matches(raw, parsed)

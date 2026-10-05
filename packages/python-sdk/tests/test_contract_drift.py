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
from collections.abc import Callable
from functools import partial
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


# Fields the engine has retired from ``/v1/meta/contract``. The TypeScript drift lane,
# mirrored from the engine and not edited here, parses the same recorded fixture and
# requires every field its SDK still declares, so the fixture keeps a retired field until
# the SDK that drops it has been mirrored, and is regenerated after that. Until then this
# lane drops such a field, and only once ``PlatformContractResult`` no longer declares it;
# any other undeclared key still fails validation, because the model forbids extra fields.
_RETIRED_CONTRACT_FIELDS = frozenset({"mcp_legacy_sse_endpoint"})


def _load_json_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name / f"{name}.fixture.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_contract_fixture() -> dict[str, Any]:
    """The recorded contract payload as served to the installed SDK's contract version."""
    raw = _load_json_fixture("contract")
    retired_here = _RETIRED_CONTRACT_FIELDS - PlatformContractResult.model_fields.keys()
    return {key: value for key, value in raw.items() if key not in retired_here}


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
    ("load_fixture", "model_class"),
    [
        pytest.param(_load_contract_fixture, PlatformContractResult, id="contract"),
        pytest.param(partial(_load_json_fixture, "receipt"), ExecutionReceiptResult, id="receipt"),
    ],
)
def test_fixture_parses_directly(
    load_fixture: Callable[[], dict[str, Any]], model_class: type[Any]
) -> None:
    """Each recorded fixture validates through its SDK model and round-trips."""
    raw = load_fixture()
    parsed = model_class.model_validate(raw)
    _round_trip_matches(raw, parsed)


def test_contract_fixture_parses_through_client(
    client: AlgentaClient,
    mock_router: respx.Router,
) -> None:
    """The recorded contract payload survives parsing in the real client path."""
    raw = _load_contract_fixture()
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

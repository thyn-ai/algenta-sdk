"""Shared fixtures for the standalone algenta-sdk test suite.

The suite is fully deterministic and network-free:

- ``respx`` intercepts every HTTP call at the httpx transport layer, so no
  request ever leaves the process.
- An autouse fixture clears ambient ``ALGENTA_*`` / ``DE_*`` environment
  variables, points the runtime directory at a per-test tmp dir (so the
  device-binding token cache never touches the real ``~/.algenta/runtime``),
  and stubs the machine-id probe so tests never shell out to platform tools.
- Retry back-off sleeps are replaced with recorders; the suite asserts on the
  computed back-off durations instead of waiting wall-clock time.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

import decision_engine.async_client_transport as async_client_transport
import decision_engine.client_transport as client_transport
from decision_engine import AlgentaClient, device_binding, device_headers

TEST_API_KEY = "de_live_test_key"
TEST_BASE_URL = "https://api.algenta.ai"
TEST_MACHINE_SEED = "sdk-test-machine-seed"

_SDK_ENV_VARS = (
    "ALGENTA_API_KEY",
    "DE_API_KEY",
    "ALGENTA_BASE_URL",
    "DE_BASE_URL",
    "ALGENTA_API_URL",
    "ALGENTA_DEPLOYMENT_MODE",
    "ALGENTA_DISABLE_CLOUD",
    "ALGENTA_APP_BASE_URL",
    "APP_BASE_URL",
    "DE_APP_BASE_URL",
    "ALGENTA_DEVICE_ID",
    "DE_DEVICE_ID",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Give every test a deterministic, side-effect-free environment.

    Yields the per-test runtime directory used for the device-binding token
    cache and install-id file.
    """
    for name in _SDK_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    runtime_dir = tmp_path / "algenta-runtime"
    monkeypatch.setenv("ALGENTA_RUNTIME_DIR", str(runtime_dir))
    # Pin the machine-id probe: the real implementation may shell out to
    # platform tooling, which is slow and machine-dependent in tests.
    monkeypatch.setattr(device_headers, "_raw_machine_id", lambda: TEST_MACHINE_SEED)
    # The binding-token cache keeps a process-level in-memory copy; clear it
    # so tokens never leak between tests.
    device_binding._MEMORY_STORE.clear()
    yield runtime_dir
    device_binding._MEMORY_STORE.clear()


@pytest.fixture(autouse=True)
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace retry back-off sleeps with a recorder.

    Back-off behavior is asserted through the recorded durations, so the
    suite runs instantly and never depends on wall-clock timing.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(client_transport.time, "sleep", sleeps.append)

    async def _fake_async_sleep(duration: float) -> None:
        sleeps.append(duration)

    monkeypatch.setattr(async_client_transport.asyncio, "sleep", _fake_async_sleep)
    return sleeps


@pytest.fixture
def mock_router() -> Iterator[respx.Router]:
    """An intercepting HTTP router that fails on unexpected requests.

    Every declared route must be hit at least once; a request that matches no
    declared route raises immediately. Tests that need to assert a route was
    *not* called should use a local ``respx.mock(assert_all_called=False)``
    context instead.
    """
    with respx.mock(assert_all_called=True) as router:
        yield router


@pytest.fixture
def client() -> Iterator[AlgentaClient]:
    instance = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)
    yield instance
    instance.close()


@pytest.fixture
def no_retry_client() -> Iterator[AlgentaClient]:
    """A client with retries disabled: exactly one HTTP attempt per call."""
    instance = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)
    yield instance
    instance.close()


def request_json(route: respx.Route, call_index: int = 0) -> dict[str, Any]:
    """Decode the JSON body of a recorded request for shape assertions."""
    request = route.calls[call_index].request
    return json.loads(request.content.decode("utf-8"))


def derived_test_device_id() -> str:
    """The deterministic device ID produced under the stubbed machine seed."""
    return device_headers._derived_device_id_from_seed(TEST_MACHINE_SEED)


def make_query_result_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query_id": "q_123",
        "result": 4200.0,
        "result_type": "scalar",
        "confidence": 0.97,
        "plan": ["resolve_column", "aggregate"],
        "resolved_column": "revenue",
        "resolved_role": "measure",
        "resolved_source": "orders",
        "row_count": 1,
        "ambiguous": False,
        "exact_spec": True,
        "latency_ms": 12.5,
        "decision_path": "governed",
        "plan_hash": "planhash123",
        "validated": True,
        "deterministic_scope": "full",
        "confidence_source": "calibrated",
    }
    payload.update(overrides)
    return payload


def make_decision_envelope_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b",
        "status": "completed",
        "engine_version": "1.0.0",
        "recommended_action": "ship_it",
        "confidence": 0.91,
        "rationale": "Expected value is positive under all scenarios.",
        "metrics": {
            "expected_value": 12500.0,
            "median": 12100.0,
            "std_deviation": 800.0,
            "variance": 640000.0,
            "probability_of_loss": 0.05,
        },
        "percentiles": {
            "p5": 10000.0,
            "p25": 11500.0,
            "p50": 12100.0,
            "p75": 13000.0,
            "p95": 14500.0,
        },
        "scenarios_run": 10000,
        "execution_ms": 42,
        "metadata": {"mode": "auto", "billing_units": 1, "engine_version": "1.0.0"},
    }
    payload.update(overrides)
    return payload


def make_decision_log_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "dec_123",
        "org_id": "org_123",
        "chosen_action": "ship_it",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_platform_contract_payload(base_url: str) -> dict[str, Any]:
    """A complete, valid ``/v1/meta/contract`` response body.

    Mirrors what the Algenta API returns: the nested
    ``primary_data_query_contract`` section ships verbatim in the SDK's
    generated contract module, so the fixture reuses that constant rather
    than restating it.
    """
    from decision_engine._contract import PRIMARY_DATA_QUERY_CONTRACT

    normalized = base_url.rstrip("/")
    return {
        "contract_version": "v1.5",
        "brand": "Algenta",
        "api_base_url": normalized,
        "mcp_endpoint": f"{normalized}/mcp",
        "mcp_transport": "streamable_http",
        "mcp_protocol_version": "2025-11-25",
        "mcp_legacy_sse_endpoint": f"{normalized}/mcp/sse",
        "mcp_tools_endpoint": f"{normalized}/mcp/tools",
        "auth_scheme": "bearer_api_key",
        "api_key_prefixes": {"live": "de_live_", "test": "de_test_"},
        "compatibility": {
            "legacy_headers": ["X-API-Key"],
            "legacy_env_vars": ["DE_API_KEY"],
            "legacy_domains": ["api.algenta.io"],
            "deprecation_window_days": 90,
        },
        "privacy_registry": {
            "algenta_owned_hosts": ["api.algenta.ai"],
            "algenta_owned_suffixes": [".algenta.ai"],
            "vendor_telemetry_hosts": [],
            "private_host_suffixes": [".internal"],
        },
        "defaults": {
            "read_only_default": True,
            "write_confirmation_required": True,
            "plan_limits": {},
        },
        "primary_data_query_contract": deepcopy(PRIMARY_DATA_QUERY_CONTRACT),
        "capability_plane": None,
        "integrations": [],
    }


def make_openapi_contract_payload(**overrides: Any) -> dict[str, Any]:
    """A minimal valid ``/openapi.json`` body for the contract-fallback path."""
    payload: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Algenta API", "version": "v1"},
        "paths": {},
        "x-primary-data-query-contract": {
            "api": {"contract_endpoint": "/v1/meta/contract"},
        },
    }
    payload.update(overrides)
    return payload


def make_runtime_manifest_payload(**overrides: Any) -> dict[str, Any]:
    """A minimal valid ``/v1/runtime/manifest`` response body.

    Enum values come from the shipped enum classes so the fixture cannot
    drift from the SDK's own contract definitions.
    """
    from decision_engine.models_runtime_manifest._enums import (
        RuntimeBenchmarkDiscoveryRuleResult,
        RuntimeDeploymentModeResult,
        RuntimeLayerResult,
        RuntimeNonShippingRuleResult,
        RuntimeSignatureAlgorithmResult,
        RuntimeSignatureScopeResult,
    )

    snapshot = {
        "snapshot_id": "snap_123",
        "sha256": "0" * 64,
        "source": "control-plane",
        "description": "Test snapshot",
    }
    payload: dict[str, Any] = {
        "runtime_version": "1.0.0",
        "mojo_version": "0.26.1",
        "llm_core_manifest": "llm-core@1.0.0",
        "module_manifest_version": "1.0.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "deployment_mode": RuntimeDeploymentModeResult.saas.value,
        "deployment_mode_raw": "saas",
        "deployment_modes": {
            "current": RuntimeDeploymentModeResult.saas.value,
            "rule": "Deployment mode is pinned by the operator.",
        },
        "policy_snapshot": snapshot,
        "schema_snapshot": dict(snapshot),
        "shipping_contract": {
            "module_count": 0,
            "function_count": 0,
            "runtime_core_layer": RuntimeLayerResult.mojo_llm_runtime_core.value,
            "benchmark_discovery_rule": (
                RuntimeBenchmarkDiscoveryRuleResult.shipping_llm_rollout_only.value
            ),
        },
        "benchmark_discovery_lane": {
            "discovered_source_modules": 0,
            "discovered_public_functions": 0,
            "shipping_manifest_modules": 0,
            "shipping_manifest_functions": 0,
            "non_shipping_rule": (
                RuntimeNonShippingRuleResult.broader_mojo_inventory_not_advertised.value
            ),
        },
        "advertised_capabilities": {},
        "execution_model": {},
        "external_nondeterminism": {"rule": "External calls are wrapped and recorded."},
        "artifact_lineage": {"immutability_rule": "Artifacts are content-addressed."},
        "capability_algebra": {"enums": {}},
        "benchmarking": {},
        "scheduler_model": {},
        "memory_model": {},
        "evaluation_science": {},
        "threat_model": {},
        "formal_release_theorem": {"statement": "A release ships only when all gates pass."},
        "release_artifact_bundle": {},
        "manifest_digest": "1" * 64,
        "signature": {
            "algorithm": RuntimeSignatureAlgorithmResult.hmac_sha256.value,
            "key_id": "key_123",
            "digest_hex": "2" * 64,
            "signature_hex": "3" * 64,
            "scope": RuntimeSignatureScopeResult.control_plane_hmac_v1.value,
        },
    }
    payload.update(overrides)
    return payload


def error_response(
    status: int,
    *,
    message: str = "something went wrong",
    code: str | None = None,
    request_id: str | None = None,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Build an error response in the API's structured error envelope."""
    error: dict[str, Any] = {"message": message}
    if code is not None:
        error["code"] = code
    if details is not None:
        error["details"] = details
    body: dict[str, Any] = {"error": error}
    if request_id is not None:
        body["request_id"] = request_id
    return Response(status, json=body, headers=headers or {})

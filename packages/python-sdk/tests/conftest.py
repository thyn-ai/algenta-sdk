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


def make_runtime_signature_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``signature`` block shared by every signed runtime payload."""
    from decision_engine.models_runtime_manifest._enums import (
        RuntimeSignatureAlgorithmResult,
        RuntimeSignatureScopeResult,
    )

    payload: dict[str, Any] = {
        "algorithm": RuntimeSignatureAlgorithmResult.hmac_sha256.value,
        "key_id": "key_123",
        "digest_hex": "2" * 64,
        "signature_hex": "3" * 64,
        "scope": RuntimeSignatureScopeResult.control_plane_hmac_v1.value,
    }
    payload.update(overrides)
    return payload


# The two shipping modules used by every runtime-admin fixture below. Their
# names are ``RuntimeModuleIdResult`` values; the parallel ``shipping_runtime_*``
# lists in the benchmarks payload must line up with this order.
RUNTIME_ADMIN_MODULES: tuple[tuple[str, int], ...] = (("bpe_tokenizer", 2), ("embeddings", 3))


def make_runtime_module_entry_payload(
    name: str,
    *,
    function_count: int,
    maturity: str = "benchmarked",
    layer: str = "mojo_llm_runtime_core",
    **overrides: Any,
) -> dict[str, Any]:
    """A valid ``RuntimeModuleManifestEntryResult`` for a shipping module."""
    payload: dict[str, Any] = {
        "name": name,
        "function_count": function_count,
        "functions": [f"{name}.fn_{index}" for index in range(function_count)],
        "layer": layer,
        "maturity": maturity,
        "benchmark_artifact": f"benchmarks/{name}.json",
        "benchmark_speedup_x": 4.0,
        "compiled_artifact": f"bin/{name}.so",
        "compiled_engine": "mojo",
        "max_cold_ms": 12.0,
        "max_warm_ms": 3.0,
        "max_hot_ms": 1.0,
    }
    payload.update(overrides)
    return payload


def make_runtime_benchmark_discovery_lane_payload(**overrides: Any) -> dict[str, Any]:
    """A discovery lane that lists the two shipping modules plus one non-shipping one.

    ``discovered_source_inventory`` must be sorted by ``import_path`` and cover
    every shipping module name; the model validators enforce both.
    """
    from decision_engine.models_runtime_manifest._enums import RuntimeNonShippingRuleResult

    payload: dict[str, Any] = {
        "discovered_source_modules": 3,
        "discovered_public_functions": 9,
        "discovered_source_inventory": [
            {"import_path": "bpe_tokenizer", "public_function_count": 2},
            {"import_path": "embeddings", "public_function_count": 3},
            {"import_path": "kv_cache", "public_function_count": 4},
        ],
        "shipping_manifest_modules": 2,
        "shipping_manifest_functions": 5,
        "non_shipping_rule": (
            RuntimeNonShippingRuleResult.broader_mojo_inventory_not_advertised.value
        ),
    }
    payload.update(overrides)
    return payload


def make_runtime_admin_modules_payload(**overrides: Any) -> dict[str, Any]:
    """A valid, internally consistent ``/v1/admin/runtime/modules`` body."""
    from decision_engine.models_runtime_manifest._enums import (
        RuntimeBenchmarkDiscoveryRuleResult,
        RuntimeLayerResult,
    )

    modules = [
        make_runtime_module_entry_payload(
            "bpe_tokenizer", function_count=2, maturity="benchmarked"
        ),
        make_runtime_module_entry_payload(
            "embeddings", function_count=3, maturity="enterprise_ready"
        ),
    ]
    payload: dict[str, Any] = {
        "runtime_version": "1.0.0",
        "llm_core_manifest": "llm-core@1.0.0",
        "module_manifest_version": "1.0.0",
        "shipping_contract": {
            "module_count": 2,
            "function_count": 5,
            "runtime_core_layer": RuntimeLayerResult.mojo_llm_runtime_core.value,
            "benchmark_discovery_rule": (
                RuntimeBenchmarkDiscoveryRuleResult.shipping_llm_rollout_only.value
            ),
        },
        "summary": {
            "module_count": 2,
            "function_count": 5,
            "maturity_counts": {"benchmarked": 1, "enterprise_ready": 1},
            "layer_counts": {"mojo_llm_runtime_core": 2},
        },
        "proof_matrix": [
            {
                "layer": "mojo_llm_runtime_core",
                "status": "benchmarked",
                "obligations": ["numerical parity", "deterministic kernels"],
                "evidence_paths": ["proofs/core.json"],
            }
        ],
        "modules": modules,
        "manifest_digest": "1" * 64,
        "signature": make_runtime_signature_payload(),
    }
    payload.update(overrides)
    return payload


def make_runtime_admin_benchmarks_payload(**overrides: Any) -> dict[str, Any]:
    """A valid, internally consistent ``/v1/admin/runtime/benchmarks`` body.

    Every quality gate is enabled, so the fixture carries the benchmark class,
    SLO budget, evaluation dimension and release blocker each gate requires.
    """
    module_benchmarks = [
        {
            "name": "bpe_tokenizer",
            "function_count": 2,
            "benchmark_artifact": "benchmarks/bpe_tokenizer.json",
            "benchmark_speedup_x": 4.0,
            "compiled_artifact": "bin/bpe_tokenizer.so",
            "compiled_engine": "mojo",
            "max_cold_ms": 12.0,
            "max_warm_ms": 3.0,
            "max_hot_ms": 1.0,
        },
        {
            "name": "embeddings",
            "function_count": 3,
            "benchmark_artifact": "benchmarks/embeddings.json",
            "benchmark_speedup_x": 6.5,
            "compiled_artifact": "bin/embeddings.so",
            "compiled_engine": "mojo",
            "max_cold_ms": 15.0,
            "max_warm_ms": 4.0,
            "max_hot_ms": 1.5,
        },
    ]
    benchmark_classes = [
        {"code": "B1", "description": "Microkernel latency", "evidence_paths": []},
        {"code": "B6", "description": "Checkpoint replay overhead", "evidence_paths": []},
        {"code": "B7", "description": "MCP tool latency", "evidence_paths": []},
        {"code": "B9", "description": "RAG retrieval quality and latency", "evidence_paths": []},
        {"code": "B10", "description": "Decision workflow completion", "evidence_paths": []},
    ]
    slo_budgets = [
        {
            "name": "replay",
            "applies_to": "agent runtime checkpoint persistence",
            "p95_objective_ms": 50.0,
        },
        {
            "name": "mcp_call_first_party",
            "applies_to": "first-party or internal MCP tools",
            "p95_objective_ms": 80.0,
            "hard_ceiling_ms": 200.0,
        },
        {
            "name": "decision_plan_creation",
            "applies_to": "decision runtime plan generation",
            "p95_objective_ms": 120.0,
            "notes": "Plan generation excludes simulation time.",
        },
        {
            "name": "ttft",
            "applies_to": "first-party native LLM serving path",
            "p95_objective_ms": 300.0,
        },
    ]
    payload: dict[str, Any] = {
        "runtime_version": "1.0.0",
        "llm_core_manifest": "llm-core@1.0.0",
        "module_manifest_version": "1.0.0",
        "benchmark_discovery_lane": make_runtime_benchmark_discovery_lane_payload(),
        "benchmarking": {
            "classes": benchmark_classes,
            "required_metrics": ["p50", "p95", "tokens_per_second"],
            "baselines": ["Python reference", "Algenta Mojo-native path"],
        },
        "slo_budgets": slo_budgets,
        "quality_gate_benchmark_classes": benchmark_classes[1:],
        "quality_gate_slo_budgets": slo_budgets[:3],
        "evaluation_science": {
            "dimensions": [
                "replay success rate",
                "tool-call correctness",
                "retrieval precision and recall",
                "decision outcome delta",
            ],
            "methods": ["regression tests", "counterfactual replay"],
            "release_blockers": [
                "replay success regression",
                "tool-call error-rate increase",
                "RAG precision drop",
                "decision-plan validity drop",
            ],
        },
        "evaluation_summary": {
            "dimension_count": 4,
            "method_count": 2,
            "release_blocker_count": 4,
            "benchmark_class_count": 4,
            "slo_budget_count": 3,
            "replay_gate_enabled": True,
            "tool_call_quality_gate_enabled": True,
            "rag_quality_gate_enabled": True,
            "decision_quality_gate_enabled": True,
        },
        "compiled_artifacts": [
            {
                "kind": "compiled_mojo_binary",
                "path": "bin/bpe_tokenizer.so",
                "sha256": "a" * 64,
                "size_bytes": 1024,
            },
            {
                "kind": "compiled_mojo_binary",
                "path": "bin/embeddings.so",
                "sha256": "b" * 64,
                "size_bytes": 2048,
            },
        ],
        "shipping_runtime_modules": ["bpe_tokenizer", "embeddings"],
        "shipping_runtime_function_counts": [2, 3],
        "shipping_runtime_benchmark_speedups_x": [4.0, 6.5],
        "shipping_runtime_benchmark_artifacts": [
            "benchmarks/bpe_tokenizer.json",
            "benchmarks/embeddings.json",
        ],
        "shipping_runtime_compiled_artifacts": ["bin/bpe_tokenizer.so", "bin/embeddings.so"],
        "shipping_runtime_compiled_engines": ["mojo", "mojo"],
        "shipping_runtime_max_cold_ms": [12.0, 15.0],
        "shipping_runtime_max_warm_ms": [3.0, 4.0],
        "shipping_runtime_max_hot_ms": [1.0, 1.5],
        "module_benchmarks": module_benchmarks,
        "manifest_digest": "1" * 64,
        "signature": make_runtime_signature_payload(),
    }
    payload.update(overrides)
    return payload


def make_runtime_release_validation_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``/v1/admin/runtime/validation`` body with two evaluated conditions."""
    payload: dict[str, Any] = {
        "runtime_version": "1.0.0",
        "llm_core_manifest": "llm-core@1.0.0",
        "module_manifest_version": "1.0.0",
        "theorem_statement": "A release ships only when all gates pass.",
        "valid_release": True,
        "conditions": [
            {
                "condition": "manifest-listed",
                "satisfied": True,
                "detail": "Every shipping module is listed in the manifest.",
                "evidence_paths": ["proofs/manifest.json"],
            },
            {
                "condition": "proof-backed",
                "satisfied": True,
                "detail": "Every module carries a proof bundle.",
                "evidence_paths": ["proofs/bpe_tokenizer.json", "proofs/embeddings.json"],
            },
        ],
        "deployment_mode": "saas",
        "deployment_mode_raw": "saas",
        "manifest_digest": "1" * 64,
        "signature": make_runtime_signature_payload(),
    }
    payload.update(overrides)
    return payload


# Capability-plane payloads, shared by the model round-trip tests and the surface tests.


def make_capability_profile_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile_id": "profile.github.user",
        "provider_id": "provider.github",
        "name": "GitHub (user)",
        "auth_kind": "oauth2",
        "default_execution_owner": "algenta_managed",
        "binding_scope_default": "user",
        "supported_binding_scopes": ["user", "org"],
    }
    payload.update(overrides)
    return payload


def make_capability_provider_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider_id": "provider.github",
        "provider_type": "mcp_provider",
        "name": "GitHub",
        "active": True,
        "profiles": [make_capability_profile_payload()],
    }
    payload.update(overrides)
    return payload


def make_capability_binding_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "binding_id": "bind_1",
        "provider_id": "provider.github",
        "profile_id": "profile.github.user",
        "binding_name": "github-main",
        "scope": "user",
        "scope_ref": "user_1",
        "status": "active",
        "execution_owner": "algenta_managed",
        "system_managed": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_capability_catalog_entry_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "capability_id": "cap.github.create_issue",
        "provider_id": "provider.github",
        "profile_id": "profile.github.user",
        "binding_id": "bind_1",
        "kind": "tool",
        "name": "Create issue",
        "implementation_kind": "mcp_tool",
        "execution_owner": "algenta_managed",
        "input_schema_ref": "schemas/create_issue.in.json",
        "output_schema_ref": "schemas/create_issue.out.json",
        "side_effect_class": "write_external",
        "risk_level": "medium",
        "required_policy": "write_confirmation",
        "replayability": "artifact_backed",
        "approval_required": True,
        "trust_tier": "verified",
        "manifest_hash": "m" * 64,
        "binding_status": "active",
    }
    payload.update(overrides)
    return payload


def make_capability_route_fallback_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "capability_id": "cap.github.create_issue",
        "provider_id": "provider.github",
        "binding_id": "bind_1",
        "kind": "tool",
        "execution_owner": "algenta_managed",
        "confidence": 0.42,
        "reason": "Same side-effect class, lower trust tier.",
    }
    payload.update(overrides)
    return payload


# Deployment, repository-intelligence and product payloads, shared the same way.


def make_deployment_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "deployment_id": "dep_1",
        "org_id": "org_1",
        "provider": "aws",
        "region": "eu-west-1",
        "status": "provisioning",
        "cost_usd_month": 420.0,
        "billable_cost_usd_month": 504.0,
        "billing_markup_pct": 20.0,
        "created_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_repository_artifact_ref_payload(
    kind: str = "repository_snapshot", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": f"art_{kind}",
        "artifact_kind": kind,
        "content_hash": "c" * 64,
        "storage_path": f"artifacts/{kind}.parquet",
        "created_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_repository_snapshot_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "repository_id": "repo_1",
        "snapshot_id": "snap_1",
        "connector_type": "github",
        "ref": "main",
        "resolved_revision": "9781711aced91c585e0c39b9262aed58eaa0fc97",
        "content_hash": "c" * 64,
        "status": "ready",
        "created_at": "2026-01-01T00:00:00Z",
        "file_count": 412,
        "language_counts": {"python": 380, "typescript": 32},
        "raw_repo_token_estimate": 1_250_000,
        "repository_snapshot_artifact": make_repository_artifact_ref_payload("repository_snapshot"),
        "repository_graph_artifact": make_repository_artifact_ref_payload("repository_graph"),
        "symbol_graph_artifact": make_repository_artifact_ref_payload("symbol_graph"),
        "dependency_graph_artifact": make_repository_artifact_ref_payload("dependency_graph"),
    }
    payload.update(overrides)
    return payload


def make_repository_evidence_item_payload(rank: int = 1, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_id": f"ev_{rank}",
        "rank": rank,
        "source_type": "symbol",
        "source_ref": "decision_engine/client_facade/__init__.py::_request",
        "file_path": "decision_engine/client_facade/__init__.py",
        "symbol_name": "_request",
        "summary": "Transport entry point for every facade call.",
        "snippet": "def _request(self, method, path, **kwargs): ...",
        "token_count": 64,
        "score": 0.91,
    }
    payload.update(overrides)
    return payload


def make_repository_triage_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "repository_id": "repo_1",
        "snapshot_id": "snap_1",
        "workspace_evidence_bundle_ref": "artifacts/evidence_bundle.json",
        "created_at": "2026-01-01T00:00:00Z",
        "suspect_files": ["decision_engine/client_facade/__init__.py"],
        "suspect_symbols": ["_request"],
        "raw_repo_token_estimate": 1_250_000,
        "evidence_bundle_token_count": 4_800,
        "reduction_ratio": 260.4,
        "evidence_items": [
            make_repository_evidence_item_payload(1),
            make_repository_evidence_item_payload(2),
        ],
        "workspace_evidence_bundle_artifact": make_repository_artifact_ref_payload(
            "evidence_bundle"
        ),
    }
    payload.update(overrides)
    return payload


def make_decision_plan_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recommended_action": "patch_transport_retry",
        "confidence": 0.88,
        "expected_value": 1200.0,
        "risk": {"p5": -50.0, "p95": 2400.0, "probability_of_loss": 0.04},
        "options": [
            {
                "name": "patch_transport_retry",
                "rank": 1,
                "expected_value": 1200.0,
                "risk": {"p5": -50.0, "p95": 2400.0, "probability_of_loss": 0.04},
                "score": 0.88,
            }
        ],
        "rationale": "The retry loop swallows the last exception.",
    }
    payload.update(overrides)
    return payload


def make_product_decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision_id": "pd_1",
        "action": "launch",
        "confidence": 0.82,
        "reasoning": "Expected value is positive with bounded downside.",
        "why": ["EV > 0", "P(loss) < 10%"],
        "expected_outcome": 15_000.0,
        "downside_risk": -2_000.0,
        "upside_potential": 40_000.0,
        "probability_of_loss": 0.08,
        "scenarios_evaluated": 10_000,
        "latency_ms": 41.5,
    }
    payload.update(overrides)
    return payload


def make_product_agent_run_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "par_1",
        "status": "completed",
        "result": "Shipped the release notes.",
        "steps": [
            {"step": 1, "action": "read_changelog", "tool": "fs.read", "result": "ok"},
            {"step": 2, "action": "summarise"},
        ],
        "tools_used": ["fs.read"],
        "latency_ms": 820.0,
    }
    payload.update(overrides)
    return payload


def make_product_forecast_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "forecast_id": "fc_1",
        "metric": "revenue",
        "baseline": 100.0,
        "forecast_mean": 112.0,
        "total_change_pct": 12.0,
        "periods": [
            {
                "period": 1,
                "forecast": 104.0,
                "lower_bound": 98.0,
                "upper_bound": 110.0,
                "trend": "up",
            },
            {
                "period": 2,
                "forecast": 112.0,
                "lower_bound": 101.0,
                "upper_bound": 123.0,
                "trend": "up",
            },
        ],
        "scenarios_evaluated": 5_000,
        "latency_ms": 66.0,
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

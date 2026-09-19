"""Tests for the signed runtime-manifest models (``models_runtime_manifest``).

The manifest is a strict (``extra="forbid"``) contract: every identifier list
must be unique, list fields must arrive as JSON arrays, module counts must
reconcile across sections, and shipping kernels must carry their proof
references. ``make_runtime_manifest_payload`` in ``conftest.py`` is the minimal
valid manifest; the rich payload built here populates every list so that each
validator actually runs, and the negative cases pin one rule each.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_runtime_manifest import (
    ReleaseConditionEvaluationResult,
    RuntimeAdvertisedCapabilitiesResult,
    RuntimeArtifactLineageSchemaResult,
    RuntimeBenchmarkClassEntryResult,
    RuntimeBenchmarkDiscoveryLaneResult,
    RuntimeBenchmarkFrameworkResult,
    RuntimeCapabilityAlgebraSchemaResult,
    RuntimeCapabilityEnumsResult,
    RuntimeDeploymentModesResult,
    RuntimeEvaluationScienceResult,
    RuntimeExecutionModelResult,
    RuntimeExternalNondeterminismPolicyResult,
    RuntimeFormalReleaseTheoremResult,
    RuntimeKernelPromotionCriteriaResult,
    RuntimeLayerProofMatrixEntryResult,
    RuntimeManifestResult,
    RuntimeMaturityResult,
    RuntimeMemoryModelResult,
    RuntimeModuleIdResult,
    RuntimeModuleManifestEntryResult,
    RuntimeReleaseArtifactBundleResult,
    RuntimeReleaseValidationResult,
    RuntimeSchedulerModelResult,
    RuntimeThreatModelResult,
)
from decision_engine.models_runtime_manifest._enums import (
    _count_runtime_values,
    _ensure_unique_runtime_values,
    _normalized_runtime_value,
)

from .conftest import (
    make_runtime_benchmark_discovery_lane_payload,
    make_runtime_manifest_payload,
    make_runtime_module_entry_payload,
    make_runtime_release_validation_payload,
)

Mutator = Callable[[dict[str, Any]], None]


def _raises_value_error(fragment: str):
    """Pydantic reports validator failures as ``Value error, <message>``."""
    return pytest.raises(PydanticValidationError, match=re.escape(fragment))


def make_rich_manifest_payload(**overrides: Any) -> dict[str, Any]:
    """A manifest with two shipping modules and every optional list populated."""
    modules = [
        make_runtime_module_entry_payload("bpe_tokenizer", function_count=2),
        make_runtime_module_entry_payload(
            "embeddings", function_count=3, maturity="enterprise_ready"
        ),
    ]
    payload = make_runtime_manifest_payload(
        modules=modules,
        compiled_artifacts=[
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
        supported_channels=["python_sdk", "typescript_sdk", "mcp"],
        validated_auxiliary_channels=["bundled_worker"],
        feature_flag_channels=["http_api_feature_flag"],
        maturity={"bpe_tokenizer": "benchmarked", "embeddings": "enterprise_ready"},
        deployment_modes={
            "current": "saas",
            "supported_modes": ["saas", "vpc", "self_hosted"],
            "rule": "Deployment mode is pinned by the operator.",
        },
        shipping_contract={
            "module_count": 2,
            "function_count": 5,
            "runtime_core_layer": "mojo_llm_runtime_core",
            "benchmark_discovery_rule": (
                "Only the 22-module, 209-function LLM rollout is treated as the shipping "
                "runtime contract."
            ),
        },
        benchmark_discovery_lane=make_runtime_benchmark_discovery_lane_payload(),
        advertised_capabilities={
            "runtime_modules": ["bpe_tokenizer", "embeddings"],
            "public_endpoints": ["/v1/meta/contract", "/v1/runtime/manifest"],
            "admin_endpoints": ["/v1/admin/runtime/modules"],
            "feature_flag_endpoints": ["/v1/libraries"],
        },
        system_invariants=[
            {"name": "Manifest Truth", "statement": "The manifest lists every shipping module."},
            {"name": "Replay Determinism", "statement": "Replays reproduce recorded outputs."},
        ],
        execution_model={
            "state_fields": ["request", "tenant"],
            "allowed_transitions": ["model_call_started", "checkpoint_committed"],
            "validity_rules": ["schema-valid", "replayable"],
        },
        external_nondeterminism={
            "sources": ["provider responses", "clock time"],
            "rule": "External calls are wrapped and recorded.",
            "required_artifacts": ["provider response record", "clock snapshot"],
            "failure_codes": ["provider_timeout"],
        },
        artifact_lineage={
            "artifact_flow": ["input", "outcome"],
            "required_node_fields": ["node_id", "content_hash"],
            "immutability_rule": "Artifacts are content-addressed.",
        },
        capability_algebra={
            "required_fields": ["tool_name", "risk_level"],
            "enums": {
                "side_effect_class": ["read_only", "write_scoped"],
                "risk_level": ["low", "high"],
                "replayability": ["deterministic"],
            },
            "rules": ["MCP tools are untrusted by default."],
        },
        kernel_promotion_criteria={
            "required_manifest_fields": ["name", "layer"],
            "required_proof_reference_fields": ["benchmark_report_ref"],
            "deterministic_test_corpus_rule": "Corpus is pinned by hash.",
            "python_parity_rule": "Outputs match the Python reference.",
            "schema_compatibility_rule": "Schemas are backward compatible.",
            "minimum_primary_metric_improvement_pct": 5.0,
            "maximum_adjacent_metric_regression_pct": 1.0,
            "benchmark_exception_rule": "Exceptions need an owner sign-off.",
            "rollback_scope_rule": "Rollback is per module.",
            "tenant_isolation_rule": "No cross-tenant cache reuse.",
            "replay_compatibility_rule": "Replays stay valid across promotions.",
        },
        proof_matrix=[
            {
                "layer": "mojo_llm_runtime_core",
                "status": "benchmarked",
                "obligations": ["numerical parity"],
                "evidence_paths": ["proofs/core.json"],
            }
        ],
        benchmarking={
            "classes": [{"code": "B1", "description": "Microkernel latency"}],
            "required_metrics": ["p50", "p95"],
            "baselines": ["Python reference"],
        },
        slo_budgets=[
            {
                "name": "ttft",
                "applies_to": "first-party native LLM serving path",
                "p95_objective_ms": 300.0,
            }
        ],
        scheduler_model={
            "policies": ["FIFO", "tenant_fair"],
            "minimize": ["tail latency"],
            "maximize": ["fairness"],
            "invariants": ["No request starves indefinitely."],
        },
        memory_model={
            "regions": ["model weights", "KV cache pages"],
            "rules": ["KV pages are tenant-scoped."],
            "failure_codes": ["kv_cache_exhausted"],
        },
        evaluation_science={
            "dimensions": ["answer correctness"],
            "methods": ["regression tests"],
            "release_blockers": ["policy violation increase"],
        },
        typed_failures=[{"code": "provider_timeout", "description": "Provider timed out."}],
        threat_model={
            "threat_classes": ["prompt injection"],
            "controls": ["tool allowlists"],
            "non_negotiable_rules": ["MCP tools are untrusted by default."],
        },
        formal_release_theorem={
            "statement": "A release ships only when all gates pass.",
            "required_conditions": ["manifest-listed", "proof-backed"],
        },
        release_artifact_bundle={
            "required_artifacts": ["signed runtime manifest", "benchmark report"]
        },
        release_gates=[
            {"gate": "A", "description": "Manifest listed"},
            {"gate": "B", "description": "Proof backed"},
        ],
        immediate_implementation_sequence=[
            {"pr": "PR-1", "focus": "tokenizer", "deliverables": ["bpe kernel"]}
        ],
    )
    payload.update(overrides)
    return payload


class TestRichManifest:
    def test_parses_every_section(self) -> None:
        manifest = RuntimeManifestResult.model_validate(make_rich_manifest_payload())

        assert [module.name for module in manifest.modules] == [
            RuntimeModuleIdResult.bpe_tokenizer,
            RuntimeModuleIdResult.embeddings,
        ]
        assert manifest.maturity[RuntimeModuleIdResult.embeddings] is (
            RuntimeMaturityResult.enterprise_ready
        )
        assert manifest.kernel_promotion_criteria is not None
        assert manifest.kernel_promotion_criteria.minimum_primary_metric_improvement_pct == 5.0
        assert [gate.gate.value for gate in manifest.release_gates] == ["A", "B"]
        assert manifest.compiled_artifacts[1].size_bytes == 2048
        assert manifest.benchmark_discovery_lane.discovered_source_modules == 3

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="extra_forbidden|Extra inputs"):
            RuntimeManifestResult.model_validate(make_rich_manifest_payload(surprise=1))

    def test_json_round_trip_is_stable(self) -> None:
        manifest = RuntimeManifestResult.model_validate(make_rich_manifest_payload())

        again = RuntimeManifestResult.model_validate(manifest.model_dump(mode="json"))

        assert again == manifest

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            pytest.param(
                lambda p: p["compiled_artifacts"].append(dict(p["compiled_artifacts"][0])),
                "compiled_artifacts must be unique",
                id="duplicate-compiled-artifact-path",
            ),
            pytest.param(
                lambda p: p["supported_channels"].append("mcp"),
                "supported_channels must be unique",
                id="duplicate-supported-channel",
            ),
            pytest.param(
                lambda p: p["validated_auxiliary_channels"].append("bundled_worker"),
                "validated_auxiliary_channels must be unique",
                id="duplicate-auxiliary-channel",
            ),
            pytest.param(
                lambda p: p["system_invariants"].append(dict(p["system_invariants"][0])),
                "system_invariants must be unique",
                id="duplicate-system-invariant",
            ),
            pytest.param(
                lambda p: p["proof_matrix"].append(dict(p["proof_matrix"][0])),
                "proof_matrix must be unique",
                id="duplicate-proof-matrix-layer",
            ),
            pytest.param(
                lambda p: p["modules"].append(dict(p["modules"][0])),
                "modules must be unique",
                id="duplicate-module",
            ),
            pytest.param(
                lambda p: p["typed_failures"].append(dict(p["typed_failures"][0])),
                "typed_failures must be unique",
                id="duplicate-typed-failure",
            ),
            pytest.param(
                lambda p: p["release_gates"].append(dict(p["release_gates"][0])),
                "release_gates must be unique",
                id="duplicate-release-gate",
            ),
            pytest.param(
                lambda p: p["immediate_implementation_sequence"].append(
                    dict(p["immediate_implementation_sequence"][0])
                ),
                "immediate_implementation_sequence must be unique",
                id="duplicate-implementation-pr",
            ),
            pytest.param(
                lambda p: p["modules"][0].__setitem__("functions", ["bpe_tokenizer.fn_0"]),
                "modules.0.functions must contain exactly 2 entries",
                id="module-function-count-mismatch",
            ),
            pytest.param(
                lambda p: p["shipping_contract"].__setitem__("module_count", 3),
                "shipping_contract.module_count must equal the number of manifest modules",
                id="shipping-module-count-mismatch",
            ),
            pytest.param(
                lambda p: p["shipping_contract"].__setitem__("function_count", 6),
                "shipping_contract.function_count must equal the total module function_count",
                id="shipping-function-count-mismatch",
            ),
            pytest.param(
                lambda p: p["benchmark_discovery_lane"].__setitem__("shipping_manifest_modules", 1),
                "shipping_manifest_modules must equal the number of manifest modules",
                id="discovery-module-count-mismatch",
            ),
            pytest.param(
                lambda p: p["benchmark_discovery_lane"].__setitem__(
                    "shipping_manifest_functions", 4
                ),
                "shipping_manifest_functions must equal the total module function_count",
                id="discovery-function-count-mismatch",
            ),
            pytest.param(
                lambda p: p["benchmark_discovery_lane"].__setitem__(
                    "discovered_source_inventory",
                    [
                        {"import_path": "bpe_tokenizer", "public_function_count": 2},
                        {"import_path": "kv_cache", "public_function_count": 4},
                        {"import_path": "paged_kv_cache", "public_function_count": 3},
                    ],
                ),
                "discovered_source_inventory must include manifest module embeddings",
                id="module-missing-from-discovery-inventory",
            ),
        ],
    )
    def test_integrity_rules_reject_inconsistent_manifests(
        self, mutate: Mutator, message: str
    ) -> None:
        payload = make_rich_manifest_payload()
        mutate(payload)

        with _raises_value_error(message):
            RuntimeManifestResult.model_validate(payload)


class TestBaseModelJsonArrayRule:
    def test_list_fields_must_be_json_arrays(self) -> None:
        with _raises_value_error("modules must be provided as a list."):
            RuntimeManifestResult.model_validate(make_rich_manifest_payload(modules={"a": 1}))

    def test_non_mapping_payloads_fall_through_to_pydantic(self) -> None:
        with pytest.raises(PydanticValidationError):
            RuntimeAdvertisedCapabilitiesResult.model_validate(["python_sdk"])


class TestModuleEntry:
    def test_candidate_modules_need_no_proof_references(self) -> None:
        entry = RuntimeModuleManifestEntryResult.model_validate(
            make_runtime_module_entry_payload(
                "kv_cache", function_count=1, promotion_status="candidate"
            )
        )

        assert entry.promotion_status is not None
        assert entry.promotion_status.value == "candidate"
        assert entry.capability_id is None

    def test_shipping_modules_require_every_proof_reference(self) -> None:
        with _raises_value_error("capability_id must be provided for shipping runtime modules."):
            RuntimeModuleManifestEntryResult.model_validate(
                make_runtime_module_entry_payload(
                    "kv_cache", function_count=1, promotion_status="shipping"
                )
            )

    def test_shipping_modules_reject_blank_proof_references(self) -> None:
        payload = make_runtime_module_entry_payload(
            "kv_cache",
            function_count=1,
            promotion_status="shipping",
            capability_id="cap.kv_cache",
            owner="runtime-team",
            contract_boundary="mojo",
            rollback_flag="   ",
            benchmark_report_ref="reports/kv.json",
            parity_report_ref="reports/kv-parity.json",
            schema_compat_report_ref="reports/kv-schema.json",
            isolation_proof_ref="proofs/kv-isolation.json",
            replay_proof_ref="proofs/kv-replay.json",
        )

        with _raises_value_error("rollback_flag must be provided for shipping runtime modules."):
            RuntimeModuleManifestEntryResult.model_validate(payload)

    def test_fully_referenced_shipping_module_parses(self) -> None:
        entry = RuntimeModuleManifestEntryResult.model_validate(
            make_runtime_module_entry_payload(
                "kv_cache",
                function_count=1,
                promotion_status="shipping",
                capability_id="cap.kv_cache",
                owner="runtime-team",
                contract_boundary="mojo",
                rollback_flag="KV_CACHE_ROLLBACK",
                benchmark_report_ref="reports/kv.json",
                parity_report_ref="reports/kv-parity.json",
                schema_compat_report_ref="reports/kv-schema.json",
                isolation_proof_ref="proofs/kv-isolation.json",
                replay_proof_ref="proofs/kv-replay.json",
            )
        )

        assert entry.rollback_flag == "KV_CACHE_ROLLBACK"

    def test_module_identifier_lists_must_be_unique(self) -> None:
        with _raises_value_error("functions must be unique"):
            RuntimeModuleManifestEntryResult.model_validate(
                make_runtime_module_entry_payload(
                    "kv_cache", function_count=2, functions=["a", "a"]
                )
            )

    def test_strict_numeric_fields_reject_strings(self) -> None:
        payload = make_runtime_module_entry_payload("kv_cache", function_count=1)
        payload["function_count"] = "1"

        with pytest.raises(PydanticValidationError):
            RuntimeModuleManifestEntryResult.model_validate(payload)


class TestBenchmarkDiscoveryLane:
    def test_the_fixture_lane_is_valid(self) -> None:
        lane = RuntimeBenchmarkDiscoveryLaneResult.model_validate(
            make_runtime_benchmark_discovery_lane_payload()
        )

        assert lane.discovered_public_functions == 9
        assert [entry.import_path for entry in lane.discovered_source_inventory] == [
            "bpe_tokenizer",
            "embeddings",
            "kv_cache",
        ]

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            pytest.param(
                lambda p: p.__setitem__("discovered_source_modules", 2),
                "discovered_source_modules must equal the number of discovered_source_inventory",
                id="inventory-count-mismatch",
            ),
            pytest.param(
                lambda p: p["discovered_source_inventory"][0].__setitem__(
                    "public_function_count", 0
                ),
                "discovered_source_inventory.0.public_function_count must be greater than 0",
                id="zero-public-functions",
            ),
            pytest.param(
                lambda p: p.__setitem__("discovered_public_functions", 8),
                "discovered_public_functions must equal the total",
                id="public-function-total-mismatch",
            ),
            pytest.param(
                lambda p: p["discovered_source_inventory"].reverse(),
                "discovered_source_inventory must be sorted by import_path",
                id="unsorted-inventory",
            ),
            pytest.param(
                lambda p: p.__setitem__("shipping_manifest_modules", 4),
                "shipping_manifest_modules cannot exceed",
                id="shipping-modules-exceed-discovered",
            ),
            pytest.param(
                lambda p: p.__setitem__("shipping_manifest_functions", 10),
                "shipping_manifest_functions cannot exceed",
                id="shipping-functions-exceed-discovered",
            ),
            pytest.param(
                lambda p: p["discovered_source_inventory"].__setitem__(
                    2, dict(p["discovered_source_inventory"][0])
                ),
                "benchmark_discovery_lane.discovered_source_inventory must be unique",
                id="duplicate-import-path",
            ),
        ],
    )
    def test_lane_integrity_rules(self, mutate: Mutator, message: str) -> None:
        payload = make_runtime_benchmark_discovery_lane_payload()
        mutate(payload)

        with _raises_value_error(message):
            RuntimeBenchmarkDiscoveryLaneResult.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload", "message"),
    [
        pytest.param(
            RuntimeDeploymentModesResult,
            {"current": "saas", "supported_modes": ["saas", "saas"], "rule": "r"},
            "supported_modes must be unique",
            id="deployment-modes",
        ),
        pytest.param(
            RuntimeKernelPromotionCriteriaResult,
            {
                "required_manifest_fields": ["name", "name"],
                "deterministic_test_corpus_rule": "r",
                "python_parity_rule": "r",
                "schema_compatibility_rule": "r",
                "minimum_primary_metric_improvement_pct": 1.0,
                "maximum_adjacent_metric_regression_pct": 1.0,
                "benchmark_exception_rule": "r",
                "rollback_scope_rule": "r",
                "tenant_isolation_rule": "r",
                "replay_compatibility_rule": "r",
            },
            "required_manifest_fields must be unique",
            id="kernel-promotion-criteria",
        ),
        pytest.param(
            RuntimeAdvertisedCapabilitiesResult,
            {"runtime_modules": ["embeddings", "embeddings"]},
            "runtime_modules must be unique",
            id="advertised-capabilities",
        ),
        pytest.param(
            RuntimeExecutionModelResult,
            {"state_fields": ["request", "request"]},
            "state_fields must be unique",
            id="execution-model",
        ),
        pytest.param(
            RuntimeExternalNondeterminismPolicyResult,
            {"sources": ["clock time", "clock time"], "rule": "r"},
            "sources must be unique",
            id="external-nondeterminism",
        ),
        pytest.param(
            RuntimeArtifactLineageSchemaResult,
            {"artifact_flow": ["input", "input"], "immutability_rule": "r"},
            "artifact_flow must be unique",
            id="artifact-lineage",
        ),
        pytest.param(
            RuntimeCapabilityEnumsResult,
            {"risk_level": ["low", "low"]},
            "risk_level must be unique",
            id="capability-enums",
        ),
        pytest.param(
            RuntimeCapabilityAlgebraSchemaResult,
            {"required_fields": ["tool_name", "tool_name"], "enums": {}},
            "required_fields must be unique",
            id="capability-algebra",
        ),
        pytest.param(
            RuntimeLayerProofMatrixEntryResult,
            {
                "layer": "agent_runtime",
                "status": "benchmarked",
                "evidence_paths": ["p.json", "p.json"],
            },
            "evidence_paths must be unique",
            id="proof-matrix-entry",
        ),
        pytest.param(
            RuntimeBenchmarkClassEntryResult,
            {"code": "B1", "description": "d", "evidence_paths": ["p", "p"]},
            "evidence_paths must be unique",
            id="benchmark-class-entry",
        ),
        pytest.param(
            RuntimeBenchmarkFrameworkResult,
            {
                "classes": [
                    {"code": "B1", "description": "one"},
                    {"code": "B1", "description": "two"},
                ]
            },
            "classes must be unique",
            id="benchmark-framework-classes",
        ),
        pytest.param(
            RuntimeBenchmarkFrameworkResult,
            {"required_metrics": ["p50", "p50"]},
            "required_metrics must be unique",
            id="benchmark-framework-metrics",
        ),
        pytest.param(
            RuntimeSchedulerModelResult,
            {"policies": ["FIFO", "FIFO"]},
            "policies must be unique",
            id="scheduler-model",
        ),
        pytest.param(
            RuntimeMemoryModelResult,
            {"regions": ["model weights", "model weights"]},
            "regions must be unique",
            id="memory-model",
        ),
        pytest.param(
            RuntimeEvaluationScienceResult,
            {"methods": ["regression tests", "regression tests"]},
            "methods must be unique",
            id="evaluation-science",
        ),
        pytest.param(
            RuntimeThreatModelResult,
            {"controls": ["SBOM", "SBOM"]},
            "controls must be unique",
            id="threat-model",
        ),
        pytest.param(
            RuntimeFormalReleaseTheoremResult,
            {"statement": "s", "required_conditions": ["proof-backed", "proof-backed"]},
            "required_conditions must be unique",
            id="formal-release-theorem",
        ),
        pytest.param(
            RuntimeReleaseArtifactBundleResult,
            {"required_artifacts": ["parity report", "parity report"]},
            "required_artifacts must be unique",
            id="release-artifact-bundle",
        ),
    ],
)
def test_section_models_reject_duplicate_identifiers(
    model: type, payload: dict[str, Any], message: str
) -> None:
    with _raises_value_error(message):
        model.model_validate(payload)


class TestReleaseValidation:
    def test_the_fixture_payload_parses(self) -> None:
        result = RuntimeReleaseValidationResult.model_validate(
            make_runtime_release_validation_payload()
        )

        assert result.valid_release is True
        assert [condition.condition.value for condition in result.conditions] == [
            "manifest-listed",
            "proof-backed",
        ]
        assert result.deployment_mode is not None
        assert result.deployment_mode.value == "saas"

    def test_deployment_mode_may_be_null_while_the_raw_value_is_kept(self) -> None:
        result = RuntimeReleaseValidationResult.model_validate(
            make_runtime_release_validation_payload(
                deployment_mode=None, deployment_mode_raw="on-prem-legacy"
            )
        )

        assert result.deployment_mode is None
        assert result.deployment_mode_raw == "on-prem-legacy"

    def test_conditions_must_be_unique(self) -> None:
        payload = make_runtime_release_validation_payload()
        payload["conditions"].append(dict(payload["conditions"][0]))

        with _raises_value_error("conditions must be unique"):
            RuntimeReleaseValidationResult.model_validate(payload)

    def test_condition_evidence_paths_must_be_unique(self) -> None:
        with _raises_value_error("evidence_paths must be unique"):
            ReleaseConditionEvaluationResult.model_validate(
                {
                    "condition": "replay-tested",
                    "satisfied": False,
                    "detail": "Replay drifted.",
                    "evidence_paths": ["replay.json", "replay.json"],
                }
            )

    def test_satisfied_is_strictly_boolean(self) -> None:
        with pytest.raises(PydanticValidationError):
            ReleaseConditionEvaluationResult.model_validate(
                {"condition": "replay-tested", "satisfied": "yes", "detail": "d"}
            )


class TestEnumHelpers:
    def test_normalised_value_unwraps_enums_and_stringifies_everything_else(self) -> None:
        assert _normalized_runtime_value(RuntimeMaturityResult.benchmarked) == "benchmarked"
        assert _normalized_runtime_value(7) == "7"
        assert _normalized_runtime_value("x") == "x"

    def test_ensure_unique_returns_the_input_when_unique(self) -> None:
        values = [RuntimeMaturityResult.benchmarked, RuntimeMaturityResult.deprecated]

        assert _ensure_unique_runtime_values(values, "maturity") is values

    def test_ensure_unique_reports_each_duplicate_once_in_first_seen_order(self) -> None:
        with pytest.raises(ValueError, match=r"names must be unique; duplicate entries: b, a$"):
            _ensure_unique_runtime_values(["a", "b", "b", "a", "b"], "names")

    def test_ensure_unique_applies_the_value_selector(self) -> None:
        entries = [{"code": "B1"}, {"code": "B2"}, {"code": "B1"}]

        with pytest.raises(ValueError, match="classes must be unique; duplicate entries: B1"):
            _ensure_unique_runtime_values(
                entries, "classes", value_selector=lambda entry: entry["code"]
            )

    def test_ensure_unique_compares_enums_by_value(self) -> None:
        with pytest.raises(ValueError, match="duplicate entries: benchmarked"):
            _ensure_unique_runtime_values(
                [RuntimeMaturityResult.benchmarked, "benchmarked"], "maturity"
            )

    def test_count_runtime_values_tallies_in_first_seen_order(self) -> None:
        counts = _count_runtime_values(
            [
                RuntimeMaturityResult.benchmarked,
                RuntimeMaturityResult.deprecated,
                RuntimeMaturityResult.benchmarked,
            ]
        )

        assert counts == {
            RuntimeMaturityResult.benchmarked: 2,
            RuntimeMaturityResult.deprecated: 1,
        }
        assert list(counts) == [RuntimeMaturityResult.benchmarked, RuntimeMaturityResult.deprecated]

    def test_count_runtime_values_of_nothing_is_empty(self) -> None:
        assert _count_runtime_values([]) == {}

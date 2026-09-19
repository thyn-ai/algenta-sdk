"""Tests for the runtime-admin models: module inventory and benchmark ledger.

``RuntimeAdminModulesResult`` and ``RuntimeAdminBenchmarksResult`` are the
strict, signed bodies of ``/v1/admin/runtime/modules`` and
``/v1/admin/runtime/benchmarks``. Each carries an ``after`` validator that
reconciles every summary figure against the module list it summarises, and the
benchmarks model additionally reconciles the parallel ``shipping_runtime_*``
columns against ``module_benchmarks`` and derives the four quality-gate flags.

``conftest.make_runtime_admin_*_payload`` build internally consistent bodies;
each negative case below mutates exactly one thing and pins the rule it trips.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_runtime_manifest import (
    RuntimeAdminBenchmarksResult,
    RuntimeAdminEvaluationSummaryResult,
    RuntimeAdminModulesResult,
    RuntimeAdminModuleSummaryResult,
    RuntimeBenchmarkModuleEntryResult,
    RuntimeImmediateImplementationPRResult,
    RuntimeLayerResult,
    RuntimeMaturityResult,
    RuntimeModuleIdResult,
    RuntimeReleaseGateResult,
)

from .conftest import (
    make_runtime_admin_benchmarks_payload,
    make_runtime_admin_modules_payload,
)

Mutator = Callable[[dict[str, Any]], None]


def _raises_value_error(fragment: str):
    return pytest.raises(PydanticValidationError, match=re.escape(fragment))


def _set(path: str, value: Any) -> Mutator:
    """Return a mutator that assigns ``value`` at a dotted/indexed ``path``."""

    def mutate(payload: dict[str, Any]) -> None:
        target: Any = payload
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[int(part)] if part.isdigit() else target[part]
        last = parts[-1]
        if last.isdigit():
            target[int(last)] = value
        else:
            target[last] = value

    return mutate


class TestAdminModulesResult:
    def test_parses_and_exposes_typed_summaries(self) -> None:
        result = RuntimeAdminModulesResult.model_validate(make_runtime_admin_modules_payload())

        assert [module.name for module in result.modules] == [
            RuntimeModuleIdResult.bpe_tokenizer,
            RuntimeModuleIdResult.embeddings,
        ]
        assert result.summary.maturity_counts == {
            RuntimeMaturityResult.benchmarked: 1,
            RuntimeMaturityResult.enterprise_ready: 1,
        }
        assert result.summary.layer_counts == {RuntimeLayerResult.mojo_llm_runtime_core: 2}
        assert result.proof_matrix[0].layer is RuntimeLayerResult.mojo_llm_runtime_core
        assert result.signature.key_id == "key_123"

    def test_an_empty_inventory_is_consistent(self) -> None:
        result = RuntimeAdminModulesResult.model_validate(
            make_runtime_admin_modules_payload(
                modules=[],
                proof_matrix=[],
                shipping_contract={
                    "module_count": 0,
                    "function_count": 0,
                    "runtime_core_layer": "mojo_llm_runtime_core",
                    "benchmark_discovery_rule": (
                        "Only the 22-module, 209-function LLM rollout is treated as the "
                        "shipping runtime contract."
                    ),
                },
                summary={"module_count": 0, "function_count": 0},
            )
        )

        assert result.modules == []
        assert result.summary.maturity_counts == {}

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="extra_forbidden|Extra inputs"):
            RuntimeAdminModulesResult.model_validate(
                make_runtime_admin_modules_payload(unexpected=True)
            )

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            pytest.param(
                _set("modules.0.functions", ["bpe_tokenizer.fn_0"]),
                "modules.0.functions must contain exactly 2 entries",
                id="module-function-count",
            ),
            pytest.param(
                _set("shipping_contract.module_count", 3),
                "shipping_contract.module_count must equal the number of manifest modules",
                id="shipping-module-count",
            ),
            pytest.param(
                _set("shipping_contract.function_count", 6),
                "shipping_contract.function_count must equal the total module function_count",
                id="shipping-function-count",
            ),
            pytest.param(
                _set("summary.module_count", 3),
                "summary.module_count must equal the number of manifest modules",
                id="summary-module-count",
            ),
            pytest.param(
                _set("summary.function_count", 9),
                "summary.function_count must equal the total module function_count",
                id="summary-function-count",
            ),
            pytest.param(
                _set("summary.maturity_counts", {"benchmarked": 2}),
                "summary.maturity_counts must equal the module maturity distribution",
                id="summary-maturity-distribution",
            ),
            pytest.param(
                _set("summary.layer_counts", {"mojo_llm_runtime_core": 1}),
                "summary.layer_counts must equal the module layer distribution",
                id="summary-layer-distribution",
            ),
            pytest.param(
                lambda p: p["proof_matrix"].append(dict(p["proof_matrix"][0])),
                "proof_matrix must be unique",
                id="duplicate-proof-matrix-layer",
            ),
            pytest.param(
                lambda p: p["modules"].append(dict(p["modules"][0])),
                "modules must be unique",
                id="duplicate-module-name",
            ),
        ],
    )
    def test_integrity_rules(self, mutate: Mutator, message: str) -> None:
        payload = make_runtime_admin_modules_payload()
        mutate(payload)

        with _raises_value_error(message):
            RuntimeAdminModulesResult.model_validate(payload)


class TestAdminBenchmarksResult:
    def test_parses_and_derives_the_quality_gates(self) -> None:
        result = RuntimeAdminBenchmarksResult.model_validate(
            make_runtime_admin_benchmarks_payload()
        )

        assert [entry.name for entry in result.module_benchmarks] == [
            RuntimeModuleIdResult.bpe_tokenizer,
            RuntimeModuleIdResult.embeddings,
        ]
        assert result.shipping_runtime_modules == [entry.name for entry in result.module_benchmarks]
        assert result.evaluation_summary.replay_gate_enabled is True
        assert result.evaluation_summary.decision_quality_gate_enabled is True
        assert [budget.name.value for budget in result.quality_gate_slo_budgets] == [
            "replay",
            "mcp_call_first_party",
            "decision_plan_creation",
        ]
        assert result.slo_budgets[1].hard_ceiling_ms == 200.0
        assert result.slo_budgets[2].notes == "Plan generation excludes simulation time."

    def test_disabled_gates_are_accepted_when_their_inputs_are_absent(self) -> None:
        """Dropping the replay budget and blocker disables exactly the replay gate."""
        payload = make_runtime_admin_benchmarks_payload()
        payload["quality_gate_slo_budgets"] = payload["quality_gate_slo_budgets"][1:]
        payload["evaluation_summary"]["slo_budget_count"] = 2
        payload["evaluation_summary"]["replay_gate_enabled"] = False

        result = RuntimeAdminBenchmarksResult.model_validate(payload)

        assert result.evaluation_summary.replay_gate_enabled is False
        assert result.evaluation_summary.tool_call_quality_gate_enabled is True

    def test_json_round_trip_is_stable(self) -> None:
        result = RuntimeAdminBenchmarksResult.model_validate(
            make_runtime_admin_benchmarks_payload()
        )

        again = RuntimeAdminBenchmarksResult.model_validate(result.model_dump(mode="json"))

        assert again == result

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            pytest.param(
                _set("benchmark_discovery_lane.shipping_manifest_modules", 1),
                "shipping_manifest_modules must equal the number of benchmark modules",
                id="lane-module-count",
            ),
            pytest.param(
                _set("shipping_runtime_modules", ["bpe_tokenizer"]),
                "shipping_runtime_modules must contain one entry per shipping benchmark module",
                id="modules-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_function_counts", [2]),
                "shipping_runtime_function_counts must contain one entry per",
                id="function-counts-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_benchmark_speedups_x", [4.0]),
                "shipping_runtime_benchmark_speedups_x must contain one entry per",
                id="speedups-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_benchmark_artifacts", ["benchmarks/bpe_tokenizer.json"]),
                "shipping_runtime_benchmark_artifacts must contain one entry per",
                id="benchmark-artifacts-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_compiled_artifacts", ["bin/bpe_tokenizer.so"]),
                "shipping_runtime_compiled_artifacts must contain one entry per",
                id="compiled-artifacts-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_compiled_engines", ["mojo"]),
                "shipping_runtime_compiled_engines must contain one entry per",
                id="compiled-engines-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_max_cold_ms", [12.0]),
                "shipping_runtime_max_cold_ms must contain one entry per",
                id="cold-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_max_warm_ms", [3.0]),
                "shipping_runtime_max_warm_ms must contain one entry per",
                id="warm-column-length",
            ),
            pytest.param(
                _set("shipping_runtime_max_hot_ms", [1.0]),
                "shipping_runtime_max_hot_ms must contain one entry per",
                id="hot-column-length",
            ),
            pytest.param(
                _set("benchmark_discovery_lane.shipping_manifest_functions", 4),
                "shipping_manifest_functions must equal the total benchmark module function_count",
                id="lane-function-total",
            ),
            pytest.param(
                lambda p: p["quality_gate_benchmark_classes"].append(
                    {"code": "B2", "description": "Not declared", "evidence_paths": []}
                ),
                "quality_gate_benchmark_classes must be declared in benchmarking.classes.",
                id="undeclared-quality-gate-class",
            ),
            pytest.param(
                lambda p: p["quality_gate_slo_budgets"].append(
                    {
                        "name": "end_to_end_turn",
                        "applies_to": "first-party native LLM serving path",
                        "p95_objective_ms": 1.0,
                    }
                ),
                "quality_gate_slo_budgets must be declared in slo_budgets.",
                id="undeclared-quality-gate-budget",
            ),
            pytest.param(
                _set("evaluation_summary.dimension_count", 3),
                "evaluation_summary.dimension_count must equal",
                id="summary-dimension-count",
            ),
            pytest.param(
                _set("evaluation_summary.method_count", 1),
                "evaluation_summary.method_count must equal",
                id="summary-method-count",
            ),
            pytest.param(
                _set("evaluation_summary.release_blocker_count", 3),
                "evaluation_summary.release_blocker_count must equal",
                id="summary-release-blocker-count",
            ),
            pytest.param(
                _set("evaluation_summary.benchmark_class_count", 3),
                "evaluation_summary.benchmark_class_count must equal",
                id="summary-benchmark-class-count",
            ),
            pytest.param(
                _set("evaluation_summary.slo_budget_count", 2),
                "evaluation_summary.slo_budget_count must equal",
                id="summary-slo-budget-count",
            ),
            pytest.param(
                _set("evaluation_summary.replay_gate_enabled", False),
                "evaluation_summary.replay_gate_enabled must match",
                id="replay-gate-flag",
            ),
            pytest.param(
                _set("evaluation_summary.tool_call_quality_gate_enabled", False),
                "evaluation_summary.tool_call_quality_gate_enabled must match",
                id="tool-call-gate-flag",
            ),
            pytest.param(
                _set("evaluation_summary.rag_quality_gate_enabled", False),
                "evaluation_summary.rag_quality_gate_enabled must match",
                id="rag-gate-flag",
            ),
            pytest.param(
                _set("evaluation_summary.decision_quality_gate_enabled", False),
                "evaluation_summary.decision_quality_gate_enabled must match",
                id="decision-gate-flag",
            ),
            pytest.param(
                _set(
                    "benchmark_discovery_lane.discovered_source_inventory",
                    [
                        {"import_path": "bpe_tokenizer", "public_function_count": 2},
                        {"import_path": "kv_cache", "public_function_count": 4},
                        {"import_path": "paged_kv_cache", "public_function_count": 3},
                    ],
                ),
                "discovered_source_inventory must include module_benchmarks.1.name (embeddings)",
                id="benchmark-module-missing-from-inventory",
            ),
            pytest.param(
                _set("shipping_runtime_modules", ["embeddings", "bpe_tokenizer"]),
                "shipping_runtime_modules.0 must equal module_benchmarks.0.name",
                id="modules-column-order",
            ),
            pytest.param(
                _set("shipping_runtime_function_counts", [3, 3]),
                "shipping_runtime_function_counts.0 must equal module_benchmarks.0.function_count",
                id="function-counts-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_benchmark_speedups_x", [5.0, 6.5]),
                "shipping_runtime_benchmark_speedups_x.0 must equal",
                id="speedups-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_benchmark_artifacts.1", "benchmarks/other.json"),
                "shipping_runtime_benchmark_artifacts.1 must equal",
                id="benchmark-artifacts-column-value",
            ),
            pytest.param(
                _set(
                    "shipping_runtime_compiled_artifacts",
                    ["bin/embeddings.so", "bin/bpe_tokenizer.so"],
                ),
                "shipping_runtime_compiled_artifacts.0 must equal",
                id="compiled-artifacts-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_compiled_engines", ["python_fallback", "mojo"]),
                "shipping_runtime_compiled_engines.0 must equal",
                id="compiled-engines-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_max_cold_ms", [13.0, 15.0]),
                "shipping_runtime_max_cold_ms.0 must equal",
                id="cold-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_max_warm_ms", [3.0, 5.0]),
                "shipping_runtime_max_warm_ms.1 must equal",
                id="warm-column-value",
            ),
            pytest.param(
                _set("shipping_runtime_max_hot_ms", [2.0, 1.5]),
                "shipping_runtime_max_hot_ms.0 must equal",
                id="hot-column-value",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.0.benchmark_speedup_x", 0.0)(p),
                    _set("shipping_runtime_benchmark_speedups_x.0", 0.0)(p),
                ),
                "module_benchmarks.0.benchmark_speedup_x must be greater than 0",
                id="non-positive-speedup",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.0.max_cold_ms", 0.0)(p),
                    _set("shipping_runtime_max_cold_ms.0", 0.0)(p),
                ),
                "module_benchmarks.0.max_cold_ms must be greater than 0",
                id="non-positive-cold",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.1.max_warm_ms", 0.0)(p),
                    _set("shipping_runtime_max_warm_ms.1", 0.0)(p),
                ),
                "module_benchmarks.1.max_warm_ms must be greater than 0",
                id="non-positive-warm",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.1.max_hot_ms", -1.0)(p),
                    _set("shipping_runtime_max_hot_ms.1", -1.0)(p),
                ),
                "module_benchmarks.1.max_hot_ms must be greater than 0",
                id="non-positive-hot",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.1.benchmark_artifact", "benchmarks/bpe_tokenizer.json")(
                        p
                    ),
                    _set("shipping_runtime_benchmark_artifacts.1", "benchmarks/bpe_tokenizer.json")(
                        p
                    ),
                ),
                "module_benchmarks.1.benchmark_artifact duplicates "
                "module_benchmarks.0.benchmark_artifact.",
                id="duplicate-benchmark-artifact",
            ),
            pytest.param(
                lambda p: (
                    _set("module_benchmarks.1.compiled_artifact", "bin/missing.so")(p),
                    _set("shipping_runtime_compiled_artifacts.1", "bin/missing.so")(p),
                ),
                "module_benchmarks.1.compiled_artifact must reference a path present in "
                "compiled_artifacts.",
                id="compiled-artifact-not-in-ledger",
            ),
            pytest.param(
                lambda p: p["compiled_artifacts"].append(dict(p["compiled_artifacts"][0])),
                "compiled_artifacts must be unique",
                id="duplicate-compiled-artifact",
            ),
            pytest.param(
                lambda p: p["quality_gate_benchmark_classes"].append(
                    dict(p["quality_gate_benchmark_classes"][0])
                ),
                "quality_gate_benchmark_classes must be unique",
                id="duplicate-quality-gate-class",
            ),
            pytest.param(
                lambda p: p["module_benchmarks"].append(dict(p["module_benchmarks"][0])),
                "module_benchmarks must be unique",
                id="duplicate-benchmark-module",
            ),
            pytest.param(
                _set("shipping_runtime_modules", ["bpe_tokenizer", "bpe_tokenizer"]),
                "shipping_runtime_modules must be unique",
                id="duplicate-shipping-module",
            ),
            pytest.param(
                lambda p: p["quality_gate_slo_budgets"].append(
                    dict(p["quality_gate_slo_budgets"][0])
                ),
                "quality_gate_slo_budgets must be unique",
                id="duplicate-quality-gate-budget",
            ),
        ],
    )
    def test_integrity_rules(self, mutate: Mutator, message: str) -> None:
        payload = make_runtime_admin_benchmarks_payload()
        mutate(payload)

        with _raises_value_error(message):
            RuntimeAdminBenchmarksResult.model_validate(payload)


class TestAdminLeafModels:
    def test_release_gate_and_implementation_pr_parse(self) -> None:
        gate = RuntimeReleaseGateResult.model_validate({"gate": "C", "description": "Policy"})
        pr = RuntimeImmediateImplementationPRResult.model_validate(
            {"pr": "PR-7", "focus": "kv cache"}
        )

        assert gate.gate.value == "C"
        assert pr.deliverables == []

    def test_module_summary_defaults_its_distributions(self) -> None:
        summary = RuntimeAdminModuleSummaryResult.model_validate(
            {"module_count": 0, "function_count": 0}
        )

        assert summary.maturity_counts == {}
        assert summary.layer_counts == {}

    def test_module_summary_rejects_unknown_maturity_keys(self) -> None:
        with pytest.raises(PydanticValidationError):
            RuntimeAdminModuleSummaryResult.model_validate(
                {"module_count": 1, "function_count": 1, "maturity_counts": {"legendary": 1}}
            )

    def test_evaluation_summary_flags_are_strict_booleans(self) -> None:
        with pytest.raises(PydanticValidationError):
            RuntimeAdminEvaluationSummaryResult.model_validate(
                {
                    "dimension_count": 0,
                    "method_count": 0,
                    "release_blocker_count": 0,
                    "benchmark_class_count": 0,
                    "slo_budget_count": 0,
                    "replay_gate_enabled": 1,
                    "tool_call_quality_gate_enabled": False,
                    "rag_quality_gate_enabled": False,
                    "decision_quality_gate_enabled": False,
                }
            )

    def test_benchmark_module_entry_rejects_numeric_strings(self) -> None:
        """Strict floats take ints and floats, never the string form the JSON may carry."""
        payload = make_runtime_admin_benchmarks_payload()["module_benchmarks"][0]

        RuntimeBenchmarkModuleEntryResult.model_validate(payload)
        with pytest.raises(PydanticValidationError):
            RuntimeBenchmarkModuleEntryResult.model_validate({**payload, "max_hot_ms": "1.0"})

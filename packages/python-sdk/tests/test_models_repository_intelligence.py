"""Round-trip tests for the repository-intelligence result models.

These models describe repository snapshots, triage bundles, graph queries and
apply results. The tests pin required fields, list/dict defaults, datetime
coercion and the nested ``DecisionPlanResult`` carried by a plan revision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_repository_intelligence import (
    RepositoryApplyResult,
    RepositoryArtifactRefResult,
    RepositoryDecisionPlanRevisionResult,
    RepositoryEvidenceItemResult,
    RepositoryGraphEdgeResult,
    RepositoryGraphImpactItemResult,
    RepositoryGraphNodeResult,
    RepositoryGraphQueryResult,
    RepositoryIntelligenceCapabilitiesResult,
    RepositoryLanguageSupportProgressResult,
    RepositorySnapshotResult,
    RepositoryTriageResult,
)

from .conftest import (
    make_decision_plan_payload,
    make_repository_artifact_ref_payload,
    make_repository_evidence_item_payload,
    make_repository_snapshot_payload,
    make_repository_triage_payload,
)

_TS = "2026-01-01T00:00:00Z"
_TS_DT = datetime(2026, 1, 1, tzinfo=UTC)


class TestArtifactAndCapabilityModels:
    def test_artifact_ref_parses_and_defaults_schema_revision(self) -> None:
        ref = RepositoryArtifactRefResult.model_validate(make_repository_artifact_ref_payload())

        assert ref.artifact_kind == "repository_snapshot"
        assert ref.created_at == _TS_DT
        assert ref.schema_revision is None

    def test_artifact_ref_requires_a_content_hash(self) -> None:
        payload = make_repository_artifact_ref_payload()
        del payload["content_hash"]

        with pytest.raises(PydanticValidationError) as exc_info:
            RepositoryArtifactRefResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("content_hash",)

    def test_language_support_progress_parses_the_fraction(self) -> None:
        progress = RepositoryLanguageSupportProgressResult.model_validate(
            {
                "supported_real_language_count": 6,
                "ranked_target_language_count": 20,
                "progress_fraction": 0.3,
                "progress_label": "6 of 20 target languages",
            }
        )

        assert progress.progress_fraction == pytest.approx(0.3)
        assert progress.progress_label == "6 of 20 target languages"

    def test_capabilities_nest_progress_and_default_languages(self) -> None:
        capabilities = RepositoryIntelligenceCapabilitiesResult.model_validate(
            {
                "support_progress": {
                    "supported_real_language_count": 1,
                    "ranked_target_language_count": 20,
                    "progress_fraction": 0.05,
                    "progress_label": "1 of 20",
                }
            }
        )

        assert capabilities.supported_languages == []
        assert capabilities.support_progress.supported_real_language_count == 1

    def test_capabilities_list_the_supported_languages(self) -> None:
        capabilities = RepositoryIntelligenceCapabilitiesResult.model_validate(
            {
                "supported_languages": ["python", "typescript"],
                "support_progress": {
                    "supported_real_language_count": 2,
                    "ranked_target_language_count": 20,
                    "progress_fraction": 0.1,
                    "progress_label": "2 of 20",
                },
            }
        )

        assert capabilities.supported_languages == ["python", "typescript"]


class TestSnapshotAndTriageModels:
    def test_snapshot_parses_the_four_artifacts_and_language_counts(self) -> None:
        snapshot = RepositorySnapshotResult.model_validate(make_repository_snapshot_payload())

        assert snapshot.ref == "main"
        assert snapshot.file_count == 412
        assert snapshot.language_counts == {"python": 380, "typescript": 32}
        assert snapshot.repository_graph_artifact.artifact_kind == "repository_graph"
        assert snapshot.dependency_graph_artifact.created_at == _TS_DT

    def test_snapshot_defaults_ref_and_language_counts(self) -> None:
        payload = make_repository_snapshot_payload()
        del payload["ref"]
        del payload["language_counts"]

        snapshot = RepositorySnapshotResult.model_validate(payload)

        assert snapshot.ref is None
        assert snapshot.language_counts == {}

    def test_snapshot_requires_every_artifact(self) -> None:
        payload = make_repository_snapshot_payload()
        del payload["symbol_graph_artifact"]

        with pytest.raises(PydanticValidationError) as exc_info:
            RepositorySnapshotResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("symbol_graph_artifact",)

    def test_evidence_item_defaults_file_and_symbol(self) -> None:
        payload = make_repository_evidence_item_payload()
        del payload["file_path"]
        del payload["symbol_name"]

        item = RepositoryEvidenceItemResult.model_validate(payload)

        assert item.file_path is None
        assert item.symbol_name is None
        assert item.score == pytest.approx(0.91)

    def test_triage_result_orders_evidence_and_reports_the_reduction(self) -> None:
        triage = RepositoryTriageResult.model_validate(make_repository_triage_payload())

        assert [item.rank for item in triage.evidence_items] == [1, 2]
        assert triage.reduction_ratio == pytest.approx(260.4)
        assert triage.suspect_symbols == ["_request"]
        assert triage.workspace_evidence_bundle_artifact.artifact_kind == "evidence_bundle"

    def test_triage_result_defaults_every_list(self) -> None:
        payload = make_repository_triage_payload()
        for key in ("suspect_files", "suspect_symbols", "evidence_items"):
            del payload[key]

        triage = RepositoryTriageResult.model_validate(payload)

        assert triage.suspect_files == []
        assert triage.suspect_symbols == []
        assert triage.evidence_items == []


class TestGraphModels:
    def test_graph_edge_and_node_parse(self) -> None:
        edge = RepositoryGraphEdgeResult.model_validate(
            {"source_file": "a.py", "target_file": "b.py", "edge_type": "imports"}
        )
        node = RepositoryGraphNodeResult.model_validate(
            {
                "file_path": "a.py",
                "depth": 0,
                "is_seed": True,
                "inbound_count": 3,
                "outbound_count": 1,
                "risk_score": 0.7,
                "contained_symbols": ["A", "helper"],
            }
        )

        assert edge.edge_type == "imports"
        assert node.is_seed is True
        assert node.contained_symbols == ["A", "helper"]
        assert node.parent_child_symbols == []

    def test_graph_node_defaults_is_seed_to_false(self) -> None:
        node = RepositoryGraphNodeResult.model_validate(
            {
                "file_path": "b.py",
                "depth": 1,
                "inbound_count": 0,
                "outbound_count": 0,
                "risk_score": 0.0,
            }
        )

        assert node.is_seed is False

    def test_impact_item_defaults_top_symbol(self) -> None:
        item = RepositoryGraphImpactItemResult.model_validate(
            {"file_path": "b.py", "depth": 1, "relationship": "dependent", "risk_score": 0.4}
        )

        assert item.top_symbol is None

    def test_graph_query_result_nests_nodes_edges_and_impact(self) -> None:
        result = RepositoryGraphQueryResult.model_validate(
            {
                "repository_id": "repo_1",
                "snapshot_id": "snap_1",
                "created_at": _TS,
                "seed_file_paths": ["a.py"],
                "direct_dependencies": ["b.py"],
                "direct_dependents": ["c.py"],
                "impacted_files": ["b.py", "c.py"],
                "graph_nodes": [
                    {
                        "file_path": "a.py",
                        "depth": 0,
                        "is_seed": True,
                        "inbound_count": 1,
                        "outbound_count": 1,
                        "risk_score": 0.9,
                    }
                ],
                "graph_edges": [
                    {"source_file": "a.py", "target_file": "b.py", "edge_type": "imports"}
                ],
                "top_change_risk_files": [
                    {
                        "file_path": "c.py",
                        "depth": 1,
                        "relationship": "dependent",
                        "risk_score": 0.6,
                        "top_symbol": "C",
                    }
                ],
            }
        )

        assert result.created_at == _TS_DT
        assert result.seed_symbols == []
        assert result.impacted_symbols == []
        assert result.graph_nodes[0].is_seed is True
        assert result.graph_edges[0].target_file == "b.py"
        assert result.top_change_risk_files[0].top_symbol == "C"


class TestPlanRevisionAndApplyModels:
    def test_plan_revision_nests_a_decision_plan(self) -> None:
        revision = RepositoryDecisionPlanRevisionResult.model_validate(
            {
                "repository_id": "repo_1",
                "snapshot_id": "snap_1",
                "decision_plan_id": "plan_1",
                "created_at": _TS,
                "decision_plan": make_decision_plan_payload(),
            }
        )

        assert revision.decision_plan.recommended_action == "patch_transport_retry"
        assert revision.decision_plan.options[0].rank == 1
        assert revision.decision_plan.risk.var_95 is None
        assert revision.decision_plan.repository_analysis is None

    def test_plan_revision_rejects_an_invalid_nested_plan(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            RepositoryDecisionPlanRevisionResult.model_validate(
                {
                    "repository_id": "repo_1",
                    "snapshot_id": "snap_1",
                    "decision_plan_id": "plan_1",
                    "created_at": _TS,
                    "decision_plan": {"recommended_action": "noop"},
                }
            )

        locations = {error["loc"][:2] for error in exc_info.value.errors()}
        assert ("decision_plan", "confidence") in locations

    def test_apply_result_parses_a_dry_run(self) -> None:
        result = RepositoryApplyResult.model_validate(
            {
                "repository_id": "repo_1",
                "snapshot_id": "snap_1",
                "decision_plan_id": "plan_1",
                "simulation_id": "sim_1",
                "mode": "dry_run",
                "applied": False,
                "created_at": _TS,
                "patch": "--- a/a.py\n+++ b/a.py\n",
            }
        )

        assert result.applied is False
        assert result.branch_name is None
        assert result.pull_request_url is None
        assert result.apply_gate == {}
        assert result.validation_summary == {}

    def test_apply_result_parses_an_applied_change(self) -> None:
        result = RepositoryApplyResult.model_validate(
            {
                "repository_id": "repo_1",
                "snapshot_id": "snap_1",
                "decision_plan_id": "plan_1",
                "simulation_id": "sim_1",
                "mode": "branch",
                "applied": True,
                "created_at": _TS,
                "patch": "--- a/a.py\n+++ b/a.py\n",
                "branch_name": "algenta/plan_1",
                "commit_sha": "9781711aced91c585e0c39b9262aed58eaa0fc97",
                "local_checkout_path": "/tmp/checkout",
                "pull_request_url": "https://github.com/thyn-ai/algenta-sdk/pull/1",
                "apply_gate": {"passed": True},
                "validation_summary": {"tests": "passed"},
            }
        )

        assert result.branch_name == "algenta/plan_1"
        assert result.apply_gate == {"passed": True}
        assert result.validation_summary == {"tests": "passed"}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (RepositoryArtifactRefResult, make_repository_artifact_ref_payload()),
        (RepositorySnapshotResult, make_repository_snapshot_payload()),
        (RepositoryEvidenceItemResult, make_repository_evidence_item_payload()),
        (RepositoryTriageResult, make_repository_triage_payload()),
    ],
)
def test_unknown_server_fields_survive_a_round_trip(model: type, payload: dict[str, Any]) -> None:
    enriched = {**payload, "future_field": "kept"}

    parsed = model.model_validate(enriched)
    dumped = parsed.model_dump(mode="json")

    assert dumped["future_field"] == "kept"
    assert model.model_validate(dumped) == parsed

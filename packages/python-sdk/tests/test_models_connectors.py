"""Round-trip tests for the connector, dataset, source-registration and batch models.

These are the response models behind the connector and data surfaces. Beyond
required fields and defaults, the tests pin the ``schema`` alias handling: the
API field is called ``schema`` (a reserved pydantic name), so the models store
it as ``schema_payload``/``source_schema`` and expose ``.schema`` as a property.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_batch_result import BatchItemResult, BatchResult
from decision_engine.models_connector_info import ConnectorInfo
from decision_engine.models_connector_list_result import ConnectorListResult
from decision_engine.models_connector_preview import ConnectorBrowseResult, ConnectorTestInfo
from decision_engine.models_dataset import (
    DatasetConnectResult,
    DatasetDeleteResult,
    DatasetDetailResult,
    DatasetInfo,
    DatasetListResult,
    DatasetSummaryResult,
)
from decision_engine.models_registration_result import SourceRegistrationResult

from .conftest import make_decision_envelope_payload

_TS = "2026-01-01T00:00:00Z"
_TS_DT = datetime(2026, 1, 1, tzinfo=UTC)


class TestConnectorModels:
    def test_connector_info_parses_and_defaults_optional_fields(self) -> None:
        info = ConnectorInfo.model_validate(
            {
                "id": "conn_1",
                "name": "warehouse",
                "connector_type": "postgres",
                "status": "active",
                "visibility": "private",
            }
        )

        assert info.description is None
        assert info.last_tested_at is None
        assert info.error_message is None
        assert info.created_at is None

    def test_connector_info_parses_timestamps(self) -> None:
        info = ConnectorInfo.model_validate(
            {
                "id": "conn_1",
                "name": "warehouse",
                "connector_type": "postgres",
                "status": "error",
                "visibility": "org",
                "last_tested_at": _TS,
                "created_at": _TS,
                "error_message": "connection refused",
            }
        )

        assert info.last_tested_at == _TS_DT
        assert info.created_at == _TS_DT
        assert info.error_message == "connection refused"

    def test_connector_list_result_nests_connectors(self) -> None:
        result = ConnectorListResult.model_validate(
            {
                "connectors": [
                    {
                        "id": "conn_1",
                        "name": "warehouse",
                        "connector_type": "postgres",
                        "status": "active",
                        "visibility": "private",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 200,
                "pages": 1,
            }
        )

        assert result.connectors[0].id == "conn_1"
        assert result.pages == 1

    def test_connector_list_result_defaults_connectors(self) -> None:
        result = ConnectorListResult.model_validate(
            {"total": 0, "page": 1, "limit": 200, "pages": 0}
        )

        assert result.connectors == []

    def test_connector_test_info_parses_a_failure(self) -> None:
        info = ConnectorTestInfo.model_validate(
            {
                "success": False,
                "message": "auth failed",
                "latency_ms": 210,
                "status": "error",
                "error_type": "authentication",
                "recoverable": True,
            }
        )

        assert info.success is False
        assert info.recoverable is True
        assert info.error_type == "authentication"

    def test_connector_test_info_defaults_diagnostics(self) -> None:
        info = ConnectorTestInfo.model_validate({"success": True, "message": "ok"})

        assert info.latency_ms is None
        assert info.status is None
        assert info.recoverable is None

    def test_connector_browse_result_defaults_items_labels_and_discovery(self) -> None:
        result = ConnectorBrowseResult.model_validate(
            {"connector_type": "postgres", "total": 0, "message": "no tables"}
        )

        assert result.items == []
        assert result.labels == {}
        assert result.discovery == {}

    def test_connector_browse_result_parses_items(self) -> None:
        result = ConnectorBrowseResult.model_validate(
            {
                "connector_type": "postgres",
                "items": [{"table": "orders"}, {"table": "customers"}],
                "total": 2,
                "message": "2 tables",
                "labels": {"orders": "Orders"},
                "discovery": {"schema": "public"},
            }
        )

        assert [item["table"] for item in result.items] == ["orders", "customers"]
        assert result.labels == {"orders": "Orders"}


class TestDatasetModels:
    def test_dataset_info_defaults_visibility_and_lists(self) -> None:
        info = DatasetInfo.model_validate({"dataset_id": "ds_1", "dataset_name": "orders"})

        assert info.visibility == "private"
        assert info.refreshable is False
        assert info.source_names == []
        assert info.roles_summary == {}
        assert info.registered_at is None

    def test_dataset_info_parses_registration_timestamp(self) -> None:
        info = DatasetInfo.model_validate(
            {"dataset_id": "ds_1", "dataset_name": "orders", "registered_at": _TS, "row_count": 10}
        )

        assert info.registered_at == _TS_DT
        assert info.row_count == 10

    def test_dataset_list_result_parses_pagination(self) -> None:
        result = DatasetListResult.model_validate(
            {
                "datasets": [{"dataset_id": "ds_1", "dataset_name": "orders"}],
                "count": 1,
                "total": 7,
                "matched_total": 1,
                "page": 2,
                "limit": 1,
                "pages": 7,
            }
        )

        assert result.matched_total == 1
        assert result.datasets[0].dataset_name == "orders"

    def test_dataset_summary_parses_query_hints(self) -> None:
        summary = DatasetSummaryResult.model_validate(
            {
                "dataset_id": "ds_1",
                "name": "orders",
                "status": "ready",
                "column_count": 12,
                "query_hints": [{"metric": "revenue"}],
            }
        )

        assert summary.column_count == 12
        assert summary.query_hints == [{"metric": "revenue"}]
        assert summary.row_count is None

    def test_dataset_detail_exposes_schema_through_the_alias(self) -> None:
        detail = DatasetDetailResult.model_validate(
            {
                "dataset": {"dataset_id": "ds_1", "dataset_name": "orders"},
                "schema": {"columns": [{"name": "revenue", "type": "float"}]},
            }
        )

        assert detail.schema == {"columns": [{"name": "revenue", "type": "float"}]}
        assert detail.schema_payload is detail.schema

    def test_dataset_detail_accepts_the_field_name_too(self) -> None:
        detail = DatasetDetailResult.model_validate(
            {
                "dataset": {"dataset_id": "ds_1", "dataset_name": "orders"},
                "schema_payload": {"columns": []},
            }
        )

        assert detail.schema == {"columns": []}

    def test_dataset_detail_defaults_schema_to_an_empty_dict(self) -> None:
        detail = DatasetDetailResult.model_validate(
            {"dataset": {"dataset_id": "ds_1", "dataset_name": "orders"}}
        )

        assert detail.schema == {}

    def test_dataset_delete_result_defaults_connection_deleted(self) -> None:
        result = DatasetDeleteResult.model_validate({"dataset_id": "ds_1", "status": "deleted"})

        assert result.connection_deleted is False

    def test_dataset_connect_result_exposes_schema_and_choices(self) -> None:
        result = DatasetConnectResult.model_validate(
            {
                "status": "connected",
                "dataset_id": "ds_1",
                "dataset_name": "orders",
                "schema": {"columns": ["revenue"]},
                "choices": [{"table": "orders"}],
                "latency_ms": 120.5,
            }
        )

        assert result.schema == {"columns": ["revenue"]}
        assert result.choices == [{"table": "orders"}]
        assert result.latency_ms == pytest.approx(120.5)

    def test_dataset_connect_result_schema_is_none_when_absent(self) -> None:
        result = DatasetConnectResult.model_validate({"status": "needs_selection"})

        assert result.schema is None
        assert result.dataset_id is None


class TestSourceRegistrationResult:
    def test_schema_alias_is_stored_as_source_schema(self) -> None:
        result = SourceRegistrationResult.model_validate(
            {
                "source_id": "src_1",
                "dataset_id": "ds_1",
                "name": "orders",
                "status": "registered",
                "schema": {"columns": ["revenue"]},
                "planner_cache_hit": True,
                "planner_schema_revision": "rev_1",
                "row_count": 42,
            }
        )

        assert result.source_schema == {"columns": ["revenue"]}
        assert result.planner_cache_hit is True
        assert result.row_count == 42

    def test_field_name_is_accepted_via_populate_by_name(self) -> None:
        result = SourceRegistrationResult.model_validate(
            {"status": "registered", "source_schema": {"columns": []}}
        )

        assert result.source_schema == {"columns": []}

    def test_only_status_is_required(self) -> None:
        result = SourceRegistrationResult.model_validate({"status": "pending"})

        assert result.source_id is None
        assert result.source_schema is None
        assert result.latency_ms is None

    def test_status_is_required(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            SourceRegistrationResult.model_validate({"source_id": "src_1"})

        assert exc_info.value.errors()[0]["loc"] == ("status",)


class TestBatchResult:
    def test_batch_item_nests_a_decision_envelope(self) -> None:
        item = BatchItemResult.model_validate(
            {"index": 0, "success": True, "envelope": make_decision_envelope_payload()}
        )

        assert item.envelope is not None
        assert item.envelope.recommended_action == "ship_it"
        assert item.error is None

    def test_batch_item_carries_an_error_without_an_envelope(self) -> None:
        item = BatchItemResult.model_validate(
            {"index": 1, "success": False, "error": "scenario has no variables"}
        )

        assert item.envelope is None
        assert item.error == "scenario has no variables"

    def test_batch_result_counts_and_nests_items(self) -> None:
        result = BatchResult.model_validate(
            {
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "results": [
                    {"index": 0, "success": True, "envelope": make_decision_envelope_payload()},
                    {"index": 1, "success": False, "error": "boom"},
                ],
            }
        )

        assert result.total == result.succeeded + result.failed
        assert [item.success for item in result.results] == [True, False]

    def test_batch_result_requires_results(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            BatchResult.model_validate({"total": 0, "succeeded": 0, "failed": 0})

        assert exc_info.value.errors()[0]["loc"] == ("results",)

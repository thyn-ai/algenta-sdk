"""Tests for the governance surface: audit logs, execution policy, and receipts."""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient

from .conftest import TEST_BASE_URL, make_decision_log_payload, request_json

_EXECUTION_POLICY_PAYLOAD = {
    "org_id": "org_123",
    "min_confidence": 0.7,
    "require_calibration": True,
    "allow_reexecution": False,
    "updated_at": "2026-01-01T00:00:00Z",
}

_EXECUTION_RECEIPT_PAYLOAD = {
    "decision_id": "dec_123",
    "webhook_url": "https://hooks.example.com/algenta",
    "execution_status": "delivered",
    "response_code": 200,
    "executed_at": "2026-01-01T00:00:00Z",
    "policy_snapshot_id": "pol_123",
    "schema_snapshot_id": "sch_123",
    "manifest_version": "1.0.0",
    "payload_summary": {"action": "ship_it"},
    "safety_overridden": False,
}


def test_get_audit_logs_sends_pagination_and_filters(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs").mock(
        return_value=Response(
            200,
            json={
                "entries": [
                    {
                        "id": "log_1",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "actor_email": "admin@example.com",
                        "action": "decision.execute",
                        "resource_type": "decision",
                        "result": "success",
                    }
                ],
                "total": 1,
                "page": 2,
                "limit": 10,
                "pages": 1,
            },
        )
    )

    result = client.get_audit_logs(
        page=2,
        limit=10,
        actor_email="admin@example.com",
        action="decision.execute",
    )

    params = route.calls[0].request.url.params
    assert params["page"] == "2"
    assert params["limit"] == "10"
    assert params["actor_email"] == "admin@example.com"
    assert params["action"] == "decision.execute"
    assert result.total == 1
    assert result.entries[0].action == "decision.execute"


def test_get_audit_logs_rejects_blank_filter_values(
    client: AlgentaClient, mock_router
) -> None:
    # No routes are declared: validation must fail before any HTTP call.
    with pytest.raises(ValueError, match="actor_email"):
        client.get_audit_logs(actor_email="   ")


def test_get_execution_policy_parses_the_policy(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/execution/policy").mock(
        return_value=Response(200, json=_EXECUTION_POLICY_PAYLOAD)
    )

    result = client.get_execution_policy()

    assert route.calls[0].request.method == "GET"
    assert result.org_id == "org_123"
    assert result.min_confidence == pytest.approx(0.7)
    assert result.require_calibration is True


def test_update_execution_policy_patches_only_the_given_fields(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.patch(f"{TEST_BASE_URL}/v1/execution/policy").mock(
        return_value=Response(200, json=_EXECUTION_POLICY_PAYLOAD)
    )

    client.update_execution_policy(min_confidence=0.7, allow_reexecution=False)

    assert request_json(route) == {"min_confidence": 0.7, "allow_reexecution": False}


def test_update_execution_policy_requires_at_least_one_field(
    client: AlgentaClient, mock_router
) -> None:
    with pytest.raises(ValueError, match="at least one policy field"):
        client.update_execution_policy()


def test_update_execution_policy_validates_field_types(
    client: AlgentaClient, mock_router
) -> None:
    with pytest.raises(TypeError, match="min_confidence must be a number"):
        client.update_execution_policy(min_confidence=True)
    with pytest.raises(ValueError, match="between 0 and 1"):
        client.update_execution_policy(min_confidence=1.5)
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        client.update_execution_policy(risk_floor=-0.1)
    with pytest.raises(TypeError, match="require_calibration must be a boolean"):
        client.update_execution_policy(require_calibration="yes")


def test_log_decision_posts_the_decision_record(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/decisions").mock(
        return_value=Response(200, json=make_decision_log_payload())
    )
    request = {
        "chosen_action": "ship_it",
        "options_considered": ["ship_it", "wait"],
        "confidence": 0.91,
    }

    result = client.log_decision(request)

    assert request_json(route) == request
    assert result.id == "dec_123"
    assert result.chosen_action == "ship_it"


def test_list_decisions_serializes_pagination_and_flags(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/decisions").mock(
        return_value=Response(
            200,
            json={
                "decisions": [],
                "total": 0,
                "page": 1,
                "limit": 25,
                "pages": 0,
                "page_size": 25,
            },
        )
    )

    result = client.list_decisions(page=1, limit=25, with_outcome_only=True)

    params = route.calls[0].request.url.params
    assert params["page"] == "1"
    assert params["limit"] == "25"
    assert params["with_outcome_only"] == "true"
    assert result.total == 0


def test_record_outcome_patches_the_outcome_payload(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.patch(f"{TEST_BASE_URL}/v1/decisions/dec_123/outcome").mock(
        return_value=Response(
            200, json=make_decision_log_payload(actual_outcome=1.5, outcome_delta=0.1)
        )
    )

    result = client.record_outcome("dec_123", actual_outcome=1.5, outcome_notes="beat plan")

    assert request_json(route) == {"actual_outcome": 1.5, "outcome_notes": "beat plan"}
    assert result.actual_outcome == pytest.approx(1.5)


def test_record_outcome_omits_notes_when_not_provided(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.patch(f"{TEST_BASE_URL}/v1/decisions/dec_123/outcome").mock(
        return_value=Response(200, json=make_decision_log_payload())
    )

    client.record_outcome("dec_123", actual_outcome=1.5)

    assert request_json(route) == {"actual_outcome": 1.5}


def test_execute_decision_posts_the_execution_request_and_parses_the_receipt(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/decisions/dec_123/execute").mock(
        return_value=Response(200, json=_EXECUTION_RECEIPT_PAYLOAD)
    )

    receipt = client.execute_decision(
        "dec_123",
        webhook_url="https://hooks.example.com/algenta",
        timeout_seconds=5.0,
        force=True,
        metadata={"initiated_by": "test"},
    )

    assert request_json(route) == {
        "webhook_url": "https://hooks.example.com/algenta",
        "timeout_seconds": 5.0,
        "force": True,
        "override_safety": False,
        "metadata": {"initiated_by": "test"},
    }
    assert receipt.decision_id == "dec_123"
    assert receipt.execution_status == "delivered"
    assert receipt.policy_snapshot_id == "pol_123"
    assert receipt.payload_summary == {"action": "ship_it"}
    assert receipt.safety_overridden is False


def test_delete_decision_issues_a_delete(client: AlgentaClient, mock_router) -> None:
    route = mock_router.delete(f"{TEST_BASE_URL}/v1/decisions/dec_123").mock(
        return_value=Response(200, json={"deleted": True})
    )

    result = client.delete_decision("dec_123")

    assert route.calls[0].request.method == "DELETE"
    assert result == {"deleted": True}

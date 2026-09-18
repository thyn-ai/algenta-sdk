"""Tests for the governed query surface: request shapes, merging, and validation."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient

from .conftest import TEST_BASE_URL, make_query_result_payload, request_json


def _mock_query(router: respx.Router, payload: dict | None = None) -> respx.Route:
    return router.post(f"{TEST_BASE_URL}/v1/query").mock(
        return_value=Response(200, json=payload or make_query_result_payload())
    )


def test_query_posts_the_request_payload(client: AlgentaClient, mock_router) -> None:
    route = _mock_query(mock_router)

    result = client.query({"metric": "revenue", "source_name": "orders"})

    assert request_json(route) == {"metric": "revenue", "source_name": "orders"}
    assert result.query_id == "q_123"
    assert result.resolved_column == "revenue"
    assert result.confidence == pytest.approx(0.97)


def test_query_merges_kwargs_over_the_request_dict(
    client: AlgentaClient, mock_router
) -> None:
    route = _mock_query(mock_router)

    client.query({"metric": "revenue", "limit": 10}, metric="margin")

    assert request_json(route) == {"metric": "margin", "limit": 10}


def test_query_with_metadata_reads_execution_headers(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/query").mock(
        return_value=Response(
            200,
            json=make_query_result_payload(),
            headers={
                "X-Request-Id": "req_meta_1",
                "X-Execution-Ms": "7.5",
                "X-Input-Tokens": "11",
                "X-Output-Tokens": "4",
                "X-Cost-Usd": "0.002",
                "X-Cache-Hit": "true",
            },
        )
    )

    result = client.query_with_metadata({"metric": "revenue"})

    assert request_json(route) == {"metric": "revenue"}
    assert result.data.query_id == "q_123"
    assert result.metadata.request_id == "req_meta_1"
    # Body fields win over headers when both are present.
    assert result.metadata.latency_ms == pytest.approx(12.5)
    assert result.metadata.tokens_in == 11
    assert result.metadata.tokens_out == 4
    assert result.metadata.cost_usd == pytest.approx(0.002)
    assert result.metadata.cache_hit is True
    assert result.headers["x-request-id"] == "req_meta_1"


def test_query_batch_posts_to_the_batch_endpoint(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/query/batch").mock(
        return_value=Response(200, json={"results": [], "request_id": "req_batch_1"})
    )
    request = {"queries": [{"metric": "revenue"}, {"metric": "margin"}]}

    result = client.query_batch(request)

    assert request_json(route) == request
    assert result.request_id == "req_batch_1"


def test_resolve_posts_to_the_resolve_endpoint(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/resolve").mock(
        return_value=Response(
            200,
            json={
                "confidence": 0.88,
                "plan": ["resolve_column"],
                "latency_ms": 3.0,
                "decision_path": "governed",
                "schema_revision": "rev_1",
                "validated": True,
                "deterministic_scope": "full",
                "confidence_source": "calibrated",
                "intent_signature": "sig_123",
            },
        )
    )

    result = client.resolve({"metric": "revenue"})

    assert request_json(route) == {"metric": "revenue"}
    assert result.clarification_required is False
    assert result.schema_revision == "rev_1"
    assert result.intent_signature == "sig_123"


def test_verify_posts_to_the_verify_endpoint(client: AlgentaClient, mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/verify").mock(
        return_value=Response(
            200,
            json={
                "valid": True,
                "errors": [],
                "suggestions": [],
                "resolved": {"revenue": "orders.revenue"},
                "latency_ms": 2.0,
                "verified": True,
            },
        )
    )

    result = client.verify({"query_id": "q_123"})

    assert request_json(route) == {"query_id": "q_123"}
    assert result.valid is True
    assert result.verified is True


def test_explain_derives_the_explanation_from_the_query_result(
    client: AlgentaClient, mock_router
) -> None:
    route = _mock_query(mock_router)

    result = client.explain({"metric": "revenue", "source_name": "orders"})

    # explain() reuses the governed query endpoint, then reshapes the result.
    assert request_json(route) == {"metric": "revenue", "source_name": "orders"}
    assert result.decision_path == "governed"
    assert result.resolved_column == "revenue"
    assert result.source_set == ["orders"]
    assert result.planner_mode == "exact_spec"
    assert result.validated is True


def test_join_path_max_hops_is_validated_before_any_http_call(
    client: AlgentaClient, mock_router
) -> None:
    # No routes are declared: any HTTP attempt would fail the test.
    with pytest.raises(ValueError, match="max_hops"):
        client.query({"metric": "revenue", "join_path": {"max_hops": 99}})


def test_join_path_edges_cannot_exceed_max_hops(
    client: AlgentaClient, mock_router
) -> None:
    edges = [{"left_source": "a", "right_source": "b"}] * 3
    with pytest.raises(ValueError, match="join_path.edges"):
        client.query({"metric": "revenue", "join_path": {"max_hops": 2, "edges": edges}})


def test_join_path_default_max_hops_is_applied(
    client: AlgentaClient, mock_router
) -> None:
    route = _mock_query(mock_router)

    client.query({"metric": "revenue", "join_path": {"edges": []}})

    assert request_json(route)["join_path"] == {"edges": [], "max_hops": 4}

"""Async-facade parity for the simulation, query, plan, source and decision surfaces.

``test_async_client.py`` proves one call per async mixin. This module walks the
remaining methods of those mixins on ``AsyncAlgentaClient`` and pins the same
request shapes the sync tests pin, so the two facades cannot drift apart. The
handful of sync methods no other module reaches (``plan_decision``,
``register_source``, ``refresh_source``, ``query_sql_report``,
``get_decision``) are covered here as well.
"""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ValidationError

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_decision_envelope_payload,
    make_decision_log_payload,
    make_query_result_payload,
    request_json,
)

_DECISION_PLAN = {
    "recommended_action": "ship_it",
    "confidence": 0.9,
    "expected_value": 1200.0,
    "risk": {"p5": -50.0, "p95": 2400.0, "probability_of_loss": 0.04},
    "options": [
        {
            "name": "ship_it",
            "rank": 1,
            "expected_value": 1200.0,
            "risk": {"p5": -50.0, "p95": 2400.0, "probability_of_loss": 0.04},
        }
    ],
    "rationale": "Positive expected value.",
}

_REGISTRATION = {
    "source_id": "src_1",
    "dataset_id": "ds_1",
    "name": "orders",
    "status": "registered",
    "schema": {"columns": ["revenue"]},
    "row_count": 42,
}

_SQL_REPORT = {
    "columns": ["region", "revenue"],
    "rows": [{"region": "EMEA", "revenue": 10.0}],
    "row_count": 1,
    "truncated": False,
    "latency_ms": 9.0,
}

_RESOLVE = {
    "confidence": 0.94,
    "plan": ["resolve_column"],
    "latency_ms": 8.5,
    "decision_path": "governed",
    "schema_revision": "rev_1",
    "validated": True,
    "deterministic_scope": "full",
    "confidence_source": "calibrated",
    "intent_signature": "sum(revenue)",
}

_VERIFY = {
    "valid": True,
    "errors": [],
    "suggestions": [],
    "resolved": {"revenue": "orders.revenue"},
    "latency_ms": 2.0,
    "verified": True,
    "plan_hash": "planhash123",
}

_RECEIPT = {
    "decision_id": "dec_123",
    "webhook_url": "https://hooks.example.com/algenta",
    "execution_status": "delivered",
    "executed_at": "2026-01-01T00:00:00Z",
    "policy_snapshot_id": "pol_1",
    "schema_snapshot_id": "sch_1",
    "manifest_version": "1.0.0",
    "payload_summary": {"action": "ship_it"},
}

_DECISION_PAGE = {
    "decisions": [make_decision_log_payload()],
    "total": 1,
    "page": 1,
    "limit": 25,
    "pages": 1,
    "page_size": 25,
}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestSyncGaps:
    def test_plan_decision_posts_the_request(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/decisions/plan").mock(
            return_value=Response(200, json=_DECISION_PLAN)
        )

        plan = client.plan_decision({"options": ["ship_it", "wait"]})

        assert request_json(route) == {"options": ["ship_it", "wait"]}
        assert plan.recommended_action == "ship_it"
        assert plan.options[0].rank == 1

    def test_register_source_wraps_a_bare_source_and_adds_the_description(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/sources/register").mock(
            return_value=Response(200, json=_REGISTRATION)
        )

        result = client.register_source(
            {"type": "csv", "path": "orders.csv"}, description="Orders export", refresh=True
        )

        assert request_json(route) == {
            "source": {"type": "csv", "path": "orders.csv"},
            "refresh": True,
            "description": "Orders export",
        }
        assert result.source_schema == {"columns": ["revenue"]}
        assert result.row_count == 42

    def test_register_source_accepts_a_pre_wrapped_payload_or_kwargs(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/sources/register").mock(
            return_value=Response(200, json=_REGISTRATION)
        )

        client.register_source({"source": {"type": "csv"}, "name": "orders"})
        client.register_source(source_type="csv", path="orders.csv")
        client.register_source(source={"type": "csv"}, name="orders")

        assert request_json(route, 0) == {"source": {"type": "csv"}, "name": "orders"}
        assert request_json(route, 1) == {"source": {"source_type": "csv", "path": "orders.csv"}}
        assert request_json(route, 2) == {"source": {"type": "csv"}, "name": "orders"}

    def test_refresh_source_posts_to_the_dataset_refresh_endpoint(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/data/ds_1/refresh").mock(
            return_value=Response(200, json={**_REGISTRATION, "status": "refreshing"})
        )

        result = client.refresh_source("ds_1")

        assert route.calls[0].request.content == b""
        assert result.status == "refreshing"

    def test_query_sql_report_posts_the_request(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/query/sql-report").mock(
            return_value=Response(200, json=_SQL_REPORT)
        )

        report = client.query_sql_report({"metrics": ["revenue"], "group_by": "region"})

        assert request_json(route) == {"metrics": ["revenue"], "group_by": "region"}
        assert report.columns == ["region", "revenue"]
        assert report.rows[0]["region"] == "EMEA"

    def test_get_decision_fetches_by_id(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/decisions/dec_123").mock(
            return_value=Response(200, json=make_decision_log_payload())
        )

        decision = client.get_decision("dec_123")

        assert route.calls[0].request.method == "GET"
        assert decision.id == "dec_123"


class TestAsyncSimulation:
    @pytest.mark.asyncio
    async def test_simulate_recommend_score_batch_and_compare(self, mock_router) -> None:
        simulate = mock_router.post(f"{TEST_BASE_URL}/v1/simulate").mock(
            return_value=Response(200, json=make_decision_envelope_payload())
        )
        recommend = mock_router.post(f"{TEST_BASE_URL}/v1/recommend").mock(
            return_value=Response(200, json={"recommended": "a"})
        )
        score = mock_router.post(f"{TEST_BASE_URL}/v1/score").mock(
            return_value=Response(200, json={"score": 0.7})
        )
        batch = mock_router.post(f"{TEST_BASE_URL}/v1/batch").mock(
            return_value=Response(200, json={"results": [{"index": 0, "success": True}]})
        )
        compare = mock_router.post(f"{TEST_BASE_URL}/v1/compare").mock(
            return_value=Response(200, json={"winner": "a"})
        )

        async with _async_client() as client:
            envelope = await client.simulate(variables={"revenue": {"low": 1, "high": 2}}, runs=500)
            recommended = await client.recommend(
                [{"name": "a", "request": {"mode": "auto", "scenario": {"variables": {}}}}],
                runs=200,
            )
            scored = await client.score({"scenario": {"variables": {}}}, scoring_weights={"a": 1.0})
            batched = await client.batch([{"variables": {"revenue": {"low": 1, "high": 2}}}])
            compared = await client.compare(
                [
                    {"label": "a", "variables": {"revenue": {"low": 1, "high": 2}}},
                    {"label": "b", "variables": {"revenue": {"low": 2, "high": 3}}},
                ]
            )

        body = request_json(simulate)
        assert body["mode"] == "auto" and body["runs"] == 500
        assert body["scenario"]["objective"] == "maximize_net_value"
        assert envelope.recommended_action == "ship_it"
        assert request_json(recommend) == {
            "actions": [{"name": "a", "request": {"mode": "auto", "scenario": {"variables": {}}}}],
            "runs": 200,
        }
        assert recommended == {"recommended": "a"}
        assert request_json(score) == {
            "request": {"scenario": {"variables": {}}},
            "scoring_weights": {"a": 1.0},
        }
        assert scored == {"score": 0.7}
        assert request_json(batch)["items"][0]["mode"] == "auto"
        assert batched == [{"index": 0, "success": True}]
        scenarios = request_json(compare)["scenarios"]
        assert [scenario["name"] for scenario in scenarios] == ["a", "b"]
        assert scenarios[0]["request"]["mode"] == "auto"
        assert scenarios[1]["request"]["scenario"]["variables"] == {
            "revenue": {"low": 2, "high": 3}
        }
        assert compared == {"winner": "a"}

    @pytest.mark.asyncio
    async def test_score_omits_empty_weights_and_batch_returns_an_empty_list_by_default(
        self, mock_router
    ) -> None:
        score = mock_router.post(f"{TEST_BASE_URL}/v1/score").mock(
            return_value=Response(200, json={"score": 0.1})
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/batch").mock(return_value=Response(200, json={}))

        async with _async_client() as client:
            await client.score({"scenario": {}})
            assert await client.batch([]) == []

        assert request_json(score) == {"request": {"scenario": {}}}


class TestAsyncQuery:
    @pytest.mark.asyncio
    async def test_resolve_query_with_metadata_batch_sql_report_and_verify(
        self, mock_router
    ) -> None:
        resolve = mock_router.post(f"{TEST_BASE_URL}/v1/resolve").mock(
            return_value=Response(200, json=_RESOLVE)
        )
        query = mock_router.post(f"{TEST_BASE_URL}/v1/query").mock(
            return_value=Response(
                200,
                json=make_query_result_payload(),
                headers={"X-Request-Id": "req_1", "X-Execution-Ms": "12.5", "X-Cache-Hit": "true"},
            )
        )
        batch = mock_router.post(f"{TEST_BASE_URL}/v1/query/batch").mock(
            return_value=Response(200, json={"results": [], "request_id": "req_b"})
        )
        report = mock_router.post(f"{TEST_BASE_URL}/v1/query/sql-report").mock(
            return_value=Response(200, json=_SQL_REPORT)
        )
        verify = mock_router.post(f"{TEST_BASE_URL}/v1/verify").mock(
            return_value=Response(200, json=_VERIFY)
        )

        async with _async_client() as client:
            resolved = await client.resolve({"metric": "revenue"})
            with_metadata = await client.query_with_metadata({"metric": "revenue"}, limit=5)
            batched = await client.query_batch({"queries": {"a": {"metric": "revenue"}}})
            reported = await client.query_sql_report({"metrics": ["revenue"]})
            verified = await client.verify({"query_id": "q_123"})

        assert request_json(resolve) == {"metric": "revenue"}
        assert resolved.intent_signature == "sum(revenue)"
        assert request_json(query) == {"metric": "revenue", "limit": 5}
        assert with_metadata.data.query_id == "q_123"
        assert with_metadata.metadata.request_id == "req_1"
        assert with_metadata.metadata.cache_hit is True
        assert with_metadata.headers["x-execution-ms"] == "12.5"
        assert request_json(batch) == {"queries": {"a": {"metric": "revenue"}}}
        assert batched.request_id == "req_b"
        assert request_json(report) == {"metrics": ["revenue"]}
        assert reported.row_count == 1
        assert request_json(verify) == {"query_id": "q_123"}
        assert verified.verified is True

    @pytest.mark.asyncio
    async def test_explain_derives_the_explanation_from_the_query_result(self, mock_router) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/query").mock(
            return_value=Response(
                200, json=make_query_result_payload(resolved_source="orders ⋈ customers")
            )
        )

        async with _async_client() as client:
            explanation = await client.explain({"metric": "revenue", "source_name": "orders"})

        assert explanation.source_set == ["orders", "customers"]
        assert explanation.join_path == [{"left_source": "orders", "right_source": "customers"}]
        assert explanation.planner_mode == "exact_spec"
        assert explanation.decision_path == "governed"

    @pytest.mark.asyncio
    async def test_join_path_limits_are_validated_before_any_request(self) -> None:
        async with _async_client() as client:
            with pytest.raises(ValueError, match="max_hops"):
                await client.query({"metric": "revenue", "join_path": {"max_hops": 99}})


class TestAsyncPlanAndSources:
    @pytest.mark.asyncio
    async def test_plan_decision_register_and_refresh_source(self, mock_router) -> None:
        plan = mock_router.post(f"{TEST_BASE_URL}/v1/decisions/plan").mock(
            return_value=Response(200, json=_DECISION_PLAN)
        )
        register = mock_router.post(f"{TEST_BASE_URL}/v1/sources/register").mock(
            return_value=Response(200, json=_REGISTRATION)
        )
        refresh = mock_router.post(f"{TEST_BASE_URL}/v1/data/ds_1/refresh").mock(
            return_value=Response(200, json={**_REGISTRATION, "status": "refreshing"})
        )

        async with _async_client() as client:
            planned = await client.plan_decision({"options": ["a"]})
            registered = await client.register_source({"type": "csv"}, description="d")
            refreshed = await client.refresh_source("ds_1")

        assert request_json(plan) == {"options": ["a"]}
        assert planned.confidence == pytest.approx(0.9)
        assert request_json(register) == {"source": {"type": "csv"}, "description": "d"}
        assert registered.status == "registered"
        assert refresh.calls[0].request.method == "POST"
        assert refreshed.status == "refreshing"


class TestAsyncDecisionMemory:
    @pytest.mark.asyncio
    async def test_list_get_record_execute_and_delete(self, mock_router) -> None:
        listing = mock_router.get(f"{TEST_BASE_URL}/v1/decisions").mock(
            return_value=Response(200, json=_DECISION_PAGE)
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/decisions/dec_123").mock(
            return_value=Response(200, json=make_decision_log_payload())
        )
        outcome = mock_router.patch(f"{TEST_BASE_URL}/v1/decisions/dec_123/outcome").mock(
            return_value=Response(200, json=make_decision_log_payload(actual_outcome=2.0))
        )
        execute = mock_router.post(f"{TEST_BASE_URL}/v1/decisions/dec_123/execute").mock(
            return_value=Response(200, json=_RECEIPT)
        )
        mock_router.delete(f"{TEST_BASE_URL}/v1/decisions/dec_123").mock(
            side_effect=[Response(200, json={"deleted": True}), Response(204)]
        )

        async with _async_client() as client:
            page = await client.list_decisions(
                page=2, limit=10, page_size=10, with_outcome_only=False
            )
            decision = await client.get_decision("dec_123")
            recorded = await client.record_outcome("dec_123", actual_outcome=2.0, outcome_notes="n")
            receipt = await client.execute_decision(
                "dec_123", webhook_url="https://hooks.example.com/algenta", metadata={"k": "v"}
            )
            deleted = await client.delete_decision("dec_123")
            deleted_empty = await client.delete_decision("dec_123")

        assert dict(listing.calls[0].request.url.params) == {
            "page": "2",
            "limit": "10",
            "page_size": "10",
            "with_outcome_only": "false",
        }
        assert page.page_size == 25 and page.decisions[0].id == "dec_123"
        assert decision.chosen_action == "ship_it"
        assert request_json(outcome) == {"actual_outcome": 2.0, "outcome_notes": "n"}
        assert recorded.actual_outcome == pytest.approx(2.0)
        assert request_json(execute) == {
            "webhook_url": "https://hooks.example.com/algenta",
            "timeout_seconds": 10.0,
            "force": False,
            "override_safety": False,
            "metadata": {"k": "v"},
        }
        assert receipt.execution_status == "delivered"
        assert deleted == {"deleted": True}
        assert deleted_empty == {}

    @pytest.mark.asyncio
    async def test_list_decisions_without_filters_sends_no_query(self, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/decisions").mock(
            return_value=Response(200, json=_DECISION_PAGE)
        )

        async with _async_client() as client:
            await client.list_decisions()

        assert str(route.calls[0].request.url) == f"{TEST_BASE_URL}/v1/decisions"

    @pytest.mark.asyncio
    async def test_typed_errors_propagate(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/decisions/missing").mock(
            return_value=error_response(404, message="decision not found")
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/decisions/plan").mock(
            return_value=error_response(422, message="options required")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="decision not found"):
                await client.get_decision("missing")
            with pytest.raises(ValidationError, match="options required"):
                await client.plan_decision({})

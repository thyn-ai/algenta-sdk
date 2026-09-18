"""Async facade parity: one request/response cycle per major async mixin."""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AsyncAlgentaClient
from decision_engine.exceptions import AuthenticationError

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    make_decision_log_payload,
    make_openapi_contract_payload,
    make_platform_contract_payload,
    make_query_result_payload,
    request_json,
)

_DATASET_PAGE = {"datasets": [], "count": 0, "total": 0, "page": 1, "limit": 200, "pages": 0}


def _async_client(**kwargs) -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, **kwargs)


@pytest.mark.asyncio
async def test_async_list_datasets_connector_mixin(mock_router) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(
            200,
            json={
                "datasets": [{"dataset_id": "ds_1", "dataset_name": "orders"}],
                "count": 1,
                "total": 1,
                "page": 1,
                "limit": 200,
                "pages": 1,
            },
        )
    )

    async with _async_client() as client:
        result = await client.list_datasets()

    assert route.calls[0].request.method == "GET"
    assert result.datasets[0].dataset_id == "ds_1"


@pytest.mark.asyncio
async def test_async_query_simulation_query_mixin(mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/query").mock(
        return_value=Response(200, json=make_query_result_payload())
    )

    async with _async_client() as client:
        result = await client.query({"metric": "revenue"})

    assert request_json(route) == {"metric": "revenue"}
    assert result.query_id == "q_123"


@pytest.mark.asyncio
async def test_async_list_models_llm_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/models").mock(
        return_value=Response(200, json={"object": "list", "data": []})
    )

    async with _async_client() as client:
        result = await client.list_models()

    assert result.object == "list"


@pytest.mark.asyncio
async def test_async_get_contract_contract_capability_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(200, json=make_platform_contract_payload(TEST_BASE_URL))
    )

    async with _async_client() as client:
        contract = await client.get_contract()

    assert contract.api_base_url == TEST_BASE_URL


@pytest.mark.asyncio
async def test_async_get_contract_falls_back_to_openapi_on_404(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{TEST_BASE_URL}/openapi.json").mock(
        return_value=Response(200, json=make_openapi_contract_payload())
    )

    async with _async_client() as client:
        contract = await client.get_contract()

    assert contract.api_base_url == TEST_BASE_URL
    assert contract.mcp_endpoint == f"{TEST_BASE_URL}/mcp"


@pytest.mark.asyncio
async def test_async_get_audit_logs_account_control_plane_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs").mock(
        return_value=Response(
            200,
            json={"entries": [], "total": 0, "page": 1, "limit": 25, "pages": 0},
        )
    )

    async with _async_client() as client:
        result = await client.get_audit_logs()

    assert result.total == 0


@pytest.mark.asyncio
async def test_async_log_decision_product_decision_mixin(mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/decisions").mock(
        return_value=Response(200, json=make_decision_log_payload())
    )

    async with _async_client() as client:
        result = await client.log_decision({"chosen_action": "ship_it"})

    assert request_json(route) == {"chosen_action": "ship_it"}
    assert result.id == "dec_123"


@pytest.mark.asyncio
async def test_async_list_triggers_trigger_source_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/triggers").mock(
        return_value=Response(
            200,
            json={
                "triggers": [],
                "count": 0,
                "total": 0,
                "page": 1,
                "limit": 25,
                "pages": 0,
            },
        )
    )

    async with _async_client() as client:
        result = await client.list_triggers()

    assert result.total == 0


@pytest.mark.asyncio
async def test_async_list_agent_runs_agent_run_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs").mock(
        return_value=Response(
            200,
            json={"object": "list", "data": [], "total": 0, "page": 1, "limit": 25, "pages": 0},
        )
    )

    async with _async_client() as client:
        result = await client.list_agent_runs()

    assert result.total == 0


@pytest.mark.asyncio
async def test_async_list_jobs_job_deployment_mixin(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/jobs/list").mock(
        return_value=Response(
            200,
            json={"jobs": [], "total": 0, "page": 1, "limit": 25, "pages": 0},
        )
    )

    async with _async_client() as client:
        result = await client.list_jobs()

    assert result.total == 0


@pytest.mark.asyncio
async def test_async_usage_account_surface(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/usage").mock(
        return_value=Response(
            200,
            json={
                "org_id": "3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b",
                "billing_period": "2026-09",
                "simulations_run": 12,
                "api_calls": 340,
                "quota_limit": 1000,
                "quota_used_pct": 34.0,
            },
        )
    )

    async with _async_client() as client:
        result = await client.usage()

    assert result.api_calls == 340


@pytest.mark.asyncio
async def test_async_retries_server_errors_with_recorded_backoff(
    mock_router, recorded_sleeps
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[
            Response(500, json={"error": {"message": "boom"}}),
            Response(200, json=_DATASET_PAGE),
        ]
    )

    async with _async_client() as client:
        result = await client.list_datasets()

    assert result.total == 0
    assert route.call_count == 2
    assert recorded_sleeps == [1.0]


@pytest.mark.asyncio
async def test_async_auth_error_uses_the_async_auth_message(
    mock_router, recorded_sleeps
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(401, json={})
    )

    async with _async_client(max_retries=0) as client:
        with pytest.raises(AuthenticationError, match="Auth failed"):
            await client.list_datasets()

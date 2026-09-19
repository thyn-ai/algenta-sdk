"""Tests for the product surface: decision, agent run, optimize, retrieve, forecast.

Five POST endpoints that forward the caller's request verbatim and parse a
typed product result. Each is pinned on both facades, plus one typed error
path per facade.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import RateLimitError, ServerError
from decision_engine.models_products import (
    ProductAgentRunResult,
    ProductDecisionResult,
    ProductForecastResult,
    ProductOptimizeResult,
    ProductRetrieveResult,
)

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_product_agent_run_payload,
    make_product_decision_payload,
    make_product_forecast_payload,
    request_json,
)

_OPTIMIZE = {
    "optimization_id": "opt_1",
    "status": "converged",
    "optimal_values": {"price": 19.99},
    "objective_value": 4_210.5,
    "improvement_vs_midpoint": 0.17,
    "constraints_satisfied": True,
    "iterations_run": 250,
    "latency_ms": 133.0,
}

_RETRIEVE = {
    "retrieval_id": "ret_1",
    "query": "retry policy",
    "results": [
        {
            "rank": 1,
            "document_id": "doc_9",
            "content": "...",
            "relevance_score": 0.93,
            "snippet": "retry",
        }
    ],
    "total_searched": 12,
    "latency_ms": 18.0,
}

# (id, call, path, request body, response, result type)
_CALLS: list[tuple[str, Callable[[Any], Any], str, dict[str, Any], Any, type]] = [
    (
        "product_decision",
        lambda c: c.product_decision({"question": "launch?", "options": ["launch", "wait"]}),
        "/v1/decision",
        {"question": "launch?", "options": ["launch", "wait"]},
        make_product_decision_payload(),
        ProductDecisionResult,
    ),
    (
        "product_agent_run",
        lambda c: c.product_agent_run({"task": "summarise", "tools": ["fs.read"]}),
        "/v1/agent/run",
        {"task": "summarise", "tools": ["fs.read"]},
        make_product_agent_run_payload(),
        ProductAgentRunResult,
    ),
    (
        "product_optimize",
        lambda c: c.product_optimize({"objective": "profit", "variables": {"price": [10, 30]}}),
        "/v1/optimize",
        {"objective": "profit", "variables": {"price": [10, 30]}},
        _OPTIMIZE,
        ProductOptimizeResult,
    ),
    (
        "product_retrieve",
        lambda c: c.product_retrieve({"query": "retry policy", "top_k": 1}),
        "/v1/retrieve",
        {"query": "retry policy", "top_k": 1},
        _RETRIEVE,
        ProductRetrieveResult,
    ),
    (
        "product_forecast",
        lambda c: c.product_forecast({"metric": "revenue", "periods": 2}),
        "/v1/forecast",
        {"metric": "revenue", "periods": 2},
        make_product_forecast_payload(),
        ProductForecastResult,
    ),
]
_IDS = [entry[0] for entry in _CALLS]
_PARAMS = [entry[1:] for entry in _CALLS]


def _mock(router: respx.Router, path: str, body: Any) -> respx.Route:
    return router.post(f"{TEST_BASE_URL}{path}").mock(return_value=Response(200, json=body))


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


@pytest.mark.parametrize(("call", "path", "body", "response", "model"), _PARAMS, ids=_IDS)
def test_sync_methods_post_the_request_and_parse_the_typed_result(
    client: AlgentaClient,
    mock_router,
    call: Callable[[Any], Any],
    path: str,
    body: dict[str, Any],
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, path, response)

    result = call(client)

    assert route.calls[0].request.method == "POST"
    assert request_json(route) == body
    assert isinstance(result, model)


@pytest.mark.asyncio
@pytest.mark.parametrize(("call", "path", "body", "response", "model"), _PARAMS, ids=_IDS)
async def test_async_methods_post_the_request_and_parse_the_typed_result(
    mock_router,
    call: Callable[[Any], Any],
    path: str,
    body: dict[str, Any],
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, path, response)

    async with _async_client() as client:
        result = await call(client)

    assert request_json(route) == body
    assert isinstance(result, model)


def test_parsed_results_expose_nested_values(client: AlgentaClient, mock_router) -> None:
    _mock(mock_router, "/v1/retrieve", _RETRIEVE)
    _mock(mock_router, "/v1/optimize", _OPTIMIZE)

    retrieved = client.product_retrieve({"query": "retry policy"})
    optimized = client.product_optimize({"objective": "profit"})

    assert retrieved.results[0].document_id == "doc_9"
    assert retrieved.total_searched == 12
    assert optimized.optimal_values == {"price": 19.99}
    assert optimized.constraints_satisfied is True


def test_server_errors_surface_as_the_typed_error(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    mock_router.post(f"{TEST_BASE_URL}/v1/forecast").mock(
        return_value=error_response(500, message="forecaster down")
    )

    with pytest.raises(ServerError, match="forecaster down"):
        no_retry_client.product_forecast({"metric": "revenue"})


@pytest.mark.asyncio
async def test_async_rate_limits_surface_with_the_retry_after(mock_router) -> None:
    mock_router.post(f"{TEST_BASE_URL}/v1/decision").mock(
        return_value=error_response(
            429, message="slow down", code="rate_limited", headers={"Retry-After": "7"}
        )
    )

    async with _async_client() as client:
        with pytest.raises(RateLimitError, match="slow down") as exc_info:
            await client.product_decision({"question": "launch?"})

    assert exc_info.value.retry_after == 7
    assert exc_info.value.error_code == "rate_limited"

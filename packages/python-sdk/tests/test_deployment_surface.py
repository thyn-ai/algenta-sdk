"""Tests for the deployment surface: regions, create, inspect, cost, delete.

``get_deployment`` returns ``None`` when the org has no deployment (the API
answers ``null``); ``create_deployment`` validates its arguments client-side
and coerces the markup to a float; the id-taking methods reject blank ids.
Sync and async facades are both exercised.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ServerError

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_deployment_payload,
    request_json,
)

_DEPLOYMENTS = f"{TEST_BASE_URL}/v1/deployments"

_REGIONS = {
    "providers": [
        {
            "id": "aws",
            "name": "Amazon Web Services",
            "description": "Dedicated engine in your AWS account.",
            "icon": "aws",
            "regions": [{"id": "eu-west-1", "label": "Ireland"}],
        }
    ]
}

_COST = {
    "deployment_id": "dep_1",
    "provider": "aws",
    "region": "eu-west-1",
    "year": 2026,
    "month": 9,
    "cost_usd_month": 420.0,
    "billable_cost_usd_month": 504.0,
    "billing_markup_pct": 20.0,
}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestRegionsAndInspect:
    def test_list_regions_parses_the_provider_catalog(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{_DEPLOYMENTS}/regions").mock(
            return_value=Response(200, json=_REGIONS)
        )

        result = client.list_deployment_regions()

        assert route.calls[0].request.method == "GET"
        assert result.providers[0].id == "aws"
        assert result.providers[0].regions[0].name == "Ireland"

    def test_get_deployment_parses_the_current_deployment(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_DEPLOYMENTS).mock(
            return_value=Response(200, json=make_deployment_payload(status="ready"))
        )

        result = client.get_deployment()

        assert result is not None
        assert result.status == "ready"
        assert result.billable_cost_usd_month == pytest.approx(504.0)

    def test_get_deployment_returns_none_when_there_is_none(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_DEPLOYMENTS).mock(
            return_value=Response(
                200, content=b"null", headers={"content-type": "application/json"}
            )
        )

        assert client.get_deployment() is None

    def test_get_deployment_cost(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{_DEPLOYMENTS}/dep_1/cost").mock(
            return_value=Response(200, json=_COST)
        )

        result = client.get_deployment_cost("dep_1")

        assert route.calls[0].request.method == "GET"
        assert (result.year, result.month) == (2026, 9)
        assert result.last_updated is None


class TestCreate:
    def test_posts_the_defaults(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(_DEPLOYMENTS).mock(
            return_value=Response(
                200,
                json=make_deployment_payload(provider="algenta_shared", region="algenta-shared"),
            )
        )

        result = client.create_deployment()

        assert request_json(route) == {
            "provider": "algenta_shared",
            "region": "algenta-shared",
            "config": None,
            "billing_markup_pct": 20.0,
        }
        assert result.provider == "algenta_shared"

    def test_posts_explicit_arguments_and_coerces_the_markup(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(_DEPLOYMENTS).mock(
            return_value=Response(200, json=make_deployment_payload())
        )

        client.create_deployment(
            provider="aws",
            region="eu-west-1",
            config={"instance": "m6i.large"},
            billing_markup_pct=15,
        )

        assert request_json(route) == {
            "provider": "aws",
            "region": "eu-west-1",
            "config": {"instance": "m6i.large"},
            "billing_markup_pct": 15.0,
        }

    @pytest.mark.parametrize(
        ("kwargs", "error", "message"),
        [
            ({"provider": " "}, ValueError, "provider must be a non-empty string"),
            ({"provider": 3}, ValueError, "provider must be a non-empty string"),
            ({"region": ""}, ValueError, "region must be a non-empty string"),
            ({"config": ["a"]}, TypeError, "config must be a mapping or None"),
            ({"billing_markup_pct": "20"}, TypeError, "billing_markup_pct must be a number"),
            ({"billing_markup_pct": True}, TypeError, "billing_markup_pct must be a number"),
        ],
    )
    def test_validates_arguments_before_any_request(
        self, client: AlgentaClient, kwargs: dict[str, Any], error: type, message: str
    ) -> None:
        with pytest.raises(error, match=message):
            client.create_deployment(**kwargs)


class TestDelete:
    def test_delete_returns_the_typed_confirmation(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.delete(f"{_DEPLOYMENTS}/dep_1").mock(
            return_value=Response(200, json={"status": "deleted", "deployment_id": "dep_1"})
        )

        result = client.delete_deployment("dep_1")

        assert route.calls[0].request.method == "DELETE"
        assert result.status == "deleted"

    @pytest.mark.parametrize("method", ["delete_deployment", "get_deployment_cost"])
    def test_deployment_id_is_required(self, client: AlgentaClient, method: str) -> None:
        with pytest.raises(ValueError, match="deployment_id must be a non-empty string"):
            getattr(client, method)("  ")


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_DEPLOYMENTS}/missing/cost").mock(
            return_value=error_response(404, message="deployment not found")
        )

        with pytest.raises(NotFoundError, match="deployment not found"):
            no_retry_client.get_deployment_cost("missing")


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_every_endpoint(self, mock_router) -> None:
        mock_router.get(f"{_DEPLOYMENTS}/regions").mock(return_value=Response(200, json=_REGIONS))
        current = mock_router.get(_DEPLOYMENTS).mock(
            side_effect=[
                Response(200, content=b"null", headers={"content-type": "application/json"}),
                Response(200, json=make_deployment_payload(status="ready")),
            ]
        )
        create = mock_router.post(_DEPLOYMENTS).mock(
            return_value=Response(200, json=make_deployment_payload())
        )
        mock_router.get(f"{_DEPLOYMENTS}/dep_1/cost").mock(return_value=Response(200, json=_COST))
        mock_router.delete(f"{_DEPLOYMENTS}/dep_1").mock(
            return_value=Response(200, json={"status": "deleted", "deployment_id": "dep_1"})
        )

        async with _async_client() as client:
            regions = await client.list_deployment_regions()
            before = await client.get_deployment()
            created = await client.create_deployment(provider="aws", region="eu-west-1")
            after = await client.get_deployment()
            cost = await client.get_deployment_cost("dep_1")
            deleted = await client.delete_deployment("dep_1")

        assert regions.providers[0].regions[0].label == "Ireland"
        assert before is None
        assert request_json(create)["billing_markup_pct"] == 20.0
        assert created.deployment_id == "dep_1"
        assert after is not None and after.status == "ready"
        assert current.call_count == 2
        assert cost.billing_markup_pct == pytest.approx(20.0)
        assert deleted.deployment_id == "dep_1"

    @pytest.mark.asyncio
    async def test_validation_happens_before_any_request(self) -> None:
        async with _async_client() as client:
            with pytest.raises(ValueError, match="region must be a non-empty string"):
                await client.create_deployment(region="")
            with pytest.raises(TypeError, match="config must be a mapping or None"):
                await client.create_deployment(config="m6i.large")
            with pytest.raises(ValueError, match="deployment_id must be a non-empty string"):
                await client.delete_deployment("")
            with pytest.raises(ValueError, match="deployment_id must be a non-empty string"):
                await client.get_deployment_cost(" ")

    @pytest.mark.asyncio
    async def test_server_errors_surface_as_the_typed_error(self, mock_router) -> None:
        mock_router.post(_DEPLOYMENTS).mock(
            return_value=error_response(500, message="provisioner down")
        )

        async with _async_client() as client:
            with pytest.raises(ServerError, match="provisioner down"):
                await client.create_deployment()

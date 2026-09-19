"""Tests for the account surface beyond usage/limits: identity, API keys, catalogs.

``me``/``update_me`` shape the identity request; the API-key helpers validate
the server's payloads defensively (a list response must never leak one-time
secret material, a create response must echo the ``raw_key`` with its prefix);
``distributions``/``templates`` accept both a bare list and a paginated
envelope. Sync and async facades are both exercised.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import AuthenticationError, NotFoundError

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_TS = "2026-01-01T00:00:00Z"

_ME = {
    "user": {
        "id": "user_1",
        "email": "ada@example.com",
        "name": "Ada",
        "role": "owner",
        "email_verified": True,
        "created_at": _TS,
    },
    "org": {
        "id": "org_1",
        "name": "Analytical Engines",
        "slug": "analytical-engines",
        "plan": "pro",
        "status": "active",
        "created_at": _TS,
    },
}

_API_KEY = {
    "id": "3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b",
    "label": "ci",
    "key_prefix": "de_live_ab12",
    "status": "active",
    "created_at": _TS,
}

_DISTRIBUTION = {
    "name": "triangular",
    "description": "Low, mode, high.",
    "required_params": ["low", "mode", "high"],
    "optional_params": [],
    "example": {"low": 1, "mode": 2, "high": 3},
}

_TEMPLATE = {
    "id": "pricing",
    "name": "Pricing decision",
    "category": "commercial",
    "description": "Evaluate a price change.",
    "example_request": {"mode": "auto"},
}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestIdentity:
    def test_me_parses_user_and_org(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/me").mock(return_value=Response(200, json=_ME))

        result = client.me()

        assert route.calls[0].request.method == "GET"
        assert result.user.email == "ada@example.com"
        assert result.user.email_verified is True
        assert result.org.slug == "analytical-engines"

    def test_update_me_patches_the_trimmed_fields(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.patch(f"{TEST_BASE_URL}/v1/me").mock(
            return_value=Response(200, json=_ME)
        )

        client.update_me(name="  Ada Lovelace ", org_name="Engines ")

        assert request_json(route) == {"name": "Ada Lovelace", "org_name": "Engines"}

    def test_update_me_sends_only_the_given_field(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.patch(f"{TEST_BASE_URL}/v1/me").mock(
            return_value=Response(200, json=_ME)
        )

        client.update_me(org_name="Engines")

        assert request_json(route) == {"org_name": "Engines"}

    def test_update_me_requires_at_least_one_field(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="requires name and/or org_name"):
            client.update_me()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"name": "  "}, "name must be a non-empty string"),
            ({"org_name": ""}, "org_name must be a non-empty string"),
            ({"name": 7}, "name must be a non-empty string"),
        ],
    )
    def test_update_me_rejects_blank_values(
        self, client: AlgentaClient, kwargs: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            client.update_me(**kwargs)


class TestApiKeys:
    def test_list_api_keys_accepts_a_bare_list(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=[_API_KEY, {**_API_KEY, "device_limit": 3}])
        )

        keys = client.list_api_keys()

        assert [key.label for key in keys] == ["ci", "ci"]
        assert keys[0].device_limit is None
        assert keys[1].device_limit == 3

    def test_list_api_keys_accepts_a_paginated_envelope(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={"api_keys": [_API_KEY], "total": 1})
        )

        keys = client.list_api_keys()

        assert len(keys) == 1
        assert keys[0].key_prefix == "de_live_ab12"

    def test_list_api_keys_rejects_an_unexpected_shape(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={"keys": [_API_KEY]})
        )

        with pytest.raises(TypeError, match="must be a list or paginated object"):
            client.list_api_keys()

    def test_list_api_keys_rejects_an_item_without_a_prefix(
        self, client: AlgentaClient, mock_router
    ) -> None:
        item = dict(_API_KEY)
        del item["key_prefix"]
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=[item])
        )

        with pytest.raises(ValueError, match="missing key_prefix"):
            client.list_api_keys()

    def test_list_api_keys_rejects_a_non_object_item(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=["de_live_ab12"])
        )

        with pytest.raises(TypeError, match="API key payload must be a JSON object"):
            client.list_api_keys()

    @pytest.mark.parametrize("device_limit", [-1, "3"])
    def test_list_api_keys_rejects_an_invalid_device_limit(
        self, client: AlgentaClient, mock_router, device_limit: Any
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=[{**_API_KEY, "device_limit": device_limit}])
        )

        with pytest.raises(ValueError, match="invalid device_limit"):
            client.list_api_keys()

    @pytest.mark.parametrize("secret_field", ["raw_key", "key"])
    def test_list_api_keys_refuses_leaked_secret_material(
        self, client: AlgentaClient, mock_router, secret_field: str
    ) -> None:
        """A list endpoint must never return the one-time secret; the SDK fails closed."""
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=[{**_API_KEY, secret_field: "de_live_ab12_secret"}])
        )

        with pytest.raises(ValueError, match="leaked one-time secret material"):
            client.list_api_keys()

    def test_create_api_key_posts_the_label_and_returns_the_raw_key(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_rest_of_secret"})
        )

        result = client.create_api_key("ci")

        assert request_json(route) == {"label": "ci"}
        assert result["raw_key"] == "de_live_ab12_rest_of_secret"

    def test_create_api_key_accepts_name_as_an_alias_for_label(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_x"})
        )

        client.create_api_key(name="deploy")

        assert request_json(route) == {"label": "deploy"}

    def test_create_api_key_requires_a_label(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="requires label= or name="):
            client.create_api_key()

    def test_create_api_key_serialises_a_naive_expiry_as_utc(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_x"})
        )

        client.create_api_key("ci", expires_at=datetime(2027, 1, 1, 12, 0, 0))

        assert request_json(route)["expires_at"] == "2027-01-01T12:00:00+00:00"

    def test_create_api_key_keeps_an_aware_expiry_offset(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_x"})
        )
        aware = datetime(2027, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))

        client.create_api_key("ci", expires_at=aware)

        assert request_json(route)["expires_at"] == "2027-01-01T12:00:00+02:00"

    def test_create_api_key_passes_a_string_expiry_through(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_x"})
        )

        client.create_api_key("ci", expires_at="2027-01-01T00:00:00Z", device_limit=2)

        assert request_json(route) == {
            "label": "ci",
            "expires_at": "2027-01-01T00:00:00Z",
            "device_limit": 2,
        }

    def test_create_api_key_rejects_an_unsupported_expiry_type(self, client: AlgentaClient) -> None:
        with pytest.raises(TypeError, match="expires_at must be a datetime"):
            client.create_api_key("ci", expires_at=1_800_000_000)

    @pytest.mark.parametrize(
        ("device_limit", "error", "message"),
        [
            ("2", TypeError, "device_limit must be an integer"),
            (-1, ValueError, "greater than or equal to 0"),
        ],
    )
    def test_create_api_key_validates_the_device_limit(
        self, client: AlgentaClient, device_limit: Any, error: type, message: str
    ) -> None:
        with pytest.raises(error, match=message):
            client.create_api_key("ci", device_limit=device_limit)

    def test_create_api_key_rejects_a_response_without_the_raw_key(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=_API_KEY)
        )

        with pytest.raises(ValueError, match="missing raw_key"):
            client.create_api_key("ci")

    def test_create_api_key_rejects_a_raw_key_that_does_not_match_the_prefix(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_test_zz99_secret"})
        )

        with pytest.raises(ValueError, match="missing raw_key"):
            client.create_api_key("ci")

    def test_create_api_key_rejects_a_non_object_response(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=["de_live_ab12_secret"])
        )

        with pytest.raises(TypeError, match="API key create response must be a JSON object"):
            client.create_api_key("ci")

    def test_revoke_api_key_deletes_by_id(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.delete(f"{TEST_BASE_URL}/v1/api-keys/key_1").mock(
            return_value=Response(200, json={"revoked": True})
        )

        assert client.revoke_api_key("key_1") == {"revoked": True}
        assert route.calls[0].request.method == "DELETE"


class TestCatalogs:
    def test_distributions_wraps_a_bare_list_in_a_page(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/distributions").mock(
            return_value=Response(200, json=[_DISTRIBUTION, {**_DISTRIBUTION, "name": "normal"}])
        )

        result = client.distributions()

        assert [item.name for item in result.distributions] == ["triangular", "normal"]
        assert (result.total, result.page, result.limit, result.pages) == (2, 1, 2, 1)

    def test_distributions_accepts_a_paginated_envelope(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/distributions").mock(
            return_value=Response(
                200,
                json={
                    "distributions": [_DISTRIBUTION],
                    "total": 9,
                    "page": 2,
                    "limit": 1,
                    "pages": 9,
                },
            )
        )

        result = client.distributions()

        assert result.total == 9 and result.page == 2
        assert result.distributions[0].required_params == ["low", "mode", "high"]

    def test_templates_wraps_an_empty_list_with_a_unit_limit(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/templates").mock(return_value=Response(200, json=[]))

        result = client.templates()

        assert result.templates == []
        assert (result.total, result.limit) == (0, 1)

    def test_templates_accepts_a_paginated_envelope(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/templates").mock(
            return_value=Response(
                200, json={"templates": [_TEMPLATE], "total": 1, "page": 1, "limit": 25, "pages": 1}
            )
        )

        result = client.templates()

        assert result.templates[0].category == "commercial"
        assert result.templates[0].example_request == {"mode": "auto"}

    def test_catalogs_reject_scalar_bodies(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/templates").mock(return_value=Response(200, json=3))

        with pytest.raises(TypeError, match="/v1/templates response must be a JSON list or object"):
            client.templates()


class TestServiceInfo:
    def test_health_and_version_return_raw_bodies(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/health").mock(
            return_value=Response(200, json={"status": "ok"})
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/version").mock(
            return_value=Response(200, json={"version": "1.0.16", "engine": "mojo"})
        )

        assert client.health() == {"status": "ok"}
        assert client.version() == {"version": "1.0.16", "engine": "mojo"}

    def test_auth_errors_surface_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/me").mock(
            return_value=error_response(401, message="key revoked")
        )

        with pytest.raises(AuthenticationError, match="key revoked"):
            no_retry_client.me()


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_identity_endpoints(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/me").mock(return_value=Response(200, json=_ME))
        patch = mock_router.patch(f"{TEST_BASE_URL}/v1/me").mock(
            return_value=Response(200, json=_ME)
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/limits").mock(
            return_value=Response(200, json={"requests_per_minute": 600})
        )

        async with _async_client() as client:
            me = await client.me()
            updated = await client.update_me(name=" Ada ")
            limits = await client.limits()

        assert me.org.plan == "pro"
        assert request_json(patch) == {"name": "Ada"}
        assert updated.user.id == "user_1"
        assert limits == {"requests_per_minute": 600}

    @pytest.mark.asyncio
    async def test_update_me_requires_a_field(self) -> None:
        async with _async_client() as client:
            with pytest.raises(ValueError, match="requires name and/or org_name"):
                await client.update_me()

    @pytest.mark.asyncio
    async def test_api_key_endpoints(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={"api_keys": [_API_KEY]})
        )
        create = mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json={**_API_KEY, "raw_key": "de_live_ab12_secret"})
        )
        mock_router.delete(f"{TEST_BASE_URL}/v1/api-keys/key_1").mock(
            return_value=Response(200, json={"revoked": True})
        )

        async with _async_client() as client:
            keys = await client.list_api_keys()
            created = await client.create_api_key(
                "ci", expires_at=datetime(2027, 1, 1), device_limit=1
            )
            revoked = await client.revoke_api_key("key_1")

        assert keys[0].label == "ci"
        assert request_json(create) == {
            "label": "ci",
            "expires_at": "2027-01-01T00:00:00+00:00",
            "device_limit": 1,
        }
        assert created["raw_key"] == "de_live_ab12_secret"
        assert revoked == {"revoked": True}

    @pytest.mark.asyncio
    async def test_api_key_payload_validation_matches_the_sync_client(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=[{**_API_KEY, "raw_key": "leak"}])
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/api-keys").mock(
            return_value=Response(200, json=_API_KEY)
        )

        async with _async_client() as client:
            with pytest.raises(ValueError, match="leaked one-time secret material"):
                await client.list_api_keys()
            with pytest.raises(ValueError, match="missing raw_key"):
                await client.create_api_key("ci")
            with pytest.raises(ValueError, match="requires label= or name="):
                await client.create_api_key()
            with pytest.raises(TypeError, match="expires_at must be a datetime"):
                await client.create_api_key("ci", expires_at=5)
            with pytest.raises(ValueError, match="greater than or equal to 0"):
                await client.create_api_key("ci", device_limit=-2)

    @pytest.mark.asyncio
    async def test_catalog_and_service_endpoints(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/distributions").mock(
            return_value=Response(200, json=[_DISTRIBUTION])
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/templates").mock(
            return_value=Response(
                200, json={"templates": [_TEMPLATE], "total": 1, "page": 1, "limit": 25, "pages": 1}
            )
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/health").mock(
            return_value=Response(200, json={"status": "ok"})
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/version").mock(
            return_value=Response(200, json={"version": "1.0.16"})
        )

        async with _async_client() as client:
            distributions = await client.distributions()
            templates = await client.templates()
            health = await client.health()
            version = await client.version()

        assert distributions.total == 1 and distributions.distributions[0].name == "triangular"
        assert templates.templates[0].id == "pricing"
        assert health == {"status": "ok"}
        assert version == {"version": "1.0.16"}

    @pytest.mark.asyncio
    async def test_catalogs_reject_scalar_bodies(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/distributions").mock(
            return_value=Response(200, json="nope")
        )

        async with _async_client() as client:
            with pytest.raises(TypeError, match="must be a JSON list or object"):
                await client.distributions()

    @pytest.mark.asyncio
    async def test_not_found_surfaces_as_the_typed_error(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/me").mock(
            return_value=error_response(404, message="no such user")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="no such user"):
                await client.me()

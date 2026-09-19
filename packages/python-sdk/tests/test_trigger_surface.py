"""Tests for the trigger surface: register, list, fire, pause, delete.

``register_trigger`` normalises the condition (trims strings, coerces the
threshold to a float, defaults the aggregation to ``sum``) and validates every
enum-like field client-side; the remaining methods validate the trigger id and
the list ``status`` filter. Sync and async facades share those validators and
are both exercised.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ValidationError

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_TS = "2026-01-01T00:00:00Z"
_TRIGGERS = f"{TEST_BASE_URL}/v1/triggers"

_CONDITION = {
    "source_id": "ds_orders",
    "metric_hint": "revenue",
    "threshold": 10_000,
    "direction": "below",
}

_TEMPLATE = {"mode": "auto", "scenario": {"variables": {"revenue": {"low": 1, "high": 2}}}}

_SUMMARY = {
    "trigger_id": "trg_1",
    "org_id": "org_1",
    "name": "Revenue dip",
    "status": "active",
    "condition": {**_CONDITION, "threshold": 10_000.0, "aggregation": "sum"},
    "created_at": _TS,
}

_FIRE = {
    "trigger_id": "trg_1",
    "condition_met": True,
    "fired": True,
    "simulation_run_id": "run_1",
    "recommended_action": "discount",
    "expected_value": 1_200.0,
    "confidence": 0.8,
    "fired_at": _TS,
    "execution_status": "pending",
    "message": "Condition met; simulation queued.",
}

_PAGE = {"triggers": [_SUMMARY], "count": 1, "total": 1, "page": 1, "limit": 25, "pages": 1}


def _register(client: Any, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "name": "Revenue dip",
        "condition": dict(_CONDITION),
        "simulation_template": _TEMPLATE,
    }
    kwargs.update(overrides)
    return client.register_trigger(**kwargs)


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestRegister:
    def test_posts_the_normalised_payload(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(_TRIGGERS).mock(return_value=Response(200, json=_SUMMARY))

        result = _register(
            client,
            name="  Revenue dip ",
            condition={
                "source_id": " ds_orders ",
                "metric_hint": " revenue ",
                "threshold": 10_000,
                "direction": " below ",
                "aggregation": " avg ",
            },
            webhook_url=" https://hooks.example.com/dip ",
            execution_webhook_url="https://hooks.example.com/exec",
            auto_execute=1,
            description=" Alert on a revenue dip. ",
        )

        assert request_json(route) == {
            "name": "Revenue dip",
            "condition": {
                "source_id": "ds_orders",
                "metric_hint": "revenue",
                "threshold": 10_000.0,
                "direction": "below",
                "aggregation": "avg",
            },
            "simulation_template": _TEMPLATE,
            "auto_execute": True,
            "webhook_url": "https://hooks.example.com/dip",
            "execution_webhook_url": "https://hooks.example.com/exec",
            "description": "Alert on a revenue dip.",
        }
        assert result.trigger_id == "trg_1"
        assert result.condition.aggregation == "sum"

    def test_omits_optional_fields_and_defaults_the_aggregation(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(_TRIGGERS).mock(return_value=Response(200, json=_SUMMARY))

        _register(client)

        body = request_json(route)
        assert body["condition"]["aggregation"] == "sum"
        assert body["auto_execute"] is False
        assert set(body) == {"name", "condition", "simulation_template", "auto_execute"}

    @pytest.mark.parametrize(
        ("overrides", "error", "message"),
        [
            ({"name": " "}, ValueError, "name must be a non-empty string"),
            ({"simulation_template": {}}, ValueError, "simulation_template must be a non-empty"),
            (
                {"simulation_template": "auto"},
                ValueError,
                "simulation_template must be a non-empty",
            ),
            ({"condition": "revenue < 1"}, TypeError, "condition must be a JSON object"),
            ({"webhook_url": ""}, ValueError, "webhook_url must be a non-empty string"),
            (
                {"execution_webhook_url": "  "},
                ValueError,
                "execution_webhook_url must be a non-empty string",
            ),
            ({"description": ""}, ValueError, "description must be a non-empty string"),
        ],
    )
    def test_validates_top_level_arguments(
        self, client: AlgentaClient, overrides: dict[str, Any], error: type, message: str
    ) -> None:
        with pytest.raises(error, match=message):
            _register(client, **overrides)

    @pytest.mark.parametrize(
        ("condition_overrides", "error", "message"),
        [
            ({"source_id": ""}, ValueError, "condition.source_id must be a non-empty string"),
            ({"metric_hint": None}, ValueError, "condition.metric_hint must be a non-empty string"),
            ({"threshold": "10"}, TypeError, "condition.threshold must be a number"),
            ({"threshold": True}, TypeError, "condition.threshold must be a number"),
            ({"direction": None}, TypeError, "condition.direction must be a string"),
            ({"direction": "sideways"}, ValueError, "condition.direction must be one of"),
            ({"aggregation": 3}, TypeError, "condition.aggregation must be a string"),
            ({"aggregation": "median"}, ValueError, "condition.aggregation must be one of"),
        ],
    )
    def test_validates_the_condition(
        self,
        client: AlgentaClient,
        condition_overrides: dict[str, Any],
        error: type,
        message: str,
    ) -> None:
        with pytest.raises(error, match=message):
            _register(client, condition={**_CONDITION, **condition_overrides})


class TestList:
    def test_defaults_to_every_status_without_a_query(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_TRIGGERS).mock(return_value=Response(200, json=_PAGE))

        result = client.list_triggers()

        assert str(route.calls[0].request.url) == _TRIGGERS
        assert result.count == 1
        assert result.triggers[0].name == "Revenue dip"

    @pytest.mark.parametrize("status", ["active", "paused"])
    def test_sends_a_specific_status_with_pagination(
        self, client: AlgentaClient, mock_router, status: str
    ) -> None:
        route = mock_router.get(_TRIGGERS).mock(return_value=Response(200, json=_PAGE))

        client.list_triggers(status=status, page=2, limit=5)

        params = route.calls[0].request.url.params
        assert params["status"] == status
        assert params["page"] == "2" and params["limit"] == "5"

    @pytest.mark.parametrize("status", ["archived", "", None])
    def test_rejects_unknown_statuses(self, client: AlgentaClient, status: Any) -> None:
        with pytest.raises(ValueError, match="status must be one of: active, paused, all"):
            client.list_triggers(status=status)

    def test_rejects_invalid_pagination(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="limit must be an integer"):
            client.list_triggers(limit=0)


class TestFirePauseDelete:
    def test_fire_posts_the_force_flag(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{_TRIGGERS}/trg_1/fire").mock(
            return_value=Response(200, json=_FIRE)
        )

        result = client.fire_trigger(" trg_1 ", force=True)

        assert request_json(route) == {"force": True}
        assert result.fired is True
        assert result.recommended_action == "discount"

    def test_fire_defaults_force_to_false(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{_TRIGGERS}/trg_1/fire").mock(
            return_value=Response(200, json={**_FIRE, "fired": False, "condition_met": False})
        )

        result = client.fire_trigger("trg_1")

        assert request_json(route) == {"force": False}
        assert result.fired is False

    @pytest.mark.parametrize("paused", [True, False])
    def test_pause_sends_the_flag_as_a_query_parameter(
        self, client: AlgentaClient, mock_router, paused: bool
    ) -> None:
        route = mock_router.patch(f"{_TRIGGERS}/trg_1/pause").mock(
            return_value=Response(
                200, json={"trigger_id": "trg_1", "status": "paused" if paused else "active"}
            )
        )

        result = client.pause_trigger("trg_1", paused=paused)

        assert route.calls[0].request.url.params["paused"] == str(paused).lower()
        assert result.status == ("paused" if paused else "active")

    def test_delete_merges_the_server_body_over_the_defaults(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.delete(f"{_TRIGGERS}/trg_1").mock(
            return_value=Response(200, json={"deleted": True, "purged_runs": 3})
        )

        result = client.delete_trigger("trg_1")

        assert route.calls[0].request.method == "DELETE"
        assert result.deleted is True
        assert result.trigger_id == "trg_1"
        assert result.model_dump()["purged_runs"] == 3

    def test_delete_defaults_deleted_when_the_body_is_empty(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.delete(f"{_TRIGGERS}/trg_1").mock(return_value=Response(200, json={}))

        assert client.delete_trigger("trg_1").deleted is True

    def test_delete_rejects_a_non_object_body(self, client: AlgentaClient, mock_router) -> None:
        mock_router.delete(f"{_TRIGGERS}/trg_1").mock(return_value=Response(200, json=[1]))

        with pytest.raises(TypeError, match="Trigger delete response must be a JSON object"):
            client.delete_trigger("trg_1")

    @pytest.mark.parametrize("method", ["fire_trigger", "pause_trigger", "delete_trigger"])
    def test_trigger_id_is_required(self, client: AlgentaClient, method: str) -> None:
        with pytest.raises(ValueError, match="trigger_id must be a non-empty string"):
            getattr(client, method)("  ")


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{_TRIGGERS}/missing/fire").mock(
            return_value=error_response(404, message="trigger not found")
        )

        with pytest.raises(NotFoundError, match="trigger not found"):
            no_retry_client.fire_trigger("missing")

    def test_validation_errors_surface_with_field_details(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(_TRIGGERS).mock(
            return_value=error_response(
                422,
                message="invalid template",
                details=[{"path": "simulation_template.mode", "message": "unknown mode"}],
            )
        )

        with pytest.raises(ValidationError) as exc_info:
            _register(no_retry_client)

        assert exc_info.value.field_errors == [
            {"path": "simulation_template.mode", "message": "unknown mode"}
        ]


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_every_endpoint(self, mock_router) -> None:
        register = mock_router.post(_TRIGGERS).mock(return_value=Response(200, json=_SUMMARY))
        listing = mock_router.get(_TRIGGERS).mock(return_value=Response(200, json=_PAGE))
        fire = mock_router.post(f"{_TRIGGERS}/trg_1/fire").mock(
            return_value=Response(200, json=_FIRE)
        )
        pause = mock_router.patch(f"{_TRIGGERS}/trg_1/pause").mock(
            return_value=Response(200, json={"trigger_id": "trg_1", "status": "paused"})
        )
        mock_router.delete(f"{_TRIGGERS}/trg_1").mock(return_value=Response(200, json={}))

        async with _async_client() as client:
            summary = await _register(client, webhook_url="https://hooks.example.com/dip")
            page = await client.list_triggers(status="paused", limit=5)
            fired = await client.fire_trigger("trg_1", force=True)
            paused = await client.pause_trigger("trg_1")
            deleted = await client.delete_trigger("trg_1")

        body = request_json(register)
        assert body["webhook_url"] == "https://hooks.example.com/dip"
        assert body["condition"]["aggregation"] == "sum"
        assert summary.status == "active"
        assert listing.calls[0].request.url.params["status"] == "paused"
        assert page.total == 1
        assert request_json(fire) == {"force": True}
        assert fired.condition_met is True
        assert pause.calls[0].request.url.params["paused"] == "true"
        assert paused.status == "paused"
        assert deleted.deleted is True and deleted.trigger_id == "trg_1"

    @pytest.mark.asyncio
    async def test_validation_happens_before_any_request(self) -> None:
        async with _async_client() as client:
            with pytest.raises(ValueError, match="condition.direction must be one of"):
                await _register(client, condition={**_CONDITION, "direction": "up"})
            with pytest.raises(ValueError, match="status must be one of"):
                await client.list_triggers(status="archived")
            with pytest.raises(ValueError, match="trigger_id must be a non-empty string"):
                await client.pause_trigger("")

    @pytest.mark.asyncio
    async def test_delete_rejects_a_non_object_body(self, mock_router) -> None:
        mock_router.delete(f"{_TRIGGERS}/trg_1").mock(return_value=Response(200, json="gone"))

        async with _async_client() as client:
            with pytest.raises(TypeError, match="Trigger delete response must be a JSON object"):
                await client.delete_trigger("trg_1")

    @pytest.mark.asyncio
    async def test_not_found_surfaces_as_the_typed_error(self, mock_router) -> None:
        mock_router.delete(f"{_TRIGGERS}/missing").mock(
            return_value=error_response(404, message="trigger not found")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="trigger not found"):
                await client.delete_trigger("missing")

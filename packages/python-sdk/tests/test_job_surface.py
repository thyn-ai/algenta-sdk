"""Tests for the async-job surface: submit, inspect, list, cancel, webhook test, poll.

``submit_job`` reuses the simulation request normaliser and unwraps a nested
``{"request": {...}}`` envelope; ``poll_job`` loops on ``get_job`` until the
job completes, fails, is cancelled, or the deadline passes. Poll sleeps go
through the recorded-sleep fixture, so the loop runs instantly and the
back-off it asks for is asserted directly. Sync and async facades are both
exercised.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import DecisionEngineError, NotFoundError

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_TS = "2026-01-01T00:00:00Z"
_JOBS = f"{TEST_BASE_URL}/v1/jobs"
_JOB_ID = "6f1d2c3b-4a5e-4f60-9b7c-8d9e0f1a2b3c"

_SUBMITTED = {
    "job_id": _JOB_ID,
    "run_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "run")),
    "status": "queued",
    "poll_url": f"/v1/jobs/{_JOB_ID}",
    "message": "queued",
}

_JOB_STATUS = {
    "job_id": _JOB_ID,
    "run_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "run")),
    "org_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "org")),
    "status": "running",
    "queue_name": "simulations",
    "retry_count": 0,
    "callback_status": "pending",
    "created_at": _TS,
    "poll_url": f"/v1/jobs/{_JOB_ID}",
}

_EXPECTED_NORMALISED_REQUEST = {
    "mode": "auto",
    "scenario": {
        "variables": {"revenue": {"low": 1, "high": 2}},
        "objective": "maximize_net_value",
    },
    "runs": 10_000,
}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestSubmit:
    def test_wraps_a_normalised_simulation_request(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))

        result = client.submit_job({"variables": {"revenue": {"low": 1, "high": 2}}})

        assert request_json(route) == {"request": _EXPECTED_NORMALISED_REQUEST}
        assert result["job_id"] == _JOB_ID

    def test_unwraps_a_nested_request_envelope(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))

        client.submit_job({"request": {"variables": {"revenue": {"low": 1, "high": 2}}}})

        assert request_json(route) == {"request": _EXPECTED_NORMALISED_REQUEST}

    def test_keeps_a_request_key_when_simulation_fields_are_present(
        self, client: AlgentaClient, mock_router
    ) -> None:
        """A top-level ``mode`` means the payload is already a simulation request."""
        route = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))

        client.submit_job({"mode": "expert", "simulation": {"variables": []}, "request": {"x": 1}})

        body = request_json(route)["request"]
        assert body["mode"] == "expert"
        assert body["request"] == {"x": 1}

    def test_merges_kwargs_over_the_request_and_adds_the_callback(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))

        client.submit_job(
            {"variables": {"revenue": {"low": 1, "high": 2}}, "runs": 50},
            callback_url="https://hooks.example.com/jobs",
            runs=500,
            seed=7,
        )

        body = request_json(route)
        assert body["callback_url"] == "https://hooks.example.com/jobs"
        assert body["request"]["runs"] == 500
        assert body["request"]["seed"] == 7

    def test_omits_an_empty_callback(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))

        client.submit_job(variables={"revenue": {"low": 1, "high": 2}}, callback_url="")

        assert "callback_url" not in request_json(route)


class TestInspect:
    def test_get_job_and_result_return_raw_bodies(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(return_value=Response(200, json=_JOB_STATUS))
        mock_router.get(f"{_JOBS}/{_JOB_ID}/result").mock(
            return_value=Response(200, json={"recommended_action": "ship_it"})
        )

        assert client.get_job(_JOB_ID) == _JOB_STATUS
        assert client.get_job_result(_JOB_ID) == {"recommended_action": "ship_it"}

    def test_list_jobs_encodes_pagination_and_status_in_the_query(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{_JOBS}/list").mock(
            return_value=Response(
                200, json={"jobs": [_JOB_STATUS], "total": 1, "page": 2, "limit": 5, "pages": 1}
            )
        )

        result = client.list_jobs(page=2, limit=5, status="running")

        params = route.calls[0].request.url.params
        assert dict(params) == {"page": "2", "limit": "5", "status": "running"}
        assert result.jobs[0].job_id == uuid.UUID(_JOB_ID)
        assert result.jobs[0].queue_name == "simulations"

    def test_list_jobs_omits_an_unset_status(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{_JOBS}/list").mock(
            return_value=Response(
                200, json={"jobs": [], "total": 0, "page": 1, "limit": 25, "pages": 0}
            )
        )

        client.list_jobs()

        assert dict(route.calls[0].request.url.params) == {"page": "1", "limit": "25"}

    def test_cancel_job_posts_to_the_cancel_endpoint(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{_JOBS}/{_JOB_ID}/cancel").mock(
            return_value=Response(200, json={**_JOB_STATUS, "status": "cancelled"})
        )

        result = client.cancel_job(_JOB_ID)

        assert route.calls[0].request.content == b""
        assert result["status"] == "cancelled"

    def test_test_webhook_delivery_posts_the_callback(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/webhooks/test").mock(
            return_value=Response(200, json={"delivered": True, "status_code": 200})
        )

        result = client.test_webhook_delivery("https://hooks.example.com/jobs")

        assert request_json(route) == {"callback_url": "https://hooks.example.com/jobs"}
        assert result["delivered"] is True


class TestPoll:
    def test_returns_the_result_once_the_job_completes(
        self, client: AlgentaClient, mock_router, recorded_sleeps: list[float]
    ) -> None:
        status = mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(
            side_effect=[
                Response(200, json={**_JOB_STATUS, "status": "queued"}),
                Response(200, json={**_JOB_STATUS, "status": "running"}),
                Response(200, json={**_JOB_STATUS, "status": "completed"}),
            ]
        )
        mock_router.get(f"{_JOBS}/{_JOB_ID}/result").mock(
            return_value=Response(200, json={"recommended_action": "ship_it"})
        )

        result = client.poll_job(_JOB_ID, poll_interval=0.5)

        assert result == {"recommended_action": "ship_it"}
        assert status.call_count == 3
        assert recorded_sleeps == [0.5, 0.5]

    @pytest.mark.parametrize("terminal", ["failed", "cancelled"])
    def test_raises_when_the_job_ends_without_a_result(
        self, client: AlgentaClient, mock_router, terminal: str
    ) -> None:
        mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(
            return_value=Response(
                200, json={**_JOB_STATUS, "status": terminal, "error_message": "worker died"}
            )
        )

        with pytest.raises(DecisionEngineError, match=f"status '{terminal}': worker died"):
            client.poll_job(_JOB_ID)

    def test_raises_when_the_deadline_passes_before_completion(self, client: AlgentaClient) -> None:
        """A zero timeout expires before the first poll, so no request is made."""
        with pytest.raises(DecisionEngineError, match="did not complete within 0 seconds"):
            client.poll_job(_JOB_ID, timeout=0)


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_JOBS}/missing").mock(
            return_value=error_response(404, message="job not found")
        )

        with pytest.raises(NotFoundError, match="job not found"):
            no_retry_client.get_job("missing")


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_submit_inspect_list_cancel_and_webhook(self, mock_router) -> None:
        submit = mock_router.post(_JOBS).mock(return_value=Response(200, json=_SUBMITTED))
        mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(return_value=Response(200, json=_JOB_STATUS))
        mock_router.get(f"{_JOBS}/{_JOB_ID}/result").mock(
            return_value=Response(200, json={"recommended_action": "ship_it"})
        )
        listing = mock_router.get(f"{_JOBS}/list").mock(
            return_value=Response(
                200, json={"jobs": [_JOB_STATUS], "total": 1, "page": 1, "limit": 25, "pages": 1}
            )
        )
        mock_router.post(f"{_JOBS}/{_JOB_ID}/cancel").mock(
            return_value=Response(200, json={**_JOB_STATUS, "status": "cancelled"})
        )
        webhook = mock_router.post(f"{TEST_BASE_URL}/v1/webhooks/test").mock(
            return_value=Response(200, json={"delivered": True})
        )

        async with _async_client() as client:
            submitted = await client.submit_job(
                {"request": {"variables": {"revenue": {"low": 1, "high": 2}}}},
                callback_url="https://hooks.example.com/jobs",
            )
            status = await client.get_job(_JOB_ID)
            result = await client.get_job_result(_JOB_ID)
            page = await client.list_jobs(status="running")
            cancelled = await client.cancel_job(_JOB_ID)
            delivery = await client.test_webhook_delivery("https://hooks.example.com/jobs")

        assert request_json(submit) == {
            "request": _EXPECTED_NORMALISED_REQUEST,
            "callback_url": "https://hooks.example.com/jobs",
        }
        assert submitted["status"] == "queued"
        assert status["queue_name"] == "simulations"
        assert result == {"recommended_action": "ship_it"}
        assert listing.calls[0].request.url.params["status"] == "running"
        assert page.total == 1
        assert cancelled["status"] == "cancelled"
        assert request_json(webhook) == {"callback_url": "https://hooks.example.com/jobs"}
        assert delivery == {"delivered": True}

    @pytest.mark.asyncio
    async def test_poll_returns_the_result_once_completed(
        self, mock_router, recorded_sleeps: list[float]
    ) -> None:
        status = mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(
            side_effect=[
                Response(200, json={**_JOB_STATUS, "status": "running"}),
                Response(200, json={**_JOB_STATUS, "status": "completed"}),
            ]
        )
        mock_router.get(f"{_JOBS}/{_JOB_ID}/result").mock(
            return_value=Response(200, json={"recommended_action": "wait"})
        )

        async with _async_client() as client:
            result = await client.poll_job(_JOB_ID, poll_interval=0.25)

        assert result == {"recommended_action": "wait"}
        assert status.call_count == 2
        assert recorded_sleeps == [0.25]

    @pytest.mark.asyncio
    async def test_poll_raises_on_a_failed_job(self, mock_router) -> None:
        mock_router.get(f"{_JOBS}/{_JOB_ID}").mock(
            return_value=Response(
                200, json={**_JOB_STATUS, "status": "failed", "error_message": "oom"}
            )
        )

        async with _async_client() as client:
            with pytest.raises(DecisionEngineError, match="status 'failed': oom"):
                await client.poll_job(_JOB_ID)

    @pytest.mark.asyncio
    async def test_poll_raises_when_the_deadline_passes(self) -> None:
        async with _async_client() as client:
            with pytest.raises(DecisionEngineError, match="timed out after 0s"):
                await client.poll_job(_JOB_ID, timeout=0)

    @pytest.mark.asyncio
    async def test_not_found_surfaces_as_the_typed_error(self, mock_router) -> None:
        mock_router.get(f"{_JOBS}/missing/result").mock(
            return_value=error_response(404, message="no result yet")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="no result yet"):
                await client.get_job_result("missing")

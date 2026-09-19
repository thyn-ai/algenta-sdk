"""Tests for the agent-run surface: lifecycle, events, checkpoints, telemetry, replay.

Every method is pinned to its HTTP method, path, query string and body on both
facades. Filter queries are exercised with every filter set (the SDK encodes
the filters it is given verbatim). ``stream_agent_run_events`` is fed a crafted
Server-Sent Events body and must yield one typed event per ``data:`` block.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError
from decision_engine.models_agent_runs import (
    AgentRunCheckpointListResponseResult,
    AgentRunCheckpointsResult,
    AgentRunEventsResult,
    AgentRunListResult,
    AgentRunMissionEventListResponseResult,
    AgentRunMissionEventsResult,
    AgentRunReplayResult,
    AgentRunResult,
    AgentRunStreamEventResult,
    AgentRunTelemetryListResult,
    AgentRunTelemetryResult,
)

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_TS = "2026-01-01T00:00:00Z"
_RUNS = f"{TEST_BASE_URL}/v1/agent/runs"

_RUN = {
    "run_id": "run_1",
    "status": "running",
    "task": "Summarise the changelog.",
    "output_format": "text",
    "approval_mode": "auto",
    "created_at": _TS,
    "updated_at": _TS,
}

_EVENT = {
    "event_id": "evt_1",
    "event_type": "step",
    "status": "running",
    "message": "Reading changelog",
    "created_at": _TS,
}

_MISSION_EVENT = {
    "mission_id": "m_1",
    "thread_id": "t_1",
    "tenant_scope": "org_1",
    "workspace_scope": "ws_1",
    "event_index": 0,
    "superstep": 1,
    "node_name": "planner",
    "event_type": "node_started",
    "event_ts": _TS,
    "request_hash": "rh",
    "policy_snapshot_id": "pol_1",
    "schema_snapshot_id": "sch_1",
    "manifest_version": "1.0.0",
}

_CHECKPOINT = {
    "checkpoint_id": "cp_1",
    "checkpoint_index": 0,
    "run_id": "run_1",
    "status": "paused",
    "event_start_index": 0,
    "event_end_index": 3,
    "request_hash": "rh",
    "decision_hash": "dh",
    "content_hash": "ch",
    "policy_snapshot_id": "pol_1",
    "schema_snapshot_id": "sch_1",
    "manifest_version": "1.0.0",
    "created_at": _TS,
}

_TELEMETRY = {
    "batch_id": "b_1",
    "telemetry_kind": "latency",
    "module_name": "embeddings",
    "tenant_scope": "org_1",
    "request_hash": "rh",
    "started_at": _TS,
    "ended_at": _TS,
    "success_count": 9,
    "failure_count": 1,
    "latency_ms_p95": 42.0,
    "cost_usd_micros": 120,
}

_REPLAY = {
    "run_id": "run_1",
    "checkpoint_id": "cp_1",
    "replay_status": "matched",
    "compared_event_count": 3,
    "checkpoint_count": 1,
    "request_hash": "rh",
    "decision_hash": "dh",
    "content_hash": "ch",
    "policy_snapshot_id": "pol_1",
    "schema_snapshot_id": "sch_1",
    "manifest_version": "1.0.0",
    "created_at": _TS,
}

_PAGE = {"total": 1, "page": 1, "limit": 25, "pages": 1}

_ALL_FILTERS = {
    "status": "running",
    "request_hash": "rh",
    "policy_snapshot_id": "pol_1",
    "schema_snapshot_id": "sch_1",
}

# (id, call, method, path, expected query (None = untested), expected json body, response, type)
_CALLS: list[tuple[str, Callable[[Any], Any], str, str, dict[str, str] | None, Any, Any, type]] = [
    (
        "create_agent_run",
        lambda c: c.create_agent_run(
            task="Summarise the changelog.",
            context={"repo": "algenta-sdk"},
            tools=["fs.read"],
            max_steps=3,
            output_format="json",
            approval_mode="manual",
            start_paused=True,
        ),
        "POST",
        "/v1/agent/runs",
        None,
        {
            "task": "Summarise the changelog.",
            "context": {"repo": "algenta-sdk"},
            "tools": ["fs.read"],
            "max_steps": 3,
            "output_format": "json",
            "approval_mode": "manual",
            "start_paused": True,
        },
        {**_RUN, "status": "paused", "approval_mode": "manual", "output_format": "json"},
        AgentRunResult,
    ),
    (
        "create_agent_run_defaults",
        lambda c: c.create_agent_run(task="Plan."),
        "POST",
        "/v1/agent/runs",
        None,
        {
            "task": "Plan.",
            "context": None,
            "tools": None,
            "max_steps": 10,
            "output_format": "text",
            "approval_mode": "auto",
            "start_paused": False,
        },
        _RUN,
        AgentRunResult,
    ),
    (
        "get_agent_run",
        lambda c: c.get_agent_run("run_1"),
        "GET",
        "/v1/agent/runs/run_1",
        {},
        None,
        _RUN,
        AgentRunResult,
    ),
    (
        "list_agent_runs",
        lambda c: c.list_agent_runs(page=2, limit=5, **_ALL_FILTERS),
        "GET",
        "/v1/agent/runs",
        {"page": "2", "limit": "5", **_ALL_FILTERS},
        None,
        {"object": "list", "data": [_RUN], **_PAGE},
        AgentRunListResult,
    ),
    (
        "get_agent_run_events",
        lambda c: c.get_agent_run_events("run_1", limit=50),
        "GET",
        "/v1/agent/runs/run_1/events",
        {"limit": "50"},
        None,
        {"run_id": "run_1", "data": [_EVENT], "total_events": 1},
        AgentRunEventsResult,
    ),
    (
        "list_agent_run_checkpoints",
        lambda c: c.list_agent_run_checkpoints("run_1"),
        "GET",
        "/v1/agent/runs/run_1/checkpoints",
        {},
        None,
        {"run_id": "run_1", "data": [_CHECKPOINT], "total_checkpoints": 1},
        AgentRunCheckpointsResult,
    ),
    (
        "query_agent_run_checkpoints",
        lambda c: c.query_agent_run_checkpoints(
            **_ALL_FILTERS, run_id="run_1", checkpoint_id="cp_1"
        ),
        "GET",
        "/v1/agent/runs/checkpoints",
        {"page": "1", "limit": "25", **_ALL_FILTERS, "run_id": "run_1", "checkpoint_id": "cp_1"},
        None,
        {"data": [{**_CHECKPOINT, "run_status": "paused"}], **_PAGE},
        AgentRunCheckpointListResponseResult,
    ),
    (
        "list_agent_run_mission_events",
        lambda c: c.list_agent_run_mission_events("run_1", limit=10),
        "GET",
        "/v1/agent/runs/run_1/mission-events",
        {"limit": "10"},
        None,
        {"run_id": "run_1", "data": [_MISSION_EVENT], "total_events": 1},
        AgentRunMissionEventsResult,
    ),
    (
        "query_agent_run_mission_events",
        lambda c: c.query_agent_run_mission_events(
            **_ALL_FILTERS, run_id="run_1", event_type="node_started"
        ),
        "GET",
        "/v1/agent/runs/mission-events",
        {
            "page": "1",
            "limit": "25",
            **_ALL_FILTERS,
            "run_id": "run_1",
            "event_type": "node_started",
        },
        None,
        {
            "data": [{**_MISSION_EVENT, "run_id": "run_1", "run_status": "running"}],
            **_PAGE,
        },
        AgentRunMissionEventListResponseResult,
    ),
    (
        "list_agent_run_telemetry",
        lambda c: c.list_agent_run_telemetry("run_1"),
        "GET",
        "/v1/agent/runs/run_1/telemetry",
        {"limit": "1000"},
        None,
        {"run_id": "run_1", "data": [_TELEMETRY], "total_batches": 1},
        AgentRunTelemetryResult,
    ),
    (
        "query_agent_run_telemetry",
        lambda c: c.query_agent_run_telemetry(
            **_ALL_FILTERS, run_id="run_1", telemetry_kind="latency", module_name="embeddings"
        ),
        "GET",
        "/v1/agent/runs/telemetry",
        {
            "page": "1",
            "limit": "25",
            **_ALL_FILTERS,
            "run_id": "run_1",
            "telemetry_kind": "latency",
            "module_name": "embeddings",
        },
        None,
        {"data": [{**_TELEMETRY, "run_id": "run_1", "run_status": "running"}], **_PAGE},
        AgentRunTelemetryListResult,
    ),
    (
        "replay_agent_run",
        lambda c: c.replay_agent_run("run_1", checkpoint_id="cp_1"),
        "POST",
        "/v1/agent/runs/run_1/replay",
        None,
        {"checkpoint_id": "cp_1"},
        _REPLAY,
        AgentRunReplayResult,
    ),
    (
        "fork_agent_run",
        lambda c: c.fork_agent_run("run_1"),
        "POST",
        "/v1/agent/runs/run_1/fork",
        None,
        {"checkpoint_id": None},
        {**_RUN, "run_id": "run_2", "source_run_id": "run_1"},
        AgentRunResult,
    ),
    (
        "resume_agent_run",
        lambda c: c.resume_agent_run("run_1"),
        "POST",
        "/v1/agent/runs/run_1/resume",
        None,
        {},
        _RUN,
        AgentRunResult,
    ),
    (
        "cancel_agent_run",
        lambda c: c.cancel_agent_run("run_1"),
        "POST",
        "/v1/agent/runs/run_1/cancel",
        None,
        {},
        {**_RUN, "status": "cancelled"},
        AgentRunResult,
    ),
    (
        "approve_agent_run",
        lambda c: c.approve_agent_run("run_1"),
        "POST",
        "/v1/agent/runs/run_1/approve",
        None,
        {},
        {**_RUN, "status": "running", "pending_action": None},
        AgentRunResult,
    ),
]
_IDS = [entry[0] for entry in _CALLS]
_PARAMS = [entry[1:] for entry in _CALLS]


def _mock(router: respx.Router, method: str, path: str, body: Any) -> respx.Route:
    return router.route(method=method, url=f"{TEST_BASE_URL}{path}").mock(
        return_value=Response(200, json=body)
    )


def _assert_call(
    route: respx.Route,
    method: str,
    query: dict[str, str] | None,
    body: Any,
    result: Any,
    model: type,
) -> None:
    request = route.calls[0].request
    assert request.method == method
    if query is not None:
        assert dict(request.url.params) == query
    if body is not None:
        assert request_json(route) == body
    assert isinstance(result, model)


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


@pytest.mark.parametrize(
    ("call", "method", "path", "query", "body", "response", "model"), _PARAMS, ids=_IDS
)
def test_sync_methods_issue_one_request_and_parse_the_typed_result(
    client: AlgentaClient,
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    query: dict[str, str] | None,
    body: Any,
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, method, path, response)

    result = call(client)

    _assert_call(route, method, query, body, result, model)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "method", "path", "query", "body", "response", "model"), _PARAMS, ids=_IDS
)
async def test_async_methods_issue_one_request_and_parse_the_typed_result(
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    query: dict[str, str] | None,
    body: Any,
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, method, path, response)

    async with _async_client() as client:
        result = await call(client)

    _assert_call(route, method, query, body, result, model)


class TestParsedShapes:
    def test_list_agent_runs_default_pagination(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(_RUNS).mock(
            return_value=Response(200, json={"object": "list", "data": [_RUN], **_PAGE})
        )

        result = client.list_agent_runs(**_ALL_FILTERS)

        params = route.calls[0].request.url.params
        assert params["page"] == "1" and params["limit"] == "25"
        assert result.data[0].run_id == "run_1"
        assert result.data[0].steps == []

    def test_step_aliases_are_honoured_in_parsed_runs(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_RUNS}/run_1").mock(
            return_value=Response(
                200,
                json={
                    **_RUN,
                    "status": "completed",
                    "result": {"summary": "done"},
                    "steps": [{"step": 1, "tool": "fs.read", "status": "completed"}],
                    "tools_used": ["fs.read"],
                },
            )
        )

        run = client.get_agent_run("run_1")

        assert run.status == "completed"
        assert run.result == {"summary": "done"}
        assert run.steps[0].step_number == 1
        assert run.steps[0].tool_name == "fs.read"

    def test_checkpoint_and_telemetry_pages_carry_run_status(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_RUNS}/checkpoints").mock(
            return_value=Response(
                200, json={"data": [{**_CHECKPOINT, "run_status": "paused"}], **_PAGE}
            )
        )
        mock_router.get(f"{_RUNS}/telemetry").mock(
            return_value=Response(
                200,
                json={
                    "data": [{**_TELEMETRY, "run_id": "run_1", "run_status": "running"}],
                    **_PAGE,
                },
            )
        )

        checkpoints = client.query_agent_run_checkpoints(**_ALL_FILTERS, run_id="run_1")
        telemetry = client.query_agent_run_telemetry(**_ALL_FILTERS, run_id="run_1")

        assert checkpoints.data[0].run_status == "paused"
        assert checkpoints.data[0].event_end_index == 3
        assert telemetry.data[0].latency_ms_p95 == pytest.approx(42.0)


class TestStreaming:
    _SSE_BODY = (
        b": keep-alive\n\n"
        b'data: {"type": "agent.run.event", "run_id": "run_1", "event": '
        + b'{"event_id": "evt_1", "event_type": "step", "status": "running", '
        + b'"message": "Reading", "created_at": "2026-01-01T00:00:00Z"}}\n\n'
        + b'data: {"type": "agent.run.completed", "run_id": "run_1", '
        + b'"status": "completed", "total_events": 1}\n\n'
        + b"data: [DONE]\n\n"
    )

    def test_stream_yields_one_typed_event_per_sse_block(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{_RUNS}/run_1/events").mock(
            return_value=Response(
                200, headers={"content-type": "text/event-stream"}, content=self._SSE_BODY
            )
        )

        events = list(client.stream_agent_run_events("run_1", limit=10))

        request = route.calls[0].request
        assert dict(request.url.params) == {"limit": "10", "stream": "true"}
        assert request.headers["Accept"] == "text/event-stream"
        assert [event.type for event in events] == ["agent.run.event", "agent.run.completed"]
        assert isinstance(events[0], AgentRunStreamEventResult)
        assert events[0].event is not None and events[0].event.event_id == "evt_1"
        assert events[1].status == "completed" and events[1].total_events == 1

    @pytest.mark.asyncio
    async def test_async_stream_yields_the_same_events(self, mock_router) -> None:
        mock_router.get(f"{_RUNS}/run_1/events").mock(
            return_value=Response(
                200, headers={"content-type": "text/event-stream"}, content=self._SSE_BODY
            )
        )

        async with _async_client() as client:
            events = [event async for event in client.stream_agent_run_events("run_1")]

        assert [event.type for event in events] == ["agent.run.event", "agent.run.completed"]


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_RUNS}/missing").mock(
            return_value=error_response(404, message="run not found")
        )

        with pytest.raises(NotFoundError, match="run not found"):
            no_retry_client.get_agent_run("missing")

    @pytest.mark.asyncio
    async def test_async_not_found_surfaces_as_the_typed_error(self, mock_router) -> None:
        mock_router.post(f"{_RUNS}/missing/approve").mock(
            return_value=error_response(404, message="run not found")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="run not found"):
                await client.approve_agent_run("missing")

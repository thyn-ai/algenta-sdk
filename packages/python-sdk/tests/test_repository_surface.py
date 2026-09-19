"""Tests for the repository-intelligence surface.

Eight thin wrappers: capabilities, snapshot create/get, triage, decision-plan
revision, graph query, simulate and apply. Each is pinned to its HTTP method,
path, body and parsed result type on both facades; ``simulate_repository``
returns the same ``DecisionEnvelope`` as the core simulation surface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ValidationError
from decision_engine.models_decision_envelope import DecisionEnvelope
from decision_engine.models_repository_intelligence import (
    RepositoryApplyResult,
    RepositoryDecisionPlanRevisionResult,
    RepositoryGraphQueryResult,
    RepositoryIntelligenceCapabilitiesResult,
    RepositorySnapshotResult,
    RepositoryTriageResult,
)

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_decision_envelope_payload,
    make_decision_plan_payload,
    make_repository_snapshot_payload,
    make_repository_triage_payload,
    request_json,
)

_TS = "2026-01-01T00:00:00Z"
_REPO = "/v1/repositories/repo_1"

_CAPABILITIES = {
    "supported_languages": ["python", "typescript"],
    "support_progress": {
        "supported_real_language_count": 2,
        "ranked_target_language_count": 20,
        "progress_fraction": 0.1,
        "progress_label": "2 of 20",
    },
}

_GRAPH = {
    "repository_id": "repo_1",
    "snapshot_id": "snap_1",
    "created_at": _TS,
    "seed_file_paths": ["a.py"],
    "impacted_files": ["b.py"],
}

_APPLY = {
    "repository_id": "repo_1",
    "snapshot_id": "snap_1",
    "decision_plan_id": "plan_1",
    "simulation_id": "sim_1",
    "mode": "branch",
    "applied": True,
    "created_at": _TS,
    "patch": "--- a/a.py\n+++ b/a.py\n",
    "branch_name": "algenta/plan_1",
}

_REVISION = {
    "repository_id": "repo_1",
    "snapshot_id": "snap_1",
    "decision_plan_id": "plan_1",
    "created_at": _TS,
    "decision_plan": make_decision_plan_payload(),
}

# (id, call, method, path, expected body, response, result type)
_CALLS: list[tuple[str, Callable[[Any], Any], str, str, Any, Any, type]] = [
    (
        "get_repository_intelligence_capabilities",
        lambda c: c.get_repository_intelligence_capabilities(),
        "GET",
        "/v1/repositories/capabilities",
        None,
        _CAPABILITIES,
        RepositoryIntelligenceCapabilitiesResult,
    ),
    (
        "create_repository_snapshot",
        lambda c: c.create_repository_snapshot("repo_1", {"ref": "main"}),
        "POST",
        f"{_REPO}/snapshots",
        {"ref": "main"},
        make_repository_snapshot_payload(),
        RepositorySnapshotResult,
    ),
    (
        "get_repository_snapshot",
        lambda c: c.get_repository_snapshot("repo_1", "snap_1"),
        "GET",
        f"{_REPO}/snapshots/snap_1",
        None,
        make_repository_snapshot_payload(),
        RepositorySnapshotResult,
    ),
    (
        "triage_repository",
        lambda c: c.triage_repository("repo_1", {"snapshot_id": "snap_1", "issue": "flaky"}),
        "POST",
        f"{_REPO}/triage",
        {"snapshot_id": "snap_1", "issue": "flaky"},
        make_repository_triage_payload(),
        RepositoryTriageResult,
    ),
    (
        "create_repository_decision_plan",
        lambda c: c.create_repository_decision_plan("repo_1", {"snapshot_id": "snap_1"}),
        "POST",
        f"{_REPO}/decision-plans",
        {"snapshot_id": "snap_1"},
        _REVISION,
        RepositoryDecisionPlanRevisionResult,
    ),
    (
        "query_repository_graph",
        lambda c: c.query_repository_graph("repo_1", {"seed_file_paths": ["a.py"]}),
        "POST",
        f"{_REPO}/graph-query",
        {"seed_file_paths": ["a.py"]},
        _GRAPH,
        RepositoryGraphQueryResult,
    ),
    (
        "simulate_repository",
        lambda c: c.simulate_repository("repo_1", {"decision_plan_id": "plan_1"}),
        "POST",
        f"{_REPO}/simulate",
        {"decision_plan_id": "plan_1"},
        make_decision_envelope_payload(),
        DecisionEnvelope,
    ),
    (
        "apply_repository",
        lambda c: c.apply_repository("repo_1", {"simulation_id": "sim_1", "mode": "branch"}),
        "POST",
        f"{_REPO}/apply",
        {"simulation_id": "sim_1", "mode": "branch"},
        _APPLY,
        RepositoryApplyResult,
    ),
]
_IDS = [entry[0] for entry in _CALLS]
_PARAMS = [entry[1:] for entry in _CALLS]


def _mock(router: respx.Router, method: str, path: str, body: Any) -> respx.Route:
    return router.route(method=method, url=f"{TEST_BASE_URL}{path}").mock(
        return_value=Response(200, json=body)
    )


def _assert_call(route: respx.Route, method: str, body: Any, result: Any, model: type) -> None:
    request = route.calls[0].request
    assert request.method == method
    if body is None:
        assert request.content == b""
    else:
        assert request_json(route) == body
    assert isinstance(result, model)


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


@pytest.mark.parametrize(("call", "method", "path", "body", "response", "model"), _PARAMS, ids=_IDS)
def test_sync_methods_issue_one_request_and_parse_the_typed_result(
    client: AlgentaClient,
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    body: Any,
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, method, path, response)

    result = call(client)

    _assert_call(route, method, body, result, model)


@pytest.mark.asyncio
@pytest.mark.parametrize(("call", "method", "path", "body", "response", "model"), _PARAMS, ids=_IDS)
async def test_async_methods_issue_one_request_and_parse_the_typed_result(
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    body: Any,
    response: Any,
    model: type,
) -> None:
    route = _mock(mock_router, method, path, response)

    async with _async_client() as client:
        result = await call(client)

    _assert_call(route, method, body, result, model)


def test_parsed_results_expose_the_nested_structures(client: AlgentaClient, mock_router) -> None:
    mock_router.post(f"{TEST_BASE_URL}{_REPO}/triage").mock(
        return_value=Response(200, json=make_repository_triage_payload())
    )
    mock_router.post(f"{TEST_BASE_URL}{_REPO}/decision-plans").mock(
        return_value=Response(200, json=_REVISION)
    )

    triage = client.triage_repository("repo_1", {"snapshot_id": "snap_1"})
    revision = client.create_repository_decision_plan("repo_1", {"snapshot_id": "snap_1"})

    assert triage.reduction_ratio == pytest.approx(260.4)
    assert [item.rank for item in triage.evidence_items] == [1, 2]
    assert revision.decision_plan.recommended_action == "patch_transport_retry"
    assert revision.decision_plan.options[0].risk.probability_of_loss == pytest.approx(0.04)


def test_not_found_surfaces_as_the_typed_error(no_retry_client: AlgentaClient, mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}{_REPO}/snapshots/missing").mock(
        return_value=error_response(404, message="snapshot not found")
    )

    with pytest.raises(NotFoundError, match="snapshot not found"):
        no_retry_client.get_repository_snapshot("repo_1", "missing")


@pytest.mark.asyncio
async def test_async_validation_errors_surface_with_details(mock_router) -> None:
    mock_router.post(f"{TEST_BASE_URL}{_REPO}/apply").mock(
        return_value=error_response(
            422, message="apply gate failed", details=[{"path": "mode", "message": "unknown"}]
        )
    )

    async with _async_client() as client:
        with pytest.raises(ValidationError, match="apply gate failed") as exc_info:
            await client.apply_repository("repo_1", {"mode": "teleport"})

    assert exc_info.value.field_errors == [{"path": "mode", "message": "unknown"}]

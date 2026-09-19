"""Tests for the capability-plane surface: providers, bindings, catalog, routing, skills.

Most methods are one request each; the parametrised table pins the HTTP
method, path, body and parsed result type of every one of them on both the
sync and async facades. The composite helpers (``enable_skill`` creates a
binding then discovers it, ``list_skills`` filters by kind,
``list_mcp_providers`` filters by provider type) and the query-string builders
(repeated ``kinds``/``provider_ids``/``binding_ids`` params,
``include_instruction``) get dedicated tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ServerError
from decision_engine.models_capability_plane import (
    CapabilityAuthorizationCompleteResult,
    CapabilityAuthorizationStartResult,
    CapabilityBindingResult,
    CapabilityBindingTestResult,
    CapabilityCatalogEntryResult,
    CapabilityDiscoverResult,
    CapabilityExecutionResult,
    CapabilityOutcomeRecordResult,
    CapabilityProviderResult,
    CapabilityRoutePlanResult,
)

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_capability_binding_payload,
    make_capability_catalog_entry_payload,
    make_capability_provider_payload,
    request_json,
)

_TS = "2026-01-01T00:00:00Z"
_BINDINGS = f"{TEST_BASE_URL}/v1/capability-bindings"
_CAPABILITIES = f"{TEST_BASE_URL}/v1/capabilities"

_TEST_RESULT = {"success": True, "binding_status": "active", "message": "ok", "latency_ms": 12}

_DISCOVER_RESULT = {
    "binding_id": "bind_1",
    "provider_id": "provider.github",
    "profile_id": "profile.github.user",
    "binding_status": "active",
    "manifest_hash": "m" * 64,
    "capability_count": 1,
    "discovered_at": _TS,
    "message": "Discovered 1 capability.",
    "capabilities": [make_capability_catalog_entry_payload()],
}

_ROUTE_PLAN = {
    "selected_capability_id": "cap.github.create_issue",
    "selected_provider_id": "provider.github",
    "selected_binding_id": "bind_1",
    "kind": "tool",
    "execution_owner": "algenta_managed",
    "requires_approval": True,
    "confidence": 0.9,
    "reason": "Exact match.",
    "policy_snapshot_id": "pol_1",
}

_EXECUTION = {
    "execution_session_id": "exec_1",
    "capability_id": "cap.github.create_issue",
    "provider_id": "provider.github",
    "binding_id": "bind_1",
    "execution_owner": "algenta_managed",
    "status": "completed",
    "output": {"issue_url": "https://github.com/thyn-ai/algenta-sdk/issues/1"},
    "started_at": _TS,
    "completed_at": _TS,
}

_OUTCOME = {
    "outcome_id": "out_1",
    "capability_id": "cap.github.create_issue",
    "provider_id": "provider.github",
    "result_status": "success",
    "success": True,
    "created_at": _TS,
}

_AUTH_START = {
    "session_id": "auth_1",
    "binding_id": "bind_1",
    "provider_id": "provider.github",
    "authorize_url": "https://github.com/login/oauth/authorize?state=abc",
    "expires_at": _TS,
}

_AUTH_COMPLETE = {
    "session_id": "auth_1",
    "binding_id": "bind_1",
    "provider_id": "provider.github",
    "status": "authorized",
    "authorized_at": _TS,
}

# (id, call, http method, path, expected json body or None, response body, result type)
_SIMPLE_CALLS: list[tuple[str, Callable[[Any], Any], str, str, Any, Any, type | None]] = [
    (
        "list_capability_providers",
        lambda c: c.list_capability_providers(),
        "GET",
        "/v1/capability-providers",
        None,
        [make_capability_provider_payload()],
        None,
    ),
    (
        "get_capability_provider",
        lambda c: c.get_capability_provider("provider.github"),
        "GET",
        "/v1/capability-providers/provider.github",
        None,
        make_capability_provider_payload(),
        CapabilityProviderResult,
    ),
    (
        "create_capability_binding",
        lambda c: c.create_capability_binding({"provider_id": "provider.github"}),
        "POST",
        "/v1/capability-bindings",
        {"provider_id": "provider.github"},
        make_capability_binding_payload(),
        CapabilityBindingResult,
    ),
    (
        "get_capability_binding",
        lambda c: c.get_capability_binding("bind_1"),
        "GET",
        "/v1/capability-bindings/bind_1",
        None,
        make_capability_binding_payload(),
        CapabilityBindingResult,
    ),
    (
        "update_capability_binding",
        lambda c: c.update_capability_binding("bind_1", {"binding_name": "renamed"}),
        "PATCH",
        "/v1/capability-bindings/bind_1",
        {"binding_name": "renamed"},
        make_capability_binding_payload(binding_name="renamed"),
        CapabilityBindingResult,
    ),
    (
        "preview_test_capability_binding",
        lambda c: c.preview_test_capability_binding({"provider_id": "provider.github"}),
        "POST",
        "/v1/capability-bindings/test",
        {"provider_id": "provider.github"},
        _TEST_RESULT,
        CapabilityBindingTestResult,
    ),
    (
        "test_capability_binding",
        lambda c: c.test_capability_binding("bind_1"),
        "POST",
        "/v1/capability-bindings/bind_1/test",
        None,
        _TEST_RESULT,
        CapabilityBindingTestResult,
    ),
    (
        "preview_discover_capability_binding",
        lambda c: c.preview_discover_capability_binding({"provider_id": "provider.github"}),
        "POST",
        "/v1/capability-bindings/discover",
        {"provider_id": "provider.github"},
        _DISCOVER_RESULT,
        CapabilityDiscoverResult,
    ),
    (
        "discover_capability_binding",
        lambda c: c.discover_capability_binding("bind_1"),
        "POST",
        "/v1/capability-bindings/bind_1/discover",
        None,
        _DISCOVER_RESULT,
        CapabilityDiscoverResult,
    ),
    (
        "start_capability_authorization",
        lambda c: c.start_capability_authorization("bind_1", {"redirect_uri": "https://x"}),
        "POST",
        "/v1/capability-bindings/bind_1/authorize/start",
        {"redirect_uri": "https://x"},
        _AUTH_START,
        CapabilityAuthorizationStartResult,
    ),
    (
        "complete_capability_authorization",
        lambda c: c.complete_capability_authorization("bind_1", {"code": "abc"}),
        "POST",
        "/v1/capability-bindings/bind_1/authorize/complete",
        {"code": "abc"},
        _AUTH_COMPLETE,
        CapabilityAuthorizationCompleteResult,
    ),
    (
        "get_capability",
        lambda c: c.get_capability("cap.github.create_issue"),
        "GET",
        "/v1/capabilities/cap.github.create_issue",
        None,
        make_capability_catalog_entry_payload(),
        CapabilityCatalogEntryResult,
    ),
    (
        "route_capabilities",
        lambda c: c.route_capabilities({"intent": "open an issue"}),
        "POST",
        "/v1/capabilities/route",
        {"intent": "open an issue"},
        _ROUTE_PLAN,
        CapabilityRoutePlanResult,
    ),
    (
        "execute_capability",
        lambda c: c.execute_capability({"capability_id": "cap.github.create_issue"}),
        "POST",
        "/v1/capabilities/execute",
        {"capability_id": "cap.github.create_issue"},
        _EXECUTION,
        CapabilityExecutionResult,
    ),
    (
        "record_capability_outcome",
        lambda c: c.record_capability_outcome({"capability_id": "cap.x", "success": True}),
        "POST",
        "/v1/capabilities/outcomes",
        {"capability_id": "cap.x", "success": True},
        _OUTCOME,
        CapabilityOutcomeRecordResult,
    ),
]
_SIMPLE_IDS = [entry[0] for entry in _SIMPLE_CALLS]


def _mock(router: respx.Router, method: str, path: str, body: Any) -> respx.Route:
    return router.route(method=method, url=f"{TEST_BASE_URL}{path}").mock(
        return_value=Response(200, json=body)
    )


def _assert_simple_call(
    route: respx.Route, method: str, body: Any, result: Any, model: Any
) -> None:
    request = route.calls[0].request
    assert request.method == method
    if body is not None:
        assert request_json(route) == body
    else:
        assert request.content == b""
    if model is None:
        assert isinstance(result, list) and all(
            isinstance(item, CapabilityProviderResult) for item in result
        )
    else:
        assert isinstance(result, model)


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


@pytest.mark.parametrize(
    ("call", "method", "path", "body", "response", "model"),
    [entry[1:] for entry in _SIMPLE_CALLS],
    ids=_SIMPLE_IDS,
)
def test_sync_methods_issue_one_request_and_parse_the_typed_result(
    client: AlgentaClient,
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    body: Any,
    response: Any,
    model: type | None,
) -> None:
    route = _mock(mock_router, method, path, response)

    result = call(client)

    _assert_simple_call(route, method, body, result, model)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "method", "path", "body", "response", "model"),
    [entry[1:] for entry in _SIMPLE_CALLS],
    ids=_SIMPLE_IDS,
)
async def test_async_methods_issue_one_request_and_parse_the_typed_result(
    mock_router,
    call: Callable[[Any], Any],
    method: str,
    path: str,
    body: Any,
    response: Any,
    model: type | None,
) -> None:
    route = _mock(mock_router, method, path, response)

    async with _async_client() as client:
        result = await call(client)

    _assert_simple_call(route, method, body, result, model)


class TestBindingFilters:
    def test_list_bindings_without_filters_sends_no_query(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_BINDINGS).mock(
            return_value=Response(200, json=[make_capability_binding_payload()])
        )

        bindings = client.list_capability_bindings()

        assert str(route.calls[0].request.url) == _BINDINGS
        assert bindings[0].binding_id == "bind_1"

    def test_list_bindings_sends_provider_and_scope(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_BINDINGS).mock(return_value=Response(200, json=[]))

        client.list_capability_bindings(provider_id="provider.github", scope="org")

        params = route.calls[0].request.url.params
        assert params["provider_id"] == "provider.github"
        assert params["scope"] == "org"

    def test_delete_binding_returns_none(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.delete(f"{_BINDINGS}/bind_1").mock(return_value=Response(204))

        assert client.delete_capability_binding("bind_1") is None
        assert route.calls[0].request.method == "DELETE"


class TestCatalogFilters:
    def test_list_capabilities_without_filters_sends_no_query(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CAPABILITIES).mock(
            return_value=Response(200, json=[make_capability_catalog_entry_payload()])
        )

        entries = client.list_capabilities()

        assert str(route.calls[0].request.url) == _CAPABILITIES
        assert entries[0].capability_id == "cap.github.create_issue"

    def test_list_capabilities_repeats_each_filter_key(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CAPABILITIES).mock(return_value=Response(200, json=[]))

        client.list_capabilities(
            kinds=["tool", "skill"],
            provider_ids=("provider.github",),
            binding_ids=["bind_1", "bind_2"],
        )

        params = route.calls[0].request.url.params
        assert params.get_list("kinds") == ["tool", "skill"]
        assert params.get_list("provider_ids") == ["provider.github"]
        assert params.get_list("binding_ids") == ["bind_1", "bind_2"]

    def test_list_capabilities_ignores_empty_filter_lists(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CAPABILITIES).mock(return_value=Response(200, json=[]))

        client.list_capabilities(kinds=[], provider_ids=(), binding_ids=None)

        assert str(route.calls[0].request.url) == _CAPABILITIES

    def test_get_capability_can_request_the_instruction_text(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{_CAPABILITIES}/cap.skill.release_notes").mock(
            return_value=Response(
                200,
                json=make_capability_catalog_entry_payload(
                    capability_id="cap.skill.release_notes",
                    kind="skill",
                    instruction_text="Summarise the changelog.",
                ),
            )
        )

        entry = client.get_capability("cap.skill.release_notes", include_instruction=True)

        assert route.calls[0].request.url.params["include_instruction"] == "1"
        assert entry.instruction_text == "Summarise the changelog."

    def test_list_skills_filters_the_catalog_by_kind(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CAPABILITIES).mock(
            return_value=Response(200, json=[make_capability_catalog_entry_payload(kind="skill")])
        )

        skills = client.list_skills()

        assert route.calls[0].request.url.params.get_list("kinds") == ["skill"]
        assert skills[0].kind == "skill"

    def test_list_mcp_providers_keeps_only_mcp_provider_types(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/capability-providers").mock(
            return_value=Response(
                200,
                json=[
                    make_capability_provider_payload(provider_id="provider.github"),
                    make_capability_provider_payload(
                        provider_id="provider.skill_pack.algenta", provider_type="skill_pack"
                    ),
                ],
            )
        )

        providers = client.list_mcp_providers()

        assert [provider.provider_id for provider in providers] == ["provider.github"]


class TestSkills:
    def test_enable_skill_creates_a_binding_then_discovers_it(
        self, client: AlgentaClient, mock_router
    ) -> None:
        create = mock_router.post(_BINDINGS).mock(
            return_value=Response(
                200, json=make_capability_binding_payload(binding_id="bind_skill")
            )
        )
        discover = mock_router.post(f"{_BINDINGS}/bind_skill/discover").mock(
            return_value=Response(200, json={**_DISCOVER_RESULT, "binding_id": "bind_skill"})
        )

        result = client.enable_skill(
            skill_name="Release Notes",
            instruction="Summarise the changelog into release notes.",
            description="Drafts release notes.",
            tags=["docs"],
            artifact_affinities=["markdown"],
        )

        assert request_json(create) == {
            "provider_id": "provider.skill_pack.algenta",
            "profile_id": "profile.skill_pack.user",
            "binding_name": "Release Notes",
            "scope": "user",
            "execution_owner": "client_managed",
            "config": {
                "manifest": {
                    "capabilities": [
                        {
                            "capability_id": "cap.skill.release_notes",
                            "name": "Release Notes",
                            "description": "Drafts release notes.",
                            "kind": "skill",
                            "implementation_kind": "instruction_only",
                            "execution_owner": "client_managed",
                            "instruction": "Summarise the changelog into release notes.",
                            "artifact_affinities": ["markdown"],
                            "tags": ["docs"],
                            "replayability": "deterministic",
                        }
                    ]
                }
            },
        }
        assert discover.call_count == 1
        assert result.binding_id == "bind_skill"

    def test_enable_skill_defaults_optional_manifest_fields(
        self, client: AlgentaClient, mock_router
    ) -> None:
        create = mock_router.post(_BINDINGS).mock(
            return_value=Response(200, json=make_capability_binding_payload())
        )
        mock_router.post(f"{_BINDINGS}/bind_1/discover").mock(
            return_value=Response(200, json=_DISCOVER_RESULT)
        )

        client.enable_skill(
            skill_name="triage", instruction="Triage.", execution_owner="algenta_managed"
        )

        capability = request_json(create)["config"]["manifest"]["capabilities"][0]
        assert capability["capability_id"] == "cap.skill.triage"
        assert capability["description"] is None
        assert capability["tags"] == []
        assert capability["artifact_affinities"] == []
        assert capability["execution_owner"] == "algenta_managed"
        assert request_json(create)["execution_owner"] == "algenta_managed"

    def test_disable_skill_deletes_the_binding(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.delete(f"{_BINDINGS}/bind_1").mock(return_value=Response(204))

        assert client.disable_skill("bind_1") is None
        assert route.call_count == 1


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_BINDINGS}/missing").mock(
            return_value=error_response(404, message="binding not found")
        )

        with pytest.raises(NotFoundError, match="binding not found"):
            no_retry_client.get_capability_binding("missing")

    def test_server_errors_surface_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{_CAPABILITIES}/route").mock(
            return_value=error_response(500, message="router down")
        )

        with pytest.raises(ServerError, match="router down"):
            no_retry_client.route_capabilities({"intent": "x"})


class TestAsyncComposites:
    @pytest.mark.asyncio
    async def test_filters_and_deletes(self, mock_router) -> None:
        bindings = mock_router.get(_BINDINGS).mock(
            return_value=Response(200, json=[make_capability_binding_payload()])
        )
        capabilities = mock_router.get(_CAPABILITIES).mock(
            return_value=Response(200, json=[make_capability_catalog_entry_payload(kind="skill")])
        )
        entry = mock_router.get(f"{_CAPABILITIES}/cap.github.create_issue").mock(
            return_value=Response(200, json=make_capability_catalog_entry_payload())
        )
        deleted = mock_router.delete(f"{_BINDINGS}/bind_1").mock(return_value=Response(204))

        async with _async_client() as client:
            binding_list = await client.list_capability_bindings(provider_id="provider.github")
            skills = await client.list_skills()
            capability = await client.get_capability(
                "cap.github.create_issue", include_instruction=True
            )
            assert await client.delete_capability_binding("bind_1") is None
            assert await client.disable_skill("bind_1") is None

        assert bindings.calls[0].request.url.params["provider_id"] == "provider.github"
        assert binding_list[0].binding_id == "bind_1"
        assert capabilities.calls[0].request.url.params.get_list("kinds") == ["skill"]
        assert skills[0].kind == "skill"
        assert entry.calls[0].request.url.params["include_instruction"] == "1"
        assert capability.capability_id == "cap.github.create_issue"
        assert deleted.call_count == 2

    @pytest.mark.asyncio
    async def test_list_capabilities_repeats_each_filter_key(self, mock_router) -> None:
        route = mock_router.get(_CAPABILITIES).mock(return_value=Response(200, json=[]))

        async with _async_client() as client:
            await client.list_capabilities(kinds=("tool",), binding_ids=["bind_1", "bind_2"])

        params = route.calls[0].request.url.params
        assert params.get_list("kinds") == ["tool"]
        assert params.get_list("binding_ids") == ["bind_1", "bind_2"]

    @pytest.mark.asyncio
    async def test_enable_skill_and_list_mcp_providers(self, mock_router) -> None:
        create = mock_router.post(_BINDINGS).mock(
            return_value=Response(200, json=make_capability_binding_payload())
        )
        mock_router.post(f"{_BINDINGS}/bind_1/discover").mock(
            return_value=Response(200, json=_DISCOVER_RESULT)
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/capability-providers").mock(
            return_value=Response(
                200,
                json=[
                    make_capability_provider_payload(provider_id="provider.github"),
                    make_capability_provider_payload(
                        provider_id="provider.pack", provider_type="skill_pack"
                    ),
                ],
            )
        )

        async with _async_client() as client:
            discovered = await client.enable_skill(skill_name="Triage Bugs", instruction="Triage.")
            providers = await client.list_mcp_providers()

        capability = request_json(create)["config"]["manifest"]["capabilities"][0]
        assert capability["capability_id"] == "cap.skill.triage_bugs"
        assert discovered.capability_count == 1
        assert [provider.provider_id for provider in providers] == ["provider.github"]

    @pytest.mark.asyncio
    async def test_server_errors_surface_as_the_typed_error(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/capability-providers").mock(
            return_value=error_response(502, message="upstream")
        )

        async with _async_client() as client:
            with pytest.raises(ServerError, match="upstream"):
                await client.list_capability_providers()

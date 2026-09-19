"""Round-trip tests for the capability-plane result models.

Every class in ``decision_engine.models_capability_plane`` is a permissive
(``extra="allow"``) pydantic model. These tests pin the required-field set,
the defaults, the datetime coercion, and that unknown server fields survive a
``model_dump()`` round trip instead of being dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_capability_plane import (
    CapabilityAuthorizationCompleteResult,
    CapabilityAuthorizationStartResult,
    CapabilityBindingResult,
    CapabilityBindingTestResult,
    CapabilityCatalogEntryResult,
    CapabilityDiscoverResult,
    CapabilityExecutionResult,
    CapabilityOutcomeRecordResult,
    CapabilityProviderProfileResult,
    CapabilityProviderResult,
    CapabilityRouteFallbackResult,
    CapabilityRoutePlanResult,
)

from .conftest import (
    make_capability_binding_payload,
    make_capability_catalog_entry_payload,
    make_capability_profile_payload,
    make_capability_provider_payload,
    make_capability_route_fallback_payload,
)

_TS = "2026-01-01T00:00:00Z"
_TS_DT = datetime(2026, 1, 1, tzinfo=UTC)


class TestProviderModels:
    def test_profile_parses_required_fields_and_defaults(self) -> None:
        profile = CapabilityProviderProfileResult.model_validate(make_capability_profile_payload())

        assert profile.profile_id == "profile.github.user"
        assert profile.supported_binding_scopes == ["user", "org"]
        assert profile.description is None
        assert profile.profile_metadata is None

    def test_provider_nests_profiles_and_optional_summaries(self) -> None:
        provider = CapabilityProviderResult.model_validate(
            make_capability_provider_payload(
                docs_url="https://docs.example.com/github",
                auth_schema={"type": "oauth2", "scopes": ["repo"]},
                certification_summary={"level": "gold"},
                supported_execution_owners=["algenta_managed", "client_managed"],
            )
        )

        assert provider.active is True
        assert provider.profiles[0].provider_id == provider.provider_id
        assert provider.auth_schema == {"type": "oauth2", "scopes": ["repo"]}
        assert provider.supported_execution_owners == ["algenta_managed", "client_managed"]
        assert provider.install_metadata is None

    def test_provider_defaults_profiles_to_an_empty_list(self) -> None:
        payload = make_capability_provider_payload()
        del payload["profiles"]

        provider = CapabilityProviderResult.model_validate(payload)

        assert provider.profiles == []

    def test_provider_requires_the_active_flag(self) -> None:
        payload = make_capability_provider_payload()
        del payload["active"]

        with pytest.raises(PydanticValidationError) as exc_info:
            CapabilityProviderResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("active",)


class TestBindingModels:
    def test_binding_coerces_timestamps_and_keeps_optional_fields_none(self) -> None:
        binding = CapabilityBindingResult.model_validate(make_capability_binding_payload())

        assert binding.created_at == _TS_DT
        assert binding.updated_at == _TS_DT
        assert binding.last_tested_at is None
        assert binding.quarantine_reason is None
        assert binding.config is None

    def test_binding_parses_every_optional_timestamp(self) -> None:
        binding = CapabilityBindingResult.model_validate(
            make_capability_binding_payload(
                last_tested_at=_TS,
                last_discovered_at=_TS,
                authorized_at=_TS,
                quarantine_reason="token revoked",
                discovery_error_message="discovery failed",
                test_error_message="401 from provider",
                config={"repo": "thyn-ai/algenta-sdk"},
            )
        )

        assert binding.last_tested_at == _TS_DT
        assert binding.last_discovered_at == _TS_DT
        assert binding.authorized_at == _TS_DT
        assert binding.quarantine_reason == "token revoked"
        assert binding.config == {"repo": "thyn-ai/algenta-sdk"}

    def test_binding_rejects_a_non_datetime_created_at(self) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityBindingResult.model_validate(
                make_capability_binding_payload(created_at="yesterday")
            )

    def test_binding_test_result_defaults_details_to_an_empty_dict(self) -> None:
        result = CapabilityBindingTestResult.model_validate(
            {"success": True, "binding_status": "active", "message": "ok"}
        )

        assert result.latency_ms is None
        assert result.details == {}

    def test_binding_test_result_keeps_latency_and_details(self) -> None:
        result = CapabilityBindingTestResult.model_validate(
            {
                "success": False,
                "binding_status": "quarantined",
                "message": "provider returned 503",
                "latency_ms": 812,
                "details": {"status_code": 503},
            }
        )

        assert result.success is False
        assert result.latency_ms == 812
        assert result.details == {"status_code": 503}


class TestCatalogAndDiscoveryModels:
    def test_catalog_entry_defaults_lists_and_optional_refs(self) -> None:
        entry = CapabilityCatalogEntryResult.model_validate(make_capability_catalog_entry_payload())

        assert entry.approval_required is True
        assert entry.artifact_affinities == []
        assert entry.tags == []
        assert entry.required_binding_ids == []
        assert entry.selected_tool_name is None
        assert entry.instruction_text is None
        assert entry.discovered_at is None

    def test_catalog_entry_parses_instruction_and_discovery_fields(self) -> None:
        entry = CapabilityCatalogEntryResult.model_validate(
            make_capability_catalog_entry_payload(
                kind="skill",
                tags=["docs", "release"],
                artifact_affinities=["markdown"],
                required_binding_ids=["bind_1", "bind_2"],
                selected_tool_name="create_issue",
                instruction_artifact_ref="artifacts/skill.md",
                instruction_text="Open an issue summarising the release.",
                discovered_at=_TS,
            )
        )

        assert entry.kind == "skill"
        assert entry.tags == ["docs", "release"]
        assert entry.required_binding_ids == ["bind_1", "bind_2"]
        assert entry.instruction_text == "Open an issue summarising the release."
        assert entry.discovered_at == _TS_DT

    def test_discover_result_nests_catalog_entries(self) -> None:
        result = CapabilityDiscoverResult.model_validate(
            {
                "binding_id": "bind_1",
                "provider_id": "provider.github",
                "profile_id": "profile.github.user",
                "snapshot_id": "snap_1",
                "binding_status": "active",
                "manifest_hash": "m" * 64,
                "capability_count": 1,
                "discovered_at": _TS,
                "message": "Discovered 1 capability.",
                "capabilities": [make_capability_catalog_entry_payload()],
            }
        )

        assert result.capability_count == 1
        assert result.capabilities[0].capability_id == "cap.github.create_issue"
        assert result.discovered_at == _TS_DT

    def test_discover_result_allows_a_preview_without_binding_or_snapshot(self) -> None:
        result = CapabilityDiscoverResult.model_validate(
            {
                "provider_id": "provider.github",
                "profile_id": "profile.github.user",
                "binding_status": "preview",
                "manifest_hash": "m" * 64,
                "capability_count": 0,
                "discovered_at": _TS,
                "message": "Preview discovery.",
            }
        )

        assert result.binding_id is None
        assert result.snapshot_id is None
        assert result.capabilities == []


class TestRoutingAndExecutionModels:
    def test_route_plan_nests_fallbacks(self) -> None:
        plan = CapabilityRoutePlanResult.model_validate(
            {
                "selected_capability_id": "cap.github.create_issue",
                "selected_provider_id": "provider.github",
                "selected_binding_id": "bind_1",
                "kind": "tool",
                "execution_owner": "algenta_managed",
                "requires_approval": True,
                "confidence": 0.93,
                "reason": "Exact tool-name match.",
                "fallbacks": [make_capability_route_fallback_payload()],
                "policy_snapshot_id": "pol_1",
                "selected_tool_name": "create_issue",
            }
        )

        assert plan.requires_approval is True
        assert plan.confidence == pytest.approx(0.93)
        assert plan.fallbacks[0].confidence == pytest.approx(0.42)
        assert plan.fallbacks[0].selected_tool_name is None
        assert plan.instruction_artifact_ref is None

    def test_route_fallback_parses_on_its_own(self) -> None:
        fallback = CapabilityRouteFallbackResult.model_validate(
            make_capability_route_fallback_payload(instruction_artifact_ref="artifacts/skill.md")
        )

        assert fallback.reason == "Same side-effect class, lower trust tier."
        assert fallback.instruction_artifact_ref == "artifacts/skill.md"

    def test_execution_result_tracks_an_in_flight_session(self) -> None:
        execution = CapabilityExecutionResult.model_validate(
            {
                "execution_session_id": "exec_1",
                "capability_id": "cap.github.create_issue",
                "provider_id": "provider.github",
                "binding_id": "bind_1",
                "execution_owner": "algenta_managed",
                "status": "running",
                "started_at": _TS,
            }
        )

        assert execution.status == "running"
        assert execution.started_at == _TS_DT
        assert execution.completed_at is None
        assert execution.output is None
        assert execution.error is None

    def test_execution_result_parses_output_error_and_completion(self) -> None:
        execution = CapabilityExecutionResult.model_validate(
            {
                "execution_session_id": "exec_1",
                "capability_id": "cap.github.create_issue",
                "provider_id": "provider.github",
                "binding_id": "bind_1",
                "execution_owner": "algenta_managed",
                "status": "failed",
                "output": {"issue_url": None},
                "error": {"code": "provider_timeout"},
                "started_at": _TS,
                "completed_at": _TS,
            }
        )

        assert execution.error == {"code": "provider_timeout"}
        assert execution.completed_at == _TS_DT

    def test_outcome_record_defaults_every_optional_field(self) -> None:
        outcome = CapabilityOutcomeRecordResult.model_validate(
            {
                "outcome_id": "out_1",
                "capability_id": "cap.github.create_issue",
                "provider_id": "provider.github",
                "result_status": "unknown",
                "created_at": _TS,
            }
        )

        assert outcome.binding_id is None
        assert outcome.success is None
        assert outcome.confidence is None
        assert outcome.latency_ms is None
        assert outcome.error_code is None
        assert outcome.details is None

    def test_outcome_record_parses_a_full_record(self) -> None:
        outcome = CapabilityOutcomeRecordResult.model_validate(
            {
                "outcome_id": "out_1",
                "capability_id": "cap.github.create_issue",
                "provider_id": "provider.github",
                "binding_id": "bind_1",
                "success": False,
                "result_status": "error",
                "confidence": 0.1,
                "latency_ms": 900,
                "error_code": "provider_timeout",
                "details": {"attempts": 3},
                "created_at": _TS,
            }
        )

        assert outcome.success is False
        assert outcome.error_code == "provider_timeout"
        assert outcome.details == {"attempts": 3}


class TestAuthorizationModels:
    def test_authorization_start_parses_the_redirect(self) -> None:
        start = CapabilityAuthorizationStartResult.model_validate(
            {
                "session_id": "auth_1",
                "binding_id": "bind_1",
                "provider_id": "provider.github",
                "authorize_url": "https://github.com/login/oauth/authorize?state=abc",
                "expires_at": _TS,
                "requested_scopes": ["repo", "read:org"],
            }
        )

        assert start.authorize_url.startswith("https://github.com/")
        assert start.expires_at == _TS_DT
        assert start.requested_scopes == ["repo", "read:org"]

    def test_authorization_start_defaults_scopes_to_an_empty_list(self) -> None:
        start = CapabilityAuthorizationStartResult.model_validate(
            {
                "session_id": "auth_1",
                "binding_id": "bind_1",
                "provider_id": "provider.github",
                "authorize_url": "https://example.com/authorize",
                "expires_at": _TS,
            }
        )

        assert start.requested_scopes == []

    def test_authorization_complete_parses_pending_and_authorized_states(self) -> None:
        pending = CapabilityAuthorizationCompleteResult.model_validate(
            {
                "session_id": "auth_1",
                "binding_id": "bind_1",
                "provider_id": "provider.github",
                "status": "pending",
            }
        )
        authorized = CapabilityAuthorizationCompleteResult.model_validate(
            {
                "session_id": "auth_1",
                "binding_id": "bind_1",
                "provider_id": "provider.github",
                "status": "authorized",
                "authorized_at": _TS,
            }
        )

        assert pending.authorized_at is None
        assert authorized.authorized_at == _TS_DT


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (CapabilityProviderProfileResult, make_capability_profile_payload()),
        (CapabilityProviderResult, make_capability_provider_payload()),
        (CapabilityBindingResult, make_capability_binding_payload()),
        (CapabilityCatalogEntryResult, make_capability_catalog_entry_payload()),
        (CapabilityRouteFallbackResult, make_capability_route_fallback_payload()),
    ],
)
def test_unknown_server_fields_survive_a_round_trip(model: type, payload: dict[str, Any]) -> None:
    """The API may add fields before the SDK learns about them; none may be dropped."""
    enriched = {**payload, "future_field": {"nested": [1, 2, 3]}}

    parsed = model.model_validate(enriched)
    dumped = parsed.model_dump(mode="json")

    assert dumped["future_field"] == {"nested": [1, 2, 3]}
    assert model.model_validate(dumped) == parsed

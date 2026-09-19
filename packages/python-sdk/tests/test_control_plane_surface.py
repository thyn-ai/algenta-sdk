"""Tests for the control-plane surface: team, billing, credits, metering, devices.

Every method is exercised through the public facade against an intercepted
transport. The request-shaping rules (pagination coercion, role/email/plan
validation, metering-event normalisation, billing-period parsing) are all
client-side and raise before any HTTP call, so those tests declare no routes.
The async facade shares the validators with the sync one and is exercised for
each endpoint once.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import NotFoundError, ServerError

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_TS = "2026-01-01T00:00:00Z"

_MEMBER = {
    "user_id": "user_1",
    "name": "Ada",
    "email": "ada@example.com",
    "role": "admin",
    "status": "active",
    "last_active": _TS,
}

_BILLING_INFO = {
    "plan": "pro",
    "stripe_customer_id": "cus_123",
    "subscription_status": "active",
    "current_period_end": _TS,
}

_CREDIT_REFRESH = {
    "credits_granted": 100,
    "credits_issued_this_month": 300,
    "monthly_limit": 1000,
    "monthly_remaining": 700,
    "billing_period": "2026-09",
    "expires_at": 1_790_000_000.0,
    "refresh_after": 1_789_990_000.0,
    "server_time": 1_789_980_000.0,
}

_DEVICE = {
    "id": "reg_1",
    "device_id": "0123456789abcdef0123456789abcdef",
    "platform": "Darwin",
    "status": "active",
    "heartbeat_count": 4,
    "registered_at": _TS,
}

_DEVICE_LIST = {
    "devices": [_DEVICE],
    "device_count": 1,
    "total": 1,
    "page": 1,
    "limit": 25,
    "pages": 1,
    "device_limit": 5,
    "plan": "pro",
}

_POLICY = {
    "org_id": "org_1",
    "min_confidence": 0.7,
    "require_calibration": True,
    "allow_reexecution": False,
    "snapshot_id": "pol_2",
    "revision": 2,
    "previous_snapshot_id": "pol_1",
    "updated_at": _TS,
}

_AUDIT_PAGE = {"entries": [], "total": 0, "page": 1, "limit": 25, "pages": 0}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestTeam:
    def test_list_team_members_without_pagination_sends_no_params(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(
            return_value=Response(
                200, json={"members": [_MEMBER], "total": 1, "page": 1, "limit": 25, "pages": 1}
            )
        )

        result = client.list_team_members()

        assert str(route.calls[0].request.url) == f"{TEST_BASE_URL}/v1/team"
        assert result.members[0].email == "ada@example.com"
        assert result.members[0].role == "admin"

    def test_list_team_members_sends_pagination(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(
            return_value=Response(
                200, json={"members": [], "total": 0, "page": 2, "limit": 10, "pages": 0}
            )
        )

        client.list_team_members(page=2, limit=10)

        params = route.calls[0].request.url.params
        assert params["page"] == "2" and params["limit"] == "10"

    def test_list_team_members_wraps_a_bare_list_in_a_page(
        self, client: AlgentaClient, mock_router
    ) -> None:
        """Older servers return the member list directly; it is normalised to one page."""
        mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(
            return_value=Response(200, json=[_MEMBER, {**_MEMBER, "user_id": "user_2"}])
        )

        result = client.list_team_members()

        assert result.total == 2
        assert (result.page, result.limit, result.pages) == (1, 2, 1)

    def test_list_team_members_rejects_a_scalar_body(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(return_value=Response(200, json="nope"))

        with pytest.raises(TypeError, match="Team response must be a list or JSON object"):
            client.list_team_members()

    @pytest.mark.parametrize("bad", [0, -1, True, "2", 1.5])
    def test_pagination_must_be_positive_integers(self, client: AlgentaClient, bad: Any) -> None:
        with pytest.raises(ValueError, match="page must be an integer"):
            client.list_team_members(page=bad)
        with pytest.raises(ValueError, match="limit must be an integer"):
            client.list_team_members(limit=bad)

    def test_invite_normalises_email_and_role(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/team/invite").mock(
            return_value=Response(200, json={"message": "Invite sent", "invite_id": "inv_1"})
        )

        result = client.invite_team_member(email="  bob@example.com ", role=" viewer ")

        assert request_json(route) == {"email": "bob@example.com", "role": "viewer"}
        assert result.invite_id == "inv_1"

    def test_invite_defaults_to_the_member_role(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/team/invite").mock(
            return_value=Response(200, json={"message": "ok", "invite_id": "inv_1"})
        )

        client.invite_team_member(email="bob@example.com")

        assert request_json(route)["role"] == "member"

    @pytest.mark.parametrize(
        ("email", "message"),
        [("", "email must be a non-empty string"), ("   ", "email must be a non-empty string")],
    )
    def test_invite_rejects_blank_emails(
        self, client: AlgentaClient, email: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            client.invite_team_member(email=email)

    def test_invite_rejects_an_email_without_an_at_sign(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="email must contain '@'"):
            client.invite_team_member(email="bob.example.com")

    @pytest.mark.parametrize("role", ["", "  ", "root"])
    def test_roles_are_restricted_to_the_documented_set(
        self, client: AlgentaClient, role: str
    ) -> None:
        with pytest.raises(ValueError, match="role must be"):
            client.invite_team_member(email="bob@example.com", role=role)

    def test_update_role_patches_the_member(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.patch(f"{TEST_BASE_URL}/v1/team/user_1/role").mock(
            return_value=Response(200, json={"message": "Role updated", "user_id": "user_1"})
        )

        result = client.update_team_member_role(" user_1 ", role="owner")

        assert request_json(route) == {"role": "owner"}
        assert result.user_id == "user_1"

    def test_update_role_requires_a_user_id(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="user_id must be a non-empty string"):
            client.update_team_member_role("  ", role="owner")

    def test_remove_member_merges_the_server_body_over_the_defaults(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.delete(f"{TEST_BASE_URL}/v1/team/user_1").mock(
            return_value=Response(200, json={"removed": True, "reassigned_to": "user_9"})
        )

        result = client.remove_team_member("user_1")

        assert route.calls[0].request.method == "DELETE"
        assert result.removed is True
        assert result.user_id == "user_1"
        assert result.model_dump()["reassigned_to"] == "user_9"

    def test_remove_member_defaults_removed_when_the_body_is_empty(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.delete(f"{TEST_BASE_URL}/v1/team/user_1").mock(
            return_value=Response(200, json={})
        )

        assert client.remove_team_member("user_1").removed is True

    def test_remove_member_rejects_a_non_object_body(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.delete(f"{TEST_BASE_URL}/v1/team/user_1").mock(
            return_value=Response(200, json=["removed"])
        )

        with pytest.raises(TypeError, match="Team remove response must be a JSON object"):
            client.remove_team_member("user_1")


class TestBilling:
    def test_get_billing_info(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/billing/info").mock(
            return_value=Response(200, json=_BILLING_INFO)
        )

        result = client.get_billing_info()

        assert result.plan == "pro"
        assert result.stripe_customer_id == "cus_123"
        assert result.current_period_end is not None

    def test_checkout_without_a_plan_posts_an_empty_object(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/billing/checkout").mock(
            return_value=Response(200, json={"url": "https://checkout.example.com/s/1"})
        )

        result = client.create_billing_checkout()

        assert request_json(route) == {}
        assert result.url == "https://checkout.example.com/s/1"

    def test_checkout_normalises_the_plan(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/billing/checkout").mock(
            return_value=Response(200, json={"url": "https://checkout.example.com/s/2"})
        )

        client.create_billing_checkout(plan=" developer ")

        assert request_json(route) == {"plan": "developer"}

    @pytest.mark.parametrize(
        ("plan", "message"),
        [("", "plan must be a non-empty string"), ("enterprise", "plan must be one of")],
    )
    def test_checkout_rejects_unknown_plans(
        self, client: AlgentaClient, plan: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            client.create_billing_checkout(plan=plan)

    def test_portal_posts_an_empty_object(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/billing/portal").mock(
            return_value=Response(200, json={"url": "https://billing.example.com/portal"})
        )

        result = client.create_billing_portal()

        assert request_json(route) == {}
        assert result.url.endswith("/portal")


class TestCredits:
    def test_refresh_credits_posts_the_normalised_request(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/credits/refresh").mock(
            return_value=Response(200, json=_CREDIT_REFRESH)
        )

        result = client.refresh_credits(
            device_id=" dev_1 ", billing_period="2026-09", credits_used=12
        )

        assert request_json(route) == {
            "device_id": "dev_1",
            "billing_period": "2026-09",
            "credits_used": 12,
        }
        assert result.monthly_remaining == 700
        assert result.server_time == pytest.approx(1_789_980_000.0)

    def test_refresh_credits_defaults_credits_used_to_zero(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/credits/refresh").mock(
            return_value=Response(200, json=_CREDIT_REFRESH)
        )

        client.refresh_credits(device_id="dev_1", billing_period="2026-01")

        assert request_json(route)["credits_used"] == 0

    @pytest.mark.parametrize(
        ("kwargs", "error", "message"),
        [
            ({"device_id": " "}, ValueError, "device_id must be a non-empty string"),
            ({"billing_period": "2026-9"}, ValueError, "billing_period must be a YYYY-MM string"),
            ({"billing_period": "2026/09"}, ValueError, "billing_period must be a YYYY-MM string"),
            ({"billing_period": "20x6-09"}, ValueError, "billing_period must be a YYYY-MM string"),
            ({"billing_period": "2026-13"}, ValueError, "month must be between 01 and 12"),
            ({"billing_period": "2026-00"}, ValueError, "month must be between 01 and 12"),
            ({"credits_used": True}, TypeError, "credits_used must be a non-negative integer"),
            ({"credits_used": 1.5}, TypeError, "credits_used must be a non-negative integer"),
            ({"credits_used": -1}, ValueError, "credits_used must be a non-negative integer"),
        ],
    )
    def test_refresh_credits_validates_its_inputs(
        self, client: AlgentaClient, kwargs: dict[str, Any], error: type, message: str
    ) -> None:
        arguments: dict[str, Any] = {"device_id": "dev_1", "billing_period": "2026-09"}
        arguments.update(kwargs)

        with pytest.raises(error, match=message):
            client.refresh_credits(**arguments)


class TestMetering:
    def test_ingest_normalises_every_supported_field(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/metering").mock(
            return_value=Response(200, json={"accepted": 1, "billing_period": "2026-09"})
        )

        result = client.ingest_metering_events(
            device_id=" dev_1 ",
            events=[
                {
                    "event_type": " runtime.call ",
                    "module": "embeddings",
                    "function": "embed",
                    "engine_used": "mojo",
                    "request_id": "req_1",
                    "latency_ms": 12,
                    "timestamp": 1_789_980_000,
                    "success": True,
                }
            ],
        )

        assert request_json(route) == {
            "device_id": "dev_1",
            "events": [
                {
                    "event_type": "runtime.call",
                    "module": "embeddings",
                    "function": "embed",
                    "engine_used": "mojo",
                    "request_id": "req_1",
                    "latency_ms": 12.0,
                    "timestamp": 1_789_980_000.0,
                    "success": True,
                }
            ],
        }
        assert result.accepted == 1

    def test_ingest_keeps_only_the_fields_each_event_provides(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/metering").mock(
            return_value=Response(200, json={"accepted": 2, "billing_period": "2026-09"})
        )

        client.ingest_metering_events(
            device_id="dev_1",
            events=[{"event_type": "a"}, {"success": False, "latency_ms": 3.5}],
        )

        assert request_json(route)["events"] == [
            {"event_type": "a"},
            {"success": False, "latency_ms": 3.5},
        ]

    @pytest.mark.parametrize(
        ("kwargs", "error", "message"),
        [
            ({"device_id": ""}, ValueError, "device_id must be a non-empty string"),
            ({"events": []}, ValueError, "events must be a non-empty list"),
            ({"events": "not-a-list"}, ValueError, "events must be a non-empty list"),
            ({"events": ["x"]}, TypeError, r"events\[0\] must be a JSON object"),
            (
                {"events": [{"event_type": "a", "colour": "red", "size": 1}]},
                ValueError,
                r"events\[0\] contains unsupported fields: colour, size",
            ),
            ({"events": [{"module": 7}]}, TypeError, r"events\[0\].module must be a string"),
            (
                {"events": [{"latency_ms": "9"}]},
                TypeError,
                r"events\[0\].latency_ms must be a number",
            ),
            (
                {"events": [{"latency_ms": True}]},
                TypeError,
                r"events\[0\].latency_ms must be a number",
            ),
            (
                {"events": [{"timestamp": "now"}]},
                TypeError,
                r"events\[0\].timestamp must be a number",
            ),
            ({"events": [{"success": 1}]}, TypeError, r"events\[0\].success must be a boolean"),
        ],
    )
    def test_ingest_validates_its_inputs(
        self, client: AlgentaClient, kwargs: dict[str, Any], error: type, message: str
    ) -> None:
        arguments: dict[str, Any] = {"device_id": "dev_1", "events": [{"event_type": "a"}]}
        arguments.update(kwargs)

        with pytest.raises(error, match=message):
            client.ingest_metering_events(**arguments)


class TestAuditArtifacts:
    def test_get_audit_log_artifacts_sends_every_filter(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs/artifacts").mock(
            return_value=Response(200, json=_AUDIT_PAGE)
        )

        result = client.get_audit_log_artifacts(
            page=3,
            limit=5,
            actor_email="ada@example.com",
            action="decision.execute",
            resource_type="decision",
            result="success",
            policy_snapshot_id="pol_1",
            schema_snapshot_id="sch_1",
            manifest_version="1.0.0",
            request_hash="rh_1",
            content_hash=" ch_1 ",
        )

        params = route.calls[0].request.url.params
        assert params["page"] == "3" and params["limit"] == "5"
        assert params["content_hash"] == "ch_1"
        assert params["manifest_version"] == "1.0.0"
        assert result.total == 0

    def test_get_audit_log_artifacts_omits_unset_filters(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs/artifacts").mock(
            return_value=Response(200, json=_AUDIT_PAGE)
        )

        client.get_audit_log_artifacts()

        assert dict(route.calls[0].request.url.params) == {"page": "1", "limit": "25"}

    def test_get_audit_log_artifacts_rejects_blank_filters(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="content_hash must be a non-empty string"):
            client.get_audit_log_artifacts(content_hash="  ")

    def test_get_audit_logs_rejects_non_string_filters(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="request_hash must be a non-empty string"):
            client.get_audit_logs(request_hash=123)


class TestExecutionPolicySnapshots:
    def test_list_snapshots(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/execution/policy/snapshots").mock(
            return_value=Response(
                200,
                json={
                    "org_id": "org_1",
                    "data": [_POLICY, {**_POLICY, "snapshot_id": "pol_1", "revision": 1}],
                    "total_snapshots": 2,
                },
            )
        )

        result = client.list_execution_policy_snapshots()

        assert result.total_snapshots == 2
        assert [snapshot.revision for snapshot in result.data] == [2, 1]
        assert result.data[0].previous_snapshot_id == "pol_1"


class TestDevices:
    def test_list_devices_without_pagination(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/device/list").mock(
            return_value=Response(200, json=_DEVICE_LIST)
        )

        result = client.list_devices()

        assert str(route.calls[0].request.url) == f"{TEST_BASE_URL}/v1/device/list"
        assert result.device_limit == 5
        assert result.devices[0].platform == "Darwin"
        assert result.devices[0].heartbeat_count == 4

    def test_list_devices_with_pagination(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(f"{TEST_BASE_URL}/v1/device/list").mock(
            return_value=Response(200, json=_DEVICE_LIST)
        )

        client.list_devices(page=2, limit=1)

        params = route.calls[0].request.url.params
        assert params["page"] == "2" and params["limit"] == "1"

    def test_revoke_device_deletes_the_registration(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.delete(f"{TEST_BASE_URL}/v1/device/reg_1").mock(
            return_value=Response(200, json={"revoked": True, "registration_id": "reg_1"})
        )

        result = client.revoke_device("reg_1")

        assert route.calls[0].request.method == "DELETE"
        assert result.revoked is True

    def test_revoke_device_requires_a_registration_id(self, client: AlgentaClient) -> None:
        with pytest.raises(ValueError, match="registration_id must be a non-empty string"):
            client.revoke_device("")


class TestErrorPaths:
    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/billing/info").mock(
            return_value=error_response(404, message="no billing account")
        )

        with pytest.raises(NotFoundError, match="no billing account"):
            no_retry_client.get_billing_info()

    def test_server_errors_surface_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/device/list").mock(
            return_value=error_response(503, message="try later", request_id="req_9")
        )

        with pytest.raises(ServerError) as exc_info:
            no_retry_client.list_devices()

        assert exc_info.value.status_code == 503
        assert exc_info.value.request_id == "req_9"


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_team_endpoints(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(return_value=Response(200, json=[_MEMBER]))
        invite = mock_router.post(f"{TEST_BASE_URL}/v1/team/invite").mock(
            return_value=Response(200, json={"message": "ok", "invite_id": "inv_1"})
        )
        role = mock_router.patch(f"{TEST_BASE_URL}/v1/team/user_1/role").mock(
            return_value=Response(200, json={"message": "ok", "user_id": "user_1"})
        )
        mock_router.delete(f"{TEST_BASE_URL}/v1/team/user_1").mock(
            return_value=Response(200, json={})
        )

        async with _async_client() as client:
            members = await client.list_team_members(page=1, limit=50)
            invited = await client.invite_team_member(email="bob@example.com", role="viewer")
            updated = await client.update_team_member_role("user_1", role="admin")
            removed = await client.remove_team_member("user_1")

        assert members.total == 1 and members.members[0].user_id == "user_1"
        assert request_json(invite) == {"email": "bob@example.com", "role": "viewer"}
        assert request_json(role) == {"role": "admin"}
        assert invited.invite_id == "inv_1" and updated.user_id == "user_1"
        assert removed.removed is True and removed.user_id == "user_1"

    @pytest.mark.asyncio
    async def test_remove_member_rejects_a_non_object_body(self, mock_router) -> None:
        mock_router.delete(f"{TEST_BASE_URL}/v1/team/user_1").mock(
            return_value=Response(200, json=[])
        )

        async with _async_client() as client:
            with pytest.raises(TypeError, match="Team remove response must be a JSON object"):
                await client.remove_team_member("user_1")

    @pytest.mark.asyncio
    async def test_billing_and_credit_endpoints(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/billing/info").mock(
            return_value=Response(200, json=_BILLING_INFO)
        )
        checkout = mock_router.post(f"{TEST_BASE_URL}/v1/billing/checkout").mock(
            return_value=Response(200, json={"url": "https://checkout.example.com"})
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/billing/portal").mock(
            return_value=Response(200, json={"url": "https://portal.example.com"})
        )
        refresh = mock_router.post(f"{TEST_BASE_URL}/v1/credits/refresh").mock(
            return_value=Response(200, json=_CREDIT_REFRESH)
        )
        metering = mock_router.post(f"{TEST_BASE_URL}/v1/metering").mock(
            return_value=Response(200, json={"accepted": 1, "billing_period": "2026-09"})
        )

        async with _async_client() as client:
            info = await client.get_billing_info()
            session = await client.create_billing_checkout(plan="pro")
            portal = await client.create_billing_portal()
            credits = await client.refresh_credits(device_id="dev_1", billing_period="2026-09")
            batch = await client.ingest_metering_events(
                device_id="dev_1", events=[{"event_type": "call", "success": True}]
            )

        assert info.plan == "pro"
        assert request_json(checkout) == {"plan": "pro"}
        assert session.url == "https://checkout.example.com"
        assert portal.url == "https://portal.example.com"
        assert request_json(refresh)["credits_used"] == 0
        assert credits.credits_granted == 100
        assert request_json(metering)["events"] == [{"event_type": "call", "success": True}]
        assert batch.accepted == 1

    @pytest.mark.asyncio
    async def test_governance_and_device_endpoints(self, mock_router) -> None:
        audit = mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs").mock(
            return_value=Response(200, json=_AUDIT_PAGE)
        )
        artifacts = mock_router.get(f"{TEST_BASE_URL}/v1/audit-logs/artifacts").mock(
            return_value=Response(200, json=_AUDIT_PAGE)
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/execution/policy").mock(
            return_value=Response(200, json=_POLICY)
        )
        mock_router.get(f"{TEST_BASE_URL}/v1/execution/policy/snapshots").mock(
            return_value=Response(
                200, json={"org_id": "org_1", "data": [_POLICY], "total_snapshots": 1}
            )
        )
        patch = mock_router.patch(f"{TEST_BASE_URL}/v1/execution/policy").mock(
            return_value=Response(200, json=_POLICY)
        )
        devices = mock_router.get(f"{TEST_BASE_URL}/v1/device/list").mock(
            return_value=Response(200, json=_DEVICE_LIST)
        )
        mock_router.delete(f"{TEST_BASE_URL}/v1/device/reg_1").mock(
            return_value=Response(200, json={"revoked": True, "registration_id": "reg_1"})
        )

        async with _async_client() as client:
            logs = await client.get_audit_logs(action="decision.execute")
            artifact_logs = await client.get_audit_log_artifacts(content_hash="ch_1")
            policy = await client.get_execution_policy()
            snapshots = await client.list_execution_policy_snapshots()
            updated = await client.update_execution_policy(risk_floor=0.2)
            device_page = await client.list_devices(page=1, limit=25)
            revoked = await client.revoke_device("reg_1")

        assert audit.calls[0].request.url.params["action"] == "decision.execute"
        assert artifacts.calls[0].request.url.params["content_hash"] == "ch_1"
        assert logs.total == 0 and artifact_logs.total == 0
        assert policy.snapshot_id == "pol_2"
        assert snapshots.total_snapshots == 1
        assert request_json(patch) == {"risk_floor": 0.2}
        assert updated.org_id == "org_1"
        assert devices.calls[0].request.url.params["limit"] == "25"
        assert device_page.device_count == 1
        assert revoked.registration_id == "reg_1"

    @pytest.mark.asyncio
    async def test_validation_happens_before_any_request(self) -> None:
        async with _async_client() as client:
            with pytest.raises(ValueError, match="role must be one of"):
                await client.invite_team_member(email="bob@example.com", role="root")
            with pytest.raises(ValueError, match="registration_id must be a non-empty string"):
                await client.revoke_device(" ")
            with pytest.raises(ValueError, match="at least one policy field"):
                await client.update_execution_policy()

    @pytest.mark.asyncio
    async def test_server_errors_surface_as_the_typed_error(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/team").mock(
            return_value=error_response(500, message="boom")
        )

        async with _async_client() as client:
            with pytest.raises(ServerError, match="boom"):
                await client.list_team_members()

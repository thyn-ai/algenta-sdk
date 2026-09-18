"""Tests for the account surface: usage and plan limits."""

from __future__ import annotations

import uuid

import pytest
from httpx import Response

from decision_engine import AlgentaClient

from .conftest import TEST_BASE_URL


def test_usage_gets_the_usage_summary(client: AlgentaClient, mock_router) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/usage").mock(
        return_value=Response(
            200,
            json={
                "org_id": "3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b",
                "billing_period": "2026-09",
                "simulations_run": 12,
                "api_calls": 340,
                "quota_limit": 1000,
                "quota_used_pct": 34.0,
            },
        )
    )

    result = client.usage()

    assert route.calls[0].request.method == "GET"
    assert result.org_id == uuid.UUID("3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b")
    assert result.quota_used_pct == pytest.approx(34.0)


def test_limits_returns_the_raw_limits_payload(client: AlgentaClient, mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/limits").mock(
        return_value=Response(
            200,
            json={"requests_per_minute": 600, "simulations_per_month": 5000},
        )
    )

    assert client.limits() == {"requests_per_minute": 600, "simulations_per_month": 5000}

"""Tests for the runtime manifest surface (signed runtime contract)."""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient
from decision_engine.exceptions import DecisionEngineError, NotFoundError

from .conftest import TEST_BASE_URL, make_runtime_manifest_payload


def test_get_runtime_manifest_parses_the_signed_manifest(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/runtime/manifest").mock(
        return_value=Response(200, json=make_runtime_manifest_payload())
    )

    manifest = client.get_runtime_manifest()

    assert route.calls[0].request.method == "GET"
    assert manifest.runtime_version == "1.0.0"
    assert manifest.deployment_mode.value == "saas"
    assert manifest.signature.key_id == "key_123"
    assert manifest.shipping_contract.module_count == 0


def test_get_runtime_manifest_rejects_an_invalid_payload(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/runtime/manifest").mock(
        return_value=Response(200, json={"runtime_version": "1.0.0"})
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.get_runtime_manifest()

    assert exc_info.value.error_code == "invalid_runtime_contract_payload"
    assert "invalid signed payload" in str(exc_info.value)


def test_get_runtime_manifest_has_no_openapi_fallback(
    client: AlgentaClient, mock_router
) -> None:
    # Unlike get_contract, a 404 here propagates immediately.
    mock_router.get(f"{TEST_BASE_URL}/v1/runtime/manifest").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )

    with pytest.raises(NotFoundError):
        client.get_runtime_manifest()

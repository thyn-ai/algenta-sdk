"""Tests for contract discovery: primary endpoint, OpenAPI fallback, failures."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient
from decision_engine.exceptions import (
    AuthenticationError,
    DecisionEngineError,
    NotFoundError,
)

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    make_openapi_contract_payload,
    make_platform_contract_payload,
)


def test_get_contract_uses_the_primary_endpoint(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(200, json=make_platform_contract_payload(TEST_BASE_URL))
    )

    contract = client.get_contract()

    assert contract.contract_version == "v1.5"
    assert contract.brand == "Algenta"
    assert contract.api_base_url == TEST_BASE_URL
    assert contract.mcp_endpoint == f"{TEST_BASE_URL}/mcp"
    assert contract.api_key_prefixes.live == "de_live_"
    api_section = contract.primary_data_query_contract["api"]
    assert api_section["query_endpoint"] == "/v1/query"


def test_get_contract_does_not_touch_the_fallback_on_primary_success(
    client: AlgentaClient,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        primary = router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
            return_value=Response(200, json=make_platform_contract_payload(TEST_BASE_URL))
        )
        fallback = router.get(f"{TEST_BASE_URL}/openapi.json").mock(
            return_value=Response(200, json=make_openapi_contract_payload())
        )

        client.get_contract()

        assert primary.called
        assert not fallback.called


def test_get_contract_falls_back_to_openapi_on_404(
    mock_router,
) -> None:
    self_hosted_url = "https://engine.internal:8443"
    client = AlgentaClient(api_key=TEST_API_KEY, base_url=self_hosted_url)
    mock_router.get(f"{self_hosted_url}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{self_hosted_url}/openapi.json").mock(
        return_value=Response(200, json=make_openapi_contract_payload())
    )

    contract = client.get_contract()

    # The fallback rebuilds the contract against the configured base URL.
    assert contract.api_base_url == self_hosted_url
    assert contract.mcp_endpoint == f"{self_hosted_url}/mcp"
    assert contract.mcp_tools_endpoint == f"{self_hosted_url}/mcp/tools"
    api_section = contract.primary_data_query_contract["api"]
    assert api_section["contract_endpoint"] == "/v1/meta/contract"


def test_get_contract_fallback_merges_server_overrides(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{TEST_BASE_URL}/openapi.json").mock(
        return_value=Response(
            200,
            json=make_openapi_contract_payload(
                **{
                    "x-primary-data-query-contract": {
                        "api": {
                            "contract_endpoint": "/v2/meta/contract",
                            "query_endpoint": "/v2/query",
                        }
                    }
                }
            ),
        )
    )

    contract = client.get_contract()

    api_section = contract.primary_data_query_contract["api"]
    assert api_section["contract_endpoint"] == "/v2/meta/contract"
    assert api_section["query_endpoint"] == "/v2/query"
    # Untouched sections keep the SDK's built-in defaults.
    assert api_section["resolve_endpoint"] == "/v1/resolve"


def test_get_contract_fallback_rejects_a_missing_extension(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{TEST_BASE_URL}/openapi.json").mock(
        return_value=Response(200, json={"openapi": "3.1.0", "paths": {}})
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.get_contract()

    assert exc_info.value.error_code == "contract_extension_missing"


def test_get_contract_fallback_rejects_an_invalid_extension(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{TEST_BASE_URL}/openapi.json").mock(
        return_value=Response(
            200,
            json={"x-primary-data-query-contract": {"api": {"contract_endpoint": 42}}},
        )
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.get_contract()

    assert exc_info.value.error_code == "invalid_contract_payload"


def test_get_contract_fails_hard_when_both_discovery_endpoints_404(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )
    mock_router.get(f"{TEST_BASE_URL}/openapi.json").mock(
        return_value=Response(404, json={"error": {"message": "not found"}})
    )

    with pytest.raises(NotFoundError):
        client.get_contract()


def test_get_contract_does_not_fall_back_on_auth_errors(
    client: AlgentaClient,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
            return_value=Response(401, json={"error": {"message": "invalid api key"}})
        )
        fallback = router.get(f"{TEST_BASE_URL}/openapi.json").mock(
            return_value=Response(200, json=make_openapi_contract_payload())
        )

        with pytest.raises(AuthenticationError):
            client.get_contract()

        assert not fallback.called


def test_get_contract_rejects_a_malformed_primary_payload(
    client: AlgentaClient, mock_router
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
        return_value=Response(200, json={"contract_version": 42})
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.get_contract()

    assert exc_info.value.error_code == "invalid_contract_payload"
    assert "get_contract() returned an invalid payload" in str(exc_info.value)

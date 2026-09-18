"""Standalone smoke tests for the public algenta-sdk package.

These are intentionally minimal: they prove the package imports and works
correctly on its own, outside any private engine infrastructure (no shared
conftest, no FastAPI app stack, no database — none of which a
`pip install algenta-sdk` user has, and none of which belong in this public
repo).

The broader standalone suite lives alongside this file: `conftest.py` holds
the shared fixtures, and the `test_*.py` modules cover client construction,
the facade surfaces, the error taxonomy, retry/back-off behavior, privacy
profiles, device binding, and contract discovery. Keep everything here
network-free (respx mocks only) and deterministic.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, DecisionEngineError


def test_import_surface() -> None:
    """The documented public import surface resolves without error."""
    from decision_engine import AsyncAlgentaClient, DecisionEngineClient  # noqa: F401

    assert AlgentaClient.__name__ == "AlgentaClient"


def test_client_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALGENTA_API_KEY", raising=False)
    monkeypatch.delenv("DE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key required"):
        AlgentaClient(base_url="https://api.algenta.ai")


def test_client_accepts_an_explicit_api_key() -> None:
    client = AlgentaClient(api_key="de_live_test_key", base_url="https://api.algenta.ai")
    assert client._api_key == "de_live_test_key"
    assert client._base_url == "https://api.algenta.ai"


@respx.mock
def test_list_datasets_round_trips_through_the_http_layer() -> None:
    """The client is a plain HTTP client: mocking the transport is enough to
    exercise a full request/response cycle with no real network or engine."""
    client = AlgentaClient(api_key="de_live_test_key", base_url="https://api.algenta.ai")
    respx.get("https://api.algenta.ai/v1/data").mock(
        return_value=Response(
            200,
            json={
                "datasets": [{"dataset_id": "ds_1", "dataset_name": "orders"}],
                "count": 1,
                "total": 1,
                "page": 1,
                "limit": 200,
                "pages": 1,
            },
        )
    )

    result = client.list_datasets(search="orders", compact=True)

    assert result.total == 1
    assert result.datasets[0].dataset_id == "ds_1"


@respx.mock
def test_error_response_raises_a_decision_engine_error() -> None:
    client = AlgentaClient(api_key="de_live_test_key", base_url="https://api.algenta.ai")
    respx.get("https://api.algenta.ai/v1/data").mock(
        return_value=Response(401, json={"detail": "invalid api key"})
    )

    with pytest.raises(DecisionEngineError):
        client.list_datasets()


@respx.mock
def test_error_response_carries_a_request_id_from_the_body() -> None:
    client = AlgentaClient(api_key="de_live_test_key", base_url="https://api.algenta.ai")
    respx.get("https://api.algenta.ai/v1/data").mock(
        return_value=Response(
            404,
            json={"error": {"message": "not found"}, "request_id": "req_abc123"},
        )
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.list_datasets()

    assert exc_info.value.request_id == "req_abc123"


@respx.mock
def test_error_response_falls_back_to_the_request_id_header() -> None:
    client = AlgentaClient(api_key="de_live_test_key", base_url="https://api.algenta.ai")
    respx.get("https://api.algenta.ai/v1/data").mock(
        return_value=Response(
            404,
            json={"error": {"message": "not found"}},
            headers={"X-Request-Id": "req_from_header"},
        )
    )

    with pytest.raises(DecisionEngineError) as exc_info:
        client.list_datasets()

    assert exc_info.value.request_id == "req_from_header"

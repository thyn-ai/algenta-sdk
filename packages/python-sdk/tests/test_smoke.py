"""Standalone smoke tests for the public algenta-sdk package.

These are intentionally minimal: they prove the package imports and works
correctly on its own, outside the private engine repo's monorepo test
infrastructure (which pulls in a shared conftest.py, a full FastAPI app
stack, and a database — none of which a `pip install algenta-sdk` user has,
and none of which belong in this public repo).

This is not a port of the private repo's full test coverage for this
package — that coverage currently lives commingled with the engine's own
test suite and isn't yet separable into something that runs standalone. If
you're picking up that follow-up, this file is the place to grow it.
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

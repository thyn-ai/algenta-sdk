"""Tests for client construction, configuration resolution, and facade shape."""

from __future__ import annotations

import httpx
import pytest
from httpx import Response

from decision_engine import (
    AlgentaClient,
    AsyncAlgentaClient,
    CodnaClient,
    DecisionEngineClient,
)

from .conftest import TEST_API_KEY, TEST_BASE_URL, derived_test_device_id


def test_public_aliases_resolve_to_the_same_client() -> None:
    assert issubclass(AlgentaClient, DecisionEngineClient)
    assert CodnaClient is AlgentaClient


def test_explicit_api_key_and_base_url_are_stored() -> None:
    client = AlgentaClient(api_key=TEST_API_KEY, base_url="https://engine.example.com")
    assert client._api_key == TEST_API_KEY
    assert client._base_url == "https://engine.example.com"
    assert client._timeout == 120.0
    assert client._max_retries == 3


def test_base_url_trailing_slash_is_normalized() -> None:
    client = AlgentaClient(api_key=TEST_API_KEY, base_url="https://engine.example.com/")
    assert client._base_url == "https://engine.example.com"


def test_base_url_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute URL"):
        AlgentaClient(api_key=TEST_API_KEY, base_url="engine.example.com")


def test_api_key_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALGENTA_API_KEY", "de_live_env_key")
    client = AlgentaClient(base_url=TEST_BASE_URL)
    assert client._api_key == "de_live_env_key"


def test_algenta_api_key_takes_precedence_over_legacy_de_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGENTA_API_KEY", "de_live_primary")
    monkeypatch.setenv("DE_API_KEY", "de_live_legacy")
    client = AlgentaClient(base_url=TEST_BASE_URL)
    assert client._api_key == "de_live_primary"


def test_legacy_de_api_key_still_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DE_API_KEY", "de_live_legacy")
    client = AlgentaClient(base_url=TEST_BASE_URL)
    assert client._api_key == "de_live_legacy"


def test_base_url_resolution_prefers_explicit_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGENTA_BASE_URL", "https://env.example.com")
    client = AlgentaClient(api_key=TEST_API_KEY, base_url="https://explicit.example.com")
    assert client._base_url == "https://explicit.example.com"


def test_base_url_resolution_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALGENTA_BASE_URL", "https://env.example.com")
    client = AlgentaClient(api_key=TEST_API_KEY)
    assert client._base_url == "https://env.example.com"


def test_base_url_resolution_defaults_to_the_algenta_cloud() -> None:
    client = AlgentaClient(api_key=TEST_API_KEY)
    assert client._base_url == "https://api.algenta.ai"


def test_missing_api_key_error_points_at_the_console() -> None:
    with pytest.raises(ValueError, match="API key required") as exc_info:
        AlgentaClient(base_url=TEST_BASE_URL)
    assert "ALGENTA_API_KEY" in str(exc_info.value)


def test_http_client_is_built_lazily() -> None:
    client = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)
    assert client._client._instance is None


def test_http_client_carries_auth_and_device_headers(client: AlgentaClient) -> None:
    http_client = client._client._ensure_instance()
    assert isinstance(http_client, httpx.Client)
    assert http_client.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert http_client.headers["Content-Type"] == "application/json"
    assert http_client.headers["User-Agent"].startswith("algenta-python/")
    assert http_client.headers["X-Algenta-Device-Id"] == derived_test_device_id()


def test_context_manager_closes_the_http_client(mock_router) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(
            200,
            json={"datasets": [], "count": 0, "total": 0, "page": 1, "limit": 200, "pages": 0},
        )
    )
    with AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL) as client:
        client.list_datasets()
        assert client._client._instance is not None
    assert client._client._instance.is_closed


def test_facade_exposes_the_major_surface_domains(client: AlgentaClient) -> None:
    """The facade mixins for the documented surface domains are wired up."""
    for method_name in (
        # LLM surface
        "list_models",
        "chat_completions",
        "embeddings",
        # query surface
        "query",
        "resolve",
        "verify",
        "query_batch",
        # simulation surface
        "simulate",
        "compare",
        # runtime / contract surface
        "get_contract",
        "get_runtime_manifest",
        # governance / receipts surface
        "get_audit_logs",
        "get_execution_policy",
        "log_decision",
        "execute_decision",
        # connector surface
        "list_datasets",
        "connect_data",
    ):
        assert callable(getattr(client, method_name)), method_name


def test_async_facade_exposes_the_major_surface_domains() -> None:
    async_client = AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)
    for method_name in (
        "list_models",
        "query",
        "simulate",
        "get_contract",
        "get_audit_logs",
        "log_decision",
        "list_datasets",
    ):
        assert callable(getattr(async_client, method_name)), method_name

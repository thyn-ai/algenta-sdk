"""Tests for the device-binding token cache and its client integration."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from httpx import Response

from decision_engine import AlgentaClient, device_binding
from decision_engine.device_binding import (
    DEVICE_BINDING_TOKEN_HEADER,
    load_device_binding_token,
    store_device_binding_token,
)

from .conftest import TEST_API_KEY, TEST_BASE_URL, derived_test_device_id

_DATASET_PAGE = {"datasets": [], "count": 0, "total": 0, "page": 1, "limit": 200, "pages": 0}

_STORE_KWARGS = {
    "base_url": TEST_BASE_URL,
    "api_key": TEST_API_KEY,
    "device_id": "test-device-id-0001",
}


def _store_path(runtime_dir: Path) -> Path:
    return runtime_dir / "hosted_device_binding_tokens.json"


def test_store_then_load_round_trips_through_the_disk_cache(
    isolated_environment: Path,
) -> None:
    store_device_binding_token(binding_token="token-abc", **_STORE_KWARGS)

    # Drop the in-memory copy to prove the value is read back from disk.
    device_binding._MEMORY_STORE.clear()

    assert load_device_binding_token(**_STORE_KWARGS) == "token-abc"


def test_store_writes_a_restricted_permissions_json_file(
    isolated_environment: Path,
) -> None:
    store_device_binding_token(binding_token="token-abc", **_STORE_KWARGS)

    path = _store_path(isolated_environment)
    assert path.exists()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_key = device_binding._binding_store_key(**_STORE_KWARGS)
    assert payload == {expected_key: "token-abc"}


def test_load_returns_none_for_an_unknown_credential_triplet(
    isolated_environment: Path,
) -> None:
    assert load_device_binding_token(**_STORE_KWARGS) is None


def test_load_tolerates_a_corrupt_store_file(isolated_environment: Path) -> None:
    path = _store_path(isolated_environment)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_device_binding_token(**_STORE_KWARGS) is None


def test_load_tolerates_a_non_object_store_file(isolated_environment: Path) -> None:
    path = _store_path(isolated_environment)
    path.parent.mkdir(parents=True)
    path.write_text('["not", "a", "dict"]', encoding="utf-8")

    assert load_device_binding_token(**_STORE_KWARGS) is None


def test_blank_tokens_are_never_stored(isolated_environment: Path) -> None:
    store_device_binding_token(binding_token="   ", **_STORE_KWARGS)

    assert load_device_binding_token(**_STORE_KWARGS) is None
    assert not _store_path(isolated_environment).exists()


def test_a_refreshed_token_replaces_the_cached_one(isolated_environment: Path) -> None:
    store_device_binding_token(binding_token="token-old", **_STORE_KWARGS)
    store_device_binding_token(binding_token="token-new", **_STORE_KWARGS)
    device_binding._MEMORY_STORE.clear()

    assert load_device_binding_token(**_STORE_KWARGS) == "token-new"


def test_tokens_are_scoped_per_base_url_api_key_and_device(
    isolated_environment: Path,
) -> None:
    store_device_binding_token(binding_token="token-a", **_STORE_KWARGS)
    store_device_binding_token(
        binding_token="token-b", **{**_STORE_KWARGS, "api_key": "de_live_other"}
    )
    device_binding._MEMORY_STORE.clear()

    assert load_device_binding_token(**_STORE_KWARGS) == "token-a"
    assert (
        load_device_binding_token(**{**_STORE_KWARGS, "api_key": "de_live_other"})
        == "token-b"
    )


def test_client_persists_binding_tokens_from_response_headers(
    mock_router, isolated_environment: Path
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(
            200,
            json=_DATASET_PAGE,
            headers={DEVICE_BINDING_TOKEN_HEADER: "token-from-server"},
        )
    )
    client = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)

    client.list_datasets()

    # The token is cached for future client instances and applied live.
    assert (
        load_device_binding_token(
            base_url=TEST_BASE_URL,
            api_key=TEST_API_KEY,
            device_id=derived_test_device_id(),
        )
        == "token-from-server"
    )
    assert client._client.headers[DEVICE_BINDING_TOKEN_HEADER] == "token-from-server"


def test_client_sends_a_cached_binding_token_on_subsequent_clients(
    mock_router, isolated_environment: Path
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(200, json=_DATASET_PAGE)
    )
    store_device_binding_token(
        base_url=TEST_BASE_URL,
        api_key=TEST_API_KEY,
        device_id=derived_test_device_id(),
        binding_token="token-cached",
    )
    client = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)

    client.list_datasets()

    headers = route.calls[0].request.headers
    assert headers[DEVICE_BINDING_TOKEN_HEADER] == "token-cached"


def test_client_omits_the_binding_header_when_no_token_is_cached(
    mock_router, isolated_environment: Path
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=Response(200, json=_DATASET_PAGE)
    )
    client = AlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)

    client.list_datasets()

    assert DEVICE_BINDING_TOKEN_HEADER not in route.calls[0].request.headers

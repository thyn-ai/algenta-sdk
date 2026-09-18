"""Tests for the device-identifying headers attached to every request."""

from __future__ import annotations

import re

import pytest

from decision_engine.device_headers import (
    DEVICE_ID_HEADER,
    HOSTNAME_HASH_HEADER,
    PLATFORM_HEADER,
    PLATFORM_VERSION_HEADER,
    SDK_VERSION_HEADER,
    _derived_device_id_from_seed,
    build_device_headers,
)

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def test_headers_include_sdk_version_and_device_identity() -> None:
    headers = build_device_headers(sdk_version="algenta-python/1.0.0", user_agent="ua")

    assert headers[SDK_VERSION_HEADER] == "algenta-python/1.0.0"
    assert _HEX_32.match(headers[DEVICE_ID_HEADER])
    assert _HEX_64.match(headers[HOSTNAME_HASH_HEADER])
    assert headers[PLATFORM_HEADER]
    assert PLATFORM_VERSION_HEADER in headers


def test_device_id_is_deterministic_for_a_given_machine_seed() -> None:
    first = build_device_headers(sdk_version="v", user_agent="ua")[DEVICE_ID_HEADER]
    second = build_device_headers(sdk_version="v", user_agent="ua")[DEVICE_ID_HEADER]
    assert first == second == _derived_device_id_from_seed("sdk-test-machine-seed")


def test_explicit_device_id_env_var_overrides_the_derived_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGENTA_DEVICE_ID", "explicit-device-id-1")
    headers = build_device_headers(sdk_version="v", user_agent="ua")
    assert headers[DEVICE_ID_HEADER] == "explicit-device-id-1"


def test_legacy_device_id_env_var_is_still_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DE_DEVICE_ID", "legacy-device-id-001")
    headers = build_device_headers(sdk_version="v", user_agent="ua")
    assert headers[DEVICE_ID_HEADER] == "legacy-device-id-001"


@pytest.mark.parametrize("bad", ["too-short", "x" * 65])
def test_explicit_device_id_length_is_validated(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("ALGENTA_DEVICE_ID", bad)
    with pytest.raises(ValueError, match="ALGENTA_DEVICE_ID"):
        build_device_headers(sdk_version="v", user_agent="ua")


def test_sdk_version_is_truncated_to_the_header_budget() -> None:
    headers = build_device_headers(sdk_version="v" * 500, user_agent="ua")
    assert len(headers[SDK_VERSION_HEADER]) == 128

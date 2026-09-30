#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regenerate the recorded-response fixtures for the contract-drift lane.

The fixtures under ``tests/fixtures/`` are engine response payloads that both SDK
language implementations parse. Each language's test lane asserts that parsing a
fixture through the SDK produces a deterministic, stable result. When the engine
contract or the SDK parser changes, run this script from the repository root and
commit the updated fixtures:

    python3 scripts/update_contract_drift_fixtures.py

The generator is deterministic (no wall-clock or environment state) and uses the
shipped contract constants so the fixtures cannot drift from the SDK's own
contract definitions.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_SDK_DIR = REPO_ROOT / "packages" / "python-sdk"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

# The Python SDK package is not installed when this script runs in CI, so add its
# source tree to the path for the duration of generation.
sys.path.insert(0, str(PYTHON_SDK_DIR))

from decision_engine._contract import (  # noqa: E402
    ALGENTA_OWNED_HOSTS,
    ALGENTA_OWNED_SUFFIXES,
    API_KEY_PREFIX_LIVE,
    API_KEY_PREFIX_TEST,
    AUTH_SCHEME,
    BRAND,
    CONTRACT_VERSION,
    DEFAULT_BASE_URL,
    DEPRECATION_WINDOW_DAYS,
    INTEGRATIONS,
    LEGACY_DOMAINS,
    LEGACY_ENV_VARS,
    LEGACY_HEADERS,
    MCP_ENDPOINT,
    MCP_LEGACY_SSE_ENDPOINT,
    MCP_PROTOCOL_VERSION,
    MCP_TOOLS_ENDPOINT,
    MCP_TRANSPORT,
    PLAN_LIMITS,
    PRIMARY_DATA_QUERY_CONTRACT,
    PRIVATE_HOST_SUFFIXES,
    READ_ONLY_DEFAULT,
    VENDOR_TELEMETRY_HOSTS,
    WRITE_CONFIRMATION_REQUIRED,
)


def make_contract_fixture() -> dict[str, object]:
    """Return a recorded ``/v1/meta/contract`` response body."""
    base_url = DEFAULT_BASE_URL
    return {
        "contract_version": CONTRACT_VERSION,
        "brand": BRAND,
        "api_base_url": base_url,
        "mcp_endpoint": MCP_ENDPOINT,
        "mcp_transport": MCP_TRANSPORT,
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "mcp_legacy_sse_endpoint": MCP_LEGACY_SSE_ENDPOINT,
        "mcp_tools_endpoint": MCP_TOOLS_ENDPOINT,
        "auth_scheme": AUTH_SCHEME,
        "api_key_prefixes": {
            "live": API_KEY_PREFIX_LIVE,
            "test": API_KEY_PREFIX_TEST,
        },
        "compatibility": {
            "legacy_headers": list(LEGACY_HEADERS),
            "legacy_env_vars": list(LEGACY_ENV_VARS),
            "legacy_domains": list(LEGACY_DOMAINS),
            "deprecation_window_days": DEPRECATION_WINDOW_DAYS,
        },
        "privacy_registry": {
            "algenta_owned_hosts": list(ALGENTA_OWNED_HOSTS),
            "algenta_owned_suffixes": list(ALGENTA_OWNED_SUFFIXES),
            "vendor_telemetry_hosts": list(VENDOR_TELEMETRY_HOSTS),
            "private_host_suffixes": list(PRIVATE_HOST_SUFFIXES),
        },
        "defaults": {
            "read_only_default": READ_ONLY_DEFAULT,
            "write_confirmation_required": WRITE_CONFIRMATION_REQUIRED,
            "plan_limits": deepcopy(PLAN_LIMITS),
        },
        "primary_data_query_contract": deepcopy(PRIMARY_DATA_QUERY_CONTRACT),
        "capability_plane": None,
        "integrations": deepcopy(INTEGRATIONS),
    }


def make_receipt_fixture() -> dict[str, object]:
    """Return a recorded ``POST /v1/decisions/{id}/execute`` response body."""
    return {
        "decision_id": "dec_123",
        "webhook_url": "https://hooks.example.test/algenta",
        "execution_status": "delivered",
        "response_code": 202,
        "executed_at": "2026-01-01T00:00:00Z",
        "policy_snapshot_id": "pol_123",
        "schema_snapshot_id": "sch_123",
        "manifest_version": "1.0.0",
        "payload_summary": {
            "action": "ship_it",
            "expected_value": 128000.0,
            "confidence": 0.82,
        },
        "safety_overridden": False,
    }


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort keys so the file is byte-stable across regenerations and easy to diff.
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    _write_json(
        FIXTURES_DIR / "contract" / "contract.fixture.json", make_contract_fixture()
    )
    _write_json(
        FIXTURES_DIR / "receipt" / "receipt.fixture.json", make_receipt_fixture()
    )
    print("Updated contract-drift fixtures under tests/fixtures/")


if __name__ == "__main__":
    main()

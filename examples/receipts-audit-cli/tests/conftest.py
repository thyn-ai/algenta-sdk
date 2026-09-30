# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for the receipts-audit-cli test suite.

The suite is fully deterministic and network-free: ``respx`` intercepts every
HTTP call at the httpx transport layer, so no request ever leaves the process.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from decision_engine import AlgentaClient

TEST_API_KEY = "de_live_test_key"
TEST_BASE_URL = "https://api.algenta.ai"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Give every test a deterministic, side-effect-free environment."""
    for name in (
        "ALGENTA_API_KEY",
        "DE_API_KEY",
        "ALGENTA_BASE_URL",
        "DE_BASE_URL",
        "ALGENTA_API_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_dir = tmp_path / "algenta-runtime"
    monkeypatch.setenv("ALGENTA_RUNTIME_DIR", str(runtime_dir))
    yield runtime_dir


@pytest.fixture
def base_url() -> str:
    return TEST_BASE_URL


@pytest.fixture
def api_key() -> str:
    return TEST_API_KEY


@pytest.fixture
def mock_router() -> Iterator[respx.Router]:
    """An intercepting HTTP router that fails on unexpected requests."""
    with respx.mock(assert_all_called=True) as router:
        yield router


@pytest.fixture
def client(base_url: str, api_key: str) -> Iterator[AlgentaClient]:
    instance = AlgentaClient(api_key=api_key, base_url=base_url, max_retries=0)
    yield instance
    instance.close()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def agent_run_fixture(fixtures_dir: Path) -> dict[str, Any]:
    import json

    return json.loads((fixtures_dir / "agent_run.json").read_text(encoding="utf-8"))


@pytest.fixture
def agent_run_events_fixture(fixtures_dir: Path) -> dict[str, Any]:
    import json

    return json.loads((fixtures_dir / "agent_run_events.json").read_text(encoding="utf-8"))

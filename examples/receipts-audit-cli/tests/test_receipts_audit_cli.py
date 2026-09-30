# SPDX-License-Identifier: Apache-2.0

"""Golden-output tests for the receipts audit CLI.

Every test runs offline against recorded JSON fixtures stored in
``tests/fixtures/``. HTTP traffic is intercepted by ``respx``, so no network
request leaves the process.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from httpx import Response

# The example directory name uses a hyphen, which is not a valid Python package
# identifier. Add the example directory to sys.path so the CLI module can be
# imported directly for testing without renaming the directory.
_EXAMPLE_DIR = Path(__file__).parent.parent
if str(_EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_DIR))

from receipts_audit_cli import fetch_audit_trail, format_json, format_timeline, main  # noqa: E402


def _stub_run_and_events(
    mock_router: Any,
    base_url: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
) -> None:
    mock_router.get(f"{base_url}/v1/agent/runs/run_audit_1").mock(
        return_value=Response(200, json=agent_run_fixture)
    )
    mock_router.get(f"{base_url}/v1/agent/runs/run_audit_1/events").mock(
        return_value=Response(200, json=agent_run_events_fixture)
    )


def test_fetch_audit_trail_returns_run_header_and_events(
    client: Any,
    mock_router: Any,
    base_url: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
) -> None:
    _stub_run_and_events(mock_router, base_url, agent_run_fixture, agent_run_events_fixture)

    trail = fetch_audit_trail(client, "run_audit_1")

    assert trail["run_id"] == "run_audit_1"
    assert trail["status"] == "completed"
    assert trail["task"] == "Summarise the changelog."
    assert trail["policy_snapshot_id"] == "pol_123"
    assert trail["schema_snapshot_id"] == "sch_123"
    assert trail["manifest_version"] == "1.0.0"
    assert trail["total_events"] == 6
    assert [event["event_id"] for event in trail["events"]] == [
        "evt_1",
        "evt_2",
        "evt_3",
        "evt_4",
        "evt_5",
        "evt_6",
    ]


def test_format_timeline_matches_golden_output(
    client: Any,
    mock_router: Any,
    base_url: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
    fixtures_dir: Path,
) -> None:
    _stub_run_and_events(mock_router, base_url, agent_run_fixture, agent_run_events_fixture)

    trail = fetch_audit_trail(client, "run_audit_1")
    output = format_timeline(trail)

    golden_path = fixtures_dir / "timeline_expected.txt"
    assert golden_path.read_text(encoding="utf-8") == output


def test_format_json_is_deterministic_and_matches_golden_output(
    client: Any,
    mock_router: Any,
    base_url: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
    fixtures_dir: Path,
) -> None:
    _stub_run_and_events(mock_router, base_url, agent_run_fixture, agent_run_events_fixture)

    trail = fetch_audit_trail(client, "run_audit_1")
    output = format_json(trail)

    # Verify the output is valid JSON and deterministic (sorted keys).
    parsed = json.loads(output)
    assert parsed["run_id"] == "run_audit_1"
    assert output == json.dumps(parsed, indent=2, sort_keys=True)

    golden_path = fixtures_dir / "audit_trail_expected.json"
    assert golden_path.read_text(encoding="utf-8") == output


def test_main_emits_timeline_by_default(
    client: Any,
    mock_router: Any,
    base_url: str,
    api_key: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_run_and_events(mock_router, base_url, agent_run_fixture, agent_run_events_fixture)
    monkeypatch.setenv("ALGENTA_API_KEY", api_key)
    monkeypatch.setenv("ALGENTA_BASE_URL", base_url)

    return_code = main(["run_audit_1"])

    captured = capsys.readouterr()
    assert return_code == 0
    assert captured.err == ""
    expected = (fixtures_dir / "timeline_expected.txt").read_text(encoding="utf-8")
    assert captured.out == expected + "\n"


def test_main_emits_json_with_json_flag(
    client: Any,
    mock_router: Any,
    base_url: str,
    api_key: str,
    agent_run_fixture: dict[str, Any],
    agent_run_events_fixture: dict[str, Any],
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_run_and_events(mock_router, base_url, agent_run_fixture, agent_run_events_fixture)
    monkeypatch.setenv("ALGENTA_API_KEY", api_key)
    monkeypatch.setenv("ALGENTA_BASE_URL", base_url)

    return_code = main(["run_audit_1", "--json"])

    captured = capsys.readouterr()
    assert return_code == 0
    assert captured.err == ""
    expected = (fixtures_dir / "audit_trail_expected.json").read_text(encoding="utf-8")
    assert captured.out == expected + "\n"


def test_main_exits_non_zero_on_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("ALGENTA_API_KEY", "DE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    return_code = main(["run_audit_1"])

    captured = capsys.readouterr()
    assert return_code == 1
    assert "ALGENTA_API_KEY" in captured.err


def test_main_exits_non_zero_when_run_not_found(
    client: Any,
    mock_router: Any,
    base_url: str,
    api_key: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_router.get(f"{base_url}/v1/agent/runs/missing").mock(
        return_value=Response(
            404, json={"error": {"message": "run not found", "code": "not_found"}}
        )
    )
    monkeypatch.setenv("ALGENTA_API_KEY", api_key)
    monkeypatch.setenv("ALGENTA_BASE_URL", base_url)

    return_code = main(["missing"])

    captured = capsys.readouterr()
    assert return_code == 1
    assert "not_found" in captured.err

# SPDX-License-Identifier: Apache-2.0

"""CLI that renders an agent run's execution receipts as a timeline table.

The audit trail is built from the public agent-run surfaces:

- ``GET /v1/agent/runs/{run_id}`` for the run header (policy/schema snapshots,
  manifest version, task, status)
- ``GET /v1/agent/runs/{run_id}/events`` for the ordered event receipt stream

The default output is a human-readable timeline table. Pass ``--json`` to emit
the same data as deterministic, sorted JSON for downstream processing.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from decision_engine import AlgentaClient
from decision_engine.exceptions import DecisionEngineError

from examples.shared.privacy_profile import (
    resolve_example_api_base_url,
    resolve_example_api_key,
)


def _coerce_iso(value: Any) -> str:
    """Return an ISO-8601 string for datetime inputs, or '-' for missing values."""
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def fetch_audit_trail(client: AlgentaClient, run_id: str) -> dict[str, Any]:
    """Fetch the run header and event stream, returning a plain audit trail.

    The returned dictionary is JSON-serializable and deterministic: datetimes
    are normalized to ISO-8601 strings and event ordering is preserved.
    """
    run = client.get_agent_run(run_id)
    events = client.get_agent_run_events(run_id)

    return {
        "run_id": run.run_id,
        "status": run.status,
        "task": run.task,
        "output_format": run.output_format,
        "approval_mode": run.approval_mode,
        "policy_snapshot_id": run.policy_snapshot_id,
        "schema_snapshot_id": run.schema_snapshot_id,
        "manifest_version": run.manifest_version,
        "request_hash": run.request_hash,
        "decision_hash": run.decision_hash,
        "created_at": _coerce_iso(run.created_at),
        "updated_at": _coerce_iso(run.updated_at),
        "latency_ms": run.latency_ms,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "status": event.status,
                "message": event.message,
                "created_at": _coerce_iso(event.created_at),
                "details": event.details or {},
            }
            for event in events.data
        ],
        "total_events": events.total_events,
    }


def _column_widths(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[int]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    return widths


def _format_row(row: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))


def format_timeline(trail: dict[str, Any]) -> str:
    """Render the audit trail as a fixed-width timeline table."""
    lines: list[str] = [
        f"Run ID:            {trail['run_id']}",
        f"Task:              {trail['task']}",
        f"Status:            {trail['status']}",
        f"Output format:     {trail['output_format']}",
        f"Approval mode:     {trail['approval_mode']}",
        f"Policy snapshot:   {trail['policy_snapshot_id'] or '-'}",
        f"Schema snapshot:   {trail['schema_snapshot_id'] or '-'}",
        f"Manifest version:  {trail['manifest_version'] or '-'}",
        f"Request hash:      {trail['request_hash'] or '-'}",
        f"Decision hash:     {trail['decision_hash'] or '-'}",
        f"Created:           {trail['created_at']}",
        f"Updated:           {trail['updated_at']}",
    ]
    if trail["latency_ms"] is not None:
        lines.append(f"Latency (ms):      {trail['latency_ms']}")
    lines.append("")
    lines.append(f"Events ({trail['total_events']} total):")

    headers = ("#", "Time", "Type", "Status", "Message")
    rows: list[tuple[str, ...]] = []
    for index, event in enumerate(trail["events"], start=1):
        rows.append(
            (
                str(index),
                event["created_at"],
                event["event_type"],
                event["status"],
                event["message"],
            )
        )

    if not rows:
        lines.append("  No events recorded.")
        return "\n".join(lines)

    widths = _column_widths(headers, rows)
    rule = "  ".join("-" * width for width in widths)
    lines.append(_format_row(headers, widths))
    lines.append(rule)
    for row in rows:
        lines.append(_format_row(row, widths))

    return "\n".join(lines)


def format_json(trail: dict[str, Any]) -> str:
    """Return deterministic, pretty-printed JSON for the audit trail."""
    return json.dumps(trail, indent=2, sort_keys=True)


def build_argument_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="receipts-audit-cli",
        description="Render an Algenta agent run's execution receipts as a timeline.",
    )
    parser.add_argument("run_id", help="Agent run identifier")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit the audit trail as deterministic JSON instead of a table",
    )
    parser.add_argument(
        "--base-url",
        help="Algenta API base URL (defaults to ALGENTA_BASE_URL / DE_BASE_URL / https://api.algenta.ai)",
    )
    parser.add_argument(
        "--api-key",
        help="Algenta API key (defaults to ALGENTA_API_KEY / DE_API_KEY)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the receipts audit CLI."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    component = "receipts audit CLI"
    try:
        api_key = args.api_key or resolve_example_api_key(component=component)
        base_url = args.base_url or resolve_example_api_base_url(component=component)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    client = AlgentaClient(api_key=api_key, base_url=base_url)
    try:
        trail = fetch_audit_trail(client, args.run_id)
    except DecisionEngineError as exc:
        error = {
            "error": {
                "code": exc.error_code,
                "message": str(exc),
                "status_code": exc.status_code,
                "request_id": exc.request_id,
            }
        }
        print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        client.close()

    if args.json_output:
        print(format_json(trail))
    else:
        print(format_timeline(trail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

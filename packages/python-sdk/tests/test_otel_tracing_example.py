# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``examples/otel-tracing`` OpenTelemetry example.

The example directory name contains a hyphen, so it is not a valid Python
package name. Tests import ``traced_client.py`` by path and use a small
in-memory stub tracer so the suite stays deterministic and does not need
OpenTelemetry installed.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from decision_engine import AlgentaClient, ServerError

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_DIR = _REPO_ROOT / "examples" / "otel-tracing"

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_EXAMPLE_DIR))
try:
    import traced_client
finally:
    sys.path.pop(0)
    sys.path.pop(0)


_EXECUTION_RECEIPT_PAYLOAD = {
    "decision_id": "dec_123",
    "webhook_url": "https://hooks.example.com/algenta",
    "execution_status": "delivered",
    "response_code": 200,
    "executed_at": "2026-01-01T00:00:00Z",
    "policy_snapshot_id": "pol_123",
    "schema_snapshot_id": "sch_123",
    "manifest_version": "1.0.0",
    "payload_summary": {"action": "ship_it"},
    "safety_overridden": False,
}


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[tuple[str, _RecordingSpan]] = []

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: Any | None = None,
    ) -> Iterator[_RecordingSpan]:
        span = _RecordingSpan()
        self.spans.append((name, span))
        try:
            yield span
        finally:
            pass


def test_traced_execute_decision_records_receipt_id(
    client: AlgentaClient,
    mock_router: respx.Router,
) -> None:
    route = mock_router.post("https://api.algenta.ai/v1/decisions/dec_123/execute").mock(
        return_value=Response(200, json=_EXECUTION_RECEIPT_PAYLOAD)
    )
    tracer = _RecordingTracer()

    receipt = traced_client.traced_execute_decision(
        client,
        "dec_123",
        webhook_url="https://hooks.example.com/algenta",
        tracer=tracer,
        metadata={"initiated_by": "test"},
    )

    assert receipt.decision_id == "dec_123"
    assert receipt.execution_status == "delivered"
    assert route.calls[0].request.method == "POST"
    request_body = route.calls[0].request.read()
    assert b'"initiated_by"' in request_body

    assert len(tracer.spans) == 1
    name, span = tracer.spans[0]
    assert name == "algenta.execute_decision"
    assert span.attributes["algenta.decision.id"] == "dec_123"
    assert span.attributes["algenta.execution.receipt_id"] == "dec_123"
    assert span.attributes["algenta.execution.status"] == "delivered"
    assert span.attributes["algenta.execution.policy_snapshot_id"] == "pol_123"
    assert span.attributes["algenta.execution.schema_snapshot_id"] == "sch_123"
    assert span.attributes["algenta.execution.manifest_version"] == "1.0.0"
    assert span.attributes["algenta.execution.safety_overridden"] is False
    assert span.attributes["algenta.execution.metadata_keys"] == ["initiated_by"]


def test_traced_execute_decision_records_error_on_failure(
    no_retry_client: AlgentaClient,
    mock_router: respx.Router,
) -> None:
    mock_router.post("https://api.algenta.ai/v1/decisions/dec_123/execute").mock(
        return_value=Response(500, json={"error": {"message": "execution refused"}})
    )
    tracer = _RecordingTracer()

    with pytest.raises(ServerError):
        traced_client.traced_execute_decision(
            no_retry_client,
            "dec_123",
            webhook_url="https://hooks.example.com/algenta",
            tracer=tracer,
        )

    assert len(tracer.spans) == 1
    span = tracer.spans[0][1]
    assert span.attributes["algenta.decision.id"] == "dec_123"
    assert span.attributes["error.type"] == "ServerError"
    assert "execution refused" in span.attributes["error.message"]

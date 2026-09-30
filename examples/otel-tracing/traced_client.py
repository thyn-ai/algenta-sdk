# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry tracing correlated with Algenta execution receipt IDs.

This example wraps ``AlgentaClient.execute_decision`` in a client span and
writes the execution receipt ID (``decision_id``) back to the span as the
attribute ``algenta.execution.receipt_id``. Operators can use that attribute to
reconcile distributed traces with the Algenta audit trail.

The module keeps OpenTelemetry as an example-only dependency: importing this
file does not require ``opentelemetry`` to be installed. ``get_tracer`` imports
OpenTelemetry lazily, so the wrapper can be unit-tested with a stub tracer and
only needs a real OpenTelemetry install when it is actually run against a
collector.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable

from decision_engine import AlgentaClient, ExecutionReceiptResult


@runtime_checkable
class _Span(Protocol):
    """Minimal span surface used by ``traced_execute_decision``."""

    def set_attribute(self, key: str, value: Any) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    """Minimal tracer surface accepted by ``traced_execute_decision``."""

    def start_as_current_span(
        self,
        name: str,
        *,
        kind: Any | None = None,
    ) -> AbstractContextManager[_Span]: ...


_DEFAULT_SPAN_KIND: Any = None


def _client_span_kind() -> Any:
    """Return ``SpanKind.CLIENT`` when OpenTelemetry is installed.

    Falls back to the string ``"client"`` for stub tracers used in tests that
    run without OpenTelemetry installed.
    """
    global _DEFAULT_SPAN_KIND
    if _DEFAULT_SPAN_KIND is None:
        try:
            from opentelemetry.trace import SpanKind

            _DEFAULT_SPAN_KIND = SpanKind.CLIENT
        except ImportError:
            _DEFAULT_SPAN_KIND = "client"
    return _DEFAULT_SPAN_KIND


def traced_execute_decision(
    client: AlgentaClient,
    decision_id: str,
    *,
    webhook_url: str,
    tracer: Tracer,
    timeout_seconds: float = 10.0,
    force: bool = False,
    override_safety: bool = False,
    metadata: Mapping[str, Any] | None = None,
    span_kind: Any | None = None,
) -> ExecutionReceiptResult:
    """Execute a decision under an OpenTelemetry span and annotate the span.

    The span is named ``algenta.execute_decision`` and carries the decision ID
    as an input attribute. After the call returns an
    ``ExecutionReceiptResult``, the receipt ID and other receipt fields are
    attached as span attributes so traces can be joined to the audit log.

    Args:
        client: Configured Algenta client.
        decision_id: Identifier of the decision to execute.
        webhook_url: Target webhook for the execution request.
        tracer: OpenTelemetry tracer (or any object implementing the
            ``Tracer`` protocol).
        timeout_seconds: Optional execution timeout.
        force: Whether to force execution past advisory gates.
        override_safety: Whether to override safety checks.
        metadata: Optional execution metadata.
        span_kind: Optional OpenTelemetry span kind. Defaults to
            ``SpanKind.CLIENT`` when OpenTelemetry is installed, otherwise the
            string ``"client"`` for stub tracers.

    Returns:
        The execution receipt returned by the Algenta API.

    Raises:
        Exception: Any exception raised by ``client.execute_decision`` is
            re-raised after ``error.type`` and ``error.message`` are recorded
            on the span.
    """
    with tracer.start_as_current_span(
        "algenta.execute_decision",
        kind=span_kind if span_kind is not None else _client_span_kind(),
    ) as span:
        span.set_attribute("algenta.decision.id", decision_id)
        if metadata:
            span.set_attribute("algenta.execution.metadata_keys", sorted(metadata.keys()))

        try:
            receipt = client.execute_decision(
                decision_id,
                webhook_url=webhook_url,
                timeout_seconds=timeout_seconds,
                force=force,
                override_safety=override_safety,
                metadata=dict(metadata) if metadata else None,
            )
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_attribute("error.message", str(exc))
            raise

        span.set_attribute("algenta.execution.receipt_id", receipt.decision_id)
        span.set_attribute("algenta.execution.status", receipt.execution_status)
        if receipt.policy_snapshot_id is not None:
            span.set_attribute(
                "algenta.execution.policy_snapshot_id",
                receipt.policy_snapshot_id,
            )
        if receipt.schema_snapshot_id is not None:
            span.set_attribute(
                "algenta.execution.schema_snapshot_id",
                receipt.schema_snapshot_id,
            )
        if receipt.manifest_version is not None:
            span.set_attribute(
                "algenta.execution.manifest_version",
                receipt.manifest_version,
            )
        span.set_attribute(
            "algenta.execution.safety_overridden",
            receipt.safety_overridden,
        )
        return receipt


def get_tracer(
    service_name: str = "algenta-otel-example",
    *,
    exporter: Any | None = None,
) -> Tracer:
    """Build an OpenTelemetry tracer for the example.

    OpenTelemetry is imported inside this function so the rest of the module
    can be imported without it installed.

    Args:
        service_name: Resource attribute used for the tracer provider.
        exporter: Optional span exporter. When omitted, the function uses
            ``OTEL_EXPORTER_OTLP_ENDPOINT`` if it is set, otherwise falls back
            to the console exporter.

    Returns:
        An OpenTelemetry tracer.

    Raises:
        ImportError: If the required OpenTelemetry packages are not installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError as exc:
        msg = (
            "OpenTelemetry is required to run this example. Install it with:\n"
            "  pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
        )
        raise ImportError(msg) from exc

    resource = Resource(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if exporter is None:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else ConsoleSpanExporter()

    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def main() -> None:
    """Run the example against the configured Algenta endpoint."""
    from examples.shared.privacy_profile import (
        resolve_example_api_base_url,
        resolve_example_api_key,
    )

    api_key = resolve_example_api_key(component="OpenTelemetry tracing example")
    base_url = resolve_example_api_base_url(component="OpenTelemetry tracing example")

    client = AlgentaClient(api_key=api_key, base_url=base_url, max_retries=0)
    tracer = get_tracer()
    try:
        receipt = traced_execute_decision(
            client,
            "dec_123",
            webhook_url="https://hooks.example.com/algenta",
            tracer=tracer,
        )
        print(
            f"Execution receipt: decision_id={receipt.decision_id} "
            f"status={receipt.execution_status}"
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()

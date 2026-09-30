# OpenTelemetry tracing correlated with execution receipt IDs

Operators running governed agent runs need traces they can reconcile with the
audit trail. This example wraps ``AlgentaClient.execute_decision`` in an
OpenTelemetry span and writes the execution receipt ID back to the span as the
attribute ``algenta.execution.receipt_id``.

## Files

- ``traced_client.py`` – wrapper that records span attributes around an SDK call.
- ``sample_trace.json`` – a deterministic example of the exported span.

## How it works

```text
┌─────────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│  your process   │────▶│ algenta.execute_decision │────▶│  Algenta API     │
│  (OpenTelemetry │     │ span with decision_id      │     │  returns receipt │
│   tracer)       │◀────│ and receipt_id attributes  │◀────│                  │
└─────────────────┘     └─────────────────────┘     └──────────────────┘
```

The span carries:

| Attribute | Source |
|---|---|
| ``algenta.decision.id`` | The decision ID passed into the wrapper. |
| ``algenta.execution.receipt_id`` | ``receipt.decision_id`` from the execution receipt. |
| ``algenta.execution.status`` | ``receipt.execution_status``. |
| ``algenta.execution.policy_snapshot_id`` | Policy snapshot captured at execution time. |
| ``algenta.execution.schema_snapshot_id`` | Schema snapshot captured at execution time. |
| ``algenta.execution.manifest_version`` | Runtime manifest version. |
| ``algenta.execution.safety_overridden`` | Whether safety was overridden. |

## Prerequisites

Install the Python SDK (editable is enough for local development):

```bash
pip install -e packages/python-sdk
```

Install OpenTelemetry (kept out of the SDK's runtime dependencies):

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

## Run against a local collector

Start an OTLP HTTP collector locally, for example with the contrib image:

```bash
docker run --rm -p 4318:4318 \
  otel/opentelemetry-collector-contrib:latest \
  --config /etc/otelcol-contrib/config.yaml
```

Then run the example with ``OTEL_EXPORTER_OTLP_ENDPOINT`` pointed at the
receiver:

```bash
export ALGENTA_API_KEY="de_live_..."
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
PYTHONPATH=. python examples/otel-tracing/traced_client.py
```

If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset, the example prints spans to the
console instead via ``ConsoleSpanExporter``.

## View the sample trace

``sample_trace.json`` shows the console-exporter JSON view of a single span
captured by the wrapper. The key correlation attribute is
``algenta.execution.receipt_id``.

## Notes

- OpenTelemetry is an example-only dependency. The SDK package itself does not
depend on it.
- The wrapper accepts any object implementing the small ``Tracer`` protocol, so
it can be unit-tested without a real OpenTelemetry install.

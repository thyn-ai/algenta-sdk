# Receipts Audit-Trail CLI

A small Python example that turns an Algenta agent run's execution receipts
into a readable timeline table, with an optional deterministic JSON export.

The CLI uses the public agent-run surfaces from the Python SDK:

- `GET /v1/agent/runs/{run_id}` for the run header, including the policy and
  schema snapshots that govern the execution
- `GET /v1/agent/runs/{run_id}/events` for the ordered event receipt stream

No data leaves your machine in the bundled tests: HTTP calls are intercepted
by `respx` and answered from recorded fixtures in `tests/fixtures/`.

## Files

- `receipts_audit_cli.py` — the CLI implementation
- `tests/test_receipts_audit_cli.py` — offline golden-output tests
- `tests/fixtures/agent_run.json` — recorded run header
- `tests/fixtures/agent_run_events.json` — recorded event stream
- `tests/fixtures/timeline_expected.txt` — expected table output
- `tests/fixtures/audit_trail_expected.json` — expected JSON export

## Run the tests

From the repository root:

```bash
python -m pytest examples/receipts-audit-cli/tests/ -v
```

The test suite is deterministic and network-free.

## Run the CLI against a real run

Set your Algenta API credentials and pass a run ID:

```bash
export ALGENTA_API_KEY="de_live_..."
# Optional: export ALGENTA_BASE_URL="https://api.algenta.ai"

python examples/receipts-audit-cli/receipts_audit_cli.py run_123
```

The CLI falls back to `DE_API_KEY` / `DE_BASE_URL` for compatibility.
In `self_hosted` or `air_gapped` profiles, set an explicit self-hosted base
URL; private profiles fail closed and do not silently fall back to Algenta
cloud.

## Export as JSON

```bash
python examples/receipts-audit-cli/receipts_audit_cli.py run_123 --json
```

The JSON output is deterministic: keys are sorted and timestamps are ISO-8601,
so it can be piped into `jq`, stored in an audit log, or diffed across runs.

## What the output shows

The default timeline table prints:

- Run metadata: task, status, output format, approval mode
- Governance context: policy snapshot, schema snapshot, manifest version
- Integrity fields: request hash, decision hash, created/updated timestamps
- An ordered event table with `#`, `Time`, `Type`, `Status`, and `Message`

This is the same audit information returned by the SDK, just formatted for
operators who need to inspect a run without reading raw JSON.

## Error handling

Missing credentials produce a clear error and exit code `1`. API errors are
printed as structured JSON to stderr, including the error code, message,
HTTP status, and request ID when available.

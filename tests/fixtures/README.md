# Contract-drift fixtures

This directory holds recorded engine response payloads used by the cross-language
contract-drift lane. The lane exists so that silent schema drift in the engine
payloads cannot reach a release without a failing test.

- `contract/contract.fixture.json` — a recorded `/v1/meta/contract` response.
- `receipt/receipt.fixture.json` — a recorded `POST /v1/decisions/{id}/execute`
  response (an `ExecutionReceipt`).

Both the Python SDK and the TypeScript SDK load these fixtures and assert that
parsing them through the SDK produces a stable, deterministic result. If the
engine contract changes or the SDK parser changes the shape, the lane fails until
the fixture is regenerated.

## Regenerating

From the repository root:

```sh
python3 scripts/update_contract_drift_fixtures.py
```

The generator is deterministic (no wall-clock or environment state) and uses the
shipped contract constants, so running it twice produces byte-identical files.
Edit `scripts/update_contract_drift_fixtures.py` to change the fixtures — do not
edit the JSON files by hand.

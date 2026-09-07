<div align="center">

# Algenta SDK

**Python and TypeScript client libraries for [Algenta](https://algenta.ai).**

[![PyPI](https://img.shields.io/pypi/v/algenta-sdk?label=PyPI)](https://pypi.org/project/algenta-sdk/)
[![npm](https://img.shields.io/npm/v/algenta-sdk?label=npm)](https://www.npmjs.com/package/algenta-sdk)
[![CI](https://github.com/thyn-ai/algenta-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/thyn-ai/algenta-sdk/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

[Docs](https://docs.algenta.ai) · [Python SDK](./packages/python-sdk) · [TypeScript SDK](./packages/ts-sdk) · [Contributing](./CONTRIBUTING.md)

</div>

---

```bash
pip install algenta-sdk       # Python
npm install algenta-sdk       # TypeScript / JavaScript
```

> **Name mapping:** the PyPI package is `algenta-sdk`, but the importable
> Python module is `decision_engine` — `from decision_engine import
> AlgentaClient`, **not** `import algenta_sdk`. The npm package name and its
> import specifier are both `algenta-sdk`. Source for both lives under
> [`packages/python-sdk`](./packages/python-sdk) and
> [`packages/ts-sdk`](./packages/ts-sdk) respectively.

## Quickstart

Try it with no account, API key, or network call at all — inspect the
published API contract locally:

```python
from decision_engine import DEFAULT_BASE_URL, PRIMARY_DATA_QUERY_CONTRACT

print(DEFAULT_BASE_URL)
print(PRIMARY_DATA_QUERY_CONTRACT["api"]["contract_endpoint"])
```

Once you have an Algenta Engine to talk to — self-hosted in your own
infrastructure (the default path for paid deployments) or Algenta's Cloud
Managed API — point the client at it. This example makes a real network
call and needs a real API key; there is no placeholder value that works:

```python
import os

from decision_engine import AlgentaClient

api_key = os.environ.get("ALGENTA_API_KEY")
if not api_key:
    raise RuntimeError("Set ALGENTA_API_KEY to a real Algenta Engine API key before running this example.")

client = AlgentaClient(
    api_key=api_key,
    base_url="http://localhost:8000",     # your self-hosted engine
    # base_url="https://api.algenta.ai",  # or Algenta's Cloud Managed API
)
datasets = client.list_datasets(search="orders", compact=True)
```

```ts
import { AlgentaClient } from "algenta-sdk";

const apiKey = process.env.ALGENTA_API_KEY;
if (!apiKey) {
  throw new Error("Set ALGENTA_API_KEY to a real Algenta Engine API key before running this example.");
}

const client = new AlgentaClient({
  apiKey,
  baseUrl: "http://localhost:8000",     // your self-hosted engine
  // baseUrl: "https://api.algenta.ai", // or Algenta's Cloud Managed API
});
const datasets = await client.listDatasets({ search: "orders", compact: true });
```

See [`packages/python-sdk/README.md`](./packages/python-sdk/README.md) and
[`packages/ts-sdk/README.md`](./packages/ts-sdk/README.md) for the full API
surface — governed queries, connectors, simulations, agent runs, repository
intelligence, and the local `Runtime` facade.

Runnable integration examples (LangGraph, ChatGPT Actions, n8n, Zapier, Power
Automate, Make, Azure AI Studio, Claude Desktop, Google Colab, and more) live
in [`examples/`](./examples).

## What is open source?

This repository contains Algenta's Python and TypeScript client SDKs. The
SDK source is licensed under **Apache-2.0** (see [LICENSE](./LICENSE) /
[NOTICE](./NOTICE)).

**The Algenta Engine/runtime is separate software and is not contained in
this repository.** Engine licensing, device entitlements, worker limits,
concurrency limits, and Server Compute Units are enforced independently by
the engine, subject to the separate Algenta Engine license.

The SDK is a plain HTTP client. It holds no license-signing keys, no
entitlement-enforcement logic, and no secret shared with the engine — every
entitlement claim is independently verified and enforced by the closed
engine, never by this SDK. Fork it, delete every check in it, or replace it
with your own HTTP client entirely — **modifying or replacing this SDK does
not change the execution capacity licensed to an Algenta Engine.** See
[SECURITY.md](./SECURITY.md) for what that means for vulnerability reports.

Algenta does not require hosted inference or telemetry for execution. Paid
licenses expand local execution and governance capacity rather than
charging per SDK call.

## Local execution

Algenta workloads execute against the Algenta Engine running in your own
infrastructure. This SDK is the developer interface to that local runtime —
it is not a hosted inference service, and no request data passes through
Algenta-operated servers to use it.

See [docs.algenta.ai](https://docs.algenta.ai) for connected and fully
air-gapped activation profiles.

## Verify a release

Every release built by [`release.yml`](./.github/workflows/release.yml) is
tied to:

- a protected `sdk-vX.Y.Z` source tag in this repository;
- the exact commit that tag points to;
- a release-authorization record, signed by Algenta's private engine repo's
  test suite, binding that commit + a contract-file digest to the version
  being released (see [`releases/`](./releases)).

`release.yml` refuses to build or publish anything unless all of the above
independently agree — see
[`scripts/verify_release_authorization.py`](./scripts/verify_release_authorization.py).

## Contributing

Bug fixes, framework integrations, docs, and tests are welcome — see
[CONTRIBUTING.md](./CONTRIBUTING.md). Requests for new API capabilities
usually require a change on Algenta's private API first; open an issue
describing the capability rather than a PR against the generated contract
files (also covered in CONTRIBUTING.md).

Please also read [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

## Community

- [Discord](https://discord.gg/w8NDsph9an)
- [Docs](https://docs.algenta.ai)
- community@algenta.ai

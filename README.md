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

```python
from decision_engine import AlgentaClient

client = AlgentaClient(api_key="...", base_url="https://api.algenta.ai")
datasets = client.list_datasets(search="orders", compact=True)
```

```ts
import { AlgentaClient } from "algenta-sdk";

const client = new AlgentaClient({ apiKey: "...", baseUrl: "https://api.algenta.ai" });
const datasets = await client.listDatasets({ search: "orders", compact: true });
```

See [`packages/python-sdk/README.md`](./packages/python-sdk/README.md) and
[`packages/ts-sdk/README.md`](./packages/ts-sdk/README.md) for the full API
surface — governed queries, connectors, simulations, agent runs, repository
intelligence, and the local `Runtime` facade.

## License boundary

This repository contains Algenta's client SDKs and is licensed under
**Apache-2.0** (see [LICENSE](./LICENSE) / [NOTICE](./NOTICE)). The **Algenta
Engine/runtime is separately distributed and subject to the Algenta Engine
license** — it is not included here, and nothing in this repository grants
rights to it.

The SDK is a plain HTTP client. It holds no license-signing keys, no
entitlement-enforcement logic, and no secret shared with the engine — every
entitlement claim is independently verified and enforced by the closed
engine, never by this SDK. Fork it, delete every check in it, or replace it
with your own HTTP client entirely — none of that can grant additional
licensed capacity on an Algenta Engine. See [SECURITY.md](./SECURITY.md) for
what that means for vulnerability reports.

## Contributing

Bug fixes, framework integrations, docs, and tests are welcome — see
[CONTRIBUTING.md](./CONTRIBUTING.md). Requests for new API capabilities
usually require a change on Algenta's private API first; open an issue
describing the capability rather than a PR against the generated contract
files (also covered in CONTRIBUTING.md).

Please also read [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

## Community

- [Discord](https://algenta.ai/discord)
- [Docs](https://docs.algenta.ai)
- community@algenta.ai

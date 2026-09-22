<div align="center">

# Algenta SDK

**Python and TypeScript client libraries and the official MCP server for [Algenta](https://algenta.ai) — self-hosted building blocks for AI applications.**

[![CI](https://github.com/thyn-ai/algenta-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/thyn-ai/algenta-sdk/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/algenta-sdk?label=PyPI)](https://pypi.org/project/algenta-sdk/)
[![npm](https://img.shields.io/npm/v/algenta-sdk?label=npm)](https://www.npmjs.com/package/algenta-sdk)
[![codecov](https://codecov.io/gh/thyn-ai/algenta-sdk/branch/main/graph/badge.svg)](https://codecov.io/gh/thyn-ai/algenta-sdk)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/thyn-ai/algenta-sdk/badge)](https://scorecard.dev/viewer/?uri=github.com/thyn-ai/algenta-sdk)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)
[![All Contributors](https://img.shields.io/badge/all_contributors-0-orange.svg)](#contributors)

📖 **Full documentation: [GitHub Wiki](https://github.com/thyn-ai/algenta-sdk/wiki)**

[Docs](https://docs.algenta.ai) · [Python SDK](./packages/python-sdk) · [TypeScript SDK](./packages/ts-sdk) · [MCP server](./packages/mcp) · [Integrations](https://github.com/thyn-ai/algenta-integrations) · [Examples](./examples) · [Contributing](./CONTRIBUTING.md)

</div>

Custom Mojo kernels give Algenta its speed. Your team never writes a line of
Mojo — the blocks speak Python and TypeScript. On your infrastructure, not
ours. These SDKs are how Python and TypeScript call the engine: typed access
to governed data queries, Monte Carlo simulations and recommendations,
decision memory with execution receipts that pin the policy and schema
snapshots each execution ran under, agent runs with human-in-the-loop
approvals, managed connectors, and a full audit trail — enforced by the
engine, never by client-side convention.

## MCP server

**MCP server (`algenta-mcp`)** — the official MCP server for Algenta lives in
THIS repository at [`packages/mcp/`](./packages/mcp) (implementation:
`packages/mcp/algenta_mcp`; stdio transport by default, Streamable HTTP
optional). Install it with `pip install algenta-mcp` and run it as the
`algenta-mcp` command; it is also on the official MCP Registry as
`io.github.thyn-ai/algenta`. The framework integrations (LangChain, LlamaIndex,
Vercel AI SDK, …) are what live in the companion repository
[thyn-ai/algenta-integrations](https://github.com/thyn-ai/algenta-integrations)
— not the MCP server.

## Installation

```bash
pip install algenta-sdk       # Python 3.12+
npm install algenta-sdk       # TypeScript / JavaScript, Node.js 18+
```

## Quickstart

Both clients read `ALGENTA_API_KEY` from the environment and default to
Algenta's hosted API at `https://api.algenta.ai`.

**Python** — note the import name is `decision_engine` (see
[Legacy names](#legacy-names)):

```python
from decision_engine import AlgentaClient

client = AlgentaClient()  # reads ALGENTA_API_KEY; defaults to https://api.algenta.ai

datasets = client.list_datasets(search="orders", compact=True)
summary = client.get_dataset_summary(datasets.datasets[0].dataset_id)
result = client.query_with_metadata(
    {
        "dataset_id": summary.dataset_id,
        "metric": {"hint": "gross_revenue"},
        "aggregation": "sum",
    }
)
print(result.data.result)
```

**TypeScript:**

```ts
import { AlgentaClient } from "algenta-sdk";

const client = new AlgentaClient(); // reads ALGENTA_API_KEY; defaults to https://api.algenta.ai

const datasets = await client.listDatasets({ search: "orders", compact: true });
const summary = await client.getDatasetSummary(datasets.datasets[0].dataset_id);
const result = await client.queryWithMetadata({
  dataset_id: summary.dataset_id,
  metric: { hint: "gross_revenue" },
  aggregation: "sum",
});
console.log(result.data.result);
```

**Self-hosted engine?** Point the client at your own deployment —
`AlgentaClient(base_url="http://localhost:8000")` in Python,
`new AlgentaClient({ baseUrl: "http://localhost:8000" })` in TypeScript — and
use the API key provisioned by your operator. The `self_hosted` and
`air_gapped` deployment profiles fail closed: they never silently fall back to
Algenta's cloud. Framework integrations in
[thyn-ai/algenta-integrations](https://github.com/thyn-ai/algenta-integrations)
take the opposite default on purpose: they are self-hosted-first, resolve their
endpoint from `ALGENTA_BASE_URL` or an explicit `base_url`, and never default or
fall back to the hosted API.

The full API surface — governed queries, connectors, simulations, jobs,
triggers, agent runs, decisions, repository intelligence, and the TypeScript
local `Runtime` facade — is documented in
[`packages/python-sdk/README.md`](./packages/python-sdk/README.md) and
[`packages/ts-sdk/README.md`](./packages/ts-sdk/README.md), with runnable
projects in [`examples/`](./examples). The MCP server lives in this repository
(see [MCP server](#mcp-server) above); framework integrations (LangChain,
LlamaIndex, Vercel AI SDK, and more) live in the companion repository
[thyn-ai/algenta-integrations](https://github.com/thyn-ai/algenta-integrations).

## Errors, retries, and timeouts

Both SDKs raise the same exception taxonomy. Every error carries the HTTP
status, the engine's machine-readable `error_code`, and — in Python — the
engine-assigned `request_id`; validation failures additionally expose
per-field details via `field_errors` (Python) / `fieldErrors` (TypeScript).

| Exception | HTTP status | Raised when | Retried by default |
| --- | --- | --- | --- |
| `AuthenticationError` | 401 | Missing or invalid API key | No |
| `NotFoundError` | 404 | Resource does not exist | No |
| `ValidationError` | 422 | Request failed schema validation | No |
| `RateLimitError` | 429 | Quota or rate limit exceeded | Yes — honors the engine's `Retry-After` (`retry_after` / `retryAfter`, default 60s) |
| `ServerError` | 5xx | Engine-side failure | Yes — exponential backoff |
| `DecisionEngineError` | any | Base class for all of the above | — |

Transient network errors are retried on the same policy as 5xx responses. The
Python SDK additionally never retries one rate-limit code,
`inline_preview_rate_limited`.

| Setting | Python | TypeScript | Default |
| --- | --- | --- | --- |
| Request timeout | `timeout` (seconds) | `timeout` (milliseconds) | 120 |
| Retries per request | `max_retries` | `maxRetries` | 3 |

## Legacy names

The SDK was renamed to Algenta partway through its history. For backward
compatibility, the legacy names below still work — existing code and
deployment configurations do not need to change:

- **Python import name** — the PyPI package is `algenta-sdk`, but the
  importable module remains `decision_engine`:
  `from decision_engine import AlgentaClient`.
- **Client aliases** — `CodnaClient` (and `AsyncCodnaClient` in Python) remain
  exported as aliases of `AlgentaClient` in both SDKs.
- **Environment variables** — `DE_API_KEY`, `DE_BASE_URL`, and
  `ALGENTA_API_URL` are still accepted alongside the canonical
  `ALGENTA_API_KEY` and `ALGENTA_BASE_URL`.

The published API contract guarantees a 90-day deprecation window
(`DEPRECATION_WINDOW_DAYS`) before any legacy name is removed.

## Powered by Mojo

The engine's compute kernels — simulation, scoring, and local query
execution — are written in [Mojo](https://www.modular.com/mojo) and are
proprietary. They are distributed as signed `algenta-runtime-native` wheels
and are **not** part of this repository.

What is open, here and under Apache-2.0: both SDKs, the published API contract
they are generated from, the client/runtime wire protocol they speak, and
runnable examples — including [`examples/mojo-quickstart/`](./examples/mojo-quickstart),
a minimal end-to-end walkthrough of calling the native runtime through the SDK.

![Mojo FFI quickstart: pixi run demo against the signed native runtime](./docs/assets/mojo-quickstart-demo.gif)

## What is open source?

This repository contains Algenta's Python and TypeScript client SDKs and the
official MCP server ([`packages/mcp/`](./packages/mcp)), licensed
under **Apache-2.0** (see [LICENSE](./LICENSE) and [NOTICE](./NOTICE)).

**The Algenta engine itself is closed source and is not contained in this
repository.** Engine licensing, device entitlements, worker limits,
concurrency limits, and Server Compute Units are enforced independently by the
engine, subject to the separate Algenta Engine license.

The SDK is a plain HTTP client. It holds no license-signing keys, no
entitlement-enforcement logic, and no secret shared with the engine — every
entitlement claim is independently verified and enforced by the closed engine,
never by this SDK. Fork it, delete every check in it, or replace it with your
own HTTP client entirely — **modifying or replacing this SDK does not change
the execution capacity licensed to an Algenta engine.** See
[SECURITY.md](./SECURITY.md) for what that means for vulnerability reports.

Algenta does not require hosted inference or telemetry for execution. Paid
licenses expand local execution and governance capacity rather than charging
per SDK call.

## Verify a release

Every release built by [`release.yml`](./.github/workflows/release.yml) is
tied to:

- a protected `sdk-vX.Y.Z` source tag in this repository;
- the exact commit that tag points to;
- a release-authorization record, signed by the internal release pipeline
  after the engine's test suite has validated the commit, binding that
  commit and a contract-file digest to the version being released (see
  [`releases/`](./releases)).

`release.yml` refuses to build or publish anything unless all of the above
independently agree — see
[`scripts/verify_release_authorization.py`](./scripts/verify_release_authorization.py).

Each [GitHub Release](https://github.com/thyn-ai/algenta-sdk/releases) cut
since signing was added (September 2026) carries, next to the wheel, the sdist
and `release-manifest.json`:

- a keyless [Sigstore](https://www.sigstore.dev/) signature bundle per asset
  (`<asset>.sigstore.json`), signed by the `release.yml` run itself;
- SLSA build provenance covering all three assets (`multiple.intoto.jsonl`),
  from the [SLSA generic generator](https://github.com/slsa-framework/slsa-github-generator).

To check an asset against both, with `VERSION` set to the release version
(`VERSION=1.0.15` for tag `sdk-v1.0.15`):

```bash
pipx run sigstore verify identity "algenta_sdk-${VERSION}-py3-none-any.whl" \
  --bundle "algenta_sdk-${VERSION}-py3-none-any.whl.sigstore.json" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --cert-identity "https://github.com/thyn-ai/algenta-sdk/.github/workflows/release.yml@refs/tags/sdk-v${VERSION}"

slsa-verifier verify-artifact "algenta_sdk-${VERSION}-py3-none-any.whl" \
  --provenance-path multiple.intoto.jsonl \
  --source-uri github.com/thyn-ai/algenta-sdk \
  --source-tag "sdk-v${VERSION}"
```

A release published through `release.yml`'s `workflow_dispatch` path was
signed from the dispatched branch, so its certificate identity ends in
`@refs/heads/main` instead of the tag; the bundle records which.

## Versioning

Both packages share one version number, since they wrap one API contract, and
follow [Semantic Versioning](https://semver.org/):

- **Patch** — bug fixes and documentation; no API surface change.
- **Minor** — backward-compatible additions (new methods, new optional
  fields).
- **Major** — breaking changes to exported symbols, required fields, or
  behavior, announced in advance through the deprecation window above.

Release history lives in [CHANGELOG.md](./CHANGELOG.md).

## Contributing

Bug fixes, framework integrations, docs, and tests are welcome — see
[CONTRIBUTING.md](./CONTRIBUTING.md). There is no CLA: contributions are
licensed inbound=outbound under Apache-2.0, per GitHub's Terms of Service.
Requests for new API capabilities usually require a change on Algenta's
private API first; open an issue describing the capability rather than a PR
against the generated contract files (also covered in CONTRIBUTING.md).

Please also read [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

- **Security reports** → [SECURITY.md](./SECURITY.md) (never a public issue)
- **Project direction and maintainership** → [GOVERNANCE.md](./GOVERNANCE.md)
- **Getting help** → [SUPPORT.md](./SUPPORT.md)

## Contributors

Thanks to everyone who contributes to this project — we follow the
[all-contributors](https://allcontributors.org) specification and recognize
contributions of [every kind](https://allcontributors.org/docs/en/emoji-key),
not just code.

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

## Community

- [Discord](https://discord.gg/w8NDsph9an)
- [Docs](https://docs.algenta.ai)
- community@algenta.ai

## Related repositories

Open-source tooling around Algenta, from the Algenta team. The Algenta engine itself is proprietary; everything listed here is Apache-2.0. Issues and discussions are welcome in whichever repository owns the code.

- [thyn-ai/algenta-sdk](https://github.com/thyn-ai/algenta-sdk) (this repository) — Python and TypeScript SDKs for Algenta plus the official MCP server ([`packages/mcp/`](./packages/mcp)): governed data queries, simulations, decision memory with execution receipts, agent runs with approvals.
- [thyn-ai/algenta-integrations](https://github.com/thyn-ai/algenta-integrations) — Framework integrations for Algenta: LangChain, LlamaIndex, pydantic-ai, MAF, Haystack, LiteLLM, Ray Serve, vLLM, Vercel AI SDK and n8n.
- [thyn-ai/mojo-kernels](https://github.com/thyn-ai/mojo-kernels) — Clean-room Mojo kernels as drop-in accelerators for popular Python/TypeScript libraries, with bit-exact parity and pure-language fallbacks.
- [thyn-ai/security-toolchain](https://github.com/thyn-ai/security-toolchain) — The pinned, checksum-verified security toolchain (Gitleaks, Opengrep, OSV-Scanner, Trivy config, actionlint) that every thyn-ai repository runs locally and in CI.
- [thyn-ai/feedback](https://github.com/thyn-ai/feedback) — Public issue intake for the open-source tooling around Algenta and for the Codna GitHub App.
- [thyn-ai/codna-action](https://github.com/thyn-ai/codna-action) — GitHub Action for Codna: fix, review or secure a repository in CI through the same packaged local runtime the CLI uses.

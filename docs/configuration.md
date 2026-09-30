<!-- SPDX-License-Identifier: Apache-2.0 -->

# Configuration reference

This page lists every public constructor option, environment variable, and default for the Python and TypeScript SDK clients. Values shown are current as of the SDK version in this repository.

## Python client

### Client classes

| Class | Description |
| --- | --- |
| `AlgentaClient` | Preferred synchronous client. |
| `DecisionEngineClient` | Backward-compatible synchronous alias for `AlgentaClient`. |
| `CodnaClient` | Backward-compatible alias that resolves to `AlgentaClient`. |
| `AsyncAlgentaClient` | Preferred asynchronous (`asyncio`) client. |
| `AsyncDecisionEngineClient` | Backward-compatible asynchronous alias for `AsyncAlgentaClient`. |
| `AsyncCodnaClient` | Backward-compatible alias that resolves to `AsyncAlgentaClient`. |

All synchronous classes share the same constructor signature. All asynchronous classes share the same constructor signature.

### Constructor options

```python
from decision_engine import AlgentaClient, AsyncAlgentaClient

sync_client = AlgentaClient(
    api_key="live_...",      # optional; falls back to environment
    base_url="...",          # optional; falls back to environment or default
    timeout=120.0,           # optional; seconds
    max_retries=3,           # optional
)

async_client = AsyncAlgentaClient(
    api_key="live_...",
    base_url="...",
    timeout=120.0,
    max_retries=3,
)
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `str \| None` | `None` | API key used for `Authorization: Bearer ...`. When omitted, the client reads `ALGENTA_API_KEY` and then the legacy `DE_API_KEY`. |
| `base_url` | `str \| None` | `None` | API base URL. When omitted, the client reads `ALGENTA_BASE_URL`, then `DE_BASE_URL`, then `ALGENTA_API_URL`, then `https://api.algenta.ai`. |
| `timeout` | `float` | `120.0` | Request timeout in **seconds**. |
| `max_retries` | `int` | `3` | Maximum retry attempts for transient failures (429 and 5xx responses). The first request does not count as a retry. |

### Environment variables

#### Authentication and endpoint

| Variable | Used by | Description |
| --- | --- | --- |
| `ALGENTA_API_KEY` | Python client | Primary API key. |
| `DE_API_KEY` | Python client | Legacy API key; accepted only if `ALGENTA_API_KEY` is unset. |
| `ALGENTA_BASE_URL` | Python client | Primary API base URL override. |
| `DE_BASE_URL` | Python client | Legacy base URL override. |
| `ALGENTA_API_URL` | Python client | Alternate base URL override; lowest precedence of the three URL variables. |

Precedence for `api_key`: constructor argument > `ALGENTA_API_KEY` > `DE_API_KEY`.
Precedence for `base_url`: constructor argument > `ALGENTA_BASE_URL` > `DE_BASE_URL` > `ALGENTA_API_URL` > `https://api.algenta.ai`.

#### Deployment profiles

| Variable | Used by | Description |
| --- | --- | --- |
| `ALGENTA_DEPLOYMENT_MODE` | Python client | Deployment mode: `saas` (default), `self_hosted`, `air_gapped`, or other engine-supported values. `self_hosted` and `air_gapped` enable the private profile. |
| `ALGENTA_DISABLE_CLOUD` | Python client | Boolean-style override (`1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off`). When true, behaves like a private profile even if `ALGENTA_DEPLOYMENT_MODE` is `saas`. |

Private profiles fail closed: if `ALGENTA_DEPLOYMENT_MODE` is `self_hosted` or `air_gapped` (or `ALGENTA_DISABLE_CLOUD` is true) and the resolved `base_url` points to an Algenta-owned host such as `api.algenta.ai`, the constructor raises `ValueError`. Configure a self-hosted `base_url` or one of the URL environment variables.

#### Console and key URLs

| Variable | Used by | Description |
| --- | --- | --- |
| `ALGENTA_APP_BASE_URL` | Python client | Base URL of the Algenta web console. Defaults to `https://app.algenta.ai` in SaaS mode. |
| `APP_BASE_URL` | Python client | Legacy alias for `ALGENTA_APP_BASE_URL`. |
| `DE_APP_BASE_URL` | Python client | Legacy alias for `ALGENTA_APP_BASE_URL`. |

These affect the URL returned in API-key help text and are used when constructing self-hosted console links in private profiles.

#### Device and runtime identifiers

| Variable | Used by | Description |
| --- | --- | --- |
| `ALGENTA_DEVICE_ID` | Python client | Explicit device identifier sent as `X-Algenta-Device-Id`. Must be 16–64 characters. |
| `DE_DEVICE_ID` | Python client | Legacy alias for `ALGENTA_DEVICE_ID`. |
| `ALGENTA_RUNTIME_DIR` | Python client | Directory used for the generated install ID fallback. Defaults to `~/.algenta/runtime`. |

When no device ID is explicitly configured, the SDK derives a stable device ID from the machine's OS-level identifier (macOS `IOPlatformUUID`, Linux `/etc/machine-id`/`/var/lib/dbus/machine-id`, Windows `MachineGuid`) and persists a UUID fallback in `ALGENTA_RUNTIME_DIR`.

The SDK always sends the following device headers when a device ID is available:

- `X-Algenta-Device-Id`
- `X-Algenta-Platform`
- `X-Algenta-Platform-Version`
- `X-Algenta-Hostname-Hash`
- `X-Algenta-SDK-Version`

### Defaults

| Constant | Value | Meaning |
| --- | --- | --- |
| `DEFAULT_BASE_URL` | `https://api.algenta.ai` | Hosted API base URL. |
| `DEFAULT_TIMEOUT` | `120.0` | Request timeout in seconds. |
| `DEFAULT_MAX_RETRIES` | `3` | Maximum retries per request. |
| `DEFAULT_RETRY_AFTER_SECONDS` | `60` | Fallback seconds to wait when a 429 response lacks a `Retry-After` header. |
| `RATE_LIMIT_BACKOFF_BASE_SECONDS` | `5` | Exponential backoff base for rate-limit retries. |
| `SERVER_ERROR_BACKOFF_BASE_SECONDS` | `1` | Exponential backoff base for server-error retries. |

### Timeouts, retries, and proxy behavior

The Python client uses `httpx` under the hood.

- Retries are attempted for HTTP `429` and `5xx` responses only. `4xx` errors other than `429` fail fast.
- For `429`, the client honors the `Retry-After` response header when present; otherwise it waits `5 * 2^attempt` seconds.
- For `5xx`, the client waits `1 * 2^attempt` seconds.
- Proxy configuration is not exposed as a constructor option. `httpx` honors the standard environment variables `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and their lowercase equivalents, plus `NO_PROXY`/`no_proxy` for exclusions.

## TypeScript client

### Client classes

| Class | Description |
| --- | --- |
| `AlgentaClient` | Preferred client class. |
| `DecisionEngineClient` | Underlying class name; exported for backward compatibility. |
| `CodnaClient` | Backward-compatible alias that resolves to `AlgentaClient`. |

All three names refer to the same implementation.

### Constructor options

The constructor accepts a single `DecisionEngineClientConfig` object:

```typescript
import { AlgentaClient } from 'algenta-sdk';

const client = new AlgentaClient({
  apiKey: 'live_...',       // optional; falls back to environment
  baseUrl: '...',           // optional; falls back to environment or default
  timeout: 120_000,         // optional; milliseconds
  maxRetries: 3,            // optional
  defaultHeaders: {         // optional
    'X-Custom-Header': 'value',
  },
});
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `apiKey` | `string \| undefined` | `undefined` | API key used for `Authorization: Bearer ...`. When omitted, the client reads `ALGENTA_API_KEY` and then the legacy `DE_API_KEY` from `process.env` in Node.js. In browsers, pass the key explicitly. |
| `baseUrl` | `string \| undefined` | `undefined` | API base URL. When omitted, the client reads `ALGENTA_BASE_URL`, then `DE_BASE_URL`, then `ALGENTA_API_URL`, then `https://api.algenta.ai`. |
| `timeout` | `number` | `120_000` | Request timeout in **milliseconds**. |
| `maxRetries` | `number` | `3` | Maximum retry attempts for transient failures (429 and 5xx responses). The first request does not count as a retry. |
| `defaultHeaders` | `Record<string, string>` | `{}` | Extra headers sent with every request. You can override `X-Algenta-Device-Id` here; it must be 16–64 characters. |

### Environment variables

| Variable | Used by | Description |
| --- | --- | --- |
| `ALGENTA_API_KEY` | TypeScript client (Node.js) | Primary API key. |
| `DE_API_KEY` | TypeScript client (Node.js) | Legacy API key; accepted only if `ALGENTA_API_KEY` is unset. |
| `ALGENTA_BASE_URL` | TypeScript client (Node.js) | Primary API base URL override. |
| `DE_BASE_URL` | TypeScript client (Node.js) | Legacy base URL override. |
| `ALGENTA_API_URL` | TypeScript client (Node.js) | Alternate base URL override; lowest precedence of the three URL variables. |
| `ALGENTA_DEPLOYMENT_MODE` | TypeScript client (Node.js) | Same semantics as the Python client. |
| `ALGENTA_DISABLE_CLOUD` | TypeScript client (Node.js) | Same semantics as the Python client. |
| `ALGENTA_APP_BASE_URL` | TypeScript client (Node.js) | Same semantics as the Python client. |
| `APP_BASE_URL` | TypeScript client (Node.js) | Legacy alias. |
| `DE_APP_BASE_URL` | TypeScript client (Node.js) | Legacy alias. |
| `ALGENTA_DEVICE_ID` | TypeScript client (Node.js / browser) | Explicit device identifier. |
| `DE_DEVICE_ID` | TypeScript client (Node.js / browser) | Legacy alias. |
| `ALGENTA_RUNTIME_DIR` | TypeScript client (Node.js) | Directory used for the generated install ID fallback. Defaults to `~/.algenta/runtime`. |
| `HOME` / `USERPROFILE` | TypeScript client (Node.js) | Used to locate the default runtime directory. |
| `HOSTNAME` / `COMPUTERNAME` | TypeScript client (Node.js) | Used as part of the device fingerprint. |

Precedence for `apiKey`: constructor argument > `ALGENTA_API_KEY` > `DE_API_KEY`.
Precedence for `baseUrl`: constructor argument > `ALGENTA_BASE_URL` > `DE_BASE_URL` > `ALGENTA_API_URL` > `https://api.algenta.ai`.

Private profiles fail closed with the same rules as the Python client.

### Defaults

| Constant | Value | Meaning |
| --- | --- | --- |
| `DEFAULT_BASE_URL` | `https://api.algenta.ai` | Hosted API base URL. |
| `DEFAULT_TIMEOUT` | `120_000` | Request timeout in milliseconds. |
| `DEFAULT_MAX_RETRIES` | `3` | Maximum retries per request. |
| `DEFAULT_JOIN_PATH_HOPS` | `4` | Default hop limit for query join-path traversal. |
| `MAX_JOIN_PATH_HOPS` | `6` | Maximum allowed hop limit for query join-path traversal. |

### Timeouts, retries, and proxy behavior

The TypeScript client uses the standard `fetch` API.

- Retries are attempted for HTTP `429` and `5xx` responses only. `4xx` errors other than `429` fail fast.
- For `429`, the client honors the `Retry-After` response header when present; otherwise it waits `2^attempt` seconds.
- For `5xx`, the client waits `2^attempt` seconds.
- The SDK does not expose a proxy option. In Node.js, proxy an HTTP client at the runtime level (for example, via a global dispatcher or by running the process behind a proxy-aware wrapper) or provide a custom `fetch` replacement if your runtime supports it.

## Cross-reference: Python and TypeScript option names

| Concept | Python | TypeScript |
| --- | --- | --- |
| API key argument | `api_key` | `apiKey` |
| Base URL argument | `base_url` | `baseUrl` |
| Timeout argument | `timeout` (seconds) | `timeout` (milliseconds) |
| Retries argument | `max_retries` | `maxRetries` |
| Extra headers | Not configurable at construction | `defaultHeaders` |
| Primary API key env var | `ALGENTA_API_KEY` | `ALGENTA_API_KEY` |
| Legacy API key env var | `DE_API_KEY` | `DE_API_KEY` |
| Primary base URL env var | `ALGENTA_BASE_URL` | `ALGENTA_BASE_URL` |
| Legacy base URL env var | `DE_BASE_URL` | `DE_BASE_URL` |
| Alternate base URL env var | `ALGENTA_API_URL` | `ALGENTA_API_URL` |
| Console base URL env vars | `ALGENTA_APP_BASE_URL`, `APP_BASE_URL`, `DE_APP_BASE_URL` | `ALGENTA_APP_BASE_URL`, `APP_BASE_URL`, `DE_APP_BASE_URL` |
| Deployment mode env var | `ALGENTA_DEPLOYMENT_MODE` | `ALGENTA_DEPLOYMENT_MODE` |
| Disable cloud env var | `ALGENTA_DISABLE_CLOUD` | `ALGENTA_DISABLE_CLOUD` |
| Device ID env vars | `ALGENTA_DEVICE_ID`, `DE_DEVICE_ID` | `ALGENTA_DEVICE_ID`, `DE_DEVICE_ID` |
| Runtime directory env var | `ALGENTA_RUNTIME_DIR` | `ALGENTA_RUNTIME_DIR` |

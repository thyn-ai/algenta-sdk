# Error code reference

This page maps every exception exported by the Algenta SDK to the engine error payload that raises it, and gives a recommended recovery action for each.

## Engine error payload shape

All error responses from the Algenta HTTP API share the same top-level shape:

```json
{
  "error": {
    "code": "error_code",
    "message": "Human-readable explanation",
    "details": {}
  },
  "request_id": "req_..."
}
```

- `error.code` — a stable machine-readable identifier. The SDK exposes this as `error_code` (Python) or `errorCode` (TypeScript).
- `error.message` — the human-readable description returned by the engine.
- `error.details` — structured context. For `422` validation failures this is usually a list of field-level errors or an object containing `validation_errors`.
- `request_id` — the request identifier to include when contacting support.

The SDK reads the error body first, then falls back to the `X-Request-Id` header if the body does not contain a `request_id`.

## Recovery actions

| Action | Meaning |
|--------|---------|
| **Retry with backoff** | The failure is usually transient. Use exponential backoff and respect `Retry-After` when present. |
| **Retry once** | Some failures may recover on a second attempt, but repeated retries are unlikely to help. |
| **Abort and surface** | Fix the request or credentials before retrying. Automatic retries are not appropriate. |
| **Abort and inspect** | Check the error details or the runtime configuration. Retrying the same request will produce the same result. |

## Python SDK exceptions

All Python exceptions live in `decision_engine.exceptions` and are re-exported from `decision_engine`.

### `DecisionEngineError`

Base exception for every SDK error. It is raised directly for any non-success HTTP status that does not map to a more specific subclass (for example, `400`, `403`, or any unrecognized 4xx).

**When it is raised**

- HTTP status is not `2xx` and does not match a specific subclass.
- A client-side failure such as an invalid payload fragment occurs before the request is sent.

**Example payload**

```json
{
  "error": {
    "code": "bad_request",
    "message": "Malformed request body",
    "details": {}
  },
  "request_id": "req_abc123"
}
```

**Recommended recovery**

Abort and surface. Inspect `error_code` and `details` to decide whether the request can be corrected.

### `AuthenticationError`

Raised when the engine returns HTTP `401`.

**When it is raised**

- Missing API key.
- Invalid or revoked API key.
- Expired token.

**Example payload**

```json
{
  "error": {
    "code": "invalid_key",
    "message": "Invalid API key",
    "details": {}
  },
  "request_id": "req_auth_001"
}
```

**Recommended recovery**

Abort and surface. Check `ALGENTA_API_KEY` or `DE_API_KEY` and verify the key has not been rotated or revoked.

### `NotFoundError`

Raised when the engine returns HTTP `404`.

**When it is raised**

- A requested dataset, connector, decision, agent run, job, or other resource does not exist.
- A stale identifier was used after a resource was deleted.

**Example payload**

```json
{
  "error": {
    "code": "dataset_not_found",
    "message": "dataset missing",
    "details": { "dataset_id": "ds_123" }
  },
  "request_id": "req_nf_001"
}
```

**Recommended recovery**

Abort and surface. Confirm the identifier is correct and the resource still exists.

### `ValidationError`

Raised when the engine returns HTTP `422`.

**When it is raised**

- A required field is missing or has an invalid value.
- A filter, query plan, or capability execution request violates the contract.

**Example payload with field errors**

```json
{
  "error": {
    "code": "validation_error",
    "message": "validation error",
    "details": [
      { "field": "limit", "message": "must be positive" }
    ]
  },
  "request_id": "req_val_001"
}
```

**Example payload with nested validation errors**

```json
{
  "error": {
    "code": "validation_error",
    "message": "validation error",
    "details": {
      "validation_errors": [
        { "loc": ["body", "limit"], "msg": "required" }
      ]
    }
  },
  "request_id": "req_val_002"
}
```

**Recommended recovery**

Abort and surface. Read `field_errors` (or `validation_errors`) to correct the request. Retrying the same payload will fail again.

### `RateLimitError`

Raised when the engine returns HTTP `429`.

**When it is raised**

- Per-minute or per-account request quota exceeded.
- Burst limit exceeded.

**Example payload**

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "slow down",
    "details": {}
  },
  "request_id": "req_rl_001"
}
```

The SDK parses the `Retry-After` header and exposes it as `retry_after` (Python) or `retryAfter` (TypeScript). If the header is absent the default is `60` seconds.

**Recommended recovery**

Retry with backoff. Honor `retry_after`/`retryAfter` and add jitter to avoid thundering herds.

### `ServerError`

Raised when the engine returns HTTP `5xx`.

**When it is raised**

- An unexpected server-side failure.
- A temporary upstream outage.

**Example payload**

```json
{
  "error": {
    "code": "server_error",
    "message": "boom",
    "details": {}
  },
  "request_id": "req_se_001"
}
```

**Recommended recovery**

Retry with backoff. If the error persists, abort and include `request_id` when contacting support.

## TypeScript SDK exceptions

All TypeScript exceptions are exported from the `algenta-sdk` package root.

### `DecisionEngineError`

Base exception for every HTTP-client error. It is raised directly for any non-success status that does not map to a more specific subclass.

**When it is raised**

- HTTP status is not `2xx` and does not match a specific subclass.
- A client-side validation failure occurs before the request is sent.

**Example payload**

```json
{
  "error": {
    "code": "bad_request",
    "message": "Malformed request body",
    "details": {}
  },
  "request_id": "req_abc123"
}
```

**Recommended recovery**

Abort and surface. Inspect `errorCode` and `details` to decide whether the request can be corrected.

### `AuthenticationError`

Raised when the engine returns HTTP `401`.

**When it is raised**

- Missing API key.
- Invalid or revoked API key.
- Expired token.

**Example payload**

```json
{
  "error": {
    "code": "invalid_key",
    "message": "Invalid API key",
    "details": {}
  },
  "request_id": "req_auth_001"
}
```

**Recommended recovery**

Abort and surface. Verify `ALGENTA_API_KEY` or `DE_API_KEY` before retrying.

### `NotFoundError`

Raised when the engine returns HTTP `404`.

**When it is raised**

- A requested resource does not exist.
- A stale identifier was used.

**Example payload**

```json
{
  "error": {
    "code": "dataset_not_found",
    "message": "dataset missing",
    "details": { "dataset_id": "ds_123" }
  },
  "request_id": "req_nf_001"
}
```

**Recommended recovery**

Abort and surface. Confirm the resource identifier is still valid.

### `ValidationError`

Raised when the engine returns HTTP `422`.

**When it is raised**

- Request validation failed.
- A field value is out of range or malformed.

**Example payload**

```json
{
  "error": {
    "code": "validation_error",
    "message": "validation error",
    "details": [
      { "field": "limit", "message": "must be positive" }
    ]
  },
  "request_id": "req_val_001"
}
```

**Recommended recovery**

Abort and surface. Read `validationErrors` (or `fieldErrors`) and correct the request.

### `RateLimitError`

Raised when the engine returns HTTP `429`.

**When it is raised**

- Quota or rate limit exceeded.

**Example payload**

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "slow down",
    "details": {}
  },
  "request_id": "req_rl_001"
}
```

The SDK parses `Retry-After` and exposes it as `retryAfter`.

**Recommended recovery**

Retry with backoff. Honor `retryAfter` and add jitter.

### `ServerError`

Raised when the engine returns HTTP `5xx`.

**When it is raised**

- Unexpected server-side failure.
- Temporary upstream outage.

**Example payload**

```json
{
  "error": {
    "code": "server_error",
    "message": "boom",
    "details": {}
  },
  "request_id": "req_se_001"
}
```

**Recommended recovery**

Retry with backoff. If the error persists, abort and include `request_id` when contacting support.

### `RuntimeError`

Base exception for local runtime failures in the TypeScript SDK.

**When it is raised**

- A local runtime operation fails (for example, an invalid runtime configuration or an error returned by the local daemon).

**Example payload**

```json
{
  "code": "runtime_operation_failed",
  "message": "Local runtime returned an error",
  "details": { "module": "evaluate" }
}
```

**Recommended recovery**

Abort and inspect. Check `code` and `details` for the underlying cause. This is not an HTTP error, so retrying the SDK call only makes sense if the local daemon state has changed.

### `RuntimeConfigurationError`

Subclass of `RuntimeError` raised when the runtime is misconfigured.

**When it is raised**

- Missing or invalid runtime mode.
- Missing required local runtime path.
- Incompatible capability ownership settings.

**Example payload**

```json
{
  "code": "runtime_configuration_error",
  "message": "Self-hosted mode requires a baseUrl",
  "details": {}
}
```

**Recommended recovery**

Abort and inspect. Correct the `Runtime` configuration before retrying.

### `RuntimeValidationError`

Subclass of `RuntimeError` raised when a runtime request is invalid.

**When it is raised**

- A local capability execution request violates the runtime contract.
- Required runtime parameters are missing.

**Example payload**

```json
{
  "code": "runtime_validation_error",
  "message": "Missing required parameter 'capability_id'",
  "details": { "field": "capability_id" }
}
```

**Recommended recovery**

Abort and surface. Fix the request payload before retrying.

### `MojoRuntimeError`

Base exception for errors that originate in the Mojo compute kernel layer.

**When it is raised**

- A local Mojo function invocation fails.
- The kernel returns an error status.

**Example payload**

```json
{
  "code": "mojo_runtime_error",
  "message": "Kernel evaluation failed",
  "details": { "module": "math.kernels" }
}
```

**Recommended recovery**

Abort and inspect. Check the kernel code and input data. Retrying with the same inputs will usually produce the same error.

### `MojoRuntimeConfigurationError`

Subclass of `MojoRuntimeError` raised for Mojo configuration problems.

**When it is raised**

- The Mojo runtime is configured with an unsupported precision or backend.
- Required kernel options are missing.

**Example payload**

```json
{
  "code": "mojo_configuration_error",
  "message": "Unsupported precision 'float16' for this kernel",
  "details": { "precision": "float16" }
}
```

**Recommended recovery**

Abort and inspect. Update the `MojoRuntime` configuration.

### `MojoModuleNotRegisteredError`

Subclass of `MojoRuntimeError` raised when a requested module is not registered.

**When it is raised**

- A library module name is misspelled.
- The module was not loaded before invocation.

**Example payload**

```json
{
  "code": "mojo_module_not_registered",
  "message": "Module 'custom.ops' is not registered",
  "details": { "module": "custom.ops" }
}
```

**Recommended recovery**

Abort and surface. Verify the module name and registration order.

### `MojoFunctionNotRegisteredError`

Subclass of `MojoRuntimeError` raised when a requested function is not registered.

**When it is raised**

- A function name is misspelled.
- The function belongs to a module that was not loaded.

**Example payload**

```json
{
  "code": "mojo_function_not_registered",
  "message": "Function 'score' is not registered in module 'custom.ops'",
  "details": { "module": "custom.ops", "function": "score" }
}
```

**Recommended recovery**

Abort and surface. Verify the function and module names.

### `MojoExecutionError`

Subclass of `MojoRuntimeError` raised when a registered function fails during execution.

**When it is raised**

- Division by zero, overflow, or another numerical failure.
- A kernel invariant is violated at runtime.

**Example payload**

```json
{
  "code": "mojo_execution_error",
  "message": "Division by zero in kernel 'normalize'",
  "details": { "kernel": "normalize" }
}
```

**Recommended recovery**

Abort and inspect. Guard inputs for numerical edge cases before retrying.

### `QueryError`

Raised when a columnar query plan is rejected by the engine or is invalid before it is sent.

**When it is raised**

- An unsupported aggregation or join is used.
- A plan references a column that does not exist.
- A window function is misconfigured.

**Example payload**

```json
{
  "code": "query_op_failed",
  "message": "Unknown aggregation 'median'",
  "op_index": 3
}
```

**Recommended recovery**

Abort and surface. Inspect `code` and `opIndex` to correct the query plan.

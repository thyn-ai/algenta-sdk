# Algenta — Out-of-Band Approval Webhook Receiver

A minimal TypeScript webhook server that receives an Algenta agent-run approval
callback, validates the payload, and resumes the pending decision.

Use this when your execution policy requires a human or external system to
approve a tool call before the run continues.

## What it does

1. Listens on `POST /webhooks/approval`.
2. Validates that the payload carries an `approval_required` event for a
   specific `run_id`.
3. Re-fetches the run from the Algenta engine to confirm current state.
4. Calls `POST /v1/agent/runs/{run_id}/approve`.
5. Calls `POST /v1/agent/runs/{run_id}/resume` to continue execution.
6. Returns a structured summary of the action taken.

## Sequence diagram

```text
┌─────────────┐          ┌──────────────┐          ┌─────────────────┐
│ Algenta     │          │ Your webhook │          │ Approver        │
│ engine      │          │ receiver     │          │ (human/system)  │
└──────┬──────┘          └──────┬───────┘          └────────┬────────┘
       │                        │                           │
       │ run enters             │                           │
       │ "requires_approval"    │                           │
       │───────────────────────>│                           │
       │   POST /webhooks/      │                           │
       │   approval             │                           │
       │                        │                           │
       │                        │  approval granted         │
       │                        │<──────────────────────────│
       │                        │                           │
       │                        │  validate payload         │
       │                        │  + callback token         │
       │                        │───────────────────────────│
       │                        │                           │
       │                        │  GET /v1/agent/runs/{id}  │
       │<───────────────────────│                           │
       │                        │                           │
       │                        │  POST /v1/agent/runs/{id}/approve
       │<───────────────────────│                           │
       │                        │                           │
       │                        │  POST /v1/agent/runs/{id}/resume
       │<───────────────────────│                           │
       │                        │                           │
       │ run continues          │                           │
       │───────────────────────>│                           │
       │                        │                           │
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ALGENTA_API_KEY` | yes* | — | Algenta API key (preferred). |
| `DE_API_KEY` | yes* | — | Legacy API key, accepted when `ALGENTA_API_KEY` is absent. |
| `ALGENTA_BASE_URL` | yes* | `https://api.algenta.ai` | Self-hosted engine base URL. |
| `DE_BASE_URL` | yes* | — | Legacy base URL override. |
| `ALGENTA_API_URL` | yes* | — | Legacy base URL override. |
| `WEBHOOK_PORT` | no | `3000` | Port the receiver binds to. |
| `WEBHOOK_SECRET` | no | — | If set, payloads must include a matching `callback_token`. |
| `APPROVAL_ACTIONS` | no | `approve,resume` | Comma-separated list of actions to invoke: `approve`, `resume`, or both. |

\* One of the listed keys/URL vars must be provided. The receiver follows the
same precedence and private-profile (`self_hosted`, `air_gapped`) rules as the
TypeScript SDK: `ALGENTA_*` env vars are canonical, legacy `DE_*` and
`ALGENTA_API_URL` are accepted for compatibility, and private profiles fail
closed instead of silently falling back to Algenta cloud.

## Run it

Install dependencies once:

```bash
cd examples/approvals-webhook
npm install
```

The example imports `algenta-sdk` from the local `packages/ts-sdk/src`
directory via a `tsconfig.json` path mapping, so no separate build step is
needed.

Start the receiver against a self-hosted engine:

```bash
export ALGENTA_API_KEY="your-api-key"
export ALGENTA_BASE_URL="https://engine.example.com"
export WEBHOOK_SECRET="a-shared-secret-for-callback-verification"

npm start
```

The server prints the webhook URL:

```text
Algenta approvals webhook receiver listening at http://localhost:3000/webhooks/approval
Targeting Algenta engine: https://engine.example.com
Webhook callback-token verification is enabled.
```

## Send a test callback

```bash
curl -X POST http://localhost:3000/webhooks/approval \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run_01J8X...",
    "event_type": "approval_required",
    "status": "requires_approval",
    "pending_action": "approve",
    "callback_token": "a-shared-secret-for-callback-verification"
  }'
```

Expected response on success:

```json
{
  "success": true,
  "result": {
    "run_id": "run_01J8X...",
    "initial_status": "requires_approval",
    "actions_taken": ["approve", "resume"],
    "final_status": "running",
    "final_pending_action": null
  }
}
```

## Test locally

The test suite starts a local stub engine and exercises the receiver end-to-end
with no network calls and no real LLM:

```bash
npm test
```

## Security notes

- Run this receiver behind HTTPS in production. The local `http://` URL is for
  development only.
- Set `WEBHOOK_SECRET` and verify `callback_token` on every inbound request.
- The receiver re-fetches the run state before acting, so a stale or replayed
  webhook cannot silently advance a run that has already changed state.

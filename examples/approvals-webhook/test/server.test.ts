import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { AlgentaClient } from "algenta-sdk";
import type { AgentRunResponse } from "algenta-sdk";
import { loadConfig } from "../src/config.js";
import { createServer, startServer, stopServer } from "../src/server.js";

const API_KEY = "test-api-key";

process.env.ALGENTA_API_KEY = API_KEY;
process.env.ALGENTA_BASE_URL = "http://127.0.0.1:1";

interface StubEngine {
  server: http.Server;
  url: string;
  requests: { method: string; path: string; body: unknown }[];
  close(): Promise<void>;
}

function makeAgentRunResponse(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    run_id: "run-test-1",
    status: "requires_approval",
    task: "test task",
    output_format: "text",
    approval_mode: "manual",
    pending_action: "approve",
    tools_available: [],
    tools_used: [],
    steps: [],
    created_at: "2026-09-30T00:00:00.000Z",
    updated_at: "2026-09-30T00:00:00.000Z",
    ...overrides,
  };
}

async function startStubEngine(): Promise<StubEngine> {
  const requests: { method: string; path: string; body: unknown }[] = [];

  const server = http.createServer((req, res) => {
    let bodyRaw = "";
    req.on("data", chunk => {
      bodyRaw += chunk as string;
    });
    req.on("end", () => {
      const body = bodyRaw.length > 0 ? (JSON.parse(bodyRaw) as unknown) : undefined;
      requests.push({ method: req.method ?? "UNKNOWN", path: req.url ?? "/", body });

      const auth = req.headers.authorization;
      if (auth !== `Bearer ${API_KEY}`) {
        sendJson(res, 401, { error: "unauthorized" });
        return;
      }

      if (req.method === "GET" && req.url === "/v1/agent/runs/run-test-1") {
        sendJson(res, 200, makeAgentRunResponse());
        return;
      }

      if (req.method === "POST" && req.url === "/v1/agent/runs/run-test-1/approve") {
        sendJson(res, 200, makeAgentRunResponse({ status: "paused", pending_action: "resume" }));
        return;
      }

      if (req.method === "POST" && req.url === "/v1/agent/runs/run-test-1/resume") {
        sendJson(res, 200, makeAgentRunResponse({ status: "running", pending_action: null }));
        return;
      }

      sendJson(res, 404, { error: "not found" });
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const address = server.address();
  assert.ok(address !== null && typeof address === "object", "stub engine address must be an object");
  const url = `http://127.0.0.1:${address.port}`;

  return {
    server,
    url,
    requests,
    close(): Promise<void> {
      return new Promise((resolve, reject) => {
        server.close(error => (error ? reject(error) : resolve()));
      });
    },
  };
}

function sendJson(res: http.ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, { "Content-Type": "application/json" });
  res.end(body);
}

async function postJson(url: string, payload: unknown): Promise<{ status: number; body: unknown }> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  const body = text.length > 0 ? (JSON.parse(text) as unknown) : undefined;
  return { status: response.status, body };
}

async function withServers(
  options: { webhookSecret?: string; approvalActions?: ("approve" | "resume")[] },
  fn: (ctx: { webhookUrl: string; stub: StubEngine }) => Promise<void>,
): Promise<void> {
  const stub = await startStubEngine();
  try {
    const config = loadConfig();
    config.apiKey = API_KEY;
    config.baseUrl = stub.url;
    config.port = 0;
    config.webhookSecret = options.webhookSecret;
    if (options.approvalActions !== undefined) {
      config.approvalActions = options.approvalActions;
    }

    const webhookServer = createServer(config, {
      createClient: () =>
        new AlgentaClient({
          apiKey: API_KEY,
          baseUrl: stub.url,
          maxRetries: 0,
          timeout: 5_000,
        }),
      approvalActions: config.approvalActions,
    });

    await startServer(webhookServer);
    const address = webhookServer.server.address();
    assert.ok(address !== null && typeof address === "object");
    const webhookUrl = `http://127.0.0.1:${address.port}`;

    try {
      await fn({ webhookUrl, stub });
    } finally {
      await stopServer(webhookServer);
    }
  } finally {
    await stub.close();
  }
}

test("approves and resumes a run on a valid approval callback", async () => {
  await withServers({ webhookSecret: "shared-secret" }, async ({ webhookUrl, stub }) => {
    const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
      run_id: "run-test-1",
      event_type: "approval_required",
      status: "requires_approval",
      pending_action: "approve",
      callback_token: "shared-secret",
    });

    assert.equal(status, 200);
    const response = body as { success: boolean; result: Record<string, unknown> };
    assert.equal(response.success, true);
    assert.equal(response.result.run_id, "run-test-1");
    assert.equal(response.result.initial_status, "requires_approval");
    assert.deepEqual(response.result.actions_taken, ["approve", "resume"]);
    assert.equal(response.result.final_status, "running");
    assert.equal(response.result.final_pending_action, null);

    assert.equal(stub.requests.length, 3);
    assert.deepEqual(
      stub.requests.map(r => ({ method: r.method, path: r.path })),
      [
        { method: "GET", path: "/v1/agent/runs/run-test-1" },
        { method: "POST", path: "/v1/agent/runs/run-test-1/approve" },
        { method: "POST", path: "/v1/agent/runs/run-test-1/resume" },
      ],
    );
  });
});

test("rejects a payload with a mismatched callback token", async () => {
  await withServers({ webhookSecret: "shared-secret" }, async ({ webhookUrl }) => {
    const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
      run_id: "run-test-1",
      event_type: "approval_required",
      callback_token: "wrong-secret",
    });

    assert.equal(status, 400);
    const response = body as { error: { code: string } };
    assert.equal(response.error.code, "callback_token_mismatch");
  });
});

test("rejects a payload missing run_id", async () => {
  await withServers({}, async ({ webhookUrl }) => {
    const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
      event_type: "approval_required",
    });

    assert.equal(status, 400);
    const response = body as { error: { code: string } };
    assert.equal(response.error.code, "missing_run_id");
  });
});

test("rejects a payload with an unsupported event_type", async () => {
  await withServers({}, async ({ webhookUrl }) => {
    const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
      run_id: "run-test-1",
      event_type: "job_completed",
    });

    assert.equal(status, 400);
    const response = body as { error: { code: string } };
    assert.equal(response.error.code, "unsupported_event_type");
  });
});

test("rejects a payload with an unexpected status", async () => {
  await withServers({}, async ({ webhookUrl }) => {
    const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
      run_id: "run-test-1",
      event_type: "approval_required",
      status: "completed",
    });

    assert.equal(status, 400);
    const response = body as { error: { code: string } };
    assert.equal(response.error.code, "unexpected_status");
  });
});

test("returns 404 for unsupported paths", async () => {
  await withServers({}, async ({ webhookUrl }) => {
    const { status } = await postJson(`${webhookUrl}/webhooks/unknown`, {
      run_id: "run-test-1",
      event_type: "approval_required",
    });
    assert.equal(status, 404);
  });
});

test("returns 502 when the engine returns an error", async () => {
  const stub = await startStubEngine();
  try {
    const config = loadConfig();
    config.apiKey = API_KEY;
    config.baseUrl = stub.url;
    config.port = 0;

    const webhookServer = createServer(config, {
      createClient: () =>
        new AlgentaClient({
          apiKey: API_KEY,
          baseUrl: stub.url,
          maxRetries: 0,
          timeout: 5_000,
        }),
      approvalActions: ["approve", "resume"],
    });

    await startServer(webhookServer);
    const address = webhookServer.server.address();
    assert.ok(address !== null && typeof address === "object");
    const webhookUrl = `http://127.0.0.1:${address.port}`;

    try {
      const { status, body } = await postJson(`${webhookUrl}/webhooks/approval`, {
        run_id: "run-does-not-exist",
        event_type: "approval_required",
      });

      assert.equal(status, 502);
      const response = body as { error: { code: string } };
      assert.equal(response.error.code, "engine_request_failed");
    } finally {
      await stopServer(webhookServer);
    }
  } finally {
    await stub.close();
  }
});

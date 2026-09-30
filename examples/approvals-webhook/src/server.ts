import http from "node:http";
import type { WebhookServerConfig } from "./config.js";
import { createDefaultHandler, handleApprovalWebhook, type HandlerDependencies } from "./handler.js";
import { validateWebhookPayload } from "./validate.js";

export interface WebhookServer {
  server: http.Server;
  port: number;
  url: string;
}

export function createServer(config: WebhookServerConfig, deps?: HandlerDependencies): WebhookServer {
  const handler = deps ?? createDefaultHandler(config);

  const server = http.createServer(async (req, res) => {
    if (req.method !== "POST" || req.url !== "/webhooks/approval") {
      sendJson(res, 404, { error: { code: "not_found", message: "Only POST /webhooks/approval is supported." } });
      return;
    }

    let body: unknown;
    try {
      body = await readJsonBody(req);
    } catch (error) {
      sendJson(res, 400, {
        error: {
          code: "invalid_json",
          message: error instanceof Error ? error.message : "Unable to parse request body as JSON.",
        },
      });
      return;
    }

    const validation = validateWebhookPayload(body, { webhookSecret: config.webhookSecret });
    if (!validation.valid || validation.payload === undefined) {
      sendJson(res, 400, {
        error: {
          code: validation.code ?? "validation_failed",
          message: validation.error ?? "Webhook payload validation failed.",
        },
      });
      return;
    }

    try {
      const result = await handleApprovalWebhook(validation.payload, handler);
      sendJson(res, 200, { success: true, result });
    } catch (error) {
      sendJson(res, 502, {
        error: {
          code: "engine_request_failed",
          message: error instanceof Error ? error.message : "Request to the Algenta engine failed.",
        },
      });
    }
  });

  const port = config.port;
  return {
    server,
    port,
    url: `http://localhost:${port}`,
  };
}

export function startServer(server: WebhookServer): Promise<void> {
  return new Promise((resolve, reject) => {
    server.server.once("error", reject);
    server.server.listen(server.port, () => {
      server.server.off("error", reject);
      resolve();
    });
  });
}

export function stopServer(server: WebhookServer): Promise<void> {
  return new Promise((resolve, reject) => {
    server.server.close(error => {
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    });
  });
}

function readJsonBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", chunk => chunks.push(chunk as Buffer));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (raw.length === 0) {
        reject(new Error("Request body is empty."));
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res: http.ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

import { DEFAULT_BASE_URL } from "algenta-sdk";
import type { WebhookServerConfig } from "./types.js";

export type { WebhookServerConfig } from "./types.js";

// Mirror of the Algenta-owned host lists in packages/ts-sdk/src/contract.ts.
// Keeping them here lets the example stay self-contained instead of reaching
// into SDK internals or generated contract internals.
const ALGENTA_OWNED_HOSTS = new Set([
  "algenta.ai",
  "api.algenta.ai",
  "docs.algenta.ai",
  "app.algenta.ai",
  "cdn.algenta.ai",
]);
const ALGENTA_OWNED_SUFFIXES = [".algenta.ai", ".algenta.io"];
const PRIVATE_DEPLOYMENT_MODES = new Set(["self_hosted", "air_gapped"]);

function envValue(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function parseOptionalBoolean(value: string | undefined): boolean | undefined {
  if (value === undefined) {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  throw new Error("ALGENTA_DISABLE_CLOUD must be a boolean-style value when set.");
}

function cloudDisabled(): boolean {
  const explicit = parseOptionalBoolean(envValue("ALGENTA_DISABLE_CLOUD"));
  if (explicit !== undefined) {
    return explicit;
  }
  return PRIVATE_DEPLOYMENT_MODES.has((envValue("ALGENTA_DEPLOYMENT_MODE") ?? "saas").toLowerCase());
}

function isAlgentaOwnedBaseUrl(baseUrl: string): boolean {
  const hostname = new URL(baseUrl).hostname.trim().toLowerCase();
  if (ALGENTA_OWNED_HOSTS.has(hostname)) {
    return true;
  }
  return ALGENTA_OWNED_SUFFIXES.some(suffix => hostname.endsWith(suffix));
}

function normalizeBaseUrl(baseUrl: string, component: string): string {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  try {
    const parsed = new URL(normalized);
    if (!parsed.protocol || !parsed.hostname) {
      throw new Error("missing host");
    }
  } catch {
    throw new Error(`${component} baseUrl must be an absolute URL including scheme and host.`);
  }
  return normalized;
}

function resolveBaseUrl(): string {
  const configuredBaseUrl =
    envValue("ALGENTA_BASE_URL") ?? envValue("DE_BASE_URL") ?? envValue("ALGENTA_API_URL");
  const normalized = normalizeBaseUrl(configuredBaseUrl ?? DEFAULT_BASE_URL, "Algenta approvals webhook receiver");
  if (cloudDisabled() && isAlgentaOwnedBaseUrl(normalized)) {
    throw new Error(
      "Algenta approvals webhook receiver private profiles cannot target Algenta-owned cloud URLs. Configure a self-hosted baseUrl or ALGENTA_BASE_URL / DE_BASE_URL / ALGENTA_API_URL.",
    );
  }
  return normalized;
}

function resolveApiKey(): string {
  const apiKey = envValue("ALGENTA_API_KEY") ?? envValue("DE_API_KEY");
  if (!apiKey) {
    throw new Error("Algenta approvals webhook receiver requires ALGENTA_API_KEY or DE_API_KEY to be set.");
  }
  return apiKey;
}

function parsePort(raw: string | undefined): number {
  if (raw === undefined) {
    return 3000;
  }
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`WEBHOOK_PORT must be an integer between 1 and 65535, got: ${raw}`);
  }
  return port;
}

function parseApprovalActions(raw: string | undefined): ("approve" | "resume")[] {
  if (raw === undefined) {
    return ["approve", "resume"];
  }
  const actions = raw
    .split(",")
    .map(part => part.trim().toLowerCase())
    .filter(part => part.length > 0);
  for (const action of actions) {
    if (action !== "approve" && action !== "resume") {
      throw new Error(`APPROVAL_ACTIONS contains unsupported action: ${action}`);
    }
  }
  if (actions.length === 0) {
    throw new Error("APPROVAL_ACTIONS must contain at least one of: approve, resume");
  }
  return actions as ("approve" | "resume")[];
}

export function loadConfig(): WebhookServerConfig {
  return {
    apiKey: resolveApiKey(),
    baseUrl: resolveBaseUrl(),
    port: parsePort(envValue("WEBHOOK_PORT")),
    webhookSecret: envValue("WEBHOOK_SECRET"),
    approvalActions: parseApprovalActions(envValue("APPROVAL_ACTIONS")),
  };
}

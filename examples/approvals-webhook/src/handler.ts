import { AlgentaClient } from "algenta-sdk";
import type { AgentRunResponse } from "algenta-sdk";
import type { WebhookServerConfig } from "./config.js";
import type { ApprovalWebhookPayload } from "./types.js";

export interface ApprovalResult {
  run_id: string;
  initial_status: string;
  actions_taken: string[];
  final_status: string;
  final_pending_action: string | null;
}

export interface HandlerDependencies {
  createClient: () => AlgentaClient;
  approvalActions: ("approve" | "resume")[];
}

export function createDefaultHandler(config: WebhookServerConfig): HandlerDependencies {
  return {
    createClient: () =>
      new AlgentaClient({
        apiKey: config.apiKey,
        baseUrl: config.baseUrl,
      }),
    approvalActions: config.approvalActions,
  };
}

export async function handleApprovalWebhook(
  payload: ApprovalWebhookPayload,
  deps: HandlerDependencies,
): Promise<ApprovalResult> {
  const client = deps.createClient();
  const runId = payload.run_id;

  // Re-fetch the run so the receiver always acts on the current engine state,
  // not whatever the webhook happened to carry.
  const run = await client.getAgentRun(runId);
  const initialStatus = run.status;
  const actionsTaken: string[] = [];

  if (run.status === "requires_approval" && deps.approvalActions.includes("approve")) {
    await client.approveAgentRun(runId);
    actionsTaken.push("approve");
  }

  let finalRun: AgentRunResponse = run;
  if (deps.approvalActions.includes("resume")) {
    finalRun = await client.resumeAgentRun(runId);
    actionsTaken.push("resume");
  }

  return {
    run_id: runId,
    initial_status: initialStatus,
    actions_taken: actionsTaken,
    final_status: finalRun.status,
    final_pending_action: finalRun.pending_action ?? null,
  };
}

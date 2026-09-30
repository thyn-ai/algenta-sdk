export interface WebhookServerConfig {
  apiKey: string;
  baseUrl: string;
  port: number;
  webhookSecret: string | undefined;
  /**
   * Which follow-up actions to invoke after validating the webhook.
   * The default mirrors the engine's out-of-band approval flow:
   * approve the paused tool call, then resume the run.
   */
  approvalActions: ("approve" | "resume")[];
}

export interface ApprovalWebhookPayload {
  run_id: string;
  event_type: "approval_required";
  status?: "requires_approval";
  pending_action?: "approve";
  callback_token?: string;
}

export interface ValidationResult {
  valid: boolean;
  payload?: ApprovalWebhookPayload;
  error?: string;
  code?: string;
}

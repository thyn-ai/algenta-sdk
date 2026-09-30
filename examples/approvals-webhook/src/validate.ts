import type { ApprovalWebhookPayload, ValidationResult } from "./types.js";

function hasString(value: unknown, key: string): value is Record<string, unknown> & { [K in typeof key]: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>)[key] === "string"
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function validateWebhookPayload(
  body: unknown,
  options?: { webhookSecret?: string },
): ValidationResult {
  if (body === null || typeof body !== "object") {
    return { valid: false, error: "Payload must be a JSON object.", code: "invalid_payload_type" };
  }

  const record = body as Record<string, unknown>;

  if (!hasString(record, "run_id") || !isNonEmptyString(record.run_id)) {
    return { valid: false, error: "Payload must contain a non-empty string run_id.", code: "missing_run_id" };
  }

  if (!hasString(record, "event_type") || record.event_type !== "approval_required") {
    return {
      valid: false,
      error: "Payload event_type must be 'approval_required'.",
      code: "unsupported_event_type",
    };
  }

  if (record.status !== undefined && record.status !== "requires_approval") {
    return {
      valid: false,
      error: "When provided, status must be 'requires_approval'.",
      code: "unexpected_status",
    };
  }

  if (record.pending_action !== undefined && record.pending_action !== "approve") {
    return {
      valid: false,
      error: "When provided, pending_action must be 'approve'.",
      code: "unexpected_pending_action",
    };
  }

  if (
    record.callback_token !== undefined &&
    (typeof record.callback_token !== "string" || record.callback_token.length === 0)
  ) {
    return {
      valid: false,
      error: "When provided, callback_token must be a non-empty string.",
      code: "invalid_callback_token",
    };
  }

  const token = record.callback_token as string | undefined;
  if (options?.webhookSecret !== undefined) {
    if (token === undefined) {
      return {
        valid: false,
        error: "Payload is missing the required callback_token.",
        code: "missing_callback_token",
      };
    }
    if (!timingSafeEqual(token, options.webhookSecret)) {
      return {
        valid: false,
        error: "callback_token does not match the configured secret.",
        code: "callback_token_mismatch",
      };
    }
  }

  return {
    valid: true,
    payload: {
      run_id: record.run_id,
      event_type: "approval_required",
      status: record.status as "requires_approval" | undefined,
      pending_action: record.pending_action as "approve" | undefined,
      callback_token: token,
    },
  };
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    // Hash the shorter value to avoid leaking the expected length.
    return false;
  }
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}

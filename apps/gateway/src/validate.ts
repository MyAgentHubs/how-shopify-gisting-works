import type { Limits } from "./limits";
import type { GatewayError, Result } from "./types";
import { fail, ok } from "./types";

export interface ChatRequest {
  readonly sessionId: string;
  readonly message: string;
  readonly turnstileToken: string | null;
  readonly ticket: string | null;
  readonly mode: Mode;
}

type Mode = "gist" | "full";

const MODES: readonly string[] = ["gist", "full"];

function decodeMode(body: Record<string, unknown>): Mode | null {
  const value = "mode" in body ? body["mode"] : "gist";
  return typeof value === "string" && MODES.includes(value) ? (value as Mode) : null;
}

function invalid(reason: string): Result<never, GatewayError> {
  return fail({ kind: "InvalidRequest", reason });
}

function field(body: Record<string, unknown>, name: string): string | null {
  const value = body[name];
  return typeof value === "string" ? value : null;
}

function optionalField(body: Record<string, unknown>, name: string): string | null | undefined {
  return name in body ? field(body, name) : undefined;
}

async function readBody(request: Request, limits: Limits): Promise<Result<string, GatewayError>> {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > limits.maxBodyBytes) {
    return fail({ kind: "TooLong", max: limits.maxBodyBytes });
  }
  const text = await request.text();
  if (new TextEncoder().encode(text).length > limits.maxBodyBytes) {
    return fail({ kind: "TooLong", max: limits.maxBodyBytes });
  }
  return ok(text);
}

function parseJsonObject(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text);
    const isObject = typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
    return isObject ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

interface Credentials {
  readonly turnstileToken: string | null;
  readonly ticket: string | null;
}

function credentials(body: Record<string, unknown>): Result<Credentials, GatewayError> {
  const turnstileToken = optionalField(body, "turnstile_token");
  const ticket = optionalField(body, "ticket");
  if (turnstileToken === null || ticket === null) {
    return invalid("missing field");
  }
  if (turnstileToken === undefined && ticket === undefined) {
    return invalid("missing field");
  }
  if (turnstileToken === "" || ticket === "") {
    return invalid("empty field");
  }
  return ok({ turnstileToken: turnstileToken ?? null, ticket: ticket ?? null });
}

function decode(body: Record<string, unknown>, limits: Limits): Result<ChatRequest, GatewayError> {
  const sessionId = field(body, "session_id");
  const message = field(body, "message");
  const held = credentials(body);
  const mode = decodeMode(body);
  if (sessionId === null || message === null) {
    return invalid("missing field");
  }
  if (!held.ok) {
    return held;
  }
  if (mode === null) {
    return invalid("bad mode");
  }
  if (!new RegExp(limits.sessionIdPattern).test(sessionId)) {
    return invalid("bad session id");
  }
  if (message.trim() === "") {
    return invalid("empty field");
  }
  if (Array.from(message).length > limits.maxMessageChars) {
    return fail({ kind: "TooLong", max: limits.maxMessageChars });
  }
  return ok({ sessionId, message, ...held.value, mode });
}

export async function parseChatRequest(
  request: Request,
  limits: Limits,
): Promise<Result<ChatRequest, GatewayError>> {
  const raw = await readBody(request, limits);
  if (!raw.ok) {
    return raw;
  }
  const body = parseJsonObject(raw.value);
  return body === null ? invalid("body is not a JSON object") : decode(body, limits);
}

import type { Fields, PublicTrace } from "./trace.ts";
import { isFields, parsePublicTrace } from "./trace.ts";

export type Mode = "gist" | "full";

export interface ChatRequest {
  readonly sessionId: string;
  readonly message: string;
  readonly turnstileToken?: string;
  readonly ticket?: string;
  readonly mode: Mode;
  readonly timeoutMs: number;
}

export interface ReplayTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

export type ReplayReason = "quota" | "offline";

export type FailureReason = "check" | "network" | "http" | "malformed" | "unexpected";

export type ChatOutcome =
  | {
      readonly kind: "reply";
      readonly answer: string;
      readonly trace: PublicTrace;
      readonly ticket?: string;
    }
  | {
      readonly kind: "replay";
      readonly reason: ReplayReason;
      readonly turns: readonly ReplayTurn[];
      readonly ticket?: string;
    }
  | { readonly kind: "failed"; readonly status: number; readonly reason: FailureReason };

export interface Gateway {
  chat(request: ChatRequest): Promise<ChatOutcome>;
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

const CHAT_PATH = "/api/chat";
const TICKET_HEADER = "x-gisting-ticket";
const TICKET_SHAPE = /^1\.[1-9][0-9]{0,9}\.[A-Za-z0-9_-]{43}$/;
const NO_RESPONSE = 0;

function failed(status: number, reason: FailureReason): ChatOutcome {
  return { kind: "failed", status, reason };
}

function parseTurns(raw: unknown): ReplayTurn[] | null {
  if (!Array.isArray(raw)) {
    return null;
  }
  const turns: ReplayTurn[] = [];
  for (const item of raw as { role?: unknown; content?: unknown }[]) {
    const role = item.role === "user" || item.role === "assistant" ? item.role : null;
    if (role === null || typeof item.content !== "string") {
      return null;
    }
    turns.push({ role, content: item.content });
  }
  return turns;
}

function parseReason(raw: unknown): ReplayReason | null {
  return raw === "quota" || raw === "offline" ? raw : null;
}

function parseReplay(body: Fields, status: number): ChatOutcome {
  const turns = parseTurns(body["turns"]);
  const reason = parseReason(body["reason"]);
  return turns === null || reason === null ? failed(status, "malformed") : { kind: "replay", reason, turns };
}

function parseBody(body: unknown, status: number): ChatOutcome {
  if (!isFields(body)) {
    return failed(status, "malformed");
  }
  if (body["served_by"] === "replay") {
    return parseReplay(body, status);
  }
  const trace = parsePublicTrace(body["trace"]);
  const answer = body["answer"];
  if (typeof answer !== "string" || trace === null) {
    return failed(status, "malformed");
  }
  return { kind: "reply", answer, trace };
}

function withTicket(outcome: ChatOutcome, header: string | null): ChatOutcome {
  if (outcome.kind === "failed" || header === null || !TICKET_SHAPE.test(header)) {
    return outcome;
  }
  return { ...outcome, ticket: header };
}

function credentials(request: ChatRequest): Record<string, string> {
  const fields: Record<string, string> = {};
  if (request.ticket !== undefined && request.ticket !== "") {
    fields["ticket"] = request.ticket;
  }
  if (request.turnstileToken !== undefined && request.turnstileToken !== "") {
    fields["turnstile_token"] = request.turnstileToken;
  }
  return fields;
}

export function httpGateway(fetcher: Fetcher, url: string = CHAT_PATH): Gateway {
  return {
    async chat(request) {
      try {
        const response = await fetcher(url, {
          method: "POST",
          signal: AbortSignal.timeout(request.timeoutMs),
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            session_id: request.sessionId,
            message: request.message,
            ...credentials(request),
            mode: request.mode,
          }),
        });
        if (!response.ok) {
          return failed(response.status, "http");
        }
        const body: unknown = await response.json();
        return withTicket(parseBody(body, response.status), response.headers.get(TICKET_HEADER));
      } catch {
        return failed(NO_RESPONSE, "network");
      }
    },
  };
}

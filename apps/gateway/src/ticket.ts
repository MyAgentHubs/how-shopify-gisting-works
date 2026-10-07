import { normalizeIp } from "./ip-normalize";
import type { GatewayError, Result, TurnstileFailure } from "./types";
import { fail, ok } from "./types";

const VERSION = "1";
const KEY_LABEL = "gisting-chat-ticket-v1";
const MS_PER_SECOND = 1000;
const SHAPE = /^1\.(0|[1-9]\d{0,9})\.([A-Za-z0-9_-]{42}[AEIMQUYcgkosw048])$/;
const ENCODER = new TextEncoder();
const HMAC = { name: "HMAC", hash: "SHA-256" } as const;

export interface TicketWindow {
  readonly ttlSeconds: number;
  readonly skewSeconds: number;
}

export interface TicketSubject {
  readonly sessionId: string;
  readonly ip: string;
}

function refusal(reason: TurnstileFailure): Result<never, GatewayError> {
  return fail({ kind: "TurnstileFailed", reason });
}

async function ticketKey(salt: string): Promise<CryptoKey> {
  const saltKey = await crypto.subtle.importKey("raw", ENCODER.encode(salt), HMAC, false, ["sign"]);
  const derived = await crypto.subtle.sign("HMAC", saltKey, ENCODER.encode(KEY_LABEL));
  return crypto.subtle.importKey("raw", derived, HMAC, false, ["sign", "verify"]);
}

function signedText(subject: TicketSubject, exp: string): BufferSource {
  return ENCODER.encode([VERSION, subject.sessionId, exp, normalizeIp(subject.ip)].join("|"));
}

function encodeMac(mac: ArrayBuffer): string {
  const text = btoa(String.fromCharCode(...new Uint8Array(mac)));
  return text.replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function decodeMac(mac: string): Uint8Array<ArrayBuffer> {
  const text = `${mac.replaceAll("-", "+").replaceAll("_", "/")}=`;
  return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
}

export async function issueTicket(
  salt: string,
  subject: TicketSubject,
  now: Date,
  ttlSeconds: number,
): Promise<string> {
  const exp = String(Math.floor(now.getTime() / MS_PER_SECOND) + ttlSeconds);
  const mac = await crypto.subtle.sign("HMAC", await ticketKey(salt), signedText(subject, exp));
  return `${VERSION}.${exp}.${encodeMac(mac)}`;
}

export async function verifyTicket(
  salt: string,
  ticket: string,
  subject: TicketSubject,
  now: Date,
  window: TicketWindow,
): Promise<Result<true, GatewayError>> {
  const shape = SHAPE.exec(ticket);
  const [, exp = "", mac = ""] = shape ?? [];
  if (shape === null) {
    return refusal("ticket_malformed");
  }
  const nowSeconds = Math.floor(now.getTime() / MS_PER_SECOND);
  if (!(Number(exp) > nowSeconds)) {
    return refusal("ticket_expired");
  }
  if (!(Number(exp) <= nowSeconds + window.ttlSeconds + window.skewSeconds)) {
    return refusal("ticket_invalid");
  }
  const genuine = await crypto.subtle.verify("HMAC", await ticketKey(salt), decodeMac(mac), signedText(subject, exp));
  return genuine ? ok(true) : refusal("ticket_invalid");
}

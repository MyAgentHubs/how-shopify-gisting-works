export interface UiLimits {
  readonly maxMessages: number;
  readonly maxCompares: number;
  readonly maxMessageChars: number;
  readonly humanCheckWaitMs: number;
  readonly humanCheckInteractiveMs: number;
  readonly chatRequestMs: number;
  readonly ticketMarginMs: number;
  readonly exampleFlashMs: number;
  readonly busyAnimationMs: number;
}

export interface Session {
  readonly id: string;
  messages: number;
  compares: number;
  ticket: string | null;
}

const ID_BYTES = 16;
const HEX_DIGITS = 2;
const HEX_RADIX = 16;

export function newSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(ID_BYTES));
  return Array.from(bytes, (byte) => byte.toString(HEX_RADIX).padStart(HEX_DIGITS, "0")).join("");
}

export function createSession(id: string): Session {
  return { id, messages: 0, compares: 0, ticket: null };
}

export function canSend(session: Session, limits: UiLimits, message: string): boolean {
  const length = Array.from(message).length;
  return (
    message.trim() !== "" &&
    length <= limits.maxMessageChars &&
    session.messages < limits.maxMessages
  );
}

export function comparesLeft(session: Session, limits: UiLimits): number {
  return Math.max(0, limits.maxCompares - session.compares);
}

const LIMIT_KEYS = [
  "maxMessages",
  "maxCompares",
  "maxMessageChars",
  "humanCheckWaitMs",
  "humanCheckInteractiveMs",
  "chatRequestMs",
  "ticketMarginMs",
  "exampleFlashMs",
  "busyAnimationMs",
] as const;

export function parseLimits(raw: unknown): UiLimits {
  const fields = (raw ?? {}) as Record<string, unknown>;
  const counts = LIMIT_KEYS.map((key) => fields[key]);
  if (!counts.every((value) => typeof value === "number" && Number.isInteger(value) && value > 0)) {
    throw new TypeError(`limits need positive integers ${LIMIT_KEYS.join(", ")}`);
  }
  return Object.fromEntries(LIMIT_KEYS.map((key) => [key, fields[key]])) as unknown as UiLimits;
}

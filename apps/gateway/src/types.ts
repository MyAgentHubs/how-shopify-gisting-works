export type Result<T, E> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

export function ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

export function fail<E>(error: E): Result<never, E> {
  return { ok: false, error };
}

export type QuotaScope = "session" | "ip" | "site" | "full";

export type TurnstileFailure =
  | "rejected"
  | "timeout"
  | "unavailable"
  | "hostname_missing"
  | "hostname_mismatch"
  | "action_mismatch"
  | "ticket_malformed"
  | "ticket_expired"
  | "ticket_invalid";

export type GatewayError =
  | {
      readonly kind: "TurnstileFailed";
      readonly reason: TurnstileFailure;
      readonly detail?: string;
    }
  | { readonly kind: "QuotaExceeded"; readonly scope: QuotaScope }
  | { readonly kind: "TooLong"; readonly max: number }
  | { readonly kind: "InvalidRequest"; readonly reason: string }
  | { readonly kind: "UpstreamError"; readonly attempts: readonly string[] }
  | {
      readonly kind: "CounterUnavailable";
      readonly reason?: CounterFailureReason;
      readonly causeName?: string;
    }
  | { readonly kind: "ConfigMissing"; readonly missing: readonly string[] };

export type CounterFailureReason =
  | "durable_object_unreachable"
  | "durable_object_bad_reply"
  | "durable_object_timeout"
  | "counter_key_rejected";

export class CounterFailure extends Error {
  readonly reason: CounterFailureReason;

  constructor(reason: CounterFailureReason, options?: ErrorOptions) {
    super(reason, options);
    this.reason = reason;
  }
}

export function errorName(thrown: unknown): string {
  return thrown instanceof Error ? thrown.name : "NonError";
}

export interface Counter {
  increment(key: string, ttlSeconds: number, limit: number): Promise<number>;
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export interface LogEvent {
  readonly kind: GatewayError["kind"];
  readonly detail: string;
}

export interface Logger {
  record(event: LogEvent): void;
}

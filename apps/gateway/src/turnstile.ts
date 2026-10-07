import type { TurnstilePolicy } from "./turnstile-policy";
import type { Fetcher, GatewayError, Result, TurnstileFailure } from "./types";
import { fail, ok } from "./types";

const SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TIMEOUT_ERRORS = new Set(["TimeoutError", "AbortError"]);

const HTTP_OK = 200;
const MAX_HOSTNAME_CHARS = 253;
const NOT_PRINTABLE = /[^ -~]/g;
const ERROR_CODE = /^[a-z0-9-]{1,64}$/;

function failure(reason: TurnstileFailure, detail?: string): Result<never, GatewayError> {
  const kind = "TurnstileFailed";
  return fail(detail === undefined || detail === "" ? { kind, reason } : { kind, reason, detail });
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && TIMEOUT_ERRORS.has(error.name);
}

export interface Verdict {
  readonly success: boolean;
  readonly hostname?: string;
  readonly action?: string;
  readonly errorCodes: readonly string[];
}

function asRecord(body: unknown): Record<string, unknown> | null {
  return typeof body === "object" && body !== null && !Array.isArray(body)
    ? (body as Record<string, unknown>)
    : null;
}

function textField(record: Record<string, unknown>, name: string): { readonly [key: string]: string } {
  const value = record[name];
  return typeof value === "string" ? { [name]: value } : {};
}

function errorCodesOf(record: Record<string, unknown>): string[] {
  const codes = record["error-codes"];
  return Array.isArray(codes)
    ? codes.filter((code): code is string => typeof code === "string" && ERROR_CODE.test(code))
    : [];
}

function parseVerdict(body: unknown): Verdict | null {
  const record = asRecord(body);
  if (record === null) {
    return null;
  }
  return {
    success: record["success"] === true,
    ...textField(record, "hostname"),
    ...textField(record, "action"),
    errorCodes: errorCodesOf(record),
  };
}

async function readVerdict(response: Response): Promise<Verdict | null> {
  try {
    return parseVerdict(await response.json());
  } catch {
    return null;
  }
}

export async function requestVerdict(
  fetcher: Fetcher,
  secret: string,
  token: string,
  timeoutMs: number,
): Promise<Result<Verdict, GatewayError>> {
  const form = new URLSearchParams({ secret, response: token });
  let response: Response;
  try {
    response = await fetcher(SITEVERIFY_URL, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error: unknown) {
    return failure(isTimeout(error) ? "timeout" : "unavailable");
  }
  if (response.status !== HTTP_OK) {
    return failure("unavailable");
  }
  const verdict = await readVerdict(response);
  return verdict === null ? failure("unavailable") : ok(verdict);
}

function policyFailure(verdict: Verdict, policy: TurnstilePolicy): Result<true, GatewayError> {
  if (!verdict.success) {
    return failure("rejected", verdict.errorCodes.join(","));
  }
  if (verdict.hostname === undefined) {
    return failure("hostname_missing");
  }
  if (!policy.hostnames.has(verdict.hostname.toLowerCase())) {
    return failure("hostname_mismatch", verdict.hostname.slice(0, MAX_HOSTNAME_CHARS).replace(NOT_PRINTABLE, "?"));
  }
  return verdict.action === policy.action ? ok(true) : failure("action_mismatch");
}

export async function verifyTurnstile(
  fetcher: Fetcher,
  secret: string,
  token: string,
  timeoutMs: number,
  policy: TurnstilePolicy,
): Promise<Result<true, GatewayError>> {
  const verdict = await requestVerdict(fetcher, secret, token, timeoutMs);
  if (!verdict.ok) {
    return verdict;
  }
  return policyFailure(verdict.value, policy);
}

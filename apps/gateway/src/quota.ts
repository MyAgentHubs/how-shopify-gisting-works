import { utcDay } from "./day";
import type { Limits } from "./limits";
import type { Counter, GatewayError, QuotaScope, Result } from "./types";
import { CounterFailure, errorName, fail, ok } from "./types";

interface Check {
  readonly scope: QuotaScope;
  readonly key: string;
  readonly limit: number;
}

function checks(
  limits: Limits,
  subject: {
    readonly ipDigest: string;
    readonly sessionId: string;
    readonly mode: string;
  },
  day: string,
): Check[] {
  const { ipDigest, sessionId, mode } = subject;
  const full: Check[] =
    mode === "full"
      ? [
          {
            scope: "full",
            key: `full:${sessionId}`,
            limit: limits.maxFullComparesPerSession,
          },
        ]
      : [];
  return [
    ...full,
    {
      scope: "session",
      key: `session:${sessionId}`,
      limit: limits.maxMessagesPerSession,
    },
    {
      scope: "ip",
      key: `ip:${day}:${ipDigest}`,
      limit: limits.maxRequestsPerIpPerDay,
    },
    {
      scope: "site",
      key: `site:${day}`,
      limit: limits.maxRequestsPerSitePerDay,
    },
  ];
}

function unavailable(error: unknown): GatewayError {
  if (!(error instanceof CounterFailure)) {
    return { kind: "CounterUnavailable", causeName: errorName(error) };
  }
  return error.cause === undefined
    ? { kind: "CounterUnavailable", reason: error.reason }
    : { kind: "CounterUnavailable", reason: error.reason, causeName: errorName(error.cause) };
}

export async function enforceQuota(
  counter: Counter,
  limits: Limits,
  subject: {
    readonly ipDigest: string;
    readonly sessionId: string;
    readonly mode: string;
    readonly now: Date;
  },
): Promise<Result<true, GatewayError>> {
  const day = utcDay(subject.now);
  for (const check of checks(limits, subject, day)) {
    let count: number;
    try {
      count = await counter.increment(check.key, limits.counterTtlSeconds, check.limit);
    } catch (error) {
      return fail(unavailable(error));
    }
    if (!Number.isFinite(count) || count > check.limit) {
      return fail({ kind: "QuotaExceeded", scope: check.scope });
    }
  }
  return ok(true);
}

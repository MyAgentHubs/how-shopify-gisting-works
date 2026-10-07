import type { GatewayEnv } from "../src/config";
import type { Runtime } from "../src/handler";
import { limits } from "../src/limits";
import type { Counter, Fetcher, LogEvent } from "../src/types";
import type { TurnstilePolicy } from "../src/turnstile-policy";
import { turnstilePolicy } from "../src/turnstile-policy";
import policyData from "../turnstile.json";

const FRAGMENT_WIDTH = 8;

export function digestFragmentIn(text: string, digest: string): string | null {
  for (let start = 0; start + FRAGMENT_WIDTH <= digest.length; start += 1) {
    const fragment = digest.slice(start, start + FRAGMENT_WIDTH);
    if (text.includes(fragment)) {
      return fragment;
    }
  }
  return null;
}

export const CLIENT_IP = "203.0.113.77";
export const SESSION = "session-0001";
export const PRIMARY = "https://primary.example.test";
export const BACKUP = "https://backup.example.test";
export const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

export class MemoryCounter implements Counter {
  readonly counts = new Map<string, number>();
  failing = false;

  increment(key: string, _ttlSeconds: number, limit: number): Promise<number> {
    if (this.failing) {
      return Promise.reject(new Error("counter down"));
    }
    const held = this.counts.get(key) ?? 0;
    if (held >= limit) {
      return Promise.resolve(limit + 1);
    }
    this.counts.set(key, held + 1);
    return Promise.resolve(held + 1);
  }
}

export interface Call {
  readonly url: string;
  readonly init: RequestInit | undefined;
}

export type Route = (call: Call) => Response | Promise<Response>;

export function bodyOf(call: Call): string {
  const body = call.init?.body;
  return typeof body === "string" || body instanceof URLSearchParams ? body.toString() : "";
}

export function routedFetcher(routes: Readonly<Record<string, Route>>): {
  fetcher: Fetcher;
  calls: Call[];
} {
  const calls: Call[] = [];
  const fetcher: Fetcher = async (url, init) => {
    const call = { url, init };
    calls.push(call);
    const route = routes[url];
    if (route === undefined) {
      throw new Error(`unexpected fetch ${url}`);
    }
    return route(call);
  };
  return { fetcher, calls };
}

export function hang(call: Call): Promise<Response> {
  const signal = call.init?.signal;
  return new Promise((_resolve, reject) => {
    signal?.addEventListener("abort", () => {
      reject(signal.reason instanceof Error ? signal.reason : new Error("aborted"));
    });
  });
}

export const POLICY: TurnstilePolicy = turnstilePolicy([]);
export const GOOD_HOSTNAME = policyData.hostnames[0] ?? "";
export const GOOD_ACTION = policyData.action;

export function verdict(success: boolean, overrides: Readonly<Record<string, unknown>> = {}): Route {
  return () =>
    Response.json({ success, hostname: GOOD_HOSTNAME, action: GOOD_ACTION, ...overrides });
}

export function healthyBackend(base: string, body: string): Readonly<Record<string, Route>> {
  return {
    [`${base}/health`]: () => new Response("ok"),
    [`${base}/generate`]: () => new Response(body, { headers: { "content-type": "text/plain" } }),
  };
}

export function chatRequest(
  overrides: Readonly<Record<string, unknown>> = {},
  headers: Readonly<Record<string, string>> = { "cf-connecting-ip": CLIENT_IP },
): Request {
  const body = {
    session_id: SESSION,
    message: "where is my parcel",
    turnstile_token: "token-ok",
    ...overrides,
  };
  return new Request("https://gateway.example.test/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export function completeEnv(counter: Counter): GatewayEnv {
  return {
    GISTING_TURNSTILE_SECRET: "turnstile-secret",
    GISTING_IP_SALT: "ip-salt-0123456789-0123456789-abcdef",
    GISTING_PRIMARY_URL: PRIMARY,
    GISTING_BACKUP_URL: BACKUP,
    GISTING_ACCESS_CLIENT_ID: "access-id",
    GISTING_ACCESS_CLIENT_SECRET: "access-secret",
    GISTING_UPSTREAM_SECRET: "upstream-secret",
    GISTING_COUNTER: counter,
  };
}

export function envWithout(name: keyof GatewayEnv, counter: Counter): GatewayEnv {
  const entries = Object.entries(completeEnv(counter)).filter(([key]) => key !== name);
  return Object.fromEntries(entries);
}

export function runtimeWith(
  fetcher: Fetcher,
  overrides: Partial<Runtime> = {},
): { runtime: Runtime; events: LogEvent[] } {
  const events: LogEvent[] = [];
  const runtime: Runtime = {
    limits,
    fetcher,
    logger: { record: (event) => events.push(event) },
    now: () => new Date("2026-10-04T12:00:00Z"),
    replay: [],
    ...overrides,
  };
  return { runtime, events };
}

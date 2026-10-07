import { describe, expect, it } from "vitest";
import { handleChat } from "../src/handler";
import { limits } from "../src/limits";
import { issueTicket, verifyTicket } from "../src/ticket";
import { parseChatRequest } from "../src/validate";
import {
  BACKUP,
  CLIENT_IP,
  MemoryCounter,
  PRIMARY,
  SESSION,
  SITEVERIFY,
  chatRequest,
  completeEnv,
  healthyBackend,
  routedFetcher,
  runtimeWith,
  verdict,
} from "./support";
import type { Route } from "./support";

const HEADER = "x-gisting-ticket";
const SHAPE = /^1\.\d{1,10}\.[A-Za-z0-9_-]{43}$/;
const SALT = "ip-salt-0123456789-0123456789-abcdef";
const MS = 1000;
const WINDOW = { ttlSeconds: limits.ticketTtlSeconds, skewSeconds: limits.ticketClockSkewSeconds };
const START = new Date("2026-10-04T12:00:00Z");
const NO_TOKEN = { turnstile_token: undefined };

function routes(siteverify: Route = verdict(true)) {
  return routedFetcher({ [SITEVERIFY]: siteverify, ...healthyBackend(PRIMARY, "streamed answer") });
}

function offlineRoutes() {
  const down: Route = () => new Response("down", { status: 503 });
  return routedFetcher({
    [SITEVERIFY]: verdict(true),
    [`${PRIMARY}/health`]: down,
    [`${BACKUP}/health`]: down,
  });
}

function siteverifyCalls(calls: readonly { url: string }[]): number {
  return calls.filter((call) => call.url === SITEVERIFY).length;
}

async function mint(): Promise<string> {
  return issueTicket(SALT, { sessionId: SESSION, ip: CLIENT_IP }, START, limits.ticketTtlSeconds);
}

async function firstTurn(counter = new MemoryCounter()) {
  const { fetcher } = routes();
  const { runtime } = runtimeWith(fetcher);
  const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
  await response.text();
  return { response, ticket: response.headers.get(HEADER) };
}

describe("handleChat after the first bot check", () => {
  it("signs a ticket on the first answer, bound to this session and address", async () => {
    const { response, ticket } = await firstTurn();
    expect(response.status).toBe(200);
    expect(ticket).toMatch(SHAPE);
    const subject = { sessionId: SESSION, ip: CLIENT_IP };
    const held = await verifyTicket(SALT, ticket ?? "", subject, START, WINDOW);
    expect(held.ok).toBe(true);
  });

  it("expires the ticket thirty minutes after the check", async () => {
    const { ticket } = await firstTurn();
    const exp = Number((ticket ?? "").split(".")[1]);
    expect(exp).toBe(START.getTime() / MS + limits.ticketTtlSeconds);
    expect(limits.ticketTtlSeconds).toBe(1800);
  });

  it("lets a ticket replace the bot check without calling siteverify or signing a new ticket", async () => {
    const { ticket } = await firstTurn();
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const request = chatRequest({ ...NO_TOKEN, ticket });
    const response = await handleChat(request, completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("streamed answer");
    expect(response.headers.get(HEADER)).toBeNull();
    expect(siteverifyCalls(calls)).toBe(0);
    expect(events).toEqual([]);
  });

  it("does not sign a new ticket even when a token rides along with a valid ticket", async () => {
    const ticket = await mint();
    const { fetcher, calls } = routes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest({ ticket }), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get(HEADER)).toBeNull();
    expect(siteverifyCalls(calls)).toBe(0);
  });

  it("refuses a bad ticket without a token, before siteverify, the counter or the upstream", async () => {
    const counter = new MemoryCounter();
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const request = chatRequest({ ...NO_TOKEN, ticket: "1.1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" });
    const response = await handleChat(request, completeEnv(counter), runtime);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "request_failed" });
    expect(response.headers.get(HEADER)).toBeNull();
    expect(calls).toHaveLength(0);
    expect(counter.counts.size).toBe(0);
    expect(events).toEqual([{ kind: "TurnstileFailed", detail: "ticket_expired" }]);
  });

  it.each([
    ["malformed", "garbage", "ticket_malformed"],
    ["tampered", "mac", "ticket_invalid"],
  ])("logs a %s ticket under its own reason", async (_name, mode, reason) => {
    const good = await mint();
    const [version = "", exp = "", mac = ""] = good.split(".");
    const forged = mode === "mac" ? `${version}.${exp}.${mac.startsWith("A") ? "B" : "A"}${mac.slice(1)}` : mode;
    const { fetcher } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest({ ...NO_TOKEN, ticket: forged }), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(403);
    expect(events).toEqual([{ kind: "TurnstileFailed", detail: reason }]);
  });

  it("refuses a ticket after thirty minutes", async () => {
    const ticket = await mint();
    const late = () => new Date(START.getTime() + limits.ticketTtlSeconds * MS);
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher, { now: late });
    const response = await handleChat(chatRequest({ ...NO_TOKEN, ticket }), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(403);
    expect(calls).toHaveLength(0);
    expect(events[0]?.detail).toBe("ticket_expired");
  });

  it("refuses a ticket used from another address or by another session", async () => {
    const ticket = await mint();
    const elsewhere = chatRequest({ ...NO_TOKEN, ticket }, { "cf-connecting-ip": "198.51.100.9" });
    const otherSession = chatRequest({ ...NO_TOKEN, ticket, session_id: "session-0002" });
    for (const request of [elsewhere, otherSession]) {
      const { fetcher, calls } = routes();
      const { runtime, events } = runtimeWith(fetcher);
      const response = await handleChat(request, completeEnv(new MemoryCounter()), runtime);
      expect(response.status).toBe(403);
      expect(calls).toHaveLength(0);
      expect(events[0]?.detail).toBe("ticket_invalid");
    }
  });

  it("falls back to siteverify when a bad ticket comes with a token, and signs a fresh ticket", async () => {
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest({ ticket: "garbage" }), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(siteverifyCalls(calls)).toBe(1);
    expect(response.headers.get(HEADER)).toMatch(SHAPE);
    expect(events).toEqual([{ kind: "TurnstileFailed", detail: "ticket_malformed" }]);
  });

  it("gives no ticket when the fallback siteverify refuses the token", async () => {
    const { fetcher } = routes(verdict(false));
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest({ ticket: "garbage" }), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(403);
    expect(response.headers.get(HEADER)).toBeNull();
  });

  it("gives no ticket when siteverify refuses the first token", async () => {
    const counter = new MemoryCounter();
    const { fetcher } = routes(verdict(false));
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(403);
    expect(response.headers.get(HEADER)).toBeNull();
    expect(counter.counts.size).toBe(0);
  });

  it("answers 400 when neither a token nor a ticket is sent", async () => {
    const { fetcher, calls } = routes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(NO_TOKEN), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(400);
    expect(calls).toHaveLength(0);
  });

  it("still counts every ticketed message against the session quota", async () => {
    const counter = new MemoryCounter();
    const ticket = await mint();
    const { fetcher, calls } = routes();
    const { runtime } = runtimeWith(fetcher);
    for (let sent = 1; sent <= limits.maxMessagesPerSession; sent += 1) {
      const response = await handleChat(chatRequest({ ...NO_TOKEN, ticket }), completeEnv(counter), runtime);
      expect(response.status).toBe(200);
      await response.text();
      expect(counter.counts.get(`session:${SESSION}`)).toBe(sent);
    }
    const over = await handleChat(chatRequest({ ...NO_TOKEN, ticket }), completeEnv(counter), runtime);
    expect(over.status).toBe(429);
    expect(over.headers.get(HEADER)).toBeNull();
    expect(siteverifyCalls(calls)).toBe(0);
  });

  it("gives an over-quota first message a 429 with no ticket", async () => {
    const counter = new MemoryCounter();
    counter.counts.set(`session:${SESSION}`, limits.maxMessagesPerSession);
    const { fetcher } = routes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(429);
    expect(response.headers.get(HEADER)).toBeNull();
  });

  it("signs a ticket on a replay answer served after a token check", async () => {
    const { fetcher } = offlineRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(response.headers.get(HEADER)).toMatch(SHAPE);
  });

  it("signs a ticket on a site-quota replay served after a token check", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("site:2026-10-04", limits.maxRequestsPerSitePerDay);
    const { fetcher } = routes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(response.headers.get(HEADER)).toMatch(SHAPE);
  });

  it("does not sign a new ticket on a replay answer served after a ticket check", async () => {
    const ticket = await mint();
    const { fetcher } = offlineRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest({ ...NO_TOKEN, ticket }), completeEnv(new MemoryCounter()), runtime);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(response.headers.get(HEADER)).toBeNull();
  });

  it("never writes a ticket into the log", async () => {
    const ticket = await mint();
    const expired = () => new Date(START.getTime() + 2 * limits.ticketTtlSeconds * MS);
    const { fetcher } = routes();
    const { runtime, events } = runtimeWith(fetcher, { now: expired });
    const lateTurn = chatRequest({ ...NO_TOKEN, ticket });
    await handleChat(lateTurn, completeEnv(new MemoryCounter()), runtime);
    const fallback = await handleChat(chatRequest({ ticket }), completeEnv(new MemoryCounter()), runtime);
    const fresh = fallback.headers.get(HEADER) ?? "";
    expect(fresh).toMatch(SHAPE);
    expect(events).toHaveLength(2);
    const logged = JSON.stringify(events);
    for (const secret of [ticket, fresh, ticket.split(".")[2] ?? ""]) {
      expect(logged).not.toContain(secret);
    }
  });
});

describe("parseChatRequest with a ticket", () => {
  it("accepts a ticket without a token and carries both fields", async () => {
    const only = await parseChatRequest(chatRequest({ ...NO_TOKEN, ticket: "t" }), limits);
    expect(only).toMatchObject({ ok: true, value: { ticket: "t", turnstileToken: null } });
    const both = await parseChatRequest(chatRequest({ ticket: "t" }), limits);
    expect(both).toMatchObject({ ok: true, value: { ticket: "t", turnstileToken: "token-ok" } });
    const plain = await parseChatRequest(chatRequest(), limits);
    expect(plain).toMatchObject({ ok: true, value: { ticket: null, turnstileToken: "token-ok" } });
  });

  it.each([
    ["neither field", { ...NO_TOKEN }],
    ["an empty ticket and no token", { ...NO_TOKEN, ticket: "" }],
    ["an empty ticket beside a token", { ticket: "" }],
    ["a numeric ticket", { ...NO_TOKEN, ticket: 5 }],
    ["a null ticket and no token", { ...NO_TOKEN, ticket: null }],
  ])("rejects %s", async (_name, override) => {
    const result = await parseChatRequest(chatRequest(override), limits);
    expect(result).toMatchObject({ ok: false, error: { kind: "InvalidRequest" } });
  });
});

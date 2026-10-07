import { describe, expect, it } from "vitest";
import { handleChat } from "../src/handler";
import { limits } from "../src/limits";
import {
  BACKUP,
  CLIENT_IP,
  MemoryCounter,
  PRIMARY,
  SITEVERIFY,
  bodyOf,
  chatRequest,
  completeEnv,
  envWithout,
  healthyBackend,
  routedFetcher,
  runtimeWith,
  verdict,
} from "./support";

function happyRoutes() {
  return routedFetcher({
    [SITEVERIFY]: verdict(true),
    ...healthyBackend(PRIMARY, "streamed answer"),
  });
}

async function everythingVisible(response: Response, events: unknown): Promise<string> {
  const headers = JSON.stringify([...response.headers.entries()]);
  return `${await response.clone().text()}${headers}${JSON.stringify(events)}`;
}

describe("handleChat", () => {
  it("verifies, counts and streams the primary answer", async () => {
    const { fetcher } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get("x-served-by")).toBe("primary");
    expect(await response.text()).toBe("streamed answer");
  });

  it("forwards the full mode to the upstream request body", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const request = chatRequest({ mode: "full" });
    await handleChat(request, completeEnv(new MemoryCounter()), runtime);
    const generate = calls.find((call) => call.url === `${PRIMARY}/generate`);
    expect(JSON.parse(generate === undefined ? "" : bodyOf(generate))).toMatchObject({
      mode: "full",
    });
  });

  it("forwards gist when the client sends no mode", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    const generate = calls.find((call) => call.url === `${PRIMARY}/generate`);
    expect(JSON.parse(generate === undefined ? "" : bodyOf(generate))).toMatchObject({
      mode: "gist",
    });
  });

  it("refuses an invalid mode before any upstream call", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(
      chatRequest({ mode: "x" }),
      completeEnv(new MemoryCounter()),
      runtime,
    );
    expect(response.status).toBe(400);
    expect(calls).toHaveLength(0);
  });

  it("refuses the fourth full comparison of a session with 429", async () => {
    const counter = new MemoryCounter();
    const { fetcher } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    for (let index = 0; index < 3; index += 1) {
      const response = await handleChat(
        chatRequest({ mode: "full" }),
        completeEnv(counter),
        runtime,
      );
      expect(response.status).toBe(200);
    }
    const refused = await handleChat(chatRequest({ mode: "full" }), completeEnv(counter), runtime);
    expect(refused.status).toBe(429);
    const gist = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(gist.status).toBe(200);
  });

  it("refuses a failed Turnstile check and spends no quota or upstream call", async () => {
    const counter = new MemoryCounter();
    const { fetcher, calls } = routedFetcher({ [SITEVERIFY]: verdict(false) });
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(403);
    expect(counter.counts.size).toBe(0);
    expect(calls).toHaveLength(1);
    expect(events[0]?.kind).toBe("TurnstileFailed");
  });

  it("refuses a too long message before any outside call", async () => {
    const { fetcher, calls } = routedFetcher({});
    const { runtime, events } = runtimeWith(fetcher);
    const request = chatRequest({ message: "a".repeat(301) });
    const response = await handleChat(request, completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(413);
    expect(calls).toHaveLength(0);
    expect(events[0]?.kind).toBe("TooLong");
  });

  it("refuses the eleventh message of a session", async () => {
    const counter = new MemoryCounter();
    const { fetcher } = happyRoutes();
    const { runtime, events } = runtimeWith(fetcher);
    const statuses: number[] = [];
    for (let turn = 0; turn < limits.maxMessagesPerSession + 1; turn += 1) {
      const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
      statuses.push(response.status);
      await response.body?.cancel();
    }
    expect(statuses.slice(-2)).toEqual([200, 429]);
    expect(events.at(-1)).toMatchObject({
      kind: "QuotaExceeded",
      detail: "session",
    });
  });

  it("refuses an address that is over its daily allowance", async () => {
    const counter = new MemoryCounter();
    const { fetcher } = happyRoutes();
    const { runtime, events } = runtimeWith(fetcher);
    for (let turn = 0; turn < limits.maxRequestsPerIpPerDay; turn += 1) {
      const request = chatRequest({
        session_id: `session-${String(turn).padStart(4, "0")}`,
      });
      await (await handleChat(request, completeEnv(counter), runtime)).body?.cancel();
    }
    const response = await handleChat(
      chatRequest({ session_id: "fresh-session" }),
      completeEnv(counter),
      runtime,
    );
    expect(response.status).toBe(429);
    expect(events.at(-1)).toMatchObject({
      kind: "QuotaExceeded",
      detail: "ip",
    });
  });

  it("answers with the recorded replay once the site allowance is used", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("site:2026-10-04", limits.maxRequestsPerSitePerDay);
    const { fetcher, calls } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const replay = [{ role: "assistant", content: "recorded" }] as const;
    const { runtime } = runtimeWith(fetcher, { replay });
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(await response.json()).toEqual({
      served_by: "replay",
      reason: "quota",
      turns: replay,
    });
    expect(calls.every((call) => call.url === SITEVERIFY)).toBe(true);
  });

  it("does not replay for refusals that are not about the site allowance", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("session:session-0001", limits.maxMessagesPerSession);
    const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const { runtime } = runtimeWith(fetcher, { replay: [{ role: "assistant", content: "x" }] });
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(429);
    expect(response.headers.get("x-served-by")).toBeNull();
  });

  it("falls back to the backup when the primary is down", async () => {
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      ...healthyBackend(BACKUP, "backup answer"),
    });
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.headers.get("x-served-by")).toBe("backup");
  });

  it("replays offline and logs the upstream attempts when no backend answers", async () => {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const replay = [{ role: "assistant", content: "recorded" }] as const;
    const { runtime, events } = runtimeWith(fetcher, { replay });
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: replay });
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      kind: "UpstreamError",
      detail: "primary:unhealthy, backup:unhealthy",
    });
  });

  it("replays offline when the primary generate answers 5xx and there is no backup", async () => {
    const env = envWithout("GISTING_BACKUP_URL", new MemoryCounter());
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}/generate`]: () => new Response("boom", { status: 500 }),
    });
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(await response.json()).toMatchObject({ served_by: "replay", reason: "offline" });
    expect(events[0]).toEqual({ kind: "UpstreamError", detail: "primary:generate failed" });
  });

  it("replays offline with an empty conversation when nothing is recorded", async () => {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: [] });
  });

  it.each([
    ["a bad request", chatRequest({ message: "a".repeat(301) }), 413],
    ["a rejected human check", chatRequest({ turnstile_token: "bad" }), 403],
    ["a missing client address", chatRequest({}, {}), 400],
  ])("does not replay for %s even when the upstream is down", async (_name, request, status) => {
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: (call) => verdict(!bodyOf(call).includes("bad"))(call),
    });
    const { runtime } = runtimeWith(fetcher, { replay: [{ role: "assistant", content: "x" }] });
    const response = await handleChat(request, completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(status);
    expect(response.headers.get("x-served-by")).toBeNull();
  });

  it("fails closed with the recorded replay, reason offline, when the counter is down", async () => {
    const counter = new MemoryCounter();
    counter.failing = true;
    const { fetcher, calls } = happyRoutes();
    const replay = [{ role: "assistant", content: "recorded" }] as const;
    const { runtime, events } = runtimeWith(fetcher, { replay });
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(response.status).toBe(200);
    expect(response.headers.get("x-served-by")).toBe("replay");
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: replay });
    expect(calls.some((call) => call.url.endsWith("/generate"))).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/health"))).toBe(false);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: "CounterUnavailable" });
  });

  it("replays an empty conversation with the reason while the recording is not confirmed", async () => {
    const counter = new MemoryCounter();
    counter.failing = true;
    const { fetcher } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: [] });
  });

  it("refuses a request without a client address", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(
      chatRequest({}, {}),
      completeEnv(new MemoryCounter()),
      runtime,
    );
    expect(response.status).toBe(400);
    expect(calls).toHaveLength(0);
  });
});

describe("handleChat privacy and uniform errors", () => {
  it("never shows the client address or the secrets in responses, headers or logs", async () => {
    const attempts = [
      chatRequest({ message: "a".repeat(301) }),
      chatRequest({ turnstile_token: "bad" }),
      chatRequest({}, {}),
      chatRequest(),
    ];
    for (const request of attempts) {
      const { fetcher } = routedFetcher({
        [SITEVERIFY]: (call) => verdict(!bodyOf(call).includes("bad"))(call),
      });
      const { runtime, events } = runtimeWith(fetcher);
      const response = await handleChat(request, completeEnv(new MemoryCounter()), runtime);
      const visible = await everythingVisible(response, events);
      for (const secret of [CLIENT_IP, "access-secret", "turnstile-secret", "ip-salt-0123456789-0123456789-abcdef"]) {
        expect(visible).not.toContain(secret);
      }
    }
  });

  it("gives every rejection the same body", async () => {
    const bodies = new Set<string>();
    const rejected = [
      chatRequest({ message: "a".repeat(301) }),
      chatRequest({ turnstile_token: "bad" }),
      chatRequest({ session_id: "x" }),
    ];
    for (const request of rejected) {
      const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(false) });
      const { runtime } = runtimeWith(fetcher);
      bodies.add(
        await (await handleChat(request, completeEnv(new MemoryCounter()), runtime)).text(),
      );
    }
    expect(bodies.size).toBe(1);
  });
});

import { describe, expect, it } from "vitest";
import { handleChat } from "../src/handler";
import { digestIp } from "../src/ip";
import { limits } from "../src/limits";
import {
  BACKUP,
  CLIENT_IP,
  MemoryCounter,
  PRIMARY,
  SITEVERIFY,
  chatRequest,
  completeEnv,
  digestFragmentIn,
  envWithout,
  healthyBackend,
  hang,
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

describe("handleChat ip digest and upstream headers", () => {
  it("sends the upstream secret to the primary health and generate calls", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    for (const path of ["/health", "/generate"]) {
      const call = calls.find((entry) => entry.url === `${PRIMARY}${path}`);
      expect(call?.init?.headers).toMatchObject({ "x-gisting-upstream-secret": "upstream-secret" });
    }
  });

  it("sends the generate call the same ip digest the quota key uses", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const counter = new MemoryCounter();
    await handleChat(chatRequest(), completeEnv(counter), runtime);
    const generate = calls.find((call) => call.url === `${PRIMARY}/generate`);
    const sent = new Headers(generate?.init?.headers).get("x-gisting-ip-digest");
    expect(sent).toMatch(/^[0-9a-f]{64}$/);
    expect([...counter.counts.keys()]).toContain(`ip:2026-10-04:${sent ?? ""}`);
    const health = calls.find((call) => call.url === `${PRIMARY}/health`);
    expect(new Headers(health?.init?.headers).has("x-gisting-ip-digest")).toBe(false);
  });

  it("sends the backup neither the upstream secret nor the ip digest", async () => {
    const { fetcher, calls } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("down", { status: 503 }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const { runtime } = runtimeWith(fetcher);
    await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    const toBackup = calls.filter((call) => call.url.startsWith(BACKUP));
    expect(toBackup).toHaveLength(2);
    for (const call of toBackup) {
      const headers = new Headers(call.init?.headers);
      expect(headers.has("x-gisting-upstream-secret")).toBe(false);
      expect(headers.has("x-gisting-ip-digest")).toBe(false);
    }
  });

  it("never forwards browser supplied copies of the secret and digest headers", async () => {
    const { fetcher, calls } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("down", { status: 503 }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const { runtime } = runtimeWith(fetcher);
    const forged = {
      "cf-connecting-ip": CLIENT_IP,
      "x-gisting-ip-digest": "f".repeat(64),
      "x-gisting-upstream-secret": "browser-secret",
      "cf-access-client-secret": "browser-access",
    };
    await handleChat(chatRequest({}, forged), completeEnv(new MemoryCounter()), runtime);
    const outbound = calls.filter((call) => !call.url.startsWith(SITEVERIFY));
    expect(outbound.length).toBeGreaterThan(0);
    for (const call of outbound) {
      const sent = JSON.stringify([...new Headers(call.init?.headers).entries()]);
      for (const value of ["f".repeat(64), "browser-secret", "browser-access"]) {
        expect(sent).not.toContain(value);
      }
    }
  });

  it("never forwards browser supplied headers to a healthy primary", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const forged = {
      "cf-connecting-ip": CLIENT_IP,
      "x-gisting-ip-digest": "f".repeat(64),
      "x-gisting-upstream-secret": "browser-secret",
      "cf-access-client-secret": "browser-access",
    };
    await handleChat(chatRequest({}, forged), completeEnv(new MemoryCounter()), runtime);
    for (const call of calls.filter((entry) => entry.url.startsWith(PRIMARY))) {
      const headers = new Headers(call.init?.headers);
      expect(headers.get("x-gisting-upstream-secret")).toBe("upstream-secret");
      expect(headers.get("cf-access-client-secret")).toBe("access-secret");
      expect(headers.get("x-gisting-ip-digest")).not.toBe("f".repeat(64));
    }
  });

  it("keeps the ip digest out of every log event, even as a fragment", async () => {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(false) });
    const { runtime, events } = runtimeWith(fetcher);
    await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    const digest = await digestIp("ip-salt-0123456789-0123456789-abcdef", CLIENT_IP, runtime.now());
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(events).toHaveLength(1);
    expect(digestFragmentIn(JSON.stringify(events), digest)).toBeNull();
    expect(Object.keys(events[0] ?? {})).toEqual(["kind", "detail"]);
  });
});

describe("handleChat generate deadline", () => {
  it("replays offline and names the timeout when generate hangs", async () => {
    const env = envWithout("GISTING_BACKUP_URL", new MemoryCounter());
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}/generate`]: (call) => hang(call),
    });
    const replay = [{ role: "assistant", content: "recorded" }] as const;
    const { runtime, events } = runtimeWith(fetcher, {
      replay,
      limits: { ...limits, generateTimeoutMs: 20 },
    });
    const response = await handleChat(chatRequest(), env, runtime);
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: replay });
    expect(events).toEqual([{ kind: "UpstreamError", detail: "primary:generate timeout" }]);
  });
});

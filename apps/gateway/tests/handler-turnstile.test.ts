import { describe, expect, it } from "vitest";
import { handleChat } from "../src/handler";
import { limits } from "../src/limits";
import {
  MemoryCounter,
  PRIMARY,
  SITEVERIFY,
  chatRequest,
  completeEnv,
  hang,
  healthyBackend,
  routedFetcher,
  runtimeWith,
  verdict,
} from "./support";
import type { Route } from "./support";

const PREVIEW = "preview.example.test";

async function snapshot(response: Response): Promise<string> {
  const headers = JSON.stringify([...response.headers.entries()]);
  return `${String(response.status)}|${headers}|${await response.text()}`;
}

const SHORT_TIMEOUT_MS = 20;

async function refusedWith(route: Route, turnstileTimeoutMs: number = limits.turnstileTimeoutMs) {
  const counter = new MemoryCounter();
  const { fetcher, calls } = routedFetcher({
    [SITEVERIFY]: route,
    ...healthyBackend(PRIMARY, "streamed answer"),
  });
  const { runtime, events } = runtimeWith(fetcher, { limits: { ...limits, turnstileTimeoutMs } });
  const response = await handleChat(chatRequest(), completeEnv(counter), runtime);
  return { response, counter, calls, events };
}

describe("handleChat Turnstile policy", () => {
  const wrongHostname = verdict(true, { hostname: "evil.example.test" });
  const wrongAction = verdict(true, { action: "login" });
  const missingFields = () => Response.json({ success: true });
  const refused = verdict(false);
  const refusedWithCodes = verdict(false, { "error-codes": ["timeout-or-duplicate"] });
  const garbled = () => new Response("not json");
  const unreachable: Route = () => Promise.reject(new Error("network"));
  const serverError = () => new Response("oops", { status: 500 });

  it("gives a wrong hostname the same response as a refused token, byte for byte", async () => {
    const reference = await snapshot((await refusedWith(refused)).response);
    expect(await snapshot((await refusedWith(wrongHostname)).response)).toBe(reference);
  });

  it.each([
    ["a wrong action", wrongAction],
    ["missing hostname and action", missingFields],
    ["an answer that is not JSON", garbled],
    ["an unreachable siteverify", unreachable],
    ["an HTTP 500 from siteverify", serverError],
    ["a siteverify that never answers", hang],
  ])("gives %s the same response as a refused token", async (_name, route) => {
    const reference = await snapshot((await refusedWith(refused)).response);
    expect(await snapshot((await refusedWith(route, SHORT_TIMEOUT_MS)).response)).toBe(reference);
  });

  it.each([
    ["hostname_mismatch:evil.example.test", wrongHostname],
    ["action_mismatch", wrongAction],
    ["hostname_missing", missingFields],
    ["rejected", refused],
    ["rejected:timeout-or-duplicate", refusedWithCodes],
    ["unavailable", garbled],
    ["unavailable", unreachable],
    ["unavailable", serverError],
    ["timeout", hang],
  ])("records %s internally and spends no quota or upstream call", async (reason, route) => {
    const { response, counter, calls, events } = await refusedWith(route, SHORT_TIMEOUT_MS);
    expect(response.status).toBe(403);
    expect(counter.counts.size).toBe(0);
    expect(calls.map((call) => call.url)).toEqual([SITEVERIFY]);
    expect(events).toEqual([{ kind: "TurnstileFailed", detail: reason }]);
  });

  it("never logs the token", async () => {
    const { events } = await refusedWith(wrongHostname);
    expect(JSON.stringify(events)).not.toContain("token-ok");
  });

  it("admits the production hostname and action and streams the answer", async () => {
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      ...healthyBackend(PRIMARY, "streamed answer"),
    });
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), completeEnv(new MemoryCounter()), runtime);
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("streamed answer");
  });

  it("refuses a preview hostname while the preview variable is unset", async () => {
    const { response, events } = await refusedWith(verdict(true, { hostname: PREVIEW }));
    expect(response.status).toBe(403);
    expect(events[0]?.detail).toBe(`hostname_mismatch:${PREVIEW}`);
  });

  it("admits a preview hostname once the preview variable lists it, and still refuses others", async () => {
    const env = { ...completeEnv(new MemoryCounter()), GISTING_TURNSTILE_EXTRA_HOSTNAMES: PREVIEW };
    for (const [hostname, status] of [[PREVIEW, 200], ["other.example.test", 403]] as const) {
      const { fetcher } = routedFetcher({
        [SITEVERIFY]: verdict(true, { hostname }),
        ...healthyBackend(PRIMARY, "streamed answer"),
      });
      const { runtime } = runtimeWith(fetcher);
      const response = await handleChat(chatRequest(), env, runtime);
      expect(response.status).toBe(status);
      await response.body?.cancel();
    }
  });

  it("fails closed before any outside call when the preview variable is malformed", async () => {
    const env = { ...completeEnv(new MemoryCounter()), GISTING_TURNSTILE_EXTRA_HOSTNAMES: "*" };
    const { fetcher, calls } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(response.status).toBe(503);
    expect(calls).toHaveLength(0);
    expect(events[0]).toMatchObject({ kind: "ConfigMissing", detail: "GISTING_TURNSTILE_EXTRA_HOSTNAMES" });
  });
});

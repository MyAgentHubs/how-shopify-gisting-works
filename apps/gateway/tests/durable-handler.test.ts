import { describe, expect, it } from "vitest";
import { DurableCounter } from "../src/durable-counter";
import { handleChat } from "../src/handler";
import { gatewayEnv } from "../src/pages-env";
import type { PagesEnv } from "../src/pages-env";
import { FakeNamespace } from "./fake-durable";
import {
  BACKUP,
  CLIENT_IP,
  PRIMARY,
  SITEVERIFY,
  chatRequest,
  healthyBackend,
  routedFetcher,
  runtimeWith,
  verdict,
} from "./support";

const MESSAGE = "where is my parcel for buyer@example.test order #1001";

function pagesEnv(namespace?: FakeNamespace): PagesEnv {
  return {
    GISTING_TURNSTILE_SECRET: "turnstile-secret",
    GISTING_IP_SALT: "ip-salt-0123456789-0123456789-abcdef",
    GISTING_PRIMARY_URL: PRIMARY,
    GISTING_BACKUP_URL: BACKUP,
    GISTING_ACCESS_CLIENT_ID: "access-id",
    GISTING_ACCESS_CLIENT_SECRET: "access-secret",
    GISTING_UPSTREAM_SECRET: "upstream-secret",
    ...(namespace === undefined ? {} : { GISTING_COUNTER: namespace }),
  };
}

function routes() {
  return routedFetcher({
    [SITEVERIFY]: verdict(true),
    ...healthyBackend(PRIMARY, "hello"),
    ...healthyBackend(BACKUP, "hello"),
  });
}

describe("the gateway on Durable Objects", () => {
  it("serves a message and names the objects only by kind, date, session and digest", async () => {
    const namespace = new FakeNamespace();
    const { fetcher } = routes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(
      chatRequest({ message: MESSAGE }),
      gatewayEnv(pagesEnv(namespace)),
      runtime,
    );
    expect(response.status).toBe(200);
    const names = [...namespace.objects.keys()];
    expect(names).toHaveLength(3);
    expect(names.every((name) => /^(session|ip|site)(:[A-Za-z0-9_-]+)+$/.test(name))).toBe(true);
  });

  it("keeps the address, message, token, order number and email out of names and stored state", async () => {
    const namespace = new FakeNamespace();
    const { fetcher } = routes();
    const { runtime } = runtimeWith(fetcher);
    await handleChat(
      chatRequest({ message: MESSAGE, mode: "full" }),
      gatewayEnv(pagesEnv(namespace)),
      runtime,
    );
    const seen = JSON.stringify([
      namespace.requested,
      [...namespace.objects.values()].map((object) => [...object.host.store.entries()]),
    ]);
    for (const secret of [CLIENT_IP, "buyer@example.test", "1001", "token-ok", "parcel"]) {
      expect(seen).not.toContain(secret);
    }
  });

  it("replays offline, logs the named reason and generates nothing when the objects cannot be reached", async () => {
    const namespace = new FakeNamespace();
    namespace.failure = new Error("Durable Object overloaded");
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), gatewayEnv(pagesEnv(namespace)), runtime);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ served_by: "replay", reason: "offline", turns: [] });
    expect(events.map((event) => event.detail)).toEqual([
      "counter unavailable: durable_object_unreachable: cause Error",
    ]);
    expect(calls.filter((call) => call.url.endsWith("/generate"))).toHaveLength(0);
  });

  it("replays offline and names a timeout when an object stalls", async () => {
    const namespace = new FakeNamespace();
    namespace.gate = new Promise<void>(() => undefined);
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const env = gatewayEnv(pagesEnv(namespace));
    const counter = new DurableCounter(namespace, 20);
    const response = await handleChat(chatRequest(), { ...env, GISTING_COUNTER: counter }, runtime);
    expect(await response.json()).toMatchObject({ served_by: "replay", reason: "offline" });
    expect(events.map((event) => event.detail)).toEqual([
      "counter unavailable: durable_object_timeout",
    ]);
    expect(calls.filter((call) => call.url.endsWith("/generate"))).toHaveLength(0);
  });

  it("answers 503 and forwards nothing when the namespace binding is missing", async () => {
    const { fetcher, calls } = routes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), gatewayEnv(pagesEnv()), runtime);
    expect(response.status).toBe(503);
    expect(events[0]?.detail).toContain("GISTING_COUNTER");
    expect(calls).toHaveLength(0);
  });

  it("refuses the eleventh message of a session with 429 across separate requests", async () => {
    const namespace = new FakeNamespace();
    const { fetcher } = routes();
    const { runtime } = runtimeWith(fetcher);
    const env = gatewayEnv(pagesEnv(namespace));
    const statuses: number[] = [];
    for (let index = 0; index < 11; index += 1) {
      statuses.push((await handleChat(chatRequest(), env, runtime)).status);
    }
    expect(statuses.slice(0, 10).every((status) => status === 200)).toBe(true);
    expect(statuses[10]).toBe(429);
  });
});

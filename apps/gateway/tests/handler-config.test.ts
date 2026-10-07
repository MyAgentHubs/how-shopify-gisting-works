import { describe, expect, it } from "vitest";
import type { GatewayEnv } from "../src/config";
import { loadConfig } from "../src/config";
import { handleChat } from "../src/handler";
import { limits } from "../src/limits";
import {
  MemoryCounter,
  PRIMARY,
  SITEVERIFY,
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

describe("handleChat configuration", () => {
  const required: (keyof GatewayEnv)[] = [
    "GISTING_TURNSTILE_SECRET",
    "GISTING_IP_SALT",
    "GISTING_PRIMARY_URL",
    "GISTING_ACCESS_CLIENT_ID",
    "GISTING_ACCESS_CLIENT_SECRET",
    "GISTING_UPSTREAM_SECRET",
    "GISTING_COUNTER",
  ];

  it.each(required)("fails closed with no outside call when %s is missing", async (name) => {
    const env = envWithout(name, new MemoryCounter());
    const { fetcher, calls } = happyRoutes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(response.status).toBe(503);
    expect(calls).toHaveLength(0);
    expect(events[0]).toMatchObject({ kind: "ConfigMissing", detail: name });
  });

  it.each([
    ["GISTING_PRIMARY_URL", "http://primary.example.test"],
    ["GISTING_PRIMARY_URL", "primary.example.test"],
    ["GISTING_PRIMARY_URL", "ftp://primary.example.test"],
    ["GISTING_BACKUP_URL", "http://backup.example.test"],
    ["GISTING_BACKUP_URL", "backup.example.test"],
  ])("fails closed with no outside call when %s is %s, not https", async (name, value) => {
    const env = { ...completeEnv(new MemoryCounter()), [name]: value };
    const { fetcher, calls } = happyRoutes();
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(response.status).toBe(503);
    expect(calls).toHaveLength(0);
    expect(events[0]).toMatchObject({ kind: "ConfigMissing", detail: name });
  });

  it("fails closed with an empty environment, the way an unconfigured deploy looks", async () => {
    const { fetcher, calls } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), {}, runtime);
    expect(response.status).toBe(503);
    expect(calls).toHaveLength(0);
  });

  it("replays offline and logs the unauthorized primary when there is no backup", async () => {
    const env = envWithout("GISTING_BACKUP_URL", new MemoryCounter());
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("no", { status: 401 }),
    });
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(await response.json()).toMatchObject({ served_by: "replay", reason: "offline" });
    expect(events.map((event) => event.detail)).toContain("primary:unauthorized:401");
  });

  it("replays offline and logs the unauthorized primary when generate answers 401", async () => {
    const env = envWithout("GISTING_BACKUP_URL", new MemoryCounter());
    const { fetcher } = routedFetcher({
      [SITEVERIFY]: verdict(true),
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}/generate`]: () => new Response("no", { status: 401 }),
    });
    const { runtime, events } = runtimeWith(fetcher);
    const response = await handleChat(chatRequest(), env, runtime);
    expect(await response.json()).toMatchObject({ served_by: "replay", reason: "offline" });
    expect(events.map((event) => event.detail)).toContain("primary:unauthorized:401");
  });

  it("treats an ip salt of 31 characters as missing and one of 32 as usable", () => {
    const counter = new MemoryCounter();
    const short = { ...completeEnv(counter), GISTING_IP_SALT: "s".repeat(limits.minSecretChars - 1) };
    const enough = { ...completeEnv(counter), GISTING_IP_SALT: "s".repeat(limits.minSecretChars) };
    expect(limits.minSecretChars).toBe(32);
    expect(loadConfig(short)).toEqual({ ok: false, error: { kind: "ConfigMissing", missing: ["GISTING_IP_SALT"] } });
    expect(loadConfig(enough).ok).toBe(true);
  });

  it("treats a blank secret as missing", async () => {
    const env = { ...completeEnv(new MemoryCounter()), GISTING_IP_SALT: "  " };
    const { fetcher } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    expect((await handleChat(chatRequest(), env, runtime)).status).toBe(503);
  });

  it("serves from the primary alone when no backup address is configured", async () => {
    const env = envWithout("GISTING_BACKUP_URL", new MemoryCounter());
    const { fetcher } = happyRoutes();
    const { runtime } = runtimeWith(fetcher);
    expect((await handleChat(chatRequest(), env, runtime)).status).toBe(200);
  });
});

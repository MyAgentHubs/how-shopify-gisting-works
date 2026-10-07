import { afterEach, describe, expect, it, vi } from "vitest";
import { onRequestPost } from "../functions/api/chat";
import { digestIp } from "../src/ip";
import type { PagesEnv } from "../src/pages-env";
import { FakeNamespace } from "./fake-durable";
import { CLIENT_IP, chatRequest, digestFragmentIn } from "./support";

describe("the Pages Function entry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fails closed and calls nothing when the deployment has no configuration", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const context = { request: chatRequest(), env: {} } as unknown as Parameters<
      typeof onRequestPost
    >[0];
    const response = await onRequestPost(context);
    expect(response.status).toBe(503);
    expect(spy).not.toHaveBeenCalled();
  });

  it("writes no part of the ip digest to the console", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-04T12:00:00Z"));
    vi.stubGlobal("fetch", () => Promise.resolve(Response.json({ success: false })));
    const written = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const env: PagesEnv = {
      GISTING_TURNSTILE_SECRET: "turnstile-secret",
      GISTING_IP_SALT: "ip-salt-0123456789-0123456789-abcdef",
      GISTING_PRIMARY_URL: "https://primary.example.test",
      GISTING_ACCESS_CLIENT_ID: "access-id",
      GISTING_ACCESS_CLIENT_SECRET: "access-secret",
      GISTING_UPSTREAM_SECRET: "upstream-secret",
      GISTING_COUNTER: new FakeNamespace(),
    };
    const context = { request: chatRequest(), env } as unknown as Parameters<
      typeof onRequestPost
    >[0];
    await onRequestPost(context);
    const digest = await digestIp("ip-salt-0123456789-0123456789-abcdef", CLIENT_IP, new Date());
    expect(written).toHaveBeenCalledTimes(1);
    expect(digestFragmentIn(JSON.stringify(written.mock.calls), digest)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { fakeGateway } from "../fakes/fake-gateway.ts";
import type { ChatRequest } from "../src/gateway.ts";
import { parsePublicTrace } from "../src/trace.ts";
import { fixedToken, flush, mount, query, say } from "./support.ts";

const REQUEST: ChatRequest = {
  sessionId: "session-abcdef01",
  message: "where is order #1042",
  turnstileToken: "t",
  mode: "gist",
  timeoutMs: 30000,
};

describe("the fake gateway", () => {
  it("answers with a trace that satisfies the public contract", async () => {
    const outcome = await fakeGateway().chat(REQUEST);
    expect(outcome.kind).toBe("reply");
    if (outcome.kind === "reply") {
      expect(parsePublicTrace(outcome.trace)).toEqual(outcome.trace);
      expect(outcome.trace.tools[0]?.order_number).toBe("#1042");
    }
  });

  it("charges the full rules more tokens than the gist", async () => {
    const gateway = fakeGateway();
    const gist = await gateway.chat(REQUEST);
    const full = await gateway.chat({ ...REQUEST, mode: "full" });
    expect(
      gist.kind === "reply" &&
        full.kind === "reply" &&
        full.trace.tokens.total > gist.trace.tokens.total,
    ).toBe(true);
  });

  it("records the requests it was asked", async () => {
    const gateway = fakeGateway();
    await gateway.chat(REQUEST);
    expect(gateway.requests).toEqual([REQUEST]);
  });

  it("can be scripted, and then answers what the script says", async () => {
    const gateway = fakeGateway(() => ({ kind: "failed", status: 503, reason: "http" }));
    expect(await gateway.chat(REQUEST)).toEqual({ kind: "failed", status: 503, reason: "http" });
  });

  it("drives the whole page the way the local preview does", async () => {
    mount({ gateway: fakeGateway(), check: fixedToken("preview") });
    await say("where is order #1042");
    await flush();
    expect(query('[data-role="log"]').textContent).toContain("where is order #1042");
    expect(query('[data-role="panel-body"]').textContent).toContain("lookup_order(#1042, •••)");
  });
});

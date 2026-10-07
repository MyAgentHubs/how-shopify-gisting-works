import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import limitsJson from "../data/limits.json";
import type { ChatOutcome, ChatRequest, Fetcher } from "../src/gateway.ts";
import { httpGateway } from "../src/gateway.ts";
import { compare, compareButton, flush, inputBox, mount, reply, say, submitMessage, TRACE } from "./support.ts";
import {
  FRESH,
  answer,
  broken,
  countingCheck,
  forbidden,
  pinClock,
  stepping,
} from "./ticket-support.ts";
import type { Step } from "./ticket-support.ts";

beforeEach(pinClock);

afterEach(() => {
  vi.useRealTimers();
});

const bubbles = (kind: "og-u" | "og-b"): string[] =>
  [...document.querySelectorAll(`[data-role="log"] .${kind}`)].map((node) => node.textContent);

const networkDown: Step = () => ({ kind: "failed", status: 0, reason: "network" });
const throttled: Step = () => ({ kind: "failed", status: 429, reason: "http" });
const malformed: Step = () => ({ kind: "failed", status: 200, reason: "malformed" });

describe("a refused ticket", () => {
  it("is thrown away, so the message after a resend that brought no new ticket asks for a token again", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), forbidden, answer("two"), answer("three")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    await say("three");
    expect(gateway.requests).toHaveLength(4);
    expect(gateway.requests[3]?.ticket).toBeUndefined();
    expect(gateway.requests[3]?.turnstileToken).toBe("token-3");
  });

  it("is resent once with a token in compare mode too", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), forbidden, answer("full")]);
    mount({ gateway, check });
    await say("one");
    await compare();
    expect(
      gateway.requests.map((request) => [request.mode, request.ticket ?? "-", request.turnstileToken ?? "-"]),
    ).toEqual([
      ["gist", "-", "token-1"],
      ["full", FRESH, "-"],
      ["full", "-", "token-2"],
    ]);
  });

  it("shows the user's message once and the answer once after the resend", async () => {
    const gateway = stepping([answer("one", FRESH), forbidden, answer("two")]);
    mount({ gateway, check: countingCheck() });
    await say("first");
    await say("second");
    expect(bubbles("og-u")).toEqual(["first", "second"]);
    expect(bubbles("og-b")).toEqual(["one", "two"]);
    expect(document.querySelectorAll("[data-reason]")).toHaveLength(0);
  });
});

describe("a failure that is not a refusal", () => {
  it.each([
    ["no connection", networkDown],
    ["a rate limit", throttled],
    ["a server error", broken],
    ["an answer that makes no sense", malformed],
  ])("after %s the ticket is kept and nothing is resent", async (_name, failure) => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), failure, answer("three")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(gateway.requests).toHaveLength(2);
    expect(check.calls()).toBe(1);
    await say("three");
    expect(gateway.requests[2]?.ticket).toBe(FRESH);
    expect(check.calls()).toBe(1);
  });

  it("after a gateway that throws the ticket is kept and nothing is resent", async () => {
    const requests: ChatRequest[] = [];
    const gateway = {
      chat(request: ChatRequest): Promise<ChatOutcome> {
        requests.push(request);
        return requests.length === 1
          ? Promise.resolve({ ...reply("one"), ticket: FRESH })
          : Promise.reject(new Error("boom"));
      },
    };
    const check = countingCheck();
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(requests).toHaveLength(2);
    expect(check.calls()).toBe(1);
    expect(document.querySelector("[data-reason]")?.getAttribute("data-reason")).toBe("unexpected");
  });

  it("after a request that times out the ticket is kept and nothing is resent", async () => {
    vi.useRealTimers();
    const bodies: { ticket?: string }[] = [];
    const fetcher: Fetcher = (_url, init) => {
      bodies.push(JSON.parse(typeof init?.body === "string" ? init.body : "null") as { ticket?: string });
      if (bodies.length === 1) {
        return Promise.resolve(Response.json({ answer: "one", trace: TRACE }, { headers: { "x-gisting-ticket": FRESH } }));
      }
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new Error("aborted"));
        });
      });
    };
    const check = countingCheck();
    mount({ gateway: httpGateway(fetcher), check, limits: { ...limitsJson, chatRequestMs: 20 } });
    await say("one");
    submitMessage("two");
    await vi.waitFor(() => {
      expect(document.querySelector("[data-reason]")?.getAttribute("data-reason")).toBe("network");
    });
    expect(bodies).toHaveLength(2);
    expect(check.calls()).toBe(1);
  });
});

describe("a resend", () => {
  it("does not use up the message limit: ten messages with nine refusals all go out, the next is blocked", async () => {
    const steps: Step[] = [answer("m1", FRESH)];
    for (let index = 2; index <= limitsJson.maxMessages; index += 1) {
      steps.push(forbidden, answer(`m${String(index)}`, FRESH));
    }
    const gateway = stepping(steps);
    mount({ gateway, check: countingCheck() });
    for (let index = 1; index <= limitsJson.maxMessages; index += 1) {
      await say(`msg ${String(index)}`);
    }
    expect(inputBox().disabled).toBe(true);
    expect(gateway.requests).toHaveLength(2 * limitsJson.maxMessages - 1);
  });

  it("does not use up the compare limit: every allowed compare goes out even when refused first", async () => {
    const steps: Step[] = [answer("m1", FRESH)];
    for (let index = 0; index < limitsJson.maxCompares; index += 1) {
      steps.push(forbidden, answer(`f${String(index)}`, FRESH));
    }
    const gateway = stepping(steps);
    mount({ gateway, check: countingCheck() });
    await say("hello");
    for (let index = 0; index < limitsJson.maxCompares; index += 1) {
      expect(compareButton().disabled).toBe(false);
      await compare();
    }
    expect(compareButton().disabled).toBe(true);
    expect(gateway.requests).toHaveLength(1 + 2 * limitsJson.maxCompares);
  });
});

describe("a send that is still in flight", () => {
  it("ignores further submits, so one message makes one request and one bubble", async () => {
    const requests: ChatRequest[] = [];
    let release: ((outcome: ChatOutcome) => void) | undefined;
    const gateway = {
      chat(request: ChatRequest): Promise<ChatOutcome> {
        requests.push(request);
        if (requests.length === 1) {
          return Promise.resolve({ ...reply("one"), ticket: FRESH });
        }
        return new Promise<ChatOutcome>((resolve) => {
          release = resolve;
        });
      },
    };
    mount({ gateway, check: countingCheck() });
    await say("one");
    submitMessage("two");
    submitMessage("three");
    submitMessage("four");
    await flush();
    expect(requests).toHaveLength(2);
    release?.(reply("two"));
    await flush();
    expect(bubbles("og-u")).toEqual(["one", "two"]);
    submitMessage("five");
    await flush();
    expect(requests).toHaveLength(3);
  });

  it("ignores submits while a refused ticket waits for a new token", async () => {
    let resolveToken: ((token: string) => void) | undefined;
    let calls = 0;
    const check = {
      warm: () => undefined, reset: () => undefined,
      token: () => {
        calls += 1;
        return calls === 1
          ? Promise.resolve("t1")
          : new Promise<string>((resolve) => {
              resolveToken = resolve;
            });
      },
    };
    const gateway = stepping([answer("one", FRESH), forbidden, answer("two")]);
    mount({ gateway, check });
    await say("one");
    submitMessage("two");
    await flush();
    submitMessage("mid");
    await flush();
    expect(gateway.requests).toHaveLength(2);
    resolveToken?.("t2");
    await flush();
    expect(gateway.requests).toHaveLength(3);
    expect(bubbles("og-u")).toEqual(["one", "two"]);
  });
});

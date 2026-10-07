import { describe, expect, it } from "vitest";
import gatewayLimits from "../../gateway/limits.json";
import limits from "../data/limits.json";
import { parseLimits } from "../src/session.ts";
import type { Fetcher } from "../src/gateway.ts";
import { httpGateway } from "../src/gateway.ts";
import { parsePublicTrace } from "../src/trace.ts";
import { CANARY, TRACE } from "./support.ts";

const REQUEST = {
  sessionId: "session-abcdef01",
  message: "hello",
  turnstileToken: "tok",
  mode: "gist",
  timeoutMs: 30000,
} as const;

function answering(
  body: unknown,
  init: ResponseInit = {},
): { fetcher: Fetcher; calls: { url: string; init: RequestInit | undefined }[] } {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetcher: Fetcher = (url, requestInit) => {
    calls.push({ url, init: requestInit });
    return Promise.resolve(Response.json(body, init));
  };
  return { fetcher, calls };
}

function bodyText(init: RequestInit | undefined): string {
  const body = init?.body;
  return typeof body === "string" ? body : "";
}

describe("httpGateway", () => {
  it("posts the chat request in the gateway's field names", async () => {
    const { fetcher, calls } = answering({ answer: "hi", trace: TRACE });
    await httpGateway(fetcher).chat(REQUEST);
    expect(calls[0]?.url).toBe("/api/chat");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(bodyText(calls[0]?.init))).toEqual({
      session_id: "session-abcdef01",
      message: "hello",
      turnstile_token: "tok",
      mode: "gist",
    });
  });

  it("returns the answer and the public trace", async () => {
    const { fetcher } = answering({ answer: "hi", trace: TRACE });
    expect(await httpGateway(fetcher).chat(REQUEST)).toEqual({
      kind: "reply",
      answer: "hi",
      trace: TRACE,
    });
  });

  it("drops every field of the trace that the contract does not name", async () => {
    const dirty = {
      answer: "hi",
      internal: { canary: CANARY },
      trace: {
        ...TRACE,
        backend_id: CANARY,
        tools: [{ ...TRACE.tools[0], result: CANARY }],
        knowledge: [{ ...TRACE.knowledge[0], title: CANARY, answer: CANARY, score: 9.5 }],
        tokens: { ...TRACE.tokens, raw_ids: [CANARY] },
      },
    };
    const outcome = await httpGateway(answering(dirty).fetcher).chat(REQUEST);
    expect(JSON.stringify(outcome)).not.toContain(CANARY);
    expect(outcome).toMatchObject({ kind: "reply", trace: TRACE });
  });

  it("passes a replay through", async () => {
    const turns = [
      { role: "user", content: "a" },
      { role: "assistant", content: "b" },
    ];
    const { fetcher } = answering({ served_by: "replay", reason: "quota", turns });
    expect(await httpGateway(fetcher).chat(REQUEST)).toEqual({
      kind: "replay",
      reason: "quota",
      turns,
    });
  });

  it("keeps the reason an offline replay came with", async () => {
    const { fetcher } = answering({ served_by: "replay", reason: "offline", turns: [] });
    expect(await httpGateway(fetcher).chat(REQUEST)).toEqual({
      kind: "replay",
      reason: "offline",
      turns: [],
    });
  });

  it("reports an error status as one uniform failure", async () => {
    const { fetcher } = answering({ error: "request_failed" }, { status: 429 });
    expect(await httpGateway(fetcher).chat(REQUEST)).toEqual({ kind: "failed", status: 429, reason: "http" });
  });

  it("fails when the network does", async () => {
    const down: Fetcher = () => Promise.reject(new Error("offline"));
    expect(await httpGateway(down).chat(REQUEST)).toEqual({ kind: "failed", status: 0, reason: "network" });
  });

  it("gives up on a request that never answers once its time is up, as a network failure", async () => {
    const silent: Fetcher = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new Error("aborted"));
        });
      });
    const outcome = await httpGateway(silent).chat({ ...REQUEST, timeoutMs: 20 });
    expect(outcome).toEqual({ kind: "failed", status: 0, reason: "network" });
  });

  it("fails on bodies that are not a reply", async () => {
    for (const body of [
      null,
      [],
      "x",
      { answer: 1, trace: TRACE },
      { answer: "hi" },
      { served_by: "replay", reason: "quota", turns: [{ role: "system", content: "x" }] },
      { served_by: "replay", turns: [] },
      { served_by: "replay", reason: "weather", turns: [] },
    ]) {
      expect(await httpGateway(answering(body).fetcher).chat(REQUEST)).toMatchObject({
        kind: "failed",
        reason: "malformed",
      });
    }
  });
});

describe("parsePublicTrace", () => {
  it("accepts the contract shape", () => {
    expect(parsePublicTrace(TRACE)).toEqual(TRACE);
  });

  it("refuses a knowledge id that does not look like a kb id", () => {
    for (const id of ["", "kb-", "KB-ship", "kb-Ship", "kb_ship", "kb-a b", "kb-a\n", CANARY]) {
      expect(parsePublicTrace({ ...TRACE, knowledge: [{ id, method: "bm25" }] })).toBeNull();
    }
  });

  it("refuses a knowledge id with an empty segment or past the length limit", () => {
    const longest = `kb-${"a".repeat(61)}`;
    for (const id of ["kb--a", "kb-a-", "kb-a--b", `${longest}a`]) {
      expect(parsePublicTrace({ ...TRACE, knowledge: [{ id, method: "bm25" }] })).toBeNull();
    }
    const edge = { ...TRACE, knowledge: [{ id: longest, method: "bm25" }] };
    expect(parsePublicTrace(edge)?.knowledge).toEqual(edge.knowledge);
  });

  it("refuses the whole trace when the knowledge list has four entries", () => {
    const entry = (id: string) => ({ id, method: "bm25" });
    const three = ["kb-a", "kb-b", "kb-c"].map(entry);
    expect(parsePublicTrace({ ...TRACE, knowledge: three })?.knowledge).toEqual(three);
    expect(parsePublicTrace({ ...TRACE, knowledge: [...three, entry("kb-d")] })).toBeNull();
  });

  it("refuses the whole trace when a knowledge id repeats", () => {
    const twice = [
      { id: "kb-a", method: "bm25" },
      { id: "kb-a", method: "bm25" },
    ];
    expect(parsePublicTrace({ ...TRACE, knowledge: twice })).toBeNull();
  });

  it("refuses the whole trace when one knowledge entry is bad among good ones", () => {
    const mixed = [
      { id: "kb-a", method: "bm25" },
      { id: "kb-b\n", method: "bm25" },
    ];
    expect(parsePublicTrace({ ...TRACE, knowledge: mixed })).toBeNull();
  });

  it("accepts an empty knowledge list and keeps only the id and the method", () => {
    expect(parsePublicTrace({ ...TRACE, knowledge: [] })).toEqual({ ...TRACE, knowledge: [] });
    const dirty = { ...TRACE, knowledge: [{ id: "kb-a-1", method: "bm25", answer: CANARY }] };
    expect(parsePublicTrace(dirty)?.knowledge).toEqual([{ id: "kb-a-1", method: "bm25" }]);
  });

  it("refuses unknown outcomes, negative counts and non-numbers", () => {
    const bad = [
      { ...TRACE, tools: [{ ...TRACE.tools[0], outcome: "mismatch" }] },
      { ...TRACE, tokens: { ...TRACE.tokens, total: -1 } },
      { ...TRACE, tokens: { ...TRACE.tokens, rules: "19" } },
      { ...TRACE, latency: { first_token_ms: Number.NaN, total_ms: 1 } },
      { ...TRACE, tools: "none" },
      { ...TRACE, tools: undefined },
      { ...TRACE, knowledge: undefined },
      { ...TRACE, knowledge: "none" },
      { ...TRACE, knowledge: [null] },
      { ...TRACE, knowledge: [{ id: "kb-ship-standard", method: "dense" }] },
      { ...TRACE, knowledge: [{ id: "kb-ship-standard" }] },
      { ...TRACE, knowledge: [{ method: "bm25" }] },
      { ...TRACE, knowledge: [{ id: 7, method: "bm25" }] },
    ];
    for (const trace of bad) {
      expect(parsePublicTrace(trace)).toBeNull();
    }
  });
});

describe("limits shown by the page", () => {
  it("agree with the gateway's own limits", () => {
    expect(limits.maxMessages).toBe(gatewayLimits.maxMessagesPerSession);
    expect(limits.maxMessageChars).toBe(gatewayLimits.maxMessageChars);
  });

  it("carry the human-check wait, which the page reads instead of a number in the script", () => {
    expect(parseLimits(limits).humanCheckWaitMs).toBe(20000);
    expect(() => parseLimits({ ...limits, humanCheckWaitMs: 0 })).toThrow(TypeError);
    expect(() => parseLimits({ ...limits, humanCheckWaitMs: undefined })).toThrow(TypeError);
  });

  it("carry the longest an interactive human check may take, longer than the normal wait", () => {
    const parsed = parseLimits(limits);
    expect(parsed.humanCheckInteractiveMs).toBe(120000);
    expect(parsed.humanCheckInteractiveMs).toBeGreaterThan(parsed.humanCheckWaitMs);
    expect(() => parseLimits({ ...limits, humanCheckInteractiveMs: 0 })).toThrow(TypeError);
    expect(() => parseLimits({ ...limits, humanCheckInteractiveMs: undefined })).toThrow(TypeError);
  });

  it("carry the longest a chat request may take, a little longer than the gateway's own upstream limit", () => {
    const parsed = parseLimits(limits);
    expect(parsed.chatRequestMs).toBeGreaterThan(gatewayLimits.generateTimeoutMs);
    expect(() => parseLimits({ ...limits, chatRequestMs: 0 })).toThrow(TypeError);
    expect(() => parseLimits({ ...limits, chatRequestMs: undefined })).toThrow(TypeError);
  });
});

import { describe, expect, it, vi } from "vitest";
import limits from "../data/limits.json";
import { hideTyping, showTyping } from "../src/chat.ts";
import { role } from "../src/dom.ts";
import type { ChatOutcome, ChatRequest, Gateway, ReplayTurn } from "../src/gateway.ts";
import { TRACE, compare, flush, inputBox, mount, query, reply, say, submitMessage } from "./support.ts";

const TICKET = "1.9999999999.mac";
const LABEL = "The agent is replying…";
const sendButton = (): HTMLButtonElement => role(document, "send", HTMLButtonElement);
const log = (): HTMLElement => query('[data-role="log"]');

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function pendingGateway(): Gateway & {
  requests: ChatRequest[];
  pending: ReturnType<typeof deferred<ChatOutcome>>[];
} {
  const requests: ChatRequest[] = [];
  const pending: ReturnType<typeof deferred<ChatOutcome>>[] = [];
  return {
    requests,
    pending,
    chat(request) {
      requests.push(request);
      const outcome = deferred<ChatOutcome>();
      pending.push(outcome);
      return outcome.promise;
    },
  };
}

function expectWaiting(): HTMLElement {
  const bubble = query(".og-typing");
  expect(log().querySelectorAll(".og-typing")).toHaveLength(1);
  expect(bubble.className).toBe("og-cm og-b og-typing");
  expect(bubble.getAttribute("role")).toBe("status");
  expect(bubble.getAttribute("aria-label")).toBe(LABEL);
  expect(bubble.textContent).toBe("");
  expect(bubble.querySelectorAll("span")).toHaveLength(3);
  expect(log().getAttribute("aria-busy")).toBe("true");
  expect(sendButton().disabled).toBe(true);
  expect(sendButton().getAttribute("aria-busy")).toBe("true");
  expect(inputBox().readOnly).toBe(true);
  return bubble;
}

function expectFinished(): void {
  expect(log().querySelector(".og-typing")).toBeNull();
  expect(log().hasAttribute("aria-busy")).toBe(false);
  expect(sendButton().disabled).toBe(false);
  expect(sendButton().hasAttribute("aria-busy")).toBe(false);
  expect(inputBox().readOnly).toBe(false);
}

function resolveRequest(gateway: ReturnType<typeof pendingGateway>, outcome: ChatOutcome): void {
  const next = gateway.pending.shift();
  if (next === undefined) {
    throw new Error("no pending request");
  }
  next.resolve(outcome);
}

const OUTCOMES: ChatOutcome[] = [
  reply("Answer"),
  { kind: "replay", reason: "quota", turns: [{ role: "assistant", content: "Replay answer" }] },
  { kind: "failed", status: 0, reason: "network" },
];

describe("typing indicator", () => {
  it.each(OUTCOMES)("cleans up before rendering $kind and restores input focus", async (outcome) => {
    const gateway = pendingGateway();
    mount({ gateway });
    submitMessage("hey");
    const bubble = expectWaiting();
    expect(bubble.previousElementSibling?.textContent).toBe("hey");
    expect(inputBox().disabled).toBe(false);
    expect(log().getAttribute("role")).toBe("log");
    expect(log().getAttribute("aria-live")).toBe("polite");
    await flush();
    expect(gateway.requests).toHaveLength(1);
    const append = log().append.bind(log());
    const rendering = vi.spyOn(log(), "append").mockImplementation((...nodes) => {
      expect(log().querySelector(".og-typing")).toBeNull();
      expect(log().hasAttribute("aria-busy")).toBe(false);
      append(...nodes);
    });
    resolveRequest(gateway, outcome);
    await flush();
    expect(rendering).toHaveBeenCalled();
    expectFinished();
    expect(document.activeElement).toBe(inputBox());
    rendering.mockRestore();
  });

  it("is idempotent and adds no visible text", () => {
    mount();
    const before = log().textContent;
    showTyping(log(), LABEL);
    const bubble = query(".og-typing");
    showTyping(log(), LABEL);
    expect(log().querySelectorAll(".og-typing")).toHaveLength(1);
    expect(query(".og-typing")).toBe(bubble);
    expect(log().textContent).toBe(before);
    hideTyping(log());
    hideTyping(log());
    expect(log().hasAttribute("aria-busy")).toBe(false);
  });

  it("keeps one bubble and one request for two quick submits", async () => {
    const gateway = pendingGateway();
    mount({ gateway });
    submitMessage("first");
    submitMessage("second");
    expectWaiting();
    await flush();
    expect(gateway.requests).toHaveLength(1);
    expect(log().querySelectorAll(".og-u")).toHaveLength(1);
    resolveRequest(gateway, reply("done"));
    await flush();
    expectFinished();
  });

  it("shows the bubble during compare without restoring input focus", async () => {
    const gateway = pendingGateway();
    mount({ gateway });
    await say("hey");
    resolveRequest(gateway, reply("gist"));
    await flush();
    sendButton().focus();
    await compare();
    expectWaiting();
    expect(gateway.requests.at(-1)?.mode).toBe("full");
    resolveRequest(gateway, reply("full"));
    await flush();
    expectFinished();
    expect(query('[data-role="compare-out"]').textContent).toContain("full");
    expect(document.activeElement).toBe(sendButton());
  });

  it("keeps the same bubble through a stored-ticket 403, challenge and resend", async () => {
    const gateway = pendingGateway();
    const challenge = deferred<string>();
    const token = vi.fn().mockResolvedValueOnce("initial").mockReturnValueOnce(challenge.promise);
    mount({ gateway, check: { warm: () => undefined, reset: () => undefined, token } });
    await say("first");
    resolveRequest(gateway, { kind: "reply", answer: "first answer", trace: TRACE, ticket: TICKET });
    await flush();
    await say("second");
    const bubble = expectWaiting();
    expect(gateway.requests.at(-1)?.ticket).toBe(TICKET);
    resolveRequest(gateway, { kind: "failed", status: 403, reason: "http" });
    await flush();
    expect(expectWaiting()).toBe(bubble);
    expect(gateway.requests).toHaveLength(2);
    challenge.resolve("renewed");
    await flush();
    expect(expectWaiting()).toBe(bubble);
    expect(gateway.requests).toHaveLength(3);
    expect(gateway.requests.at(-1)?.turnstileToken).toBe("renewed");
    resolveRequest(gateway, reply("second answer"));
    await flush();
    expectFinished();
    expect(document.activeElement).toBe(inputBox());
  });

  it("shows the bubble while the first human check is pending", async () => {
    const challenge = deferred<string>();
    const gateway = pendingGateway();
    mount({ gateway, check: { warm: () => undefined, reset: () => undefined, token: () => challenge.promise } });
    await say("hey");
    expectWaiting();
    expect(gateway.requests).toHaveLength(0);
    challenge.resolve("checked");
    await flush();
    expectWaiting();
    resolveRequest(gateway, reply("checked answer"));
    await flush();
    expectFinished();
    expect(document.activeElement).toBe(inputBox());
  });

  it("cleans up when the human check rejects", async () => {
    const token = vi.fn().mockRejectedValue(new Error("check failed"));
    const gateway = pendingGateway();
    mount({ gateway, check: { warm: () => undefined, reset: () => undefined, token } });
    submitMessage("hey");
    expectWaiting();
    await flush();
    expectFinished();
    expect(gateway.requests).toHaveLength(0);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("check");
    expect(document.activeElement).toBe(inputBox());
  });

  it("cleans up when the finish handler throws", async () => {
    const gateway = pendingGateway();
    mount({ gateway });
    await say("hey");
    expectWaiting();
    resolveRequest(gateway, { kind: "replay", reason: "quota", turns: null as unknown as ReplayTurn[] });
    await flush();
    expectFinished();
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("unexpected");
    expect(document.activeElement).toBe(inputBox());
  });

  it("keeps the input disabled at the message cap and does not restore its focus", async () => {
    const gateway = pendingGateway();
    mount({ gateway, limits: { ...limits, maxMessages: 1 } });
    await say("last");
    expectWaiting();
    expect(inputBox().disabled).toBe(true);
    resolveRequest(gateway, reply("done"));
    await flush();
    expectFinished();
    expect(inputBox().disabled).toBe(true);
    expect(document.activeElement).not.toBe(inputBox());
  });
});

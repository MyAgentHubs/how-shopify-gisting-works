import { describe, expect, it, vi } from "vitest";
import limits from "../data/limits.json";
import { role } from "../src/dom.ts";
import { text } from "../src/copy.ts";
import { createHumanCheck } from "../src/turnstile.ts";
import { compare, english, flush, inputBox, mount, query, reply, say } from "./support.ts";
import { fakeTurnstile } from "./turnstile-fake.ts";
import { buildPages } from "./page-helpers.mjs";
import { readRuntime } from "../src/runtime.ts";

const row = (): HTMLElement => query('[data-role="log"] [data-reason="check"]');
const retryButton = (): HTMLButtonElement => {
  const button = row().querySelector("button");
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("missing retry button");
  }
  return button;
};
const sendButton = (): HTMLButtonElement => role(document, "send", HTMLButtonElement);

describe("retrying a human check", () => {
  it("shows the dedicated copy and retry button in the check error row", async () => {
    const page = mount({ check: {
      warm: () => undefined, reset: () => undefined,
      token: () => Promise.reject(new Error("verification failed")),
    } });
    await say("hello");
    expect(row().textContent).toContain(text(english, "ui.checkFailed"));
    expect(retryButton().textContent).toBe(text(english, "ui.checkRetry"));
    expect(row().textContent).not.toContain(text(english, "ui.error"));
    expect(page.gateway.requests).toHaveLength(0);
  });

  it("resets once, resends the same text once, and restores the usual send state", async () => {
    let solve!: (value: string) => void;
    const pending = new Promise<string>((resolve) => { solve = resolve; });
    const reset = vi.fn();
    const token = vi.fn().mockRejectedValueOnce(new Error("failed")).mockReturnValueOnce(pending);
    const page = mount({
      limits: { ...limits, maxMessages: 2 },
      check: { warm: () => undefined, reset, token },
    });
    await say("original");
    const button = retryButton();
    button.click();
    button.click();
    expect(reset).toHaveBeenCalledTimes(1);
    expect(button.isConnected).toBe(false);
    expect(query(".og-typing")).toBeDefined();
    expect(sendButton().disabled).toBe(true);
    expect(sendButton().getAttribute("aria-busy")).toBe("true");
    expect(inputBox().readOnly).toBe(true);
    expect(document.querySelectorAll(".og-u")).toHaveLength(1);
    solve("renewed");
    await flush();
    expect(page.gateway.requests).toHaveLength(1);
    expect(page.gateway.requests[0]).toMatchObject({ message: "original", turnstileToken: "renewed" });
    expect(document.querySelectorAll(".og-u")).toHaveLength(1);
    expect(query('[data-role="log"]').textContent).toContain("Answer one");
    expect(row().querySelector("button")).toBeNull();
    expect(document.querySelector(".og-typing")).toBeNull();
    expect(sendButton().disabled).toBe(false);
    expect(inputBox().readOnly).toBe(false);
    expect(inputBox().disabled).toBe(false);
    expect(document.activeElement).toBe(inputBox());
    await say("second");
    expect(inputBox().disabled).toBe(true);
  });

  it("shows another retry row if verification fails again", async () => {
    const reset = vi.fn();
    mount({ check: {
      warm: () => undefined, reset,
      token: () => Promise.reject(new Error("failed")),
    } });
    await say("original");
    retryButton().click();
    await flush();
    const rows = document.querySelectorAll('[data-reason="check"]');
    expect(rows).toHaveLength(2);
    expect(rows[1]?.textContent).toContain(text(english, "ui.checkFailed"));
    expect(rows[1]?.querySelector("button")?.textContent).toBe(text(english, "ui.checkRetry"));
    expect(sendButton().disabled).toBe(false);
  });

  it("ignores retry clicks while another send is busy", async () => {
    let solve!: (value: string) => void;
    const pending = new Promise<string>((resolve) => { solve = resolve; });
    const reset = vi.fn();
    const token = vi.fn().mockRejectedValueOnce(new Error("failed")).mockReturnValueOnce(pending);
    mount({ check: { warm: () => undefined, reset, token } });
    await say("original");
    const button = retryButton();
    await say("next");
    button.click();
    expect(reset).not.toHaveBeenCalled();
    expect(button.isConnected).toBe(true);
    solve("checked");
    await flush();
  });

  it("keeps the generic error without a button for network failures", async () => {
    mount({ outcomes: [{ kind: "failed", status: 0, reason: "network" }] });
    await say("hello");
    const error = query('[data-role="log"] [data-reason="network"]');
    expect(error.textContent).toBe(text(english, "ui.error"));
    expect(error.querySelector("button")).toBeNull();
  });

  it("keeps the generic error for a comparison check failure", async () => {
    const token = vi.fn().mockResolvedValueOnce("checked").mockRejectedValueOnce(new Error("failed"));
    mount({ check: { warm: () => undefined, reset: () => undefined, token }, outcomes: [reply("answer")] });
    await say("hello");
    await compare();
    expect(row().textContent).toBe(text(english, "ui.error"));
    expect(row().querySelector("button")).toBeNull();
  });

  it("resets the real abstraction after widget failure without resetting twice", async () => {
    const fake = fakeTurnstile();
    const page = mount({ humanCheck: (config, waits) => createHumanCheck({
      container: role(document, "turnstile", HTMLElement), config, ...waits,
      api: () => fake.api, load: () => Promise.resolve(),
    }) });
    await say("original");
    fake.fail();
    await flush();
    retryButton().click();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("renewed");
    await flush();
    expect(page.gateway.requests).toHaveLength(1);
    expect(page.gateway.requests[0]?.message).toBe("original");
  });

  it("keeps new copy in runtime data and falls back to English in ja and ko", () => {
    const pages = buildPages();
    for (const lang of ["en", "zh-CN", "ja", "ko"]) {
      const doc = pages.doc(lang);
      const copy = readRuntime(doc).copy;
      if (lang !== "zh-CN") {
        expect(text(copy, "ui.checkFailed")).toBe(text(english, "ui.checkFailed"));
        expect(text(copy, "ui.checkRetry")).toBe(text(english, "ui.checkRetry"));
      }
      doc.querySelectorAll("script").forEach((node) => { node.remove(); });
      expect(doc.body.textContent).not.toContain(text(copy, "ui.checkFailed"));
      expect(doc.body.textContent).not.toContain(text(copy, "ui.checkRetry"));
    }
  });
});

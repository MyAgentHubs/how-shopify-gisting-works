import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import limitsJson from "../data/limits.json";
import runtimeData from "../data/runtime.json";
import { text } from "../src/copy.ts";
import { role } from "../src/dom.ts";
import { readRuntime } from "../src/runtime.ts";
import { createHumanCheck, injectScript } from "../src/turnstile.ts";
import { english, flush, inputBox, mount, query, say, submitMessage } from "./support.ts";
import { fakeTurnstile } from "./turnstile-fake.ts";

const SCRIPT_SELECTOR = 'script[src*="challenges.cloudflare.com"]';
const settle = (): Promise<unknown> => vi.advanceTimersByTimeAsync(0);
const WAITED_MS = 25000;

beforeEach(() => {
  document.head.replaceChildren();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the chat page with the human check wired in", () => {
  function wired(): {
    readonly fake: ReturnType<typeof fakeTurnstile>;
    readonly requests: () => readonly { turnstileToken?: string }[];
    readonly loadScript: () => Promise<void>;
  } {
    const fake = fakeTurnstile();
    const page = mount({
      humanCheck: (config, waits) =>
        createHumanCheck({
          container: role(document, "turnstile", HTMLElement),
          config,
          ...waits,
          api: () => fake.api,
          load: injectScript(document),
        }),
    });
    return {
      fake,
      requests: () => page.gateway.requests,
      loadScript: async () => {
        document.querySelector(SCRIPT_SELECTOR)?.dispatchEvent(new Event("load"));
        await flush();
      },
    };
  }

  it("takes the sitekey and action from runtime.json through the page's own data block", () => {
    mount();
    const { turnstile } = readRuntime(document);
    expect(turnstile).toEqual({
      sitekey: runtimeData.turnstile.sitekey,
      action: runtimeData.turnstile.action,
    });
  });

  it("does not touch Cloudflare before the visitor focuses the box or presses an example", () => {
    wired();
    expect(document.querySelector(SCRIPT_SELECTOR)).toBeNull();
  });

  it("loads the script when the box is first focused, once, with the runtime.json action on the widget", async () => {
    const { fake, loadScript } = wired();
    inputBox().dispatchEvent(new Event("focus"));
    inputBox().dispatchEvent(new Event("focus"));
    expect(document.querySelectorAll(SCRIPT_SELECTOR)).toHaveLength(1);
    await loadScript();
    expect(fake.widgets).toHaveLength(1);
    expect(fake.widgets[0]?.options.action).toBe(runtimeData.turnstile.action);
    expect(fake.widgets[0]?.options.sitekey).toBe(runtimeData.turnstile.sitekey);
    expect(role(document, "turnstile", HTMLElement).contains(fake.widgets[0]?.container ?? null)).toBe(true);
  });

  it("loads the script when an example button is pressed", () => {
    wired();
    query(".og-exbtn").click();
    expect(document.querySelectorAll(SCRIPT_SELECTOR)).toHaveLength(1);
  });

  it("sends the token with the chat request, and a new one for the next message", async () => {
    const { fake, loadScript, requests } = wired();
    inputBox().dispatchEvent(new Event("focus"));
    await loadScript();
    fake.solve("token-one");
    await say("hello");
    expect(requests()[0]?.turnstileToken).toBe("token-one");
    fake.solve("token-two");
    await say("again");
    expect(requests()[1]?.turnstileToken).toBe("token-two");
  });

  it("shows the verification error and retry when the check fails", async () => {
    const { fake, loadScript } = wired();
    inputBox().dispatchEvent(new Event("focus"));
    await loadScript();
    const sent = say("hello");
    await flush();
    fake.fail();
    await sent;
    await flush();
    const log = query('[data-role="log"]').textContent;
    const line = query('[data-role="log"] [data-reason]');
    expect(line.textContent).toContain(text(english, "ui.checkFailed"));
    expect(line.querySelector("button")?.textContent).toBe(text(english, "ui.checkRetry"));
    expect(log).not.toMatch(/turnstile|human check|failed/i);
    expect(line.getAttribute("data-reason")).toBe("check");
  });

  async function readyToSend(): Promise<ReturnType<typeof wired>> {
    vi.useFakeTimers();
    const page = wired();
    inputBox().dispatchEvent(new Event("focus"));
    document.querySelector(SCRIPT_SELECTOR)?.dispatchEvent(new Event("load"));
    await settle();
    return page;
  }

  it("sends the message once the visitor has worked through an interactive challenge, however long it took", async () => {
    const { fake, requests } = await readyToSend();
    submitMessage("hey");
    await settle();
    fake.interact();
    await vi.advanceTimersByTimeAsync(WAITED_MS);
    fake.interactDone();
    fake.solve("t");
    await settle();
    expect(requests()[0]?.turnstileToken).toBe("t");
    expect(document.querySelector('[data-role="log"] [data-reason="check"]')).toBeNull();
  });

  it("shows the verification error and frees the send button when an interactive challenge is never finished", async () => {
    const { fake, requests } = await readyToSend();
    submitMessage("hey");
    await settle();
    fake.interact();
    await vi.advanceTimersByTimeAsync(limitsJson.humanCheckInteractiveMs);
    expect(requests()).toEqual([]);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("check");
    expect(role(document, "send", HTMLButtonElement).disabled).toBe(false);
  });

  it("shows the verification error and frees the send button when the script never loads", async () => {
    vi.useFakeTimers();
    const { requests } = wired();
    inputBox().dispatchEvent(new Event("focus"));
    submitMessage("hey");
    await vi.advanceTimersByTimeAsync(limitsJson.humanCheckWaitMs);
    expect(requests()).toEqual([]);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("check");
    expect(role(document, "send", HTMLButtonElement).disabled).toBe(false);
  });
});

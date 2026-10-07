import { describe, expect, it } from "vitest";
import { role } from "../src/dom.ts";
import { createHumanCheck } from "../src/turnstile.ts";
import { flush, inputBox, mount, say, submitMessage } from "./support.ts";
import { FRESH, answer, forbidden, stepping } from "./ticket-support.ts";
import type { Step } from "./ticket-support.ts";
import { fakeTurnstile } from "./turnstile-fake.ts";

const CONFIG = { sitekey: "site-key", action: "an-action" };

function unit(): { readonly fake: ReturnType<typeof fakeTurnstile>; readonly check: ReturnType<typeof createHumanCheck> } {
  const fake = fakeTurnstile();
  const check = createHumanCheck({
    container: document.createElement("div"),
    config: CONFIG,
    waitMs: 5000,
    interactiveMs: 20000,
    api: () => fake.api,
    load: () => Promise.resolve(),
  });
  return { fake, check };
}

function page(steps: Parameters<typeof stepping>[0]): {
  readonly fake: ReturnType<typeof fakeTurnstile>;
  readonly requests: ReturnType<typeof stepping>["requests"];
  readonly send: (message: string, token?: string) => Promise<void>;
} {
  const fake = fakeTurnstile();
  const gateway = stepping(steps);
  mount({
    gateway,
    humanCheck: (config, waits) =>
      createHumanCheck({
        container: role(document, "turnstile", HTMLElement),
        config,
        ...waits,
        api: () => fake.api,
        load: () => Promise.resolve(),
      }),
  });
  return {
    fake,
    requests: gateway.requests,
    send: async (message, token) => {
      submitMessage(message);
      await flush();
      if (token !== undefined) {
        fake.solve(token);
        await flush();
      }
    },
  };
}

describe("the widget after a token has been handed out", () => {
  it("does not reset until the next token is really needed", async () => {
    const { check, fake } = unit();
    check.warm();
    await flush();
    fake.solve("first");
    await expect(check.token()).resolves.toBe("first");
    expect(fake.resets).toEqual([]);
    const next = check.token();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("second");
    await expect(next).resolves.toBe("second");
    expect(fake.resets).toEqual(["widget-1"]);
  });

  it("does not reset after a token that a waiting send received", async () => {
    const { check, fake } = unit();
    const pending = check.token();
    await flush();
    fake.solve("late");
    await expect(pending).resolves.toBe("late");
    expect(fake.resets).toEqual([]);
  });

  it("ignores the expiry of a token that was already used", async () => {
    const { check, fake } = unit();
    const pending = check.token();
    await flush();
    fake.solve("used");
    await pending;
    fake.expire();
    expect(fake.resets).toEqual([]);
  });

  it("warms up by starting the next challenge when the last token was used and no ticket protects the page", async () => {
    const { check, fake } = unit();
    const pending = check.token();
    await flush();
    fake.solve("used");
    await pending;
    check.warm();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("prefetched");
    await expect(check.token()).resolves.toBe("prefetched");
  });
});

const unavailable: Step = () => ({ kind: "failed", status: 502, reason: "http" });
const throttled: Step = () => ({ kind: "failed", status: 429, reason: "http" });

describe("the page while it holds no ticket", () => {
  it.each([
    ["a gateway error", unavailable],
    ["a rate limit", throttled],
  ])("starts the next challenge in the background after %s", async (_name, failure) => {
    const { fake, send, requests } = page([failure, answer("two")]);
    await send("one", "token-one");
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("token-two");
    await send("two");
    expect(requests[1]?.turnstileToken).toBe("token-two");
  });

  it("starts it again after each send that leaves the page without a ticket", async () => {
    const { fake, send } = page([unavailable, unavailable, answer("three")]);
    await send("one", "token-one");
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("token-two");
    await send("two");
    expect(fake.resets).toEqual(["widget-1", "widget-1"]);
  });
});

describe("the page while it holds a ticket", () => {
  it("leaves the widget alone after the send that brought the ticket", async () => {
    const { fake, send } = page([answer("one", FRESH)]);
    await send("one", "token-one");
    expect(fake.resets).toEqual([]);
  });

  it("renders the widget once and never resets or re-challenges for later messages or focus", async () => {
    const { fake, send, requests } = page([answer("one", FRESH), answer("two"), answer("three")]);
    await send("one", "token-one");
    inputBox().dispatchEvent(new Event("focus"));
    await send("two");
    await send("three");
    expect(requests).toHaveLength(3);
    expect(fake.widgets).toHaveLength(1);
    expect(fake.resets).toEqual([]);
  });

  it("does not warm the widget on a focus or an example button once it holds a ticket", async () => {
    const { fake, send } = page([answer("one", FRESH)]);
    await send("one", "token-one");
    inputBox().dispatchEvent(new Event("focus"));
    document.querySelector<HTMLElement>(".og-exbtn")?.click();
    await flush();
    expect(fake.resets).toEqual([]);
    expect(fake.widgets).toHaveLength(1);
  });

  it("removes the expired widget while the ticket is held and renders a new one when a refused ticket needs a token", async () => {
    const { fake, send, requests } = page([answer("one", FRESH), forbidden, answer("two")]);
    await send("one", "token-one");
    fake.expire();
    expect(fake.removed).toEqual(["widget-1"]);
    await send("two");
    expect(fake.widgets).toHaveLength(2);
    expect(fake.resets).toEqual([]);
    fake.solve("token-two");
    await flush();
    expect(requests).toHaveLength(3);
    expect(requests[2]?.turnstileToken).toBe("token-two");
  });

  it("resets the widget once a refused ticket sends the page back to the bot check", async () => {
    const { fake, send, requests } = page([answer("one", FRESH), forbidden, answer("two")]);
    await send("one", "token-one");
    await send("two");
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("token-two");
    await flush();
    expect(requests).toHaveLength(3);
    expect(requests[2]?.turnstileToken).toBe("token-two");
  });

  it("keeps the send button usable after the first message", async () => {
    const { send } = page([answer("one", FRESH), answer("two")]);
    await send("one", "token-one");
    await say("two");
    expect(role(document, "send", HTMLButtonElement).disabled).toBe(false);
  });
});

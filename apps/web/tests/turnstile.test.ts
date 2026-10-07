import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TURNSTILE_SCRIPT_URL, createHumanCheck, injectScript } from "../src/turnstile.ts";
import { flush } from "./support.ts";
import { fakeTurnstile } from "./turnstile-fake.ts";

const CONFIG = { sitekey: "site-key", action: "an-action" };
const SCRIPT_SELECTOR = 'script[src*="challenges.cloudflare.com"]';
const WAIT_LIMIT_MS = 5000;
const INTERACTIVE_LIMIT_MS = 20000;
const settle = (): Promise<unknown> => vi.advanceTimersByTimeAsync(0);

function setup(): {
  readonly fake: ReturnType<typeof fakeTurnstile>;
  readonly loads: string[];
  readonly check: ReturnType<typeof createHumanCheck>;
} {
  const fake = fakeTurnstile();
  const loads: string[] = [];
  const check = createHumanCheck({
    container: document.createElement("div"),
    config: CONFIG,
    waitMs: WAIT_LIMIT_MS,
    interactiveMs: INTERACTIVE_LIMIT_MS,
    api: () => fake.api,
    load: (src) => {
      loads.push(src);
      return Promise.resolve();
    },
  });
  return { fake, loads, check };
}

beforeEach(() => {
  document.head.replaceChildren();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the human check", () => {
  it("loads nothing until it is warmed up, then loads Cloudflare's script once", async () => {
    const { check, loads, fake } = setup();
    expect(loads).toEqual([]);
    check.warm();
    check.warm();
    await flush();
    expect(loads).toEqual([TURNSTILE_SCRIPT_URL]);
    expect(TURNSTILE_SCRIPT_URL).toBe("https://challenges.cloudflare.com/turnstile/v0/api.js");
    expect(fake.widgets).toHaveLength(1);
  });

  it("renders an interaction-only widget with the sitekey and action it was given", async () => {
    const { check, fake } = setup();
    check.warm();
    await flush();
    expect(fake.widgets[0]?.options).toMatchObject({
      sitekey: "site-key",
      action: "an-action",
      appearance: "interaction-only",
      "refresh-expired": "manual",
    });
  });

  it("hands over a token that is already there, then asks for a fresh one", async () => {
    const { check, fake } = setup();
    check.warm();
    await flush();
    fake.solve("first");
    await expect(check.token()).resolves.toBe("first");
    expect(fake.resets).toEqual([]);
    void check.token();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
  });

  it("waits for the token when none has arrived yet, and never gives one out twice", async () => {
    const { check, fake } = setup();
    const pending = check.token();
    await flush();
    fake.solve("late");
    await expect(pending).resolves.toBe("late");
    expect(fake.resets).toEqual([]);
    const second = check.token();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("next");
    await expect(second).resolves.toBe("next");
  });

  it("never hands the same token to two sends, whether it was held or just arrived", async () => {
    const { check, fake } = setup();
    check.warm();
    await flush();
    fake.solve("only-once");
    await expect(check.token()).resolves.toBe("only-once");
    let second: string | null = null;
    void check.token().then((token) => {
      second = token;
    });
    await flush();
    expect(second).toBeNull();
    fake.solve("fresh");
    await flush();
    expect(second).toBe("fresh");
  });

  it("gives two sends that wait together two different tokens, in order", async () => {
    const { check, fake } = setup();
    const first = check.token();
    await flush();
    const second = check.token();
    await flush();
    fake.solve("one");
    await expect(first).resolves.toBe("one");
    fake.solve("two");
    await expect(second).resolves.toBe("two");
  });

  it("drops an expired token and resets the widget", async () => {
    const { check, fake } = setup();
    check.warm();
    await flush();
    fake.solve("old");
    fake.expire();
    expect(fake.resets).toEqual(["widget-1"]);
    const pending = check.token();
    await flush();
    fake.solve("new");
    await expect(pending).resolves.toBe("new");
  });

  it("fails a waiting send with one plain error when the check fails, and resets before the next try", async () => {
    const { check, fake } = setup();
    const pending = check.token();
    await flush();
    fake.fail();
    await expect(pending).rejects.toThrow("the human check failed");
    const retry = check.token();
    await flush();
    expect(fake.resets).toEqual(["widget-1"]);
    fake.solve("again");
    await expect(retry).resolves.toBe("again");
  });

  it("fails a waiting send when an interactive challenge times out", async () => {
    const { check, fake } = setup();
    const pending = check.token();
    await flush();
    fake.stall();
    await expect(pending).rejects.toThrow("the human check failed");
  });

  it("gives up waiting after the limit it was given, and resets the widget", async () => {
    vi.useFakeTimers();
    const { check, fake } = setup();
    const pending = check.token();
    const outcome = expect(pending).rejects.toThrow("the human check timed out");
    await vi.advanceTimersByTimeAsync(WAIT_LIMIT_MS - 1);
    expect(fake.resets).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    await outcome;
    expect(fake.resets).toEqual(["widget-1"]);
  });

  it("keeps waiting past the normal limit while the visitor works through an interactive challenge", async () => {
    vi.useFakeTimers();
    const { check, fake } = setup();
    const pending = check.token();
    await settle();
    fake.interact();
    await vi.advanceTimersByTimeAsync(WAIT_LIMIT_MS * 3);
    expect(fake.resets).toEqual([]);
    fake.solve("after-click");
    await expect(pending).resolves.toBe("after-click");
  });

  it("applies the interactive limit to a send that starts while a challenge is already showing", async () => {
    vi.useFakeTimers();
    const { check, fake } = setup();
    check.warm();
    await settle();
    fake.interact();
    const pending = check.token();
    await vi.advanceTimersByTimeAsync(WAIT_LIMIT_MS * 3);
    expect(fake.resets).toEqual([]);
    fake.solve("late");
    await expect(pending).resolves.toBe("late");
  });

  it("gives up on an interactive challenge after the interactive limit, and resets the widget", async () => {
    vi.useFakeTimers();
    const { check, fake } = setup();
    const pending = check.token();
    const outcome = expect(pending).rejects.toThrow("the human check timed out");
    await settle();
    fake.interact();
    await vi.advanceTimersByTimeAsync(INTERACTIVE_LIMIT_MS - 1);
    expect(fake.resets).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    await outcome;
    expect(fake.resets).toEqual(["widget-1"]);
  });

  it("starts the normal wait over once the visitor is done interacting", async () => {
    vi.useFakeTimers();
    const { check, fake } = setup();
    const pending = check.token();
    const outcome = expect(pending).rejects.toThrow("the human check timed out");
    await settle();
    fake.interact();
    await vi.advanceTimersByTimeAsync(INTERACTIVE_LIMIT_MS - 1);
    fake.interactDone();
    await vi.advanceTimersByTimeAsync(WAIT_LIMIT_MS - 1);
    expect(fake.resets).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    await outcome;
    expect(fake.resets).toEqual(["widget-1"]);
  });

  it("fails and loads the script again next time when the script cannot be loaded", async () => {
    const fake = fakeTurnstile();
    let attempts = 0;
    const check = createHumanCheck({
      container: document.createElement("div"),
      config: CONFIG,
    waitMs: WAIT_LIMIT_MS,
    interactiveMs: INTERACTIVE_LIMIT_MS,
      api: () => fake.api,
      load: () => {
        attempts += 1;
        return attempts === 1 ? Promise.reject(new Error("offline")) : Promise.resolve();
      },
    });
    await expect(check.token()).rejects.toThrow("offline");
    const retry = check.token();
    await flush();
    fake.solve("ok");
    await expect(retry).resolves.toBe("ok");
    expect(attempts).toBe(2);
  });

  it("fails when the script never finishes loading, and loads it again next time", async () => {
    vi.useFakeTimers();
    const fake = fakeTurnstile();
    let attempts = 0;
    const check = createHumanCheck({
      container: document.createElement("div"),
      config: CONFIG,
      waitMs: WAIT_LIMIT_MS,
      interactiveMs: INTERACTIVE_LIMIT_MS,
      api: () => fake.api,
      load: () => {
        attempts += 1;
        return attempts === 1 ? new Promise<void>(() => undefined) : Promise.resolve();
      },
    });
    const stuck = expect(check.token()).rejects.toThrow("did not load in time");
    await vi.advanceTimersByTimeAsync(WAIT_LIMIT_MS);
    await stuck;
    const retry = check.token();
    await settle();
    fake.solve("ok");
    await expect(retry).resolves.toBe("ok");
    expect(attempts).toBe(2);
  });

  it("fails when the script loaded but left no turnstile object", async () => {
    const check = createHumanCheck({
      container: document.createElement("div"),
      config: CONFIG,
    waitMs: WAIT_LIMIT_MS,
    interactiveMs: INTERACTIVE_LIMIT_MS,
      api: () => undefined,
      load: () => Promise.resolve(),
    });
    await expect(check.token()).rejects.toThrow(TypeError);
  });
});

describe("the script loader", () => {
  it("adds one async script with the given source and settles when it loads or fails", async () => {
    const load = injectScript(document);
    const loaded = load(TURNSTILE_SCRIPT_URL);
    const script = document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR);
    expect(script?.getAttribute("src")).toBe(TURNSTILE_SCRIPT_URL);
    expect(script?.async).toBe(true);
    script?.dispatchEvent(new Event("load"));
    await expect(loaded).resolves.toBeUndefined();
    const broken = load(TURNSTILE_SCRIPT_URL);
    document.querySelectorAll(SCRIPT_SELECTOR).item(1).dispatchEvent(new Event("error"));
    await expect(broken).rejects.toThrow("could not be loaded");
  });
});

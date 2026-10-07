import { afterEach, describe, expect, it, vi } from "vitest";
import { createHumanCheck } from "../src/turnstile.ts";
import { flush } from "./support.ts";
import { fakeTurnstile } from "./turnstile-fake.ts";

const CONFIG = { sitekey: "site-key", action: "an-action" };
const WAIT_MS = 5000;
const INTERACTIVE_MS = 20000;
const settle = (): Promise<unknown> => vi.advanceTimersByTimeAsync(0);

afterEach(() => {
  vi.useRealTimers();
});

function unit(): {
  readonly fake: ReturnType<typeof fakeTurnstile>;
  readonly check: ReturnType<typeof createHumanCheck>;
  readonly loads: () => number;
} {
  const fake = fakeTurnstile();
  let loads = 0;
  const check = createHumanCheck({
    container: document.createElement("div"),
    config: CONFIG,
    waitMs: WAIT_MS,
    interactiveMs: INTERACTIVE_MS,
    api: () => fake.api,
    load: () => {
      loads += 1;
      return Promise.resolve();
    },
  });
  return { fake, check, loads: () => loads };
}

async function spend(
  { fake, check }: ReturnType<typeof unit>,
  token: string,
): Promise<void> {
  const pending = check.token();
  await flush();
  fake.solve(token);
  await expect(pending).resolves.toBe(token);
}

describe("a widget whose token expires after it was used", () => {
  it("is removed from the page, not reset, so no stale refresh box can appear", async () => {
    const page = unit();
    await spend(page, "used");
    page.fake.expire();
    expect(page.fake.removed).toEqual(["widget-1"]);
    expect(page.fake.resets).toEqual([]);
  });

  it("is rendered again, once, when the next token is needed", async () => {
    const page = unit();
    await spend(page, "used");
    page.fake.expire();
    const next = page.check.token();
    await flush();
    expect(page.fake.widgets).toHaveLength(2);
    expect(page.fake.resets).toEqual([]);
    page.fake.solve("fresh");
    await expect(next).resolves.toBe("fresh");
    expect(page.loads()).toBe(1);
  });

  it("is rendered again by a warm-up and then hands out the prefetched token", async () => {
    const page = unit();
    await spend(page, "used");
    page.fake.expire();
    page.check.warm();
    await flush();
    expect(page.fake.widgets).toHaveLength(2);
    page.fake.solve("prefetched");
    await expect(page.check.token()).resolves.toBe("prefetched");
    expect(page.fake.resets).toEqual([]);
  });

  it("is removed only once however many times the expiry is reported", async () => {
    const page = unit();
    await spend(page, "used");
    page.fake.expire();
    page.fake.expire();
    expect(page.fake.removed).toEqual(["widget-1"]);
  });

  it("still lets a visitor take more than the usual wait to pass an interactive challenge", async () => {
    vi.useFakeTimers();
    const page = unit();
    const first = page.check.token();
    await settle();
    page.fake.solve("used");
    await first;
    page.fake.expire();
    const next = page.check.token();
    await settle();
    page.fake.interact();
    await vi.advanceTimersByTimeAsync(INTERACTIVE_MS - 1);
    page.fake.interactDone();
    page.fake.solve("solved");
    await expect(next).resolves.toBe("solved");
  });
});

describe("a widget whose unused token expires", () => {
  it("is reset in place and never removed", async () => {
    const page = unit();
    page.check.warm();
    await flush();
    page.fake.solve("early");
    page.fake.expire();
    expect(page.fake.resets).toEqual(["widget-1"]);
    expect(page.fake.removed).toEqual([]);
    page.fake.solve("late");
    await expect(page.check.token()).resolves.toBe("late");
  });
});

describe("the widget after a warm-up reset", () => {
  it("counts as fresh, so handing out the prefetched token does not reset it a second time", async () => {
    const page = unit();
    await spend(page, "used");
    page.check.warm();
    await flush();
    expect(page.fake.resets).toEqual(["widget-1"]);
    page.fake.solve("prefetched");
    await expect(page.check.token()).resolves.toBe("prefetched");
    expect(page.fake.resets).toEqual(["widget-1"]);
  });
});

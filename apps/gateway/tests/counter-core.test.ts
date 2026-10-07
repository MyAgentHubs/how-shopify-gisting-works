import { describe, expect, it } from "vitest";
import { CounterCore } from "../counter-worker/src/counter-core";
import { FakeHost } from "./fake-durable";

const TTL = 86400;
const TTL_MS = TTL * 1000;
const ROOMY = 1000;

function fresh(): { host: FakeHost; core: CounterCore } {
  const host = new FakeHost();
  return { host, core: new CounterCore(host) };
}

describe("CounterCore", () => {
  it("counts upward from one", async () => {
    const { core } = fresh();
    expect(await core.increment(TTL, ROOMY)).toBe(1);
    expect(await core.increment(TTL, ROOMY)).toBe(2);
    expect(await core.increment(TTL, ROOMY)).toBe(3);
  });

  it("hands out distinct counts to concurrent callers", async () => {
    const { core } = fresh();
    const counts = await Promise.all(Array.from({ length: 50 }, () => core.increment(TTL, ROOMY)));
    expect([...counts].sort((left, right) => left - right)).toEqual(
      Array.from({ length: 50 }, (_, index) => index + 1),
    );
  });

  it("schedules one sweep at the end of the window and none for later increments", async () => {
    const { host, core } = fresh();
    host.nowMs = 1000;
    await core.increment(TTL, ROOMY);
    await core.increment(TTL, ROOMY);
    expect(host.sweeps).toEqual([1000 + TTL_MS]);
  });

  it("starts a new window from one once the old one has ended", async () => {
    const { host, core } = fresh();
    host.nowMs = 1000;
    await core.increment(TTL, ROOMY);
    await core.increment(TTL, ROOMY);
    host.nowMs = 1000 + TTL_MS;
    expect(await core.increment(TTL, ROOMY)).toBe(1);
    expect(host.sweeps).toEqual([1000 + TTL_MS, 1000 + 2 * TTL_MS]);
  });

  it("erases everything when the sweep finds the window ended", async () => {
    const { host, core } = fresh();
    await core.increment(TTL, ROOMY);
    host.nowMs += TTL_MS;
    await core.sweep();
    expect(host.erased).toBe(1);
    expect(host.store.size).toBe(0);
  });

  it("keeps the count and moves the sweep when it runs before the window ended", async () => {
    const { host, core } = fresh();
    host.nowMs = 5000;
    await core.increment(TTL, ROOMY);
    host.nowMs = 5000 + TTL_MS - 1;
    await core.sweep();
    expect(host.erased).toBe(0);
    expect(await core.increment(TTL, ROOMY)).toBe(2);
    expect(host.sweeps).toEqual([5000 + TTL_MS, 5000 + TTL_MS]);
  });

  it("sweeps an object that holds nothing without error", async () => {
    const { host, core } = fresh();
    await core.sweep();
    expect(host.erased).toBe(1);
  });

  it.each([0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "refuses the window length %s",
    async (ttl) => {
      const { host, core } = fresh();
      await expect(core.increment(ttl, ROOMY)).rejects.toThrow();
      expect(host.writes).toBe(0);
    },
  );

  it.each([
    { count: "many", expiresAt: 5000 },
    { count: -1, expiresAt: 5000 },
    { count: 0, expiresAt: 5000 },
    { count: 1.5, expiresAt: 5000 },
    { count: 1, expiresAt: -5000 },
    { count: 1, expiresAt: 0 },
    { count: 1, expiresAt: Number.NaN },
    { count: 1, expiresAt: Number.POSITIVE_INFINITY },
    { count: 1 },
    null,
    "window",
  ])("fails loudly on stored state it does not recognise: %j", async (stored) => {
    const { host, core } = fresh();
    host.store.set("window", stored);
    await expect(core.increment(TTL, ROOMY)).rejects.toThrow();
    expect(host.writes).toBe(0);
  });

  it.each([0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "refuses the limit %s",
    async (limit) => {
      const { host, core } = fresh();
      await expect(core.increment(TTL, limit)).rejects.toThrow();
      expect(host.writes).toBe(0);
    },
  );

  it("stops writing once the limit is reached but keeps answering above it", async () => {
    const { host, core } = fresh();
    const counts: number[] = [];
    for (let index = 0; index < 8; index += 1) {
      counts.push(await core.increment(TTL, 3));
    }
    expect(counts.slice(0, 3)).toEqual([1, 2, 3]);
    expect(counts.slice(3).every((count) => count > 3)).toBe(true);
    expect(host.writes).toBe(3);
  });

  it("saturates under concurrent callers the same way", async () => {
    const { host, core } = fresh();
    const counts = await Promise.all(Array.from({ length: 20 }, () => core.increment(TTL, 3)));
    expect(counts.filter((count) => count <= 3).sort()).toEqual([1, 2, 3]);
    expect(host.writes).toBe(3);
  });

  it("counts again from one after a saturated window ends", async () => {
    const { host, core } = fresh();
    for (let index = 0; index < 5; index += 1) {
      await core.increment(TTL, 2);
    }
    host.nowMs += TTL_MS;
    expect(await core.increment(TTL, 2)).toBe(1);
  });

  it("stores the count and the end of the window and nothing else", async () => {
    const { host, core } = fresh();
    host.nowMs = 7000;
    await core.increment(TTL, ROOMY);
    expect([...host.store.values()]).toEqual([{ count: 1, expiresAt: 7000 + TTL_MS }]);
  });
});

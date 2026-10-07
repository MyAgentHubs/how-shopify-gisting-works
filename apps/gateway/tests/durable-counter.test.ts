import { describe, expect, it } from "vitest";
import { DurableCounter } from "../src/durable-counter";
import { limits } from "../src/limits";
import { enforceQuota } from "../src/quota";
import { CounterFailure } from "../src/types";
import { FakeNamespace } from "./fake-durable";
import { SESSION } from "./support";

const DAY_MS = limits.counterTtlSeconds * 1000;
const DIGEST = "a".repeat(64);
const ROOMY = 1000;
const SHORT_TIMEOUT_MS = 20;

function subject(overrides: Partial<Parameters<typeof enforceQuota>[2]> = {}) {
  return {
    ipDigest: DIGEST,
    sessionId: SESSION,
    mode: "gist",
    now: new Date("2026-10-04T12:00:00Z"),
    ...overrides,
  };
}

function setup() {
  const namespace = new FakeNamespace();
  namespace.nowMs = Date.parse("2026-10-04T12:00:00Z");
  return { namespace, counter: new DurableCounter(namespace, limits.counterTimeoutMs) };
}

async function reasonOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error instanceof CounterFailure ? error.reason : error;
  }
  return null;
}

describe("DurableCounter", () => {
  it("counts each key in its own object", async () => {
    const { namespace, counter } = setup();
    expect(await counter.increment("session:abc12345", 60, ROOMY)).toBe(1);
    expect(await counter.increment("session:abc12345", 60, ROOMY)).toBe(2);
    expect(await counter.increment("session:other-one", 60, ROOMY)).toBe(1);
    expect([...namespace.objects.keys()].sort()).toEqual(["session:abc12345", "session:other-one"]);
  });

  it.each([
    "ip:203.0.113.77",
    "session:buyer@example.test",
    "session:#1001",
    "order:1001",
    "session:two words",
    "fail:session-0001",
    "",
    "ip",
    `session:${"a".repeat(200)}`,
  ])("refuses the key %j before any object is reached", async (key) => {
    const { namespace, counter } = setup();
    expect(await reasonOf(counter.increment(key, 60, ROOMY))).toBe("counter_key_rejected");
    expect(namespace.requested).toEqual([]);
  });

  it("reports an object that throws as unreachable", async () => {
    const { namespace, counter } = setup();
    namespace.failure = new Error("Durable Object daily request limit exceeded");
    expect(await reasonOf(counter.increment("site:2026-10-04", 60, ROOMY))).toBe(
      "durable_object_unreachable",
    );
  });

  it.each([Number.NaN, "7", -1, 1.5, null, 0])("reports the reply %j as malformed", async (reply) => {
    const { namespace, counter } = setup();
    namespace.reply = () => reply;
    expect(await reasonOf(counter.increment("site:2026-10-04", 60, ROOMY))).toBe(
      "durable_object_bad_reply",
    );
  });

  it("never counts in its own memory: after an outage the object's count still rules", async () => {
    const { namespace, counter } = setup();
    await counter.increment("session:abc12345", 60, ROOMY);
    namespace.failure = new Error("down");
    await reasonOf(counter.increment("session:abc12345", 60, ROOMY));
    await reasonOf(counter.increment("session:abc12345", 60, ROOMY));
    namespace.failure = null;
    expect(await counter.increment("session:abc12345", 60, ROOMY)).toBe(2);
  });
});

function stalledNamespace(): { namespace: FakeNamespace; release: () => void } {
  const namespace = new FakeNamespace();
  let release: () => void = () => undefined;
  namespace.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { namespace, release };
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function caught(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  return null;
}

describe("DurableCounter failures", () => {
  it("keeps the original error as the cause", async () => {
    const { namespace, counter } = setup();
    const original = new TypeError("detail that must not be logged");
    namespace.failure = original;
    const error = await caught(counter.increment("site:2026-10-04", 60, ROOMY));
    expect(error).toBeInstanceOf(CounterFailure);
    expect((error as CounterFailure).cause).toBe(original);
  });

  it("keeps a thrown value that is not an Error as the cause too", async () => {
    const { namespace, counter } = setup();
    namespace.failure = "plain string";
    const error = await caught(counter.increment("site:2026-10-04", 60, ROOMY));
    expect((error as CounterFailure).reason).toBe("durable_object_unreachable");
    expect((error as CounterFailure).cause).toBe("plain string");
  });

  it("reports only the error name, never its message, in the quota result", async () => {
    const { namespace, counter } = setup();
    namespace.failure = new RangeError(`broke on ip:${DIGEST}`);
    const result = await enforceQuota(counter, limits, subject());
    expect(result).toEqual({
      ok: false,
      error: {
        kind: "CounterUnavailable",
        reason: "durable_object_unreachable",
        causeName: "RangeError",
      },
    });
    expect(JSON.stringify(result)).not.toContain(DIGEST);
  });

  it("names a stalled object as a timeout and does not wait for it", async () => {
    const { namespace } = stalledNamespace();
    const counter = new DurableCounter(namespace, SHORT_TIMEOUT_MS);
    const started = Date.now();
    expect(await reasonOf(counter.increment("site:2026-10-04", 60, ROOMY))).toBe(
      "durable_object_timeout",
    );
    expect(Date.now() - started).toBeLessThan(limits.counterTimeoutMs);
  });

  it("fails closed with the timeout reason through the quota check", async () => {
    const { namespace } = stalledNamespace();
    const counter = new DurableCounter(namespace, SHORT_TIMEOUT_MS);
    expect(await enforceQuota(counter, limits, subject())).toEqual({
      ok: false,
      error: { kind: "CounterUnavailable", reason: "durable_object_timeout" },
    });
  });

  it("discards a failure that arrives after the timeout, which vitest would report as an unhandled rejection", async () => {
    const { namespace, release } = stalledNamespace();
    namespace.failure = new Error("failed after the deadline");
    const counter = new DurableCounter(namespace, SHORT_TIMEOUT_MS);
    expect(await reasonOf(counter.increment("site:2026-10-04", 60, ROOMY))).toBe(
      "durable_object_timeout",
    );
    release();
    await pause(SHORT_TIMEOUT_MS);
  });

  it("does not let a late success turn a timeout into an answer", async () => {
    const { namespace, release } = stalledNamespace();
    const counter = new DurableCounter(namespace, SHORT_TIMEOUT_MS);
    const pending = reasonOf(counter.increment("site:2026-10-04", 60, ROOMY));
    await pause(SHORT_TIMEOUT_MS * 2);
    release();
    expect(await pending).toBe("durable_object_timeout");
  });
});

describe("saturating counts", () => {
  it("stops writing storage once a key is past its limit and still answers above it", async () => {
    const { namespace, counter } = setup();
    const counts: number[] = [];
    for (let index = 0; index < 8; index += 1) {
      counts.push(await counter.increment("ip:2026-10-04:abc", 60, 3));
    }
    expect(counts.slice(0, 3)).toEqual([1, 2, 3]);
    expect(counts.slice(3).every((count) => count > 3)).toBe(true);
    expect(namespace.objects.get("ip:2026-10-04:abc")?.host.writes).toBe(3);
  });

  it("writes at most the limit per object across repeated quota checks", async () => {
    const { namespace, counter } = setup();
    for (let index = 0; index < limits.maxMessagesPerSession + 5; index += 1) {
      await enforceQuota(counter, limits, subject());
    }
    expect(namespace.objects.get(`session:${SESSION}`)?.host.writes).toBe(
      limits.maxMessagesPerSession,
    );
    expect(namespace.objects.get("site:2026-10-04")?.host.writes).toBe(
      limits.maxMessagesPerSession,
    );
  });
});

describe("quota on Durable Objects", () => {
  it("lets exactly the session allowance through under concurrent requests", async () => {
    const { counter } = setup();
    const results = await Promise.all(
      Array.from({ length: 40 }, (_, index) =>
        enforceQuota(counter, limits, subject({ ipDigest: index.toString(16).padStart(64, "0") })),
      ),
    );
    const allowed = results.filter((result) => result.ok).length;
    expect(allowed).toBe(limits.maxMessagesPerSession);
    const kinds = results.flatMap((result) => (result.ok ? [] : [result.error.kind]));
    expect(kinds).toEqual(Array(40 - limits.maxMessagesPerSession).fill("QuotaExceeded"));
  });

  it("lets exactly the daily address allowance through under concurrent sessions", async () => {
    const { counter } = setup();
    const results = await Promise.all(
      Array.from({ length: 60 }, (_, index) =>
        enforceQuota(counter, limits, subject({ sessionId: `session-${String(index).padStart(4, "0")}` })),
      ),
    );
    expect(results.filter((result) => result.ok)).toHaveLength(limits.maxRequestsPerIpPerDay);
  });

  it("lets exactly the full-comparison allowance through under concurrent clicks", async () => {
    const { counter } = setup();
    const results = await Promise.all(
      Array.from({ length: 12 }, () => enforceQuota(counter, limits, subject({ mode: "full" }))),
    );
    expect(results.filter((result) => result.ok)).toHaveLength(limits.maxFullComparesPerSession);
  });

  it("starts a new daily count when the UTC date turns over", async () => {
    const { namespace, counter } = setup();
    const evening = subject({ now: new Date("2026-10-04T23:59:59Z") });
    for (let index = 0; index < limits.maxRequestsPerIpPerDay; index += 1) {
      const result = await enforceQuota(counter, limits, {
        ...evening,
        sessionId: `session-${String(index).padStart(4, "0")}`,
      });
      expect(result.ok).toBe(true);
    }
    expect((await enforceQuota(counter, limits, { ...evening, sessionId: "session-fresh" })).ok).toBe(
      false,
    );
    const morning = subject({ now: new Date("2026-10-05T00:00:01Z"), sessionId: "session-next" });
    expect((await enforceQuota(counter, limits, morning)).ok).toBe(true);
    expect([...namespace.objects.keys()]).toContain(`ip:2026-10-05:${DIGEST}`);
  });

  it("sweeps every daily object away once its window has passed", async () => {
    const { namespace, counter } = setup();
    await enforceQuota(counter, limits, subject());
    namespace.advance(DAY_MS + 1);
    await namespace.sweepAll();
    expect([...namespace.objects.values()].every((object) => object.host.store.size === 0)).toBe(
      true,
    );
  });

  it("fails closed with a named reason when the object cannot be reached", async () => {
    const { namespace, counter } = setup();
    namespace.failure = new Error("down");
    expect(await enforceQuota(counter, limits, subject())).toEqual({
      ok: false,
      error: {
        kind: "CounterUnavailable",
        reason: "durable_object_unreachable",
        causeName: "Error",
      },
    });
  });
});

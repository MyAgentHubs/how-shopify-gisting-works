import { describe, expect, it } from "vitest";
import { limits } from "../src/limits";
import { enforceQuota } from "../src/quota";
import { MemoryCounter, SESSION } from "./support";

const subject = {
  ipDigest: "digest",
  sessionId: SESSION,
  mode: "gist" as const,
  now: new Date("2026-10-04T12:00:00Z"),
};
const fullSubject = { ...subject, mode: "full" as const };

async function spend(counter: MemoryCounter, times: number) {
  let last = await enforceQuota(counter, limits, subject);
  for (let index = 1; index < times; index += 1) {
    last = await enforceQuota(counter, limits, subject);
  }
  return last;
}

describe("enforceQuota", () => {
  it("allows the tenth message of a session and refuses the eleventh", async () => {
    expect((await spend(new MemoryCounter(), 10)).ok).toBe(true);
    expect(await spend(new MemoryCounter(), 11)).toEqual({
      ok: false,
      error: { kind: "QuotaExceeded", scope: "session" },
    });
  });

  it("refuses an address that has used its daily allowance across sessions", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("ip:2026-10-04:digest", limits.maxRequestsPerIpPerDay);
    expect(await enforceQuota(counter, limits, subject)).toEqual({
      ok: false,
      error: { kind: "QuotaExceeded", scope: "ip" },
    });
  });

  it("refuses everyone once the site allowance is used", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("site:2026-10-04", limits.maxRequestsPerSitePerDay);
    expect(await enforceQuota(counter, limits, subject)).toEqual({
      ok: false,
      error: { kind: "QuotaExceeded", scope: "site" },
    });
  });

  it("does not spend the site allowance on a request the address limit already refused", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("ip:2026-10-04:digest", limits.maxRequestsPerIpPerDay);
    await enforceQuota(counter, limits, subject);
    expect(counter.counts.has("site:2026-10-04")).toBe(false);
  });

  it("keys the daily counters by day and never by the clear address", async () => {
    const counter = new MemoryCounter();
    await enforceQuota(counter, limits, subject);
    expect([...counter.counts.keys()].sort()).toEqual([
      "ip:2026-10-04:digest",
      "session:session-0001",
      "site:2026-10-04",
    ]);
  });

  it("allows the third full comparison of a session and refuses the fourth", async () => {
    const counter = new MemoryCounter();
    for (let index = 0; index < limits.maxFullComparesPerSession; index += 1) {
      expect((await enforceQuota(counter, limits, fullSubject)).ok).toBe(true);
    }
    expect(await enforceQuota(counter, limits, fullSubject)).toEqual({
      ok: false,
      error: { kind: "QuotaExceeded", scope: "full" },
    });
  });

  it("does not count gist messages against the full allowance", async () => {
    const counter = new MemoryCounter();
    await enforceQuota(counter, limits, subject);
    expect(counter.counts.has("full:session-0001")).toBe(false);
  });

  it("does not spend the daily allowances on a full comparison already refused", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("full:session-0001", limits.maxFullComparesPerSession);
    await enforceQuota(counter, limits, fullSubject);
    expect(counter.counts.has("site:2026-10-04")).toBe(false);
  });

  it("fails closed for a full comparison when the counter cannot be reached", async () => {
    const counter = new MemoryCounter();
    counter.failing = true;
    expect(await enforceQuota(counter, limits, fullSubject)).toEqual({
      ok: false,
      error: { kind: "CounterUnavailable", causeName: "Error" },
    });
  });

  it("fails closed when the counter cannot be reached", async () => {
    const counter = new MemoryCounter();
    counter.failing = true;
    expect(await enforceQuota(counter, limits, subject)).toEqual({
      ok: false,
      error: { kind: "CounterUnavailable", causeName: "Error" },
    });
  });

  it("fails closed when the counter returns something that is not a number", async () => {
    const counter = { increment: () => Promise.resolve(Number.NaN) };
    expect((await enforceQuota(counter, limits, subject)).ok).toBe(false);
  });

  it("asks from the narrowest scope to the widest, so a refused request spends nothing wider", async () => {
    const order: string[] = [];
    const counter = {
      increment: (key: string) => {
        order.push(key.split(":")[0] ?? "");
        return Promise.resolve(1);
      },
    };
    await enforceQuota(counter, limits, fullSubject);
    expect(order).toEqual(["full", "session", "ip", "site"]);
  });

  it("does not spend the address or site allowance on a request the session limit refused", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("session:session-0001", limits.maxMessagesPerSession);
    expect(await enforceQuota(counter, limits, subject)).toEqual({
      ok: false,
      error: { kind: "QuotaExceeded", scope: "session" },
    });
    expect([...counter.counts.keys()]).toEqual(["session:session-0001"]);
  });

  it("does not spend the session, address or site allowance on a refused full comparison", async () => {
    const counter = new MemoryCounter();
    counter.counts.set("full:session-0001", limits.maxFullComparesPerSession);
    await enforceQuota(counter, limits, fullSubject);
    expect([...counter.counts.keys()]).toEqual(["full:session-0001"]);
  });

  it("hands each scope its own limit", async () => {
    const seen: Record<string, number> = {};
    const counter = {
      increment: (key: string, _ttl: number, limit: number) => {
        seen[key.split(":")[0] ?? ""] = limit;
        return Promise.resolve(1);
      },
    };
    await enforceQuota(counter, limits, fullSubject);
    expect(seen).toEqual({
      full: limits.maxFullComparesPerSession,
      session: limits.maxMessagesPerSession,
      ip: limits.maxRequestsPerIpPerDay,
      site: limits.maxRequestsPerSitePerDay,
    });
  });
});

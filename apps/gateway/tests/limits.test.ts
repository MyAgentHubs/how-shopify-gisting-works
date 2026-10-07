import { describe, expect, it } from "vitest";
import serveLimits from "../../../data/serve/limits.json";
import { limits } from "../src/limits";

const SECONDS_PER_DAY = 86400;
const MS_PER_SECOND = 1000;

describe("limits data", () => {
  it("keeps counters alive for a whole day, because the address and site keys are daily", () => {
    expect(limits.counterTtlSeconds).toBeGreaterThanOrEqual(SECONDS_PER_DAY);
  });

  it("gives every counter call a positive deadline no longer than the Turnstile one", () => {
    expect(limits.counterTimeoutMs).toBeGreaterThan(0);
    expect(limits.counterTimeoutMs).toBeLessThanOrEqual(limits.turnstileTimeoutMs);
  });

  it("allows more per address and per site than per session", () => {
    expect(limits.maxRequestsPerIpPerDay).toBeGreaterThanOrEqual(limits.maxMessagesPerSession);
    expect(limits.maxRequestsPerSitePerDay).toBeGreaterThanOrEqual(limits.maxRequestsPerIpPerDay);
  });

  it("waits for generate longer than the serve total deadline, so serve gives up first", () => {
    expect(limits.generateTimeoutMs).toBeGreaterThan(serveLimits.totalDeadlineS * MS_PER_SECOND);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compare, say, mount, query } from "./support.ts";
import {
  FRESH,
  answer,
  broken,
  countingCheck,
  forbidden,
  pinClock,
  stepping,
  ticketExpiringIn,
} from "./ticket-support.ts";

beforeEach(pinClock);

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const SECOND = "1.4102444800." + "B".repeat(43);

describe("reusing the chat ticket", () => {
  it("passes the bot check once, sends the token without a ticket, and keeps the ticket the answer brings", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH)]);
    mount({ gateway, check });
    await say("hello");
    expect(check.calls()).toBe(1);
    expect(gateway.requests[0]?.turnstileToken).toBe("token-1");
    expect(gateway.requests[0]?.ticket).toBeUndefined();
  });

  it("sends the next messages and a compare with the ticket alone, without touching the bot check", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), answer("two"), answer("three"), answer("full")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    await say("three");
    await compare();
    expect(check.calls()).toBe(1);
    expect(gateway.requests).toHaveLength(4);
    for (const request of gateway.requests.slice(1)) {
      expect(request.ticket).toBe(FRESH);
      expect("turnstileToken" in request).toBe(false);
    }
    expect(gateway.requests[3]?.mode).toBe("full");
  });

  it("drops a rejected ticket, passes the bot check once, and resends exactly once", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), forbidden, answer("two")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(check.calls()).toBe(2);
    expect(gateway.requests).toHaveLength(3);
    expect(gateway.requests[1]?.ticket).toBe(FRESH);
    expect(gateway.requests[2]?.turnstileToken).toBe("token-2");
    expect(gateway.requests[2]?.ticket).toBeUndefined();
    expect(query('[data-role="log"]').textContent).toContain("two");
  });

  it("shows the plain error and does not retry again when the resend is refused too", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), forbidden, forbidden]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(gateway.requests).toHaveLength(3);
    expect(check.calls()).toBe(2);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("http");
  });

  it("neither retries nor drops the ticket after a failure that is not a 403", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), broken, answer("three")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(gateway.requests).toHaveLength(2);
    await say("three");
    expect(gateway.requests[2]?.ticket).toBe(FRESH);
    expect(check.calls()).toBe(1);
  });

  it("goes straight to the bot check when the ticket has under a minute left", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", ticketExpiringIn(59)), answer("two")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(check.calls()).toBe(2);
    expect(gateway.requests[1]?.turnstileToken).toBe("token-2");
    expect(gateway.requests[1]?.ticket).toBeUndefined();
  });

  it("still uses a ticket that has a little over a minute left", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", ticketExpiringIn(61)), answer("two")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(check.calls()).toBe(1);
    expect(gateway.requests[1]?.ticket).toBeDefined();
  });

  it("ignores a ticket header that is not in the agreed shape", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", "1.12.short"), answer("two")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(check.calls()).toBe(2);
    expect(gateway.requests[1]?.ticket).toBeUndefined();
  });

  it("replaces the ticket when a later answer brings a new one", async () => {
    const check = countingCheck();
    const gateway = stepping([answer("one", FRESH), forbidden, answer("two", SECOND), answer("three")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    await say("three");
    expect(gateway.requests[3]?.ticket).toBe(SECOND);
    expect(check.calls()).toBe(2);
  });

  it("adopts the ticket that came with a replay answer", async () => {
    const check = countingCheck();
    const replayWithTicket = () =>
      ({ kind: "replay", reason: "quota", turns: [], ticket: FRESH }) as const;
    const gateway = stepping([replayWithTicket, answer("two")]);
    mount({ gateway, check });
    await say("one");
    await say("two");
    expect(check.calls()).toBe(1);
    expect(gateway.requests[1]?.ticket).toBe(FRESH);
  });
});

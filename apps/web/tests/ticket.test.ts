import { describe, expect, it } from "vitest";
import { ticketIfUsable } from "../src/ticket.ts";

const NOW_MS = Date.UTC(2026, 9, 6, 12, 0, 0);
const NOW_S = NOW_MS / 1000;
const MARGIN_MS = 60000;
const MAC = "A".repeat(43);
const usable = (ticket: string | null): string | null => ticketIfUsable(ticket, NOW_MS, MARGIN_MS);

describe("ticketIfUsable", () => {
  it("returns the ticket only while more than the margin is left", () => {
    expect(usable(`1.${String(NOW_S + 1800)}.${MAC}`)).toBe(`1.${String(NOW_S + 1800)}.${MAC}`);
    expect(usable(`1.${String(NOW_S + 61)}.${MAC}`)).not.toBeNull();
    expect(usable(`1.${String(NOW_S + 60)}.${MAC}`)).toBeNull();
    expect(usable(`1.${String(NOW_S - 5)}.${MAC}`)).toBeNull();
  });

  it("returns nothing for no ticket or an empty one", () => {
    expect(usable(null)).toBeNull();
    expect(usable("")).toBeNull();
    expect(usable("garbage")).toBeNull();
  });

  it.each([
    "1.NaN.x",
    "1.Infinity.x",
    "1.-5.x",
    "1.0.x",
    "1..x",
    "1.1e21.x",
    "1.0x7f.x",
    "1.0x7fffffffff.x",
    "1. 9999999999 .x",
    "1. 99 .x",
    "1.99999999999999999999.x",
    "1.9007199254740993.x",
  ])("treats an expiry that is not a plain whole number of seconds as unusable: %s", (ticket) => {
    expect(ticketIfUsable(ticket, 0, 0)).toBeNull();
  });

  it("accepts a plain whole number far in the future", () => {
    expect(ticketIfUsable("1.9999999999.x", NOW_MS, MARGIN_MS)).toBe("1.9999999999.x");
  });
});

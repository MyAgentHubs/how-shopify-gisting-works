import { describe, expect, it } from "vitest";
import { limits } from "../src/limits";
import { issueTicket, verifyTicket } from "../src/ticket";

const SALT = "ip-salt-0123456789-0123456789-abcdef";
const SID = "session-0001";
const IP = "203.0.113.77";
const MS = 1000;
const NOW = new Date("2026-10-04T12:00:00Z");
const TTL = limits.ticketTtlSeconds;
const SKEW = limits.ticketClockSkewSeconds;
const WINDOW = { ttlSeconds: TTL, skewSeconds: SKEW };
const ENCODER = new TextEncoder();

function nowSeconds(at: Date): number {
  return Math.floor(at.getTime() / MS);
}

function later(seconds: number): Date {
  return new Date(NOW.getTime() + seconds * MS);
}

async function check(ticket: string, overrides: { sid?: string; ip?: string; at?: Date; salt?: string; window?: { ttlSeconds: number; skewSeconds: number } } = {}) {
  return verifyTicket(
    overrides.salt ?? SALT,
    ticket,
    { sessionId: overrides.sid ?? SID, ip: overrides.ip ?? IP },
    overrides.at ?? NOW,
    overrides.window ?? WINDOW,
  );
}

async function reasonOf(ticket: string, overrides: Parameters<typeof check>[1] = {}): Promise<unknown> {
  const result = await check(ticket, overrides);
  return result.ok ? "accepted" : result.error;
}

function refused(reason: string) {
  return { kind: "TurnstileFailed", reason };
}

function base64url(bytes: ArrayBuffer): string {
  const text = btoa(String.fromCharCode(...new Uint8Array(bytes)));
  return text.replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function hmac(keyBytes: BufferSource, message: string): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return crypto.subtle.sign("HMAC", key, ENCODER.encode(message));
}

async function macFor(keyBytes: BufferSource, exp: number): Promise<string> {
  return base64url(await hmac(keyBytes, `1|${SID}|${String(exp)}|${IP}`));
}

function parts(ticket: string): [string, string, string] {
  const [version = "", exp = "", mac = ""] = ticket.split(".");
  return [version, exp, mac];
}

function flipFirst(text: string): string {
  return (text.startsWith("A") ? "B" : "A") + text.slice(1);
}

describe("chat ticket", () => {
  it("is accepted for the same session and address", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket)).toBe("accepted");
  });

  it("has the shape 1.<exp>.<43 character mac>, expires after the ttl and hides the address", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const [version, exp, mac] = parts(ticket);
    expect(version).toBe("1");
    expect(Number(exp)).toBe(nowSeconds(NOW) + TTL);
    expect(mac).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(ticket).not.toContain(IP);
  });

  it("matches a mac computed independently from the derived key", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const derived = await hmac(ENCODER.encode(SALT), "gisting-chat-ticket-v1");
    expect(parts(ticket)[2]).toBe(await macFor(derived, nowSeconds(NOW) + TTL));
  });

  it("is not signed with the raw salt, so it differs from a digest-style mac", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const direct = await macFor(ENCODER.encode(SALT), nowSeconds(NOW) + TTL);
    expect(parts(ticket)[2]).not.toBe(direct);
  });

  it("is refused under another salt", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { salt: "other-salt" })).toEqual(refused("ticket_invalid"));
  });

  it("is refused for another session", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { sid: "session-0002" })).toEqual(refused("ticket_invalid"));
  });

  it.each(["203.0.113.78", "198.51.100.1", "2001:db8::1"])("is refused for another address %s", async (ip) => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { ip })).toEqual(refused("ticket_invalid"));
  });

  it("is refused when the expiry is edited, even to a still valid time", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const [version, exp, mac] = parts(ticket);
    const edited = `${version}.${String(Number(exp) - 1)}.${mac}`;
    expect(await reasonOf(edited)).toEqual(refused("ticket_invalid"));
  });

  it("is refused when one character of the mac changes", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const [version, exp, mac] = parts(ticket);
    expect(await reasonOf(`${version}.${exp}.${flipFirst(mac)}`)).toEqual(refused("ticket_invalid"));
  });

  it("is refused when the last mac character is changed to a non-canonical one", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const [version, exp, mac] = parts(ticket);
    const forged = `${version}.${exp}.${mac.slice(0, -1)}${mac.endsWith("B") ? "C" : "B"}`;
    expect(await reasonOf(forged)).toEqual(refused("ticket_malformed"));
  });

  it.each(["0", "2", "01", "v1"])("is refused with the version %j", async (version) => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const [, exp, mac] = parts(ticket);
    expect(await reasonOf(`${version}.${exp}.${mac}`)).toEqual(refused("ticket_malformed"));
  });

  it("is accepted one second before it expires and refused at the expiry second", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { at: later(TTL - 1) })).toBe("accepted");
    expect(await reasonOf(ticket, { at: later(TTL) })).toEqual(refused("ticket_expired"));
    expect(await reasonOf(ticket, { at: later(TTL + 600) })).toEqual(refused("ticket_expired"));
  });

  it("is refused when it claims to outlive the ttl plus the skew, even with a valid mac", async () => {
    const derived = await hmac(ENCODER.encode(SALT), "gisting-chat-ticket-v1");
    const exp = nowSeconds(NOW) + TTL + SKEW + 1;
    const forged = `1.${String(exp)}.${await macFor(derived, exp)}`;
    expect(await reasonOf(forged)).toEqual(refused("ticket_invalid"));
  });

  it("is accepted at exactly the ttl when the clock has not moved", async () => {
    const derived = await hmac(ENCODER.encode(SALT), "gisting-chat-ticket-v1");
    const exp = nowSeconds(NOW) + TTL;
    expect(await reasonOf(`1.${String(exp)}.${await macFor(derived, exp)}`)).toBe("accepted");
  });

  it.each([
    "",
    "   ",
    "1",
    "1..",
    "1.123.",
    "1.1.x",
    "1.1.2.3",
    "1.01800.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "1.-5.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "1.99999999999.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "1.1800.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "1.1800.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+",
    "1.1800.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "1.1800.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "x".repeat(5000),
  ])("is refused as malformed: %j", async (ticket) => {
    expect(await reasonOf(ticket)).toEqual(refused("ticket_malformed"));
  });

  it("is refused with a trailing newline", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(`${ticket}\n`)).toEqual(refused("ticket_malformed"));
  });

  it("reads one address written two ways as the same ticket subject", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: "2001:db8:0:1:0:0:0:5" }, NOW, TTL);
    for (const ip of ["2001:0DB8:0000:0001::5", "2001:db8:0:1::5", "2001:db8:0:1:ffff:ffff:ffff:ffff"]) {
      expect(await reasonOf(ticket, { ip })).toBe("accepted");
    }
  });

  it("treats an IPv4-mapped IPv6 address as the plain IPv4 address", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { ip: `::ffff:${IP}` })).toBe("accepted");
  });

  it("stays valid across UTC midnight inside the ttl", async () => {
    const before = new Date("2026-10-04T23:50:00Z");
    const after = new Date("2026-10-05T00:10:00Z");
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, before, TTL);
    expect(await reasonOf(ticket, { at: after })).toBe("accepted");
  });

  it("is refused when the ticket carries a different ip written in another /64", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: "2001:db8:0:1::5" }, NOW, TTL);
    expect(await reasonOf(ticket, { ip: "2001:db8:0:2::5" })).toEqual(refused("ticket_invalid"));
  });

  it("allows the verifier clock to be at most the skew behind the issuer", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { at: later(-SKEW) })).toBe("accepted");
    expect(await reasonOf(ticket, { at: later(-SKEW - 1) })).toEqual(refused("ticket_invalid"));
  });

  it("keeps the skew at five seconds", () => {
    expect(SKEW).toBe(5);
  });

  it("is refused when the clock is not a valid date, even for an expired ticket", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    expect(await reasonOf(ticket, { at: new Date(NaN) })).toEqual(refused("ticket_expired"));
    const expired = later(TTL + 600);
    expect(await reasonOf(ticket, { at: expired })).toEqual(refused("ticket_expired"));
  });

  it("is refused when the ttl is NaN", async () => {
    const ttlSeconds = NaN;
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const window = { ttlSeconds, skewSeconds: SKEW };
    expect(await reasonOf(ticket, { window })).not.toBe("accepted");
  });

  it("is refused when the skew is NaN", async () => {
    const ticket = await issueTicket(SALT, { sessionId: SID, ip: IP }, NOW, TTL);
    const window = { ttlSeconds: TTL, skewSeconds: NaN };
    expect(await reasonOf(ticket, { window })).toEqual(refused("ticket_invalid"));
  });
});

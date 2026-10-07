import { describe, expect, it } from "vitest";
import serveLimits from "../../../data/serve/limits.json";
import { clientIp, digestIp } from "../src/ip";
import { normalizeIp } from "../src/ip-normalize";
import { CLIENT_IP, chatRequest } from "./support";

const TODAY = new Date("2026-10-04T12:00:00Z");
const TOMORROW = new Date("2026-10-05T00:00:01Z");
const LATE_TODAY = new Date("2026-10-04T23:59:59Z");

describe("digestIp", () => {
  it("is a stable 64 character hex digest that does not contain the address", async () => {
    const digest = await digestIp("salt", CLIENT_IP, TODAY);
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(digest).toBe(await digestIp("salt", CLIENT_IP, TODAY));
    expect(digest).not.toContain(CLIENT_IP);
  });

  it("changes with the salt and with the address", async () => {
    const base = await digestIp("salt", CLIENT_IP, TODAY);
    expect(await digestIp("other", CLIENT_IP, TODAY)).not.toBe(base);
    expect(await digestIp("salt", "203.0.113.78", TODAY)).not.toBe(base);
  });

  it("stays the same within a UTC day and cannot be linked across days", async () => {
    const morning = await digestIp("salt", CLIENT_IP, TODAY);
    expect(await digestIp("salt", CLIENT_IP, LATE_TODAY)).toBe(morning);
    expect(await digestIp("salt", CLIENT_IP, TOMORROW)).not.toBe(morning);
  });

  it("treats every host inside one IPv6 /64 as the same client", async () => {
    const base = await digestIp("salt", "2001:db8:1:2::1", TODAY);
    expect(await digestIp("salt", "2001:db8:1:2:aaaa:bbbb:cccc:dddd", TODAY)).toBe(base);
    expect(await digestIp("salt", "2001:DB8:1:2:0:0:0:ffff", TODAY)).toBe(base);
  });

  it("tells different IPv6 /64 prefixes apart", async () => {
    const base = await digestIp("salt", "2001:db8:1:2::1", TODAY);
    expect(await digestIp("salt", "2001:db8:1:3::1", TODAY)).not.toBe(base);
    expect(await digestIp("salt", "2001:db8:2:2::1", TODAY)).not.toBe(base);
    expect(await digestIp("salt", "2001:db9:1:2::1", TODAY)).not.toBe(base);
  });

  it("keeps IPv4 addresses apart one by one", async () => {
    const base = await digestIp("salt", "203.0.113.77", TODAY);
    expect(await digestIp("salt", "203.0.113.78", TODAY)).not.toBe(base);
  });

  it("treats an IPv4-mapped IPv6 address as the IPv4 address", async () => {
    const base = await digestIp("salt", "203.0.113.77", TODAY);
    expect(await digestIp("salt", "::ffff:203.0.113.77", TODAY)).toBe(base);
    expect(await digestIp("salt", "::ffff:cb00:714d", TODAY)).toBe(base);
    expect(await digestIp("salt", "0:0:0:0:0:ffff:cb00:714d", TODAY)).toBe(base);
  });

  it.each(["not-an-ip", "2001:db8::1::2", "2001:db8:::1", "1.2.3", "2001:db8:1:2:3:4:5:6:7", "", "g::1"])(
    "still digests the malformed value %j as an opaque string",
    async (value) => {
      const digest = await digestIp("salt", value, TODAY);
      expect(digest).toMatch(/^[0-9a-f]{64}$/);
      expect(digest).not.toBe(await digestIp("salt", `${value}x`, TODAY));
    },
  );
});

describe("normalizeIp", () => {
  it("leaves IPv4 and malformed values as they are", () => {
    expect(normalizeIp("203.0.113.77")).toBe("203.0.113.77");
    expect(normalizeIp("not-an-ip")).toBe("not-an-ip");
    expect(normalizeIp("2001:db8::1::2")).toBe("2001:db8::1::2");
  });

  it("reduces IPv6 to the first four groups, written the same way every time", () => {
    const expected = normalizeIp("2001:db8:1:2::1");
    expect(normalizeIp("2001:0db8:0001:0002:ffff:ffff:ffff:ffff")).toBe(expected);
    expect(expected).not.toContain("::");
    expect(expected).not.toBe(normalizeIp("2001:db8:1:3::1"));
  });

  it("maps IPv4-mapped IPv6 to dotted IPv4", () => {
    expect(normalizeIp("::ffff:203.0.113.77")).toBe("203.0.113.77");
    expect(normalizeIp("::FFFF:cb00:714d")).toBe("203.0.113.77");
  });

  it("handles the all-zero and loopback forms", () => {
    expect(normalizeIp("::")).toBe(normalizeIp("0:0:0:0:0:0:0:0"));
    expect(normalizeIp("::1")).toBe(normalizeIp("0:0:0:0:0:0:0:2"));
  });
});

describe("clientIp", () => {
  it("reads the Cloudflare address header and refuses requests without one", () => {
    expect(clientIp(chatRequest())).toEqual({ ok: true, value: CLIENT_IP });
    expect(clientIp(chatRequest({}, {}))).toMatchObject({ ok: false });
  });
});

describe("digestIp against the serve contract", () => {
  const pattern = new RegExp(serveLimits.ipDigestPattern);

  it.each([
    ["IPv4", "203.0.113.77"],
    ["IPv6", "2001:db8:1:2::1"],
    ["IPv4-mapped IPv6", "::ffff:203.0.113.77"],
  ])("produces a digest the serve accepts for %s", async (_name, ip) => {
    expect(await digestIp("salt", ip, TODAY)).toMatch(pattern);
  });
});

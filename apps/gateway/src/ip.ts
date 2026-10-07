import { utcDay } from "./day";
import { normalizeIp } from "./ip-normalize";
import type { GatewayError, Result } from "./types";
import { fail, ok } from "./types";

const IP_HEADER = "cf-connecting-ip";
const HEX_RADIX = 16;
const HEX_BYTE_WIDTH = 2;

export function clientIp(request: Request): Result<string, GatewayError> {
  const ip = request.headers.get(IP_HEADER);
  if (ip === null || ip.trim() === "") {
    return fail({ kind: "InvalidRequest", reason: "no client address" });
  }
  return ok(ip.trim());
}

export async function digestIp(salt: string, ip: string, now: Date): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(salt),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode(`${utcDay(now)}|${normalizeIp(ip)}`));
  return Array.from(new Uint8Array(mac), (byte) =>
    byte.toString(HEX_RADIX).padStart(HEX_BYTE_WIDTH, "0"),
  ).join("");
}

const GROUP_COUNT = 8;
const PREFIX_GROUPS = 4;
const MAPPED_ZERO_GROUPS = 5;
const MAPPED_MARKER = 0xffff;
const BYTE_BITS = 8;
const BYTE_RANGE = 256;
const HEX_RADIX = 16;
const GROUP_WIDTH = 4;
const OCTET = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
const IPV4_TEXT = new RegExp(`^${OCTET}(?:\\.${OCTET}){3}$`);
const MAX_PARTS = 2;
const HEX_GROUP = /^[0-9a-f]{1,4}$/i;

function ipv4Groups(text: string): number[] | null {
  if (!IPV4_TEXT.test(text)) {
    return null;
  }
  const [a = 0, b = 0, c = 0, d = 0] = text.split(".").map(Number);
  return [a * BYTE_RANGE + b, c * BYTE_RANGE + d];
}

function withoutDottedTail(text: string): string | null {
  if (!text.includes(".")) {
    return text;
  }
  const cut = text.lastIndexOf(":");
  const tail = ipv4Groups(text.slice(cut + 1));
  if (cut < 0 || tail === null) {
    return null;
  }
  return `${text.slice(0, cut + 1)}${tail.map((group) => group.toString(HEX_RADIX)).join(":")}`;
}

function words(side: string): number[] | null {
  if (side === "") {
    return [];
  }
  const tokens = side.split(":");
  return tokens.every((token) => HEX_GROUP.test(token))
    ? tokens.map((token) => Number.parseInt(token, HEX_RADIX))
    : null;
}

function parseGroups(text: string): number[] | null {
  const parts = text.split("::");
  if (parts.length > MAX_PARTS) {
    return null;
  }
  const [head = "", tail] = parts;
  const left = words(head);
  const right = tail === undefined ? [] : words(tail);
  if (left === null || right === null) {
    return null;
  }
  if (tail === undefined) {
    return left.length === GROUP_COUNT ? left : null;
  }
  const gap = GROUP_COUNT - left.length - right.length;
  return gap < 1 ? null : [...left, ...Array<number>(gap).fill(0), ...right];
}

function mappedIpv4(groups: readonly number[]): string | null {
  const [, , , , , marker = 0, high = 0, low = 0] = groups;
  const isMapped =
    groups.slice(0, MAPPED_ZERO_GROUPS).every((group) => group === 0) && marker === MAPPED_MARKER;
  if (!isMapped) {
    return null;
  }
  const octets = [high >> BYTE_BITS, high % BYTE_RANGE, low >> BYTE_BITS, low % BYTE_RANGE];
  return octets.join(".");
}

function prefix64(groups: readonly number[]): string {
  const hex = groups
    .slice(0, PREFIX_GROUPS)
    .map((group) => group.toString(HEX_RADIX).padStart(GROUP_WIDTH, "0"));
  return `${hex.join(":")}/64`;
}

export function normalizeIp(ip: string): string {
  if (!ip.includes(":")) {
    return ip;
  }
  const plain = withoutDottedTail(ip);
  const groups = plain === null ? null : parseGroups(plain);
  if (groups === null) {
    return ip;
  }
  return mappedIpv4(groups) ?? prefix64(groups);
}

type Formatter = (value: number, lang: string) => string;

interface Unit {
  readonly size: number;
  readonly label: string;
  readonly cap: number | null;
}

const SIGNIFICANT = 3;
const EXACT_DIGITS = 100;
const GROUPING = "en-US";
const CJK_LANGUAGES: ReadonlySet<string> = new Set(["zh-CN"]);
const LATIN_UNITS: readonly Unit[] = [
  { size: 1e9, label: "B", cap: null },
  { size: 1e6, label: "M", cap: 1e3 },
  { size: 1e3, label: "K", cap: 1e3 },
];
const CJK_UNITS: readonly Unit[] = [
  { size: 1e8, label: "亿", cap: null },
  { size: 1e4, label: "万", cap: 1e4 },
];
const USD_ROUND_ABOVE = 100;
const CENT_DIGITS = 2;
const FINE_DIGITS = 3;
const RATIO_DIGITS = 4;
const BINARY = 2;
const DECIMAL = 10;
const HALF = /^50*$/;

function grouped(value: number, digits: number): string {
  return new Intl.NumberFormat(GROUPING, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function roundHalfEven(value: number, digits: number): number {
  const scaled = value * BINARY ** (digits + 1);
  const exactTie = Number.isInteger(scaled) && Math.abs(scaled % BINARY) === 1;
  if (!exactTie) {
    return Number(value.toFixed(digits));
  }
  const below = Math.floor(value * DECIMAL ** digits);
  return (below % BINARY === 0 ? below : below + 1) / DECIMAL ** digits;
}

function roundSignificant(value: number): number {
  const [mantissa = "", exponent = ""] = value.toExponential(EXACT_DIGITS).split("e");
  const digits = mantissa.replace(".", "");
  const kept = digits.slice(0, SIGNIFICANT);
  const tie = HALF.test(digits.slice(SIGNIFICANT));
  if (tie && Number(kept.slice(-1)) % BINARY === 0) {
    return Number(`${kept.slice(0, 1)}.${kept.slice(1)}e${exponent}`);
  }
  return Number(value.toPrecision(SIGNIFICANT));
}

function formatInt(value: number): string {
  return grouped(roundHalfEven(value, 0), 0);
}

function formatTokens(value: number, lang: string): string {
  const units = CJK_LANGUAGES.has(lang) ? CJK_UNITS : LATIN_UNITS;
  for (const { size, label, cap } of units) {
    if (value >= size) {
      const scaled = roundSignificant(value / size);
      if (cap === null || scaled < cap) {
        return `${String(scaled)} ${label}`;
      }
    }
  }
  return formatInt(value);
}

function formatUsd(value: number): string {
  if (value >= USD_ROUND_ABOVE) {
    return `$${formatInt(value)}`;
  }
  return `$${formatDecimal(value)}`;
}

function formatFineUsd(value: number): string {
  if (value >= USD_ROUND_ABOVE) {
    return formatUsd(value);
  }
  return `$${grouped(roundHalfEven(value, FINE_DIGITS), FINE_DIGITS)}`;
}

function formatDecimal(value: number): string {
  return grouped(roundHalfEven(value, CENT_DIGITS), CENT_DIGITS);
}

const FORMATTERS = new Map<string, Formatter>([
  ["int", formatInt],
  ["tokens", formatTokens],
  ["usd", formatUsd],
  ["usd3", formatFineUsd],
  ["decimal", formatDecimal],
  ["ratio", (value) => value.toFixed(RATIO_DIGITS)],
  ["plain", (value) => String(value)],
]);

export const FORMAT_NAMES: readonly string[] = [...FORMATTERS.keys()];

export function formatValue(format: string, value: unknown, lang: string): string {
  const formatter = FORMATTERS.get(format);
  if (formatter === undefined) {
    throw new RangeError(`unknown format ${format}; known: ${FORMAT_NAMES.join(", ")}`);
  }
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new TypeError(`format ${format} needs a finite non-negative number, got ${String(value)}`);
  }
  return formatter(value, lang);
}

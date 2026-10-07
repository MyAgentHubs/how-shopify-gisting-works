import { formatValue } from "./format.ts";

export type CopyKey = keyof (typeof import("../copy/en.json"))["strings"];

export interface Copy {
  readonly lang: string;
  readonly strings: Readonly<Record<string, string>>;
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    Object.values(value).every((entry) => typeof entry === "string")
  );
}

export function parseCopy(raw: unknown): Copy {
  const { lang, strings } = (raw ?? {}) as { lang?: unknown; strings?: unknown };
  if (typeof lang !== "string" || lang === "" || !isStringRecord(strings)) {
    throw new TypeError("copy needs a language and a strings object of strings");
  }
  return { lang, strings };
}

export function text(copy: Copy, key: CopyKey): string {
  const value = Object.hasOwn(copy.strings, key) ? copy.strings[key] : undefined;
  if (value === undefined) {
    throw new RangeError(`missing copy key ${key}`);
  }
  return value;
}

export function fill(template: string, values: Readonly<Record<string, string | number>>): string {
  return template.replace(/\{(\w+)\}/g, (whole: string, name: string) => {
    const value = Object.hasOwn(values, name) ? values[name] : undefined;
    return value === undefined ? whole : String(value);
  });
}

export function formatNumber(copy: Copy, value: number): string {
  return formatValue("int", value, copy.lang);
}

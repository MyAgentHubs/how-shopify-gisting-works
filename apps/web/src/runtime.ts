import type { Pricing } from "../../../contracts/pricing.generated.ts";
import type { Copy } from "./copy.ts";
import { parseCopy } from "./copy.ts";
import type { MeterConstants } from "./meter.ts";
import { isFields } from "./trace.ts";
import type { Fields } from "./trace.ts";
import type { TurnstileConfig } from "./turnstile.ts";

export const RUNTIME_BLOCK_ID = "runtime-data";

export interface Runtime {
  readonly copy: Copy;
  readonly meter: MeterConstants;
  readonly turnstile: TurnstileConfig;
  readonly pricing: Pricing;
}

export function readRuntimeBlock(doc: Document): Fields {
  const block = doc.getElementById(RUNTIME_BLOCK_ID);
  if (block === null) {
    throw new ReferenceError(`the page needs the #${RUNTIME_BLOCK_ID} data block`);
  }
  const data: unknown = JSON.parse(block.textContent);
  if (!isFields(data)) {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} must hold an object`);
  }
  return data;
}

function count(value: unknown, name: string): number {
  if (typeof value !== "number") {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} numbers need ${name}`);
  }
  return value;
}

function isNumberList(value: unknown): value is readonly number[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "number");
}

export function isPricing(value: unknown): value is Pricing {
  const pricing = value as Partial<Pricing> | null;
  const calculator = pricing?.calculator;
  return (
    typeof pricing?.default === "string" &&
    Array.isArray(pricing.models) &&
    isNumberList(calculator?.stops) &&
    isNumberList(calculator.chart_stops) &&
    typeof calculator.max_turns === "number"
  );
}

function readTurnstile(raw: unknown): TurnstileConfig {
  const { sitekey, action } = isFields(raw) ? raw : ({} as Fields);
  if (typeof sitekey !== "string" || sitekey === "" || typeof action !== "string" || action === "") {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} turnstile needs a sitekey and an action`);
  }
  return { sitekey, action };
}

function readPricing(raw: unknown): Pricing {
  if (!isPricing(raw)) {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} needs the pricing`);
  }
  return raw;
}

export function readRuntime(doc: Document): Runtime {
  const { lang, copy: strings, numbers, turnstile, pricing } = readRuntimeBlock(doc);
  const pageLanguage = doc.documentElement.lang;
  if (lang !== pageLanguage) {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} is in ${String(lang)} but the page says ${pageLanguage}`);
  }
  const figures = isFields(numbers) ? numbers : {};
  return {
    copy: parseCopy({ lang: pageLanguage, strings }),
    meter: { rulesFull: count(figures["rulesFull"], "rulesFull"), rulesGist: count(figures["rulesGist"], "rulesGist") },
    turnstile: readTurnstile(turnstile),
    pricing: readPricing(pricing),
  };
}

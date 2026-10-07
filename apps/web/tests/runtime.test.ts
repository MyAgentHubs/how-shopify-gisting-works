import { describe, expect, it } from "vitest";
import pricingData from "../data/pricing.json";
import runtimeKeys from "../data/runtime_keys.json";
import { readRuntime, readRuntimeBlock } from "../src/runtime.ts";
import { text } from "../src/copy.ts";
import { english } from "./support.ts";
import { buildPages } from "./page-helpers.mjs";

const NUMBERS = { rulesFull: 526, rulesGist: 19 };
const TURNSTILE = { sitekey: "site-key", action: "an-action" };
const PRICING = pricingData;

function page(block: unknown, lang = "en"): Document {
  const json = typeof block === "string" ? block : JSON.stringify(block);
  const html = `<html lang="${lang}"><head><script type="application/json" id="runtime-data">${json}</script></head></html>`;
  return new DOMParser().parseFromString(html, "text/html");
}

describe("the runtime data block", () => {
  it("gives the copy, its language and the rules sizes of the page it sits in", () => {
    const runtime = readRuntime(page({ lang: "en", copy: { "ui.send": "Send" }, numbers: NUMBERS, turnstile: TURNSTILE, pricing: PRICING }));
    expect(runtime.copy).toEqual({ lang: "en", strings: { "ui.send": "Send" } });
    expect(runtime.meter).toEqual(NUMBERS);
    expect(runtime.turnstile).toEqual(TURNSTILE);
    expect(runtime.pricing).toEqual(PRICING);
  });

  it("takes the language from the html element and refuses a block in another language", () => {
    const block = { lang: "en", copy: {}, numbers: NUMBERS, turnstile: TURNSTILE, pricing: PRICING };
    expect(readRuntime(page({ ...block, lang: "zh-CN" }, "zh-CN")).copy.lang).toBe("zh-CN");
    expect(() => readRuntime(page(block, "zh-CN"))).toThrow(/en.*zh-CN/);
    expect(() => readRuntime(page({ ...block, lang: undefined }))).toThrow(TypeError);
  });

  it("refuses a page without the block, malformed JSON, a non-object and missing figures", () => {
    expect(() => readRuntime(new DOMParser().parseFromString("<html lang='en'></html>", "text/html"))).toThrow(/runtime-data/);
    expect(() => readRuntimeBlock(page("{oops"))).toThrow(SyntaxError);
    expect(() => readRuntimeBlock(page("[1]"))).toThrow(TypeError);
    expect(() => readRuntime(page({ lang: "en", copy: {}, numbers: { rulesFull: 526 }, turnstile: TURNSTILE, pricing: PRICING }))).toThrow(/rulesGist/);
    expect(() => readRuntime(page({ lang: "en", copy: { a: 1 }, numbers: NUMBERS, turnstile: TURNSTILE, pricing: PRICING }))).toThrow(TypeError);
    const block = { lang: "en", copy: {}, numbers: NUMBERS, pricing: PRICING };
    expect(() => readRuntime(page(block))).toThrow(/sitekey and an action/);
    expect(() => readRuntime(page({ ...block, turnstile: { sitekey: "k", action: "" } }))).toThrow(TypeError);
    expect(() => readRuntime(page({ ...block, turnstile: { sitekey: 1, action: "a" } }))).toThrow(TypeError);
    const complete = { ...block, turnstile: TURNSTILE };
    expect(() => readRuntime(page({ ...complete, pricing: undefined }))).toThrow(/pricing/);
    expect(() => readRuntime(page({ ...complete, pricing: { default: "x" } }))).toThrow(TypeError);
  });
});

describe("the block the build writes into every page", () => {
  const pages = buildPages();

  it("carries exactly the whitelisted copy keys, in each language, and the page's own language", () => {
    for (const lang of ["en", "zh-CN", "ja", "ko"]) {
      const doc = new DOMParser().parseFromString(pages.html(lang), "text/html");
      const runtime = readRuntime(doc);
      expect(Object.keys(runtime.copy.strings).sort(), lang).toEqual([...runtimeKeys.copy].sort());
      expect(runtime.copy.lang).toBe(doc.documentElement.lang);
    }
  });

  it("is enough for the browser code: the English block holds the text the panel and the chat ask for", () => {
    const runtime = readRuntime(new DOMParser().parseFromString(pages.html("en"), "text/html"));
    for (const key of ["hood.help", "ui.error", "replay.banner", "replay.banner_offline", "hood.summary"] as const) {
      expect(text(runtime.copy, key)).toBe(text(english, key));
    }
    expect(runtime.meter).toEqual(NUMBERS);
  });
});

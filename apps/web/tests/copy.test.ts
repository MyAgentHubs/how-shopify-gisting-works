import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyJa from "../copy/ja.json";
import copyKo from "../copy/ko.json";
import copyZh from "../copy/zh-CN.json";
import verifyRules from "../scripts/verify-rules.json";
import runtimeKeys from "../data/runtime_keys.json";
import productJson from "../product.json";
import { fill, formatNumber, parseCopy, text } from "../src/copy.ts";
import type { CopyKey } from "../src/copy.ts";
import { formatValue } from "../src/format.ts";

const FILES = { en: copyEn, "zh-CN": copyZh, ja: copyJa, ko: copyKo } as const;
const KEYS_OF = (file: { strings: Record<string, string> }): string[] =>
  Object.keys(file.strings).sort();
const NOTICE_KEY = "page.notice";
const DENIAL_KEY = "fine.no_speed_claim";
const HOSTING_OR_SPEED =
  new RegExp(verifyRules.forbidden.map(({ pattern }) => pattern).join("|") + "|より速|더 빠", "i");
const PLACEHOLDER = /\{(\w+)\}/g;

function placeholders(value: string): string[] {
  return [...value.matchAll(PLACEHOLDER)].map((match) => match[1] ?? "").sort();
}

describe("copy files", () => {
  it("exist for exactly the four languages the product table lists", () => {
    const table = productJson.languages.map((language) => language.code);
    expect(Object.keys(FILES).sort()).toEqual([...table].sort());
  });

  it("declare their own language", () => {
    for (const [name, file] of Object.entries(FILES)) {
      expect(file.lang).toBe(name);
    }
  });

  it("give zh-CN exactly the key set of en", () => {
    expect(KEYS_OF(copyZh)).toEqual(KEYS_OF(copyEn));
  });

  it("give ja and ko the page notice and nothing else, so the page body is English", () => {
    for (const file of [copyJa, copyKo]) {
      expect(KEYS_OF(file)).toEqual([NOTICE_KEY]);
    }
    expect(KEYS_OF(copyEn)).not.toContain(NOTICE_KEY);
    expect(KEYS_OF(copyZh)).not.toContain(NOTICE_KEY);
  });

  it("carry a native-speaker review state, pending, approved_draft or done", () => {
    for (const file of [copyJa, copyKo]) {
      expect(Object.keys(file).sort()).toEqual(["lang", "native_review", "status", "strings"]);
      expect(["pending", "approved_draft", "done"]).toContain(file.native_review);
      expect(file.strings[NOTICE_KEY].trim()).not.toBe("");
      expect(file.strings[NOTICE_KEY]).not.toMatch(/\n/);
    }
  });

  it("carry the same placeholders in every language", () => {
    for (const key of Object.keys(copyEn.strings)) {
      const expected = placeholders(copyEn.strings[key as keyof typeof copyEn.strings]);
      for (const file of Object.values(FILES)) {
        const value = (file.strings as Record<string, string>)[key];
        if (value !== undefined) {
          expect(placeholders(value), key).toEqual(expected);
        }
      }
    }
  });

  it("have no empty string", () => {
    for (const file of Object.values(FILES)) {
      for (const [key, value] of Object.entries(file.strings)) {
        expect(value.trim(), key).not.toBe("");
      }
    }
  });

  it("translate every hood.* string into zh-CN", () => {
    const english = copyEn.strings as Record<string, string>;
    const strings = copyZh.strings as Record<string, string>;
    for (const key of Object.keys(english).filter((name) => name.startsWith("hood."))) {
      expect(strings[key], key).not.toBe(english[key]);
    }
  });

  it("describe no knowledge hits, snippets or backup server on the public page", () => {
    for (const file of Object.values(FILES)) {
      expect(Object.keys(file.strings).filter((key) => key.startsWith("hood.knowledge"))).toEqual([]);
      for (const [key, value] of Object.entries(file.strings)) {
        expect(value, key).not.toMatch(/knowledge snippets|served by|backup/i);
      }
    }
  });

  it("call the orders test data in a Shopify store, never a make-believe or generated store", () => {
    const banned = /make-believe|development store|generated|虚构|开发店|生成的|架空|開発ストア|生成された|가상|개발 스토어|생성된/;
    for (const file of Object.values(FILES)) {
      for (const [key, value] of Object.entries(file.strings)) {
        expect(value, `${file.lang} ${key}`).not.toMatch(banned);
      }
    }
  });

  it("never name hardware, hosting details or a speed claim, except the key that denies it", () => {
    for (const file of Object.values(FILES)) {
      for (const [key, value] of Object.entries(file.strings)) {
        if (key !== DENIAL_KEY) {
          expect(value, `${file.lang} ${key}`).not.toMatch(HOSTING_OR_SPEED);
        }
      }
    }
  });

  it("catches hardware, hosting details or a speed claim in any of the four languages", () => {
    for (const sample of ["built on a Raspberry Pi", "self-hosted box", "now faster", "速度更快", "より速い", "더 빠릅니다", "quicker replies", "a snappier agent", "lower latency", "低延迟", "提速", "加速"]) {
      expect(sample).toMatch(HOSTING_OR_SPEED);
    }
    expect("Machine learning, fewer tokens").not.toMatch(HOSTING_OR_SPEED);
    expect("font-family: -apple-system").not.toMatch(HOSTING_OR_SPEED);
  });

  it("lets the speed denial name speed, by its key and nowhere else", () => {
    expect(copyZh.strings[DENIAL_KEY]).toMatch(/更快/);
    expect(KEYS_OF(copyEn)).toContain(DENIAL_KEY);
  });

  it("use the name Gisting Lab only as the store name", () => {
    for (const file of Object.values(FILES)) {
      for (const [key, value] of Object.entries(file.strings)) {
        expect(value, `${file.lang} ${key}`).not.toMatch(/Gisting Lab(?! Store)/);
      }
    }
  });

  it("never mention the retired Benchmarks block in the privacy section", () => {
    for (const file of Object.values(FILES)) {
      for (const [key, value] of Object.entries(file.strings)) {
        if (key.startsWith("privacy.")) {
          expect(value, `${file.lang} ${key}`).not.toMatch(/Benchmarks/i);
        }
      }
    }
  });

  it("disclose the Turnstile bot check right after the processors card, in en and zh-CN", () => {
    for (const file of [copyEn, copyZh]) {
      const keys = Object.keys(file.strings);
      expect(keys.indexOf("privacy.turnstile"), file.lang).toBe(keys.indexOf("privacy.processors") + 1);
      expect(file.strings["privacy.turnstile"], file.lang).toMatch(/challenges\.cloudflare\.com/);
    }
  });

  it("are approved, all four together", () => {
    for (const file of Object.values(FILES)) {
      expect(file.status).toBe("approved");
    }
  });

  it("hold every key the browser code asks for, in the runtime list too", () => {
    for (const file of [copyEn, copyZh]) {
      for (const key of runtimeKeys.copy) {
        expect(file.strings, `${file.lang} ${key}`).toHaveProperty(key);
      }
    }
  });

  it("keep no retired Benchmarks keys", () => {
    for (const file of Object.values(FILES)) {
      expect(Object.keys(file.strings).filter((key) => key.startsWith("bench."))).toEqual([]);
    }
  });
});

describe("copy helpers", () => {
  it("parseCopy refuses anything without a language and a strings object of strings", () => {
    expect(() => parseCopy(null)).toThrow(TypeError);
    expect(() => parseCopy({ lang: "", strings: {} })).toThrow(TypeError);
    expect(() => parseCopy({ lang: "en", strings: { a: 1 } })).toThrow(TypeError);
    expect(() => parseCopy({ strings: {} })).toThrow(TypeError);
    expect(parseCopy({ lang: "ja", strings: { a: "b" } })).toEqual({ lang: "ja", strings: { a: "b" } });
  });

  it("fails loudly on a missing key, also one every object has", () => {
    const empty = parseCopy({ lang: "en", strings: {} });
    expect(() => text(empty, "hero.title")).toThrow(RangeError);
    expect(() => text(empty, "constructor" as CopyKey)).toThrow(RangeError);
  });

  it("fills named placeholders and leaves unknown ones alone", () => {
    expect(fill("{a} of {b} {c}", { a: 2, b: "3" })).toBe("2 of 3 {c}");
    expect(fill("{constructor} {toString}", {})).toBe("{constructor} {toString}");
  });

  it("formatNumber is the shared int formatter, not a second implementation", () => {
    const copy = parseCopy({ lang: "zh-CN", strings: {} });
    for (const value of [0, 2.5, 3.5, 1234.5, 1_000_000, 1e9]) {
      expect(formatNumber(copy, value)).toBe(formatValue("int", value, "zh-CN"));
    }
    expect(formatNumber(copy, 1234.5)).toBe("1,234");
  });

});

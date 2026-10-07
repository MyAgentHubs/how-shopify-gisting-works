import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyZh from "../copy/zh-CN.json";
import benchmarks from "../data/benchmarks.json";
import pricing from "../data/pricing.json";

type Strings = Record<string, string>;
interface Claim {
  readonly name: string;
  readonly pattern: RegExp;
  readonly expected: readonly number[];
}

const FULL = benchmarks.tokens.full;
const GIST = benchmarks.tokens.gist;
const RULES = [FULL.rules_tokens_per_call, GIST.rules_tokens_per_call];
const TURN_TOTALS = [Math.round(FULL.total_tokens_per_turn), Math.round(GIST.total_tokens_per_turn)];

const CLAIMS: Record<"en" | "zh-CN", readonly Claim[]> = {
  en: [
    { name: "test cases", pattern: /(\d[\d,]*) test cases/g, expected: [benchmarks.source.graded] },
    { name: "model calls", pattern: /(\d[\d,]*) calls\b/g, expected: [GIST.model_calls] },
    { name: "rules tokens", pattern: /(\d+) → (\d+) tokens?/g, expected: RULES },
    { name: "rules tokens, spelled out", pattern: /from (\d+) to (\d+)\b/g, expected: RULES },
    {
      name: "tokens per turn",
      pattern: /averages (\d+) tokens with the full rules and (\d+) with Gist/g,
      expected: TURN_TOTALS,
    },
  ],
  "zh-CN": [
    { name: "test cases", pattern: /(\d[\d,]*) 个测试用例/g, expected: [benchmarks.source.graded] },
    { name: "model calls", pattern: /(\d[\d,]*) 次调用/g, expected: [GIST.model_calls] },
    { name: "rules tokens", pattern: /(\d+) → (\d+) token/g, expected: RULES },
    { name: "rules tokens, spelled out", pattern: /从 (\d+) 降到 (\d+)/g, expected: RULES },
    {
      name: "tokens per turn",
      pattern: /每轮平均 (\d+) token（完整规则）对 (\d+) token（Gist）/g,
      expected: TURN_TOTALS,
    },
  ],
};

function numbersIn(match: RegExpMatchArray): number[] {
  return match.slice(1).map((digits) => Number(digits.replace(/,/g, "")));
}

function claimMismatches(key: string, value: string, claim: Claim): string[] {
  return [...value.matchAll(claim.pattern)]
    .map(numbersIn)
    .filter((numbers) => numbers.join() !== claim.expected.join())
    .map((numbers) => `${key} (${claim.name}): ${numbers.join()} is not ${claim.expected.join()}`);
}

function mismatches(strings: Strings, claims: readonly Claim[]): string[] {
  return Object.entries(strings).flatMap(([key, value]) =>
    claims.flatMap((claim) => claimMismatches(key, value, claim)),
  );
}

function matchCount(strings: Strings, claim: Claim): number {
  return Object.values(strings).reduce((sum, value) => sum + [...value.matchAll(claim.pattern)].length, 0);
}

describe("counts written into the copy", () => {
  it("equal the numbers in benchmarks.json, in en and zh-CN", () => {
    expect(mismatches(copyEn.strings, CLAIMS.en)).toEqual([]);
    expect(mismatches(copyZh.strings, CLAIMS["zh-CN"])).toEqual([]);
  });

  it("are really found by the patterns, so a pattern that goes dead is noticed", () => {
    for (const [name, strings] of [["en", copyEn.strings], ["zh-CN", copyZh.strings]] as const) {
      for (const claim of CLAIMS[name].slice(0, 3)) {
        expect(matchCount(strings, claim), `${name} ${claim.name}`).toBeGreaterThan(0);
      }
    }
  });

  it("are caught when a hard-coded count drifts", () => {
    const drifted = {
      a: "Average call across 934 test cases.",
      b: "908 calls ÷ 933 test cases",
      c: "rules 526 → 20 tokens",
    };
    expect(mismatches(drifted, CLAIMS.en)).toHaveLength(2);
  });
});

describe("the lines C2 retired", () => {
  const RETIRED = ["calc.formula", "chat.hint_transit", "real.store_sub", "rules.security"];

  it("have no key left in en or zh-CN", () => {
    for (const strings of [copyEn.strings, copyZh.strings] as Strings[]) {
      expect(Object.keys(strings).filter((key) => RETIRED.includes(key))).toEqual([]);
    }
  });
});

describe("model names and calculator numbers", () => {
  const grouped = (value: number): string => new Intl.NumberFormat("en-US").format(value);
  const REPEATED = [
    ...pricing.models.flatMap((model) => [model.name, model.short]),
    ...pricing.models.map((model) => grouped(model.min_cacheable)),
    grouped(pricing.calculator.default_per_day),
    `${String(pricing.calculator.days_per_month)} days`,
    `${String(pricing.calculator.days_per_month)} 天`,
  ];

  it("are written in no copy string, because the data fills them in", () => {
    for (const strings of [copyEn.strings, copyZh.strings] as Strings[]) {
      const offences = Object.entries(strings).flatMap(([key, value]) =>
        REPEATED.filter((literal) => value.includes(literal)).map((literal) => `${key}: ${literal}`),
      );
      expect(offences).toEqual([]);
    }
  });

  it("are caught when a string spells one out", () => {
    expect(REPEATED.filter((literal) => "Showing 10,000 a day on Claude Sonnet 5.5".includes(literal))).toHaveLength(3);
  });
});

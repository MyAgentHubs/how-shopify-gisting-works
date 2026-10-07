import { describe, expect, it } from "vitest";
import type { Pricing } from "../../../contracts/pricing.generated.ts";
import benchmarksJson from "../data/benchmarks.json";
import pricingJson from "../data/pricing.json";
import { barChart, scenarioOutcome, sessionUsd } from "../src/savings.ts";
import type { Scenario } from "../src/savings.ts";

const composition = benchmarksJson.composition;
const pricing: Pricing = pricingJson;
const GOLDEN: Scenario = { perDay: 10000, turns: 3, modelId: "sonnet-5-5" };

function cents(value: number): string {
  return value.toFixed(2);
}

describe("scenarioOutcome", () => {
  it("saves 444 million tokens a month at 10,000 conversations a day, 3 turns", () => {
    const outcome = scenarioOutcome(composition, pricing, GOLDEN);
    expect(Math.round(outcome.tokens / 1e6)).toBe(444);
    expect(outcome.tokens).toBeCloseTo(10000 * 3 * 30 * (507 * 908) / 933, 3);
  });

  it("prices Sonnet at 888 dollars list and 88.81 cached", () => {
    const outcome = scenarioOutcome(composition, pricing, GOLDEN);
    expect(Math.round(outcome.usd.list)).toBe(888);
    expect(cents(outcome.usd.cached)).toBe("88.81");
    expect([outcome.listPrice, outcome.cachedPrice]).toEqual([2, 0.2]);
  });

  it("prices Opus at 1,776 dollars list and the same cached 88.81", () => {
    const outcome = scenarioOutcome(composition, pricing, { ...GOLDEN, modelId: "opus-5-5" });
    expect(Math.round(outcome.usd.list)).toBe(1776);
    expect(cents(outcome.usd.cached)).toBe("88.81");
  });

  it("cannot cache the prefix on Haiku, so both prices are 444", () => {
    const outcome = scenarioOutcome(composition, pricing, { ...GOLDEN, modelId: "haiku-4-5" });
    expect(Math.round(outcome.usd.list)).toBe(444);
    expect(outcome.usd.cached).toBe(outcome.usd.list);
    expect(outcome.cachedPrice).toBe(outcome.listPrice);
  });

  it("caches as soon as the prefix reaches the model minimum", () => {
    const exact = { ...composition, prefix_tokens: 4096 };
    const outcome = scenarioOutcome(exact, pricing, { ...GOLDEN, modelId: "haiku-4-5" });
    expect(outcome.cachedPrice).toBe(0.1);
    const short = scenarioOutcome({ ...exact, prefix_tokens: 4095 }, pricing, {
      ...GOLDEN,
      modelId: "haiku-4-5",
    });
    expect(short.cachedPrice).toBe(1);
  });

  it("scales linearly with conversations and turns", () => {
    const base = scenarioOutcome(composition, pricing, GOLDEN);
    const doubled = scenarioOutcome(composition, pricing, { ...GOLDEN, perDay: 20000, turns: 6 });
    expect(doubled.tokens).toBeCloseTo(base.tokens * 4, 3);
  });

  it("refuses a model, turn count or volume the data does not allow", () => {
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, modelId: "gpt" })).toThrow(
      RangeError,
    );
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, turns: 0 })).toThrow(RangeError);
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, turns: 11 })).toThrow(
      RangeError,
    );
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, turns: 2.5 })).toThrow(
      RangeError,
    );
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, perDay: -1 })).toThrow(
      RangeError,
    );
    expect(() => scenarioOutcome(composition, pricing, { ...GOLDEN, perDay: Number.NaN })).toThrow(
      RangeError,
    );
  });
});

describe("barChart", () => {
  it("has one row per chart stop, in order, from the data", () => {
    const { rows } = barChart(composition, pricing, GOLDEN);
    expect(rows.map((row) => row.perDay)).toEqual(pricing.calculator.chart_stops);
    expect(rows).toHaveLength(5);
  });

  it("scales every width against the largest list price shown", () => {
    const { rows, you } = barChart(composition, pricing, GOLDEN);
    const last = rows[rows.length - 1];
    expect(last?.listWidth).toBe(1);
    expect(last?.cachedWidth).toBeCloseTo(0.1, 6);
    expect(you.listWidth).toBeCloseTo(0.01, 6);
    for (const row of [...rows, you]) {
      expect(row.listWidth).toBeLessThanOrEqual(1);
      expect(row.cachedWidth).toBeLessThanOrEqual(row.listWidth);
    }
  });

  it("describes the chosen scenario as its own row", () => {
    const { you } = barChart(composition, pricing, { ...GOLDEN, perDay: 500 });
    expect(you.perDay).toBe(500);
    expect(Math.round(you.usd.list)).toBe(44);
  });

  it("keeps the chosen row on the scale when it is the largest", () => {
    const wide: Pricing = {
      ...pricing,
      calculator: { ...pricing.calculator, chart_stops: [100, 1000] },
    };
    const { you } = barChart(composition, wide, { ...GOLDEN, perDay: 1000000 });
    expect(you.listWidth).toBe(1);
  });

  it("shows equal list and cached widths for a model that cannot cache", () => {
    const { rows } = barChart(composition, pricing, { ...GOLDEN, modelId: "haiku-4-5" });
    for (const row of rows) {
      expect(row.cachedWidth).toBe(row.listWidth);
    }
  });
});

describe("sessionUsd", () => {
  it("prices the saved tokens at the default model list price", () => {
    expect(sessionUsd(1014, pricing)).toBeCloseTo(0.002028, 9);
  });

  it("prices them at the model asked for", () => {
    expect(sessionUsd(1000000, pricing, "opus-5-5")).toBe(4);
  });

  it("refuses an unknown model", () => {
    expect(() => sessionUsd(1, pricing, "gpt")).toThrow(RangeError);
  });
});

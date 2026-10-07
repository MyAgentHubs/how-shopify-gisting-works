import { describe, expect, it } from "vitest";
import type { Pricing } from "../../../contracts/pricing.generated.ts";
import benchmarksJson from "../data/benchmarks.json";
import pricingJson from "../data/pricing.json";
import { basisOf, defaultScenario, savingsProvider, savingsView } from "../src/savings-provider.ts";

const pricing: Pricing = pricingJson;
const numbers = {
  savedPerTurn: benchmarksJson.composition.saved_per_turn,
  prefixTokens: benchmarksJson.composition.prefix_tokens,
};
const basis = basisOf(numbers);

describe("the default scenario", () => {
  it("is 10,000 conversations a day, 3 turns, Sonnet, all read from the pricing file", () => {
    expect(defaultScenario(pricing)).toEqual({ perDay: 10000, turns: 3, modelId: "sonnet-5-5" });
  });

  it("saves 444 M tokens, 888 dollars at list price and 88.81 with caching", () => {
    const view = savingsView(basis, pricing, defaultScenario(pricing));
    expect(Math.round(view.tokens / 1e6)).toBe(444);
    expect(view.listUsd.toFixed(2)).toBe("888.15");
    expect(view.cachedUsd.toFixed(2)).toBe("88.81");
    expect([view.listPrice, view.cachedPrice, view.cacheHelps]).toEqual([2, 0.2, true]);
  });

  it("tells the slider where it stands: stop 6 of 0 to 12, turn 3 of 1 to 10", () => {
    const view = savingsView(basis, pricing, defaultScenario(pricing));
    expect([view.stopIndex, view.stopMax, view.turns, view.turnsMax]).toEqual([6, 12, 3, 10]);
  });
});

describe("the bar chart rows", () => {
  it("has one row per chart stop with widths scaled to the largest list price", () => {
    const { rows, you } = savingsView(basis, pricing, defaultScenario(pricing));
    expect(rows.map((row) => row.perDay)).toEqual(pricing.calculator.chart_stops);
    [0.0001, 0.001, 0.01, 0.1, 1].forEach((width, index) => {
      expect(rows[index]?.listWidth).toBeCloseTo(width, 12);
    });
    expect(rows.map((row) => row.cachedWidth)[4]).toBeCloseTo(0.1, 12);
    expect(you).toEqual(rows[2]);
  });

  it("scales to the visitor's own scenario when it is bigger than every stop", () => {
    const short = { ...pricing, calculator: { ...pricing.calculator, chart_stops: [100, 1000] } };
    const view = savingsView(basis, short, { ...defaultScenario(pricing), perDay: 1000000 });
    expect(view.you.listWidth).toBe(1);
    expect(view.rows[1]?.listWidth).toBeCloseTo(0.001, 12);
  });
});

describe("the models", () => {
  it("lists every priced model and marks the chosen one", () => {
    const view = savingsView(basis, pricing, { ...defaultScenario(pricing), modelId: "opus-5-5" });
    expect(view.models.map((model) => [model.id, model.selected])).toEqual([
      ["sonnet-5-5", false],
      ["opus-5-5", true],
      ["haiku-4-5", false],
    ]);
    expect(view.models[2]).toEqual({
      id: "haiku-4-5",
      name: "Claude Haiku 4.5",
      short: "Haiku 4.5",
      input: 1,
      cacheRead: 0.1,
      minCacheable: 4096,
      selected: false,
    });
  });

  it("carries the words the copy fills in: the chosen model, the days and the model that cannot cache", () => {
    const view = savingsView(basis, pricing, defaultScenario(pricing));
    expect(view.modelName).toBe("Claude Sonnet 5.5");
    expect(view.daysPerMonth).toBe(30);
    expect(view.uncacheable?.short).toBe("Haiku 4.5");
    expect(view.uncacheable?.minCacheable).toBe(4096);
    const cheap = { ...pricing, models: pricing.models.map((model) => ({ ...model, min_cacheable: 1 })) };
    expect(savingsView(basis, cheap, defaultScenario(pricing)).uncacheable).toBeNull();
  });

  it("prices Haiku the same with and without caching and says so", () => {
    const view = savingsView(basis, pricing, { ...defaultScenario(pricing), modelId: "haiku-4-5" });
    expect(view.cacheHelps).toBe(false);
    expect(view.cachedUsd).toBe(view.listUsd);
    expect(Math.round(view.listUsd)).toBe(444);
    expect(view.cachedPrice).toBe(view.listPrice);
  });
});

describe("bad input", () => {
  it("refuses a volume that is not one of the slider stops", () => {
    expect(() => savingsView(basis, pricing, { ...defaultScenario(pricing), perDay: 1234 })).toThrow(RangeError);
  });

  it("refuses runtime numbers that lack the saving or the prefix", () => {
    expect(() => basisOf({ savedPerTurn: 493 })).toThrow(TypeError);
    expect(() => basisOf({ prefixTokens: 921, savedPerTurn: "493" })).toThrow(TypeError);
  });
});

describe("the build-time provider", () => {
  it("gives the default scenario view and needs the pricing", () => {
    expect(savingsProvider({ numbers, pricing })).toEqual(savingsView(basis, pricing, defaultScenario(pricing)));
    expect(() => savingsProvider({ numbers, pricing: null })).toThrow(/pricing/);
  });

  it("stops the build when no model, or more than one, is too small to cache the prompt", () => {
    const withMinimums = (minimums: readonly number[]): Pricing => ({
      ...pricing,
      models: pricing.models.map((model, index) => ({ ...model, min_cacheable: minimums[index] ?? 1 })),
    });
    expect(() => savingsProvider({ numbers, pricing: withMinimums([1, 1, 1]) })).toThrow(
      /exactly one model.*gives no model/,
    );
    expect(() => savingsProvider({ numbers, pricing: withMinimums([99999, 1, 99999]) })).toThrow(
      /exactly one model.*gives 2 models.*Claude Sonnet 5\.5.*Claude Haiku 4\.5/,
    );
  });
});

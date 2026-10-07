import type { Pricing } from "../../../contracts/pricing.generated.ts";
import { barChart, modelNameOf, scenarioOutcome } from "./savings.ts";
import type { Basis, BarChart, Scenario } from "./savings.ts";

export interface ChartRow {
  readonly perDay: number;
  readonly listUsd: number;
  readonly cachedUsd: number;
  readonly listWidth: number;
  readonly cachedWidth: number;
}

interface PricedModel {
  readonly id: string;
  readonly name: string;
  readonly short: string;
  readonly input: number;
  readonly cacheRead: number;
  readonly minCacheable: number;
  readonly selected: boolean;
}

export interface SavingsView extends Scenario {
  readonly stopIndex: number;
  readonly stopMax: number;
  readonly turnsMax: number;
  readonly tokens: number;
  readonly listUsd: number;
  readonly cachedUsd: number;
  readonly listPrice: number;
  readonly cachedPrice: number;
  readonly cacheHelps: boolean;
  readonly rows: readonly ChartRow[];
  readonly you: ChartRow;
  readonly models: readonly PricedModel[];
  readonly modelName: string;
  readonly daysPerMonth: number;
  readonly uncacheable: PricedModel | null;
}

export type RuntimeNumbers = Readonly<Record<string, unknown>>;

export function basisOf(numbers: RuntimeNumbers): Basis {
  const { savedPerTurn, prefixTokens } = numbers;
  if (typeof savedPerTurn !== "number" || typeof prefixTokens !== "number") {
    throw new TypeError("runtime numbers need savedPerTurn and prefixTokens");
  }
  return { saved_per_turn: savedPerTurn, prefix_tokens: prefixTokens };
}

export function defaultScenario(pricing: Pricing): Scenario {
  const { default_per_day: perDay, default_turns: turns } = pricing.calculator;
  return { perDay, turns, modelId: pricing.default };
}

function chartRow(row: BarChart["rows"][number]): ChartRow {
  return {
    perDay: row.perDay,
    listUsd: row.usd.list,
    cachedUsd: row.usd.cached,
    listWidth: row.listWidth,
    cachedWidth: row.cachedWidth,
  };
}

function stopIndexOf(pricing: Pricing, perDay: number): number {
  const index = pricing.calculator.stops.indexOf(perDay);
  if (index < 0) {
    throw new RangeError(`${String(perDay)} conversations a day is not one of the slider stops`);
  }
  return index;
}

function pricedModels(pricing: Pricing, chosen: string): readonly PricedModel[] {
  return pricing.models.map((model) => ({
    id: model.id,
    name: model.name,
    short: model.short,
    input: model.input,
    cacheRead: model.cache_read,
    minCacheable: model.min_cacheable,
    selected: model.id === chosen,
  }));
}

export function savingsView(basis: Basis, pricing: Pricing, scenario: Scenario): SavingsView {
  const outcome = scenarioOutcome(basis, pricing, scenario);
  const chart = barChart(basis, pricing, scenario);
  const models = pricedModels(pricing, scenario.modelId);
  return {
    ...scenario,
    stopIndex: stopIndexOf(pricing, scenario.perDay),
    stopMax: pricing.calculator.stops.length - 1,
    turnsMax: pricing.calculator.max_turns,
    tokens: outcome.tokens,
    listUsd: outcome.usd.list,
    cachedUsd: outcome.usd.cached,
    listPrice: outcome.listPrice,
    cachedPrice: outcome.cachedPrice,
    cacheHelps: outcome.cachedPrice < outcome.listPrice,
    rows: chart.rows.map(chartRow),
    you: chartRow(chart.you),
    models,
    modelName: modelNameOf(pricing, scenario.modelId),
    daysPerMonth: pricing.calculator.days_per_month,
    uncacheable: models.find((model) => basis.prefix_tokens < model.minCacheable) ?? null,
  };
}

export function savingsProvider({
  numbers,
  pricing,
}: {
  readonly numbers: RuntimeNumbers;
  readonly pricing: Pricing | null;
}): SavingsView {
  if (pricing === null) {
    throw new TypeError("the savings provider needs the pricing data");
  }
  const basis = basisOf(numbers);
  const view = savingsView(basis, pricing, defaultScenario(pricing));
  const small = view.models.filter((model) => basis.prefix_tokens < model.minCacheable);
  if (small.length !== 1) {
    const found = small.length === 0 ? "no model" : `${String(small.length)} models (${small.map((model) => model.name).join(", ")})`;
    throw new RangeError(
      `the page copy names exactly one model that cannot cache a ${String(basis.prefix_tokens)}-token prompt, but pricing.json gives ${found}`,
    );
  }
  return view;
}

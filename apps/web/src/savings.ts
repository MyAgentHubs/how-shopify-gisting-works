import type { Benchmarks } from "../../../contracts/benchmarks.generated.ts";
import type { Pricing } from "../../../contracts/pricing.generated.ts";

export type Basis = Pick<Benchmarks["composition"], "saved_per_turn" | "prefix_tokens">;
type ModelPrice = Pricing["models"][number];

const TOKENS_PER_MILLION = 1_000_000;

export interface Scenario {
  readonly perDay: number;
  readonly turns: number;
  readonly modelId: string;
}

interface Money {
  readonly list: number;
  readonly cached: number;
}

export interface Outcome {
  readonly tokens: number;
  readonly usd: Money;
  readonly listPrice: number;
  readonly cachedPrice: number;
}

interface BarRow {
  readonly perDay: number;
  readonly usd: Money;
  readonly listWidth: number;
  readonly cachedWidth: number;
}

export interface BarChart {
  readonly rows: readonly BarRow[];
  readonly you: BarRow;
}

export function modelNameOf(pricing: Pricing, id: string = pricing.default): string {
  return findModel(pricing, id).name;
}

function findModel(pricing: Pricing, id: string): ModelPrice {
  const model = pricing.models.find((candidate) => candidate.id === id);
  if (model === undefined) {
    throw new RangeError(`unknown model ${id}`);
  }
  return model;
}

function checkScenario(pricing: Pricing, scenario: Scenario): void {
  const { turns, perDay } = scenario;
  if (!Number.isInteger(turns) || turns < 1 || turns > pricing.calculator.max_turns) {
    throw new RangeError(`turns must be a whole number from 1 to ${String(pricing.calculator.max_turns)}`);
  }
  if (!Number.isFinite(perDay) || perDay < 0) {
    throw new RangeError("conversations a day must be a non-negative number");
  }
}

function cachedPriceOf(model: ModelPrice, composition: Basis): number {
  return composition.prefix_tokens >= model.min_cacheable ? model.cache_read : model.input;
}

function monthTokens(composition: Basis, pricing: Pricing, perDay: number, turns: number) {
  return perDay * turns * pricing.calculator.days_per_month * composition.saved_per_turn;
}

function moneyFor(tokens: number, model: ModelPrice, composition: Basis): Money {
  return {
    list: (tokens / TOKENS_PER_MILLION) * model.input,
    cached: (tokens / TOKENS_PER_MILLION) * cachedPriceOf(model, composition),
  };
}

export function scenarioOutcome(
  composition: Basis,
  pricing: Pricing,
  scenario: Scenario,
): Outcome {
  checkScenario(pricing, scenario);
  const model = findModel(pricing, scenario.modelId);
  const tokens = monthTokens(composition, pricing, scenario.perDay, scenario.turns);
  return {
    tokens,
    usd: moneyFor(tokens, model, composition),
    listPrice: model.input,
    cachedPrice: cachedPriceOf(model, composition),
  };
}

function widthOf(value: number, scale: number): number {
  return scale === 0 ? 0 : value / scale;
}

function sized(perDay: number, usd: Money, scale: number): BarRow {
  return {
    perDay,
    usd,
    listWidth: widthOf(usd.list, scale),
    cachedWidth: widthOf(usd.cached, scale),
  };
}

export function barChart(
  composition: Basis,
  pricing: Pricing,
  scenario: Scenario,
): BarChart {
  const money = (perDay: number): Money =>
    scenarioOutcome(composition, pricing, { ...scenario, perDay }).usd;
  const stops = pricing.calculator.chart_stops;
  const scale = Math.max(money(scenario.perDay).list, ...stops.map((stop) => money(stop).list));
  return {
    rows: stops.map((stop) => sized(stop, money(stop), scale)),
    you: sized(scenario.perDay, money(scenario.perDay), scale),
  };
}

export function sessionUsd(
  savedTokens: number,
  pricing: Pricing,
  modelId: string = pricing.default,
): number {
  return (savedTokens / TOKENS_PER_MILLION) * findModel(pricing, modelId).input;
}

import type { Pricing } from "../../../contracts/pricing.generated.ts";
import { formatValue } from "./format.ts";
import { basisOf, savingsView } from "./savings-provider.ts";
import type { ChartRow, RuntimeNumbers, SavingsView } from "./savings-provider.ts";
import { RUNTIME_BLOCK_ID, isPricing, readRuntimeBlock } from "./runtime.ts";
import type { Basis } from "./savings.ts";

type Show = (format: string, value: number) => string;

interface Parts {
  readonly root: Element;
  readonly controls: HTMLElement;
  readonly notice: HTMLElement;
  readonly day: HTMLInputElement;
  readonly turns: HTMLInputElement;
  readonly dayOut: HTMLElement;
  readonly turnsOut: HTMLElement;
  readonly you: HTMLElement;
  readonly stops: readonly Element[];
  readonly models: readonly Element[];
}

interface Runtime {
  readonly lang: string;
  readonly basis: Basis;
  readonly pricing: Pricing;
}

const SELECTORS = {
  root: "[data-calculator]",
  controls: '[data-role="controls"]',
  notice: '[data-role="nojs-note"]',
  day: "#og-s-day",
  turns: "#og-s-turns",
  dayOut: "#og-o-day",
  turnsOut: "#og-o-turns",
  you: '[data-role="you"]',
  stop: '[data-role="stop"]',
  model: "tr[data-model]",
  chosen: 'input[name="og-model"]:checked',
};

function missing(selector: string): ReferenceError {
  return new ReferenceError(`the calculator needs ${selector}`);
}

function required(root: ParentNode, selector: string): HTMLElement {
  const node = root.querySelector<HTMLElement>(selector);
  if (node === null) {
    throw missing(selector);
  }
  return node;
}

function requiredInput(root: ParentNode, selector: string): HTMLInputElement {
  const node = root.querySelector<HTMLInputElement>(selector);
  if (node === null) {
    throw missing(selector);
  }
  return node;
}

function readRuntime(doc: Document): Runtime {
  const { lang, numbers, pricing } = readRuntimeBlock(doc) as {
    lang?: unknown;
    numbers?: RuntimeNumbers;
    pricing?: unknown;
  };
  if (typeof lang !== "string" || numbers === undefined || !isPricing(pricing)) {
    throw new TypeError(`#${RUNTIME_BLOCK_ID} needs lang, numbers and pricing`);
  }
  return { lang, basis: basisOf(numbers), pricing };
}

function collect(doc: Document, root: Element): Parts {
  return {
    root,
    controls: required(root, SELECTORS.controls),
    notice: required(root, SELECTORS.notice),
    day: requiredInput(root, SELECTORS.day),
    turns: requiredInput(root, SELECTORS.turns),
    dayOut: required(root, SELECTORS.dayOut),
    turnsOut: required(root, SELECTORS.turnsOut),
    you: required(root, SELECTORS.you),
    stops: [...root.querySelectorAll(SELECTORS.stop)],
    models: [...doc.querySelectorAll(SELECTORS.model)],
  };
}

function scenarioOf(parts: Parts, pricing: Pricing) {
  const perDay = pricing.calculator.stops[Number(parts.day.value)];
  if (perDay === undefined) {
    throw new RangeError(`no volume stop at position ${parts.day.value}`);
  }
  const modelId = requiredInput(parts.root, SELECTORS.chosen).value;
  return { perDay, turns: Number(parts.turns.value), modelId };
}

function setText(root: ParentNode, name: string, text: string): void {
  required(root, `[data-out="${name}"]`).textContent = text;
}

function paintBars(row: Element, data: ChartRow, show: Show): void {
  const [list, cached] = [...row.querySelectorAll("i")];
  const [listLabel, cachedLabel] = [...row.querySelectorAll("[data-v]")];
  if (list === undefined || cached === undefined || listLabel === undefined || cachedLabel === undefined) {
    throw new ReferenceError("a chart row needs two bars with a value each");
  }
  list.setAttribute("style", `--w:${show("ratio", data.listWidth)}`);
  cached.setAttribute("style", `--w:${show("ratio", data.cachedWidth)}`);
  listLabel.textContent = show("usd", data.listUsd);
  cachedLabel.textContent = show("usd", data.cachedUsd);
}

function paintResults(parts: Parts, view: SavingsView, show: Show): void {
  const { root } = parts;
  setText(root, "tokens", show("tokens", view.tokens));
  setText(root, "usd-list", show("usd", view.listUsd));
  setText(root, "usd-cache", show("usd", view.cachedUsd));
  setText(root, "p-list", show("usd", view.listPrice));
  setText(root, "p-cache", show("usd", view.cachedPrice));
  required(root, '[data-out="same-price"]').hidden = view.cacheHelps;
  parts.dayOut.textContent = show("int", view.perDay);
  parts.turnsOut.textContent = show("int", view.turns);
  parts.day.setAttribute("aria-valuetext", show("int", view.perDay));
}

function paintChart(parts: Parts, view: SavingsView, show: Show): void {
  view.rows.forEach((data, index) => {
    const row = parts.stops[index];
    if (row === undefined) {
      throw new ReferenceError(`the chart has no row for stop ${String(index)}`);
    }
    paintBars(row, data, show);
  });
  paintBars(parts.you, view.you, show);
  parts.you.hidden = false;
  for (const row of parts.models) {
    row.setAttribute("data-selected", String(row.getAttribute("data-model") === view.modelId));
  }
}

function render(parts: Parts, runtime: Runtime): void {
  const view = savingsView(runtime.basis, runtime.pricing, scenarioOf(parts, runtime.pricing));
  const show: Show = (format, value) => formatValue(format, value, runtime.lang);
  paintResults(parts, view, show);
  paintChart(parts, view, show);
}

export function mountCalculator(doc: Document): void {
  const root = doc.querySelector(SELECTORS.root);
  if (root === null) {
    return;
  }
  const runtime = readRuntime(doc);
  const parts = collect(doc, root);
  parts.controls.addEventListener("input", () => {
    render(parts, runtime);
  });
  render(parts, runtime);
  parts.controls.hidden = false;
  parts.notice.hidden = true;
}

import type { Pricing } from "../../../contracts/pricing.generated.ts";
import type { Copy, CopyKey } from "./copy.ts";
import { fill, text } from "./copy.ts";
import { el } from "./dom.ts";
import { formatValue } from "./format.ts";
import type { MeterState } from "./meter.ts";
import { modelNameOf, sessionUsd } from "./savings.ts";

const PERCENT = 100;
const SHARE_DIGITS = 1;
const SPACE = " ";
const SEPARATOR = " · ";
const APPROX = "≈";
const SCALE_ANCHOR = "#savings";
const DOWN_ARROW = "↓";

function track(...fills: HTMLElement[]): HTMLElement {
  return el("span", { class: "og-tr", "aria-hidden": "true" }, ...fills);
}

function gistTrack(share: number): HTMLElement {
  const gist = el("i", { class: "og-g" });
  gist.style.width = `${String(share)}%`;
  return track(gist, el("i", { class: "og-sv", style: `--l:${String(share)}%` }));
}

function row(label: string, bar: HTMLElement, value: string): HTMLElement {
  return el("div", { class: "og-mrow" }, el("span", {}, label), bar, el("b", {}, value));
}

function savedBlock(copy: Copy, saved: number, pricing: Pricing): HTMLElement {
  const label = (key: CopyKey): string => text(copy, key);
  const money = formatValue("usd3", sessionUsd(saved, pricing), copy.lang);
  return el(
    "div",
    { class: "og-msaved" },
    el(
      "p",
      { class: "og-mv" },
      `${label("meter.saved")} ${formatValue("int", saved, copy.lang)}${SPACE}`,
      el("small", {}, label("meter.unit")),
      `${SEPARATOR}${APPROX} ${money}`,
    ),
    el("p", {}, fill(label("meter.footnote"), { model: modelNameOf(pricing) })),
    el("a", { href: SCALE_ANCHOR }, `${label("meter.scale_link")}${SPACE}`, el("span", { "aria-hidden": "true" }, DOWN_ARROW)),
  );
}

export function renderMeter(root: HTMLElement, state: MeterState, copy: Copy, pricing: Pricing): void {
  if (state.calls === 0) {
    root.replaceChildren();
    root.hidden = true;
    return;
  }
  const show = (value: number): string => formatValue("int", value, copy.lang);
  const share = Number(((state.gistUsed / state.fullWould) * PERCENT).toFixed(SHARE_DIGITS));
  root.replaceChildren(
    el(
      "div",
      {},
      el("p", { class: "og-mt" }, text(copy, "meter.title")),
      row(text(copy, "meter.gist_used"), gistTrack(share), show(state.gistUsed)),
      row(text(copy, "meter.full_would"), track(el("i", { class: "og-f" })), show(state.fullWould)),
    ),
    savedBlock(copy, state.fullWould - state.gistUsed, pricing),
  );
  root.hidden = false;
}

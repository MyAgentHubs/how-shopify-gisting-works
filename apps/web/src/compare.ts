import type { Copy, CopyKey } from "./copy.ts";
import { fill, formatNumber, text } from "./copy.ts";
import { el } from "./dom.ts";
import type { PublicTrace } from "./trace.ts";

export interface Side {
  readonly answer: string;
  readonly trace: PublicTrace;
}

const MS = "ms";
const SEPARATOR = " · ";

function card(copy: Copy, label: CopyKey, side: Side, className: string): HTMLElement {
  const { tokens, latency } = side.trace;
  const figures = [
    formatNumber(copy, tokens.total),
    `${formatNumber(copy, latency.first_token_ms)} ${MS}`,
    `${formatNumber(copy, latency.total_ms)} ${MS}`,
  ].join(SEPARATOR);
  return el(
    "div",
    { class: `og-cc ${className}` },
    el("h4", {}, text(copy, label), el("span", {}, figures)),
    el("p", {}, side.answer),
  );
}

export function renderCompare(out: HTMLElement, copy: Copy, gist: Side, full: Side): void {
  out.replaceChildren(
    card(copy, "ui.mode_gist", gist, "og-gist"),
    card(copy, "ui.mode_full", full, "og-full"),
  );
  out.hidden = false;
}

export function comparesLeftText(copy: Copy, left: number, max: number): string {
  return fill(text(copy, "hood.compare_left"), { left, max });
}

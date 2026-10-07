import type { Copy, CopyKey } from "./copy.ts";
import { fill, formatNumber, text } from "./copy.ts";
import type { Child } from "./dom.ts";
import { el } from "./dom.ts";
import type { MeterConstants } from "./meter.ts";
import { fullEquivalent } from "./meter.ts";
import type { PublicTrace } from "./trace.ts";

export interface TurnView {
  readonly trace: PublicTrace;
}

type Titled = "hood.tool_call" | "hood.prompt" | "hood.check" | "hood.first_token";
type Part = readonly [label: CopyKey, tokens: number, className: string];

const PERCENT = 100;
const MS = "ms";
const NO_VALUE = "–";
const HELP_MARK = "?";
const SPACE = " ";
const EMAIL_MASK = "•••";

function help(copy: Copy, body: string): HTMLElement {
  return el(
    "details",
    { class: "og-hq" },
    el("summary", { "aria-label": text(copy, "hood.help") }, HELP_MARK),
    el("span", { class: "og-hh" }, body),
  );
}

function section(copy: Copy, key: Titled, ...content: Child[]): HTMLElement {
  const title: CopyKey = `${key}.title`;
  const body: CopyKey = `${key}.body`;
  return el(
    "div",
    { class: "og-hs" },
    el("h4", {}, text(copy, title), help(copy, text(copy, body))),
    ...content,
  );
}

function callLabel(tool: PublicTrace["tools"][number]): string {
  const args = tool.order_number === null ? [] : [tool.order_number, EMAIL_MASK];
  return `${tool.tool}(${args.join(", ")})`;
}

function toolCalls(copy: Copy, turn: TurnView): Child[] {
  if (turn.trace.tools.length === 0) {
    return [el("p", { class: "og-empty" }, NO_VALUE)];
  }
  return turn.trace.tools.map((tool) =>
    el(
      "div",
      { class: "og-tcall" },
      el("code", {}, callLabel(tool)),
      el("span", { class: "og-res" }, text(copy, "ui.result_returned")),
    ),
  );
}

function partsOf(tokens: PublicTrace["tokens"]): Part[] {
  const history = Math.max(0, tokens.total - tokens.rules - tokens.tools);
  return [
    ["ui.part_rules", tokens.rules, "og-r"],
    ["ui.part_tools", tokens.tools, "og-t"],
    ["ui.part_history", history, "og-h"],
  ];
}

function partBar(parts: readonly Part[], total: number): HTMLElement {
  const segments = parts.map(([, tokens, className]) => {
    const segment = el("i", { class: className });
    segment.style.width = `${String(total === 0 ? 0 : (tokens / total) * PERCENT)}%`;
    return segment;
  });
  const label = parts.map(([, tokens]) => String(tokens)).join(" + ");
  return el("div", { class: "og-pbar", role: "img", "aria-label": label }, ...segments);
}

function partRow(copy: Copy, part: Part, fullRules: number | null): HTMLElement {
  const [label, tokens, className] = part;
  const note =
    label === "ui.part_rules" && fullRules !== null
      ? [el("small", {}, `· ${text(copy, "ui.mode_full")} ${formatNumber(copy, fullRules)}`)]
      : [];
  return el(
    "tr",
    {},
    el("td", {}, el("i", { class: `og-pk ${className}` }), `${text(copy, label)}${SPACE}`, ...note),
    el("td", {}, formatNumber(copy, tokens)),
  );
}

function promptTable(copy: Copy, trace: PublicTrace, meter: MeterConstants): HTMLElement {
  const { tokens } = trace;
  const parts = partsOf(tokens);
  const fullRules = fullEquivalent(trace, meter)?.rules ?? null;
  const total = el(
    "tr",
    { class: "og-ptot" },
    el("td", {}, text(copy, "ui.part_total")),
    el("td", {}, formatNumber(copy, tokens.total)),
  );
  return el(
    "div",
    {},
    partBar(parts, tokens.total),
    el("table", { class: "og-ptab" }, ...parts.map((part) => partRow(copy, part, fullRules)), total),
  );
}

function latency(copy: Copy, trace: PublicTrace): HTMLElement {
  const show = (ms: number): string => `${formatNumber(copy, ms)} ${MS}`;
  return el(
    "p",
    { class: "og-lat" },
    el("b", {}, show(trace.latency.first_token_ms)),
    SPACE,
    el("span", { class: "og-lt" }, text(copy, "ui.latency_total"), SPACE, el("b", {}, show(trace.latency.total_ms))),
  );
}

export function renderPanel(
  body: HTMLElement,
  copy: Copy,
  turn: TurnView | null,
  meter: MeterConstants,
): void {
  if (turn === null) {
    body.replaceChildren(el("p", { class: "og-empty" }, text(copy, "ui.panel_empty")));
    return;
  }
  body.replaceChildren(
    section(copy, "hood.tool_call", ...toolCalls(copy, turn)),
    section(copy, "hood.prompt", promptTable(copy, turn.trace, meter)),
    section(copy, "hood.check", el("div", { class: "og-tcall og-done" }, text(copy, "ui.check_done"))),
    section(copy, "hood.first_token", latency(copy, turn.trace)),
  );
}

export function drawerSummary(copy: Copy, turn: TurnView | null, meter: MeterConstants): string {
  const full = turn === null ? null : fullEquivalent(turn.trace, meter);
  if (turn === null || full === null) {
    return "";
  }
  return fill(text(copy, "hood.summary"), {
    gist: formatNumber(copy, turn.trace.tokens.total),
    full: formatNumber(copy, full.total),
  });
}

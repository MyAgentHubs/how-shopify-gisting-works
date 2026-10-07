import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyZh from "../copy/zh-CN.json";
import hoodStyle from "../styles/55-hood.css?raw";
import type { MeterConstants } from "../src/meter.ts";
import { drawerSummary, renderPanel } from "../src/panel.ts";
import type { TurnView } from "../src/panel.ts";
import { parseCopy, text } from "../src/copy.ts";
import type { PublicTrace } from "../src/trace.ts";
import { TRACE, english } from "./support.ts";

const METER: MeterConstants = { rulesFull: 526, rulesGist: 19 };
const SECTION_KEYS = ["hood.tool_call", "hood.prompt", "hood.check", "hood.first_token"] as const;

function turnOf(trace: PublicTrace = TRACE): TurnView {
  return { trace };
}

function render(turn: TurnView | null, copy = english): HTMLElement {
  const body = document.createElement("div");
  renderPanel(body, copy, turn, METER);
  return body;
}

function sections(body: HTMLElement): HTMLElement[] {
  return [...body.querySelectorAll<HTMLElement>(".og-hs")];
}

function textOf(node: Element): string {
  return node.textContent.replace(/\s+/g, " ").trim();
}

describe("the panel's sections", () => {
  it("are the four the design shows, in order, each with a title and a ? that opens its help", () => {
    const found = sections(render(turnOf()));
    expect(found).toHaveLength(SECTION_KEYS.length);
    SECTION_KEYS.forEach((key, index) => {
      const section = found[index];
      expect(section?.querySelector("h4")?.firstChild?.textContent).toBe(
        text(english, `${key}.title`),
      );
      const summary = section?.querySelector("h4 details.og-hq > summary");
      expect(summary?.textContent).toBe("?");
      expect(summary?.getAttribute("aria-label")).toBe(text(english, "hood.help"));
      expect(textOf(section?.querySelector("h4 .og-hh") ?? document.body)).toBe(
        text(english, `${key}.body`),
      );
    });
  });

  it("follow the language of the copy", () => {
    const zh = parseCopy(copyZh);
    const title = render(turnOf(), zh).querySelector("h4")?.firstChild?.textContent;
    expect(title).toBe(copyZh.strings["hood.tool_call.title"]);
  });

  it("show only a note to send a message before the first turn", () => {
    const body = render(null);
    expect(sections(body)).toHaveLength(0);
    expect(textOf(body)).toBe(text(english, "ui.panel_empty"));
  });
});

describe("the time to first word", () => {
  it("is a bare reading under its title, with no second label in front of it", () => {
    const section = sections(render(turnOf()))[3];
    const title = text(english, "hood.first_token.title");
    expect(section).toBeDefined();
    expect(textOf(section ?? document.body).split(title)).toHaveLength(2);
    expect(textOf(section?.querySelector(".og-lat b") ?? document.body)).toBe("900 ms");
    expect(textOf(section?.querySelector(".og-lat") ?? document.body)).toBe(
      `900 ms ${text(english, "ui.latency_total")} 1,800 ms`,
    );
  });
});

describe("the prompt section", () => {
  it("lists the parts and the total, and puts what the full rules would have cost next to the rules", () => {
    const rows = [...render(turnOf()).querySelectorAll(".og-ptab tr")].map((row) =>
      [...row.children].map(textOf),
    );
    expect(rows).toEqual([
      ["Fixed rules · Full rules 526", "19"],
      ["Tools", "120"],
      ["Chat history", "40"],
      ["Total input", "179"],
    ]);
  });

  it("counts everything that is not rules or tools as chat history, so the parts always add up", () => {
    const trace: PublicTrace = {
      ...TRACE,
      tokens: { rules: 19, tools: 120, history: 40, tool_results: 25, total: 204 },
    };
    expect(render(turnOf(trace)).querySelectorAll(".og-ptab tr")[2]?.lastElementChild?.textContent).toBe("65");
  });

  it("leaves out the full-rules note when the rules are not a whole number of gist blocks", () => {
    const trace: PublicTrace = { ...TRACE, tokens: { ...TRACE.tokens, rules: 20, total: 180 } };
    const cells = [...(render(turnOf(trace)).querySelector(".og-ptab tr")?.children ?? [])].map(textOf);
    expect(cells).toEqual(["Fixed rules", "20"]);
  });

  it("keeps its own class names for the total row and the swatches, apart from figures two and three", () => {
    const body = render(turnOf());
    expect(body.querySelector("tr.og-ptot")).not.toBeNull();
    expect(body.querySelectorAll(".og-pk")).toHaveLength(3);
    expect(body.querySelector(".og-tot, .og-sw")).toBeNull();
    expect(hoodStyle).toContain(".og-ptab .og-ptot td");
    expect(hoodStyle).not.toMatch(/\.og-(tot|sw)\b/);
  });

  it("draws one bar whose parts fill it in proportion", () => {
    const bar = render(turnOf()).querySelector(".og-pbar");
    expect(bar?.getAttribute("role")).toBe("img");
    expect(bar?.getAttribute("aria-label")).toBe("19 + 120 + 40");
    const widths = [...(bar?.querySelectorAll("i") ?? [])].map((part) => part.style.width);
    expect(widths.map(parseFloat).reduce((sum, width) => sum + width, 0)).toBeCloseTo(100, 5);
  });
});

describe("the tool call", () => {
  it("shows the tool, the order number and a fixed mask for the email, then 'result returned'", () => {
    const body = render(turnOf());
    expect(textOf(body.querySelector(".og-tcall") ?? document.body)).toBe(
      "lookup_order(#1042, •••)result returned",
    );
  });

  it("never shows any part of what the visitor typed as the email", () => {
    const code = render(turnOf()).querySelector(".og-tcall code");
    expect(code?.textContent).toBe("lookup_order(#1042, •••)");
  });

  it("shows no arguments when the trace has no order number", () => {
    const trace: PublicTrace = {
      ...TRACE,
      tools: [{ tool: "handoff_to_human", order_number: null, outcome: "completed" }],
    };
    expect(textOf(render(turnOf(trace)).querySelector(".og-tcall") ?? document.body)).toBe(
      "handoff_to_human()result returned",
    );
  });

  it("shows a dash when no tool ran", () => {
    const body = render(turnOf({ ...TRACE, tools: [] }));
    expect(textOf(body.querySelector(".og-hs .og-empty") ?? document.body)).toBe("–");
  });
});

describe("the one-line summary", () => {
  it("is empty before the first turn, so the narrow-screen title is not shown twice", () => {
    expect(drawerSummary(english, null, METER)).toBe("");
  });

  it("works out the full-rules size from the rules blocks, without a compare run", () => {
    expect(drawerSummary(english, turnOf(), METER)).toBe("Prompt 179 vs 686 tokens");
    const two: PublicTrace = { ...TRACE, tokens: { ...TRACE.tokens, rules: 38, total: 500 } };
    expect(drawerSummary(english, turnOf(two), METER)).toBe("Prompt 500 vs 1,514 tokens");
  });

  it("stays empty instead of showing a number it cannot work out", () => {
    const odd: PublicTrace = { ...TRACE, tokens: { ...TRACE.tokens, rules: 20, total: 180 } };
    expect(drawerSummary(english, turnOf(odd), METER)).toBe("");
  });

  it("is written in the language of the page", () => {
    expect(drawerSummary(parseCopy(copyZh), turnOf(), METER)).toBe("提示词 179 对 686 token");
    expect(copyEn.strings["hood.summary"]).toContain("{full}");
  });
});

describe("the panel's stylesheet", () => {
  it("shows the one-line summary only on a narrow screen, where the panel starts closed", () => {
    expect(hoodStyle).toMatch(/\.og-cv\{[^}]*display:none/);
    expect(hoodStyle).toMatch(/@media \(max-width:820px\)\{\s*\.og-cv\{display:inline\}/);
  });

  it("keeps the summary line and the ? buttons at a 44px touch target", () => {
    expect(hoodStyle).toMatch(/\.og-hood>summary\{[^}]*min-height:44px/);
    expect(hoodStyle).toMatch(/\.og-hq>summary::after\{[^}]*inset:-10px/);
  });

  it("uses colour tokens only", () => {
    expect(hoodStyle).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});

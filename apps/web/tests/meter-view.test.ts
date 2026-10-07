import { describe, expect, it } from "vitest";
import copyZh from "../copy/zh-CN.json";
import pricingData from "../data/pricing.json";
import { parseCopy, text } from "../src/copy.ts";
import { emptyMeter } from "../src/meter.ts";
import type { MeterState } from "../src/meter.ts";
import { renderMeter } from "../src/meter-view.ts";
import meterStyle from "../styles/56-meter.css?raw";
import type { PublicTrace } from "../src/trace.ts";
import { FULL_TRACE, TRACE, compare, english, mount, query, reply, say } from "./support.ts";

function meter(): HTMLElement {
  return query('[data-role="meter"]');
}

function textOf(node: Element): string {
  return node.textContent.replace(/\s+/g, " ").trim();
}

function rows(): string[] {
  return [...meter().querySelectorAll(".og-mrow")].map((row) => [...row.children].map(textOf).filter(Boolean).join(" "));
}

function traceWith(rules: number, total: number): PublicTrace {
  return { ...TRACE, tokens: { ...TRACE.tokens, rules, total } };
}

function drawn(state: MeterState, copy = english, pricing = pricingData): HTMLElement {
  const root = document.createElement("div");
  renderMeter(root, state, copy, pricing);
  return root;
}

describe("the running total of a chat", () => {
  it("is hidden until a Gist reply has been counted", () => {
    mount();
    expect(meter().hidden).toBe(true);
    expect(meter().childElementCount).toBe(0);
  });

  it("shows what Gist used, what the full rules would have used and what was saved after one reply", async () => {
    mount();
    await say("hello");
    expect(meter().hidden).toBe(false);
    expect(textOf(meter().querySelector(".og-mt") ?? meter())).toBe(text(english, "meter.title"));
    expect(rows()).toEqual([`${text(english, "meter.gist_used")} 179`, `${text(english, "meter.full_would")} 686`]);
    expect(textOf(query(".og-mv"))).toBe("Saved 507 tokens · ≈ $0.001");
    expect(textOf(query(".og-msaved"))).toContain("What-if at Claude Sonnet 5.5 list input price");
  });

  it("adds up over the replies of the chat", async () => {
    mount({ outcomes: [reply("a"), reply("b", traceWith(38, 500))] });
    await say("one");
    await say("two");
    expect(rows()).toEqual([
      `${text(english, "meter.gist_used")} 679`,
      `${text(english, "meter.full_would")} 2,200`,
    ]);
    expect(textOf(query(".og-mv"))).toBe("Saved 1,521 tokens · ≈ $0.003");
  });

  it("draws the Gist bar as its share of the full bar, with the saved part dashed after it", async () => {
    mount();
    await say("hello");
    const share = (179 / 686) * 100;
    expect(Number.parseFloat(query(".og-tr .og-g").style.width)).toBeCloseTo(share, 1);
    expect(query(".og-tr .og-sv").getAttribute("style")).toContain(`--l:${share.toFixed(1)}%`);
    expect(query(".og-tr .og-f")).not.toBeNull();
    for (const track of document.querySelectorAll(".og-tr")) {
      expect(track.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("points to the calculator", async () => {
    mount();
    await say("hello");
    const link = query(".og-msaved a");
    expect(link.getAttribute("href")).toBe("#savings");
    expect(document.querySelector("#savings")).not.toBeNull();
    expect(textOf(link)).toBe(`${text(english, "meter.scale_link")} ↓`);
  });

  it("does not count the Full-rules comparison", async () => {
    mount({ outcomes: [reply("gist"), reply("full", FULL_TRACE)] });
    await say("hello");
    const before = rows();
    await compare();
    expect(rows()).toEqual(before);
    expect(textOf(query(".og-mv"))).toBe("Saved 507 tokens · ≈ $0.001");
  });

  it("does not count a pre-recorded replay, and stays hidden", async () => {
    const turns = [{ role: "assistant", content: "Recorded" }] as const;
    mount({ outcomes: [{ kind: "replay", reason: "quota", turns }] });
    await say("hello");
    expect(meter().hidden).toBe(true);
  });

  it("does not count a failed reply, and keeps what was counted before", async () => {
    mount({ outcomes: [reply("a"), { kind: "failed", status: 502, reason: "http" }] });
    await say("one");
    const before = rows();
    await say("two");
    expect(rows()).toEqual(before);
  });

  it("shows nothing for a reply whose rules are not a whole number of Gist blocks", async () => {
    mount({ outcomes: [reply("odd", traceWith(20, 180))] });
    await say("hello");
    expect(meter().hidden).toBe(true);
  });

  it("sends nothing about the total to the gateway", async () => {
    const page = mount();
    await say("hello");
    expect(Object.keys(page.gateway.requests[0] ?? {}).sort()).toEqual([
      "message",
      "mode",
      "sessionId",
      "timeoutMs",
      "turnstileToken",
    ]);
  });
});

describe("renderMeter", () => {
  const state: MeterState = { calls: 1, gistUsed: 179, fullWould: 686 };

  it("empties and hides the block for a state with nothing counted", () => {
    const root = drawn(state);
    renderMeter(root, emptyMeter(), english, pricingData);
    expect(root.hidden).toBe(true);
    expect(root.childElementCount).toBe(0);
  });

  it("prices the saved tokens at the list input price of the default model", () => {
    const million: MeterState = { calls: 1, gistUsed: 1, fullWould: 1_000_001 };
    const usd = (id: string): string =>
      textOf(drawn(million, english, { ...pricingData, default: id }).querySelector(".og-mv") ?? document.body);
    expect(usd("sonnet-5-5")).toBe("Saved 1,000,000 tokens · ≈ $2.000");
    expect(usd("opus-5-5")).toBe("Saved 1,000,000 tokens · ≈ $4.000");
    expect(usd("haiku-4-5")).toBe("Saved 1,000,000 tokens · ≈ $1.000");
  });

  it("is written in the language of the copy", () => {
    const zh = drawn(state, parseCopy(copyZh));
    expect(textOf(zh.querySelector(".og-mt") ?? zh)).toBe(copyZh.strings["meter.title"]);
    expect(textOf(zh.querySelector(".og-mv") ?? zh)).toBe("省了 507 token · ≈ $0.001");
    expect(textOf(zh.querySelector(".og-msaved a") ?? zh)).toBe(`${copyZh.strings["meter.scale_link"]} ↓`);
  });

  it("can be drawn again without piling up", () => {
    const root = drawn(state);
    renderMeter(root, state, english, pricingData);
    expect(root.querySelectorAll(".og-mrow")).toHaveLength(2);
  });
});

describe("the total's stylesheet", () => {
  it("uses colour tokens only and its own og- class names", () => {
    expect(meterStyle).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(meterStyle).not.toMatch(/(^|[},\s])\.(?!og-)[a-z]/);
  });

  it("stacks on a narrow screen and keeps the link at a 44px touch target", () => {
    expect(meterStyle).toMatch(/@media \(max-width:820px\)\{[^@]*\.og-meter\{grid-template-columns:1fr\}/);
    expect(meterStyle).toMatch(/\.og-msaved a\{[^}]*min-height:44px/);
  });
});

describe("the footnote of the meter", () => {
  const state: MeterState = { calls: 1, gistUsed: 179, fullWould: 686 };
  const note = (root: HTMLElement): string => textOf(root.querySelector(".og-msaved p:nth-of-type(2)") ?? root);

  it("names the default model of the pricing data, in both languages", () => {
    expect(note(drawn(state))).toBe("What-if at Claude Sonnet 5.5 list input price");
    expect(note(drawn(state, parseCopy(copyZh)))).toBe("按 Claude Sonnet 5.5 的输入标价折算（假设情景）");
  });

  it("follows the data when the default model changes", () => {
    const opus = { ...pricingData, default: "opus-5-5" };
    expect(note(drawn(state, english, opus))).toBe("What-if at Claude Opus 5.5 list input price");
  });
});

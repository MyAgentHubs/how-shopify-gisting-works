import { readFileSync } from "node:fs";
import { join } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { mountCalculator } from "../src/calculator.ts";
import { formatValue } from "../src/format.ts";
import { scenarioOutcome } from "../src/savings.ts";
import { REAL_WEB, buildPages, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const pricing = JSON.parse(readFileSync(join(REAL_WEB, "data", "pricing.json"), "utf8"));
const composition = JSON.parse(readFileSync(join(REAL_WEB, "data", "benchmarks.json"), "utf8")).composition;
const STOP = { 100: 0, 10000: 6, 100000: 9, 1000000: 12 };

function open(lang = "en", html = pages.html(lang)) {
  const dom = new JSDOM(html);
  const { document, Event } = dom.window;
  mountCalculator(document);
  const find = (selector) => document.querySelector(selector);
  const fire = (node) => node.dispatchEvent(new Event("input", { bubbles: true }));
  return {
    document,
    out: (name) => textOf(find(`[data-out="${name}"]`)),
    you: () => find("[data-role=you]"),
    slide(selector, value) {
      const node = find(selector);
      node.value = String(value);
      fire(node);
    },
    pick: (id) => find(`input[value="${id}"]`).click(),
    stops: () => [...document.querySelectorAll("[data-role=stop]")],
  };
}

function session(lang) {
  const view = open(lang);
  return {
    ...view,
    setDay: (perDay) => view.slide("#og-s-day", STOP[perDay]),
    setTurns: (turns) => view.slide("#og-s-turns", turns),
  };
}

const widths = (row) => [...row.querySelectorAll("i")].map((bar) => /--w:([\d.]+)/.exec(bar.getAttribute("style"))[1]);
const amounts = (row) => [...row.querySelectorAll("[data-v]")].map(textOf);
const expected = (scenario, lang = "en") => {
  const outcome = scenarioOutcome(composition, pricing, scenario);
  return {
    tokens: formatValue("tokens", outcome.tokens, lang),
    list: formatValue("usd", outcome.usd.list, lang),
    cached: formatValue("usd", outcome.usd.cached, lang),
  };
};
const SONNET = { perDay: 10000, turns: 3, modelId: "sonnet-5-5" };

describe("mounting", () => {
  it("shows the controls, drops the no-script note and the your-scenario row appears", () => {
    const page = session();
    expect(page.document.querySelector("[data-role=controls]").hidden).toBe(false);
    expect(page.document.querySelector("[data-role=nojs-note]").hidden).toBe(true);
    expect(page.you().hidden).toBe(false);
  });

  it("leaves the pre-rendered default scenario exactly as the build wrote it", () => {
    const before = new JSDOM(pages.html("en")).window.document.querySelector("[data-calculator]").innerHTML;
    const page = session();
    const after = page.document.querySelector("[data-calculator]").cloneNode(true);
    after.querySelector("[data-role=controls]").setAttribute("hidden", "");
    after.querySelector("[data-role=nojs-note]").removeAttribute("hidden");
    after.querySelector("[data-role=you]").setAttribute("hidden", "");
    expect(after.innerHTML).toBe(before);
  });

  it("does nothing on a page without a calculator and fails loudly without its data", () => {
    expect(() => mountCalculator(new JSDOM("<p>none</p>").window.document)).not.toThrow();
    const bare = '<div data-calculator></div>';
    expect(() => mountCalculator(new JSDOM(bare).window.document)).toThrow(/runtime-data/);
    const broken = `${bare}<script type="application/json" id="runtime-data">{"lang":"en","numbers":{}}</script>`;
    expect(() => mountCalculator(new JSDOM(broken).window.document)).toThrow(TypeError);
  });
});

describe("the sliders", () => {
  it("move the results with the volume: 1,000,000 a day gives 44.4 B tokens", () => {
    const page = session();
    page.setDay(1000000);
    const want = expected({ ...SONNET, perDay: 1000000 });
    expect([page.out("tokens"), page.out("usd-list"), page.out("usd-cache")]).toEqual([want.tokens, want.list, want.cached]);
    expect([page.out("tokens"), page.out("usd-list"), page.out("usd-cache")]).toEqual(["44.4 B", "$88,815", "$8,881"]);
    expect(textOf(page.document.querySelector("#og-o-day"))).toBe("1,000,000");
    expect(page.document.querySelector("#og-s-day").getAttribute("aria-valuetext")).toBe("1,000,000");
  });

  it("move the results with the turns: 10 turns gives 1.48 B tokens", () => {
    const page = session();
    page.setTurns(10);
    const want = expected({ ...SONNET, turns: 10 });
    expect([page.out("tokens"), page.out("usd-list"), page.out("usd-cache")]).toEqual([want.tokens, want.list, want.cached]);
    expect([page.out("tokens"), page.out("usd-list"), page.out("usd-cache")]).toEqual(["1.48 B", "$2,960", "$296"]);
    expect(textOf(page.document.querySelector("#og-o-turns"))).toBe("10");
  });

  it("show the visitor's own scenario in the chart, scaled against the five fixed stops", () => {
    const page = session();
    page.setDay(100000);
    expect(widths(page.you())).toEqual(["0.1000", "0.0100"]);
    expect(amounts(page.you())).toEqual(["$8,881", "$888"]);
    page.setDay(100);
    expect(widths(page.you())).toEqual(["0.0001", "0.0000"]);
    expect(amounts(page.you())).toEqual(["$8.88", "$0.89"]);
  });

  it("re-price every chart row when the turns change, and keep their widths in proportion", () => {
    const page = session();
    page.setTurns(1);
    const rows = page.stops();
    expect(rows.map(amounts)).toEqual([
      ["$2.96", "$0.30"],
      ["$29.60", "$2.96"],
      ["$296", "$29.60"],
      ["$2,960", "$296"],
      ["$29,605", "$2,960"],
    ]);
    expect(rows.map((row) => widths(row)[0])).toEqual(["0.0001", "0.0010", "0.0100", "0.1000", "1.0000"]);
  });

  it("format for the page's language: 444 亿 tokens at a million a day on the Chinese page", () => {
    const page = session("zh-CN");
    expect(page.out("tokens")).toBe("4.44 亿");
    page.setDay(1000000);
    expect(page.out("tokens")).toBe("444 亿");
    expect(page.out("tokens")).toBe(expected({ ...SONNET, perDay: 1000000 }, "zh-CN").tokens);
  });
});

describe("the model choice", () => {
  it("prices Opus at 1,776 dollars with the same 88.81 cache read", () => {
    const page = session();
    page.pick("opus-5-5");
    expect([page.out("usd-list"), page.out("usd-cache")]).toEqual(["$1,776", "$88.81"]);
    expect([page.out("p-list"), page.out("p-cache")]).toEqual(["$4.00", "$0.20"]);
    const rows = [...page.document.querySelectorAll("tbody tr")];
    expect(rows.map((row) => row.dataset.selected)).toEqual(["false", "true", "false"]);
  });

  it("gives Haiku the same figure both ways, shows why, and takes it away again", () => {
    const page = session();
    const note = page.document.querySelector("[data-out=same-price]");
    expect(note.hidden).toBe(true);
    page.pick("haiku-4-5");
    expect([page.out("usd-list"), page.out("usd-cache")]).toEqual(["$444", "$444"]);
    expect([page.out("p-list"), page.out("p-cache")]).toEqual(["$1.00", "$1.00"]);
    expect(note.hidden).toBe(false);
    expect(page.stops().map((row) => widths(row)[0])).toEqual(page.stops().map((row) => widths(row)[1]));
    page.pick("sonnet-5-5");
    expect(note.hidden).toBe(true);
    expect(page.out("usd-cache")).toBe("$88.81");
  });
});

describe("keyboard and assistive tech", () => {
  it("uses native sliders and radios in a labelled group, none taken out of the tab order", () => {
    const { document } = session();
    const inputs = [...document.querySelectorAll("[data-calculator] input")];
    expect(inputs.map((input) => input.type)).toEqual(["range", "range", "radio", "radio", "radio"]);
    for (const input of inputs) {
      expect(input.tabIndex, input.id).toBeGreaterThanOrEqual(0);
      expect(input.closest("[hidden]"), input.id).toBeNull();
    }
    expect(document.querySelector("fieldset legend")).not.toBeNull();
    for (const id of ["og-s-day", "og-s-turns"]) {
      expect(document.querySelector(`label[for="${id}"] output`).getAttribute("for")).toBe(id);
    }
  });

  it("announces results politely and hides decorative swatches", () => {
    const { document } = session();
    expect(document.querySelector(".og-saved").getAttribute("aria-live")).toBe("polite");
    for (const swatch of document.querySelectorAll(".og-sw")) {
      expect(swatch.getAttribute("aria-hidden")).toBe("true");
    }
  });
});

describe("what the calculator keeps to itself", () => {
  const read = (name) => readFileSync(join(REAL_WEB, name), "utf8");

  it("sends nothing and stores nothing: its source has no network, storage or cookie call", () => {
    for (const file of ["src/calculator.ts", "src/savings-provider.ts", "src/savings.ts"]) {
      expect(read(file), file).not.toMatch(/fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|cookie|WebSocket/);
    }
  });

  it("shares one formatter with the build: both import src/format.ts, and nothing else rounds money", () => {
    expect(read("src/calculator.ts")).toContain('from "./format.ts"');
    expect(read("scripts/fragments.mjs")).toContain('from "../src/format.ts"');
    for (const file of ["src/calculator.ts", "src/savings-provider.ts", "scripts/fragments.mjs"]) {
      expect(read(file), file).not.toMatch(/Intl\.NumberFormat|toLocaleString|toFixed|toPrecision/);
    }
  });
});

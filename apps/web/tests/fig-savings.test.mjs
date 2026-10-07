import { readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { REAL_WEB, buildPages, readCopy, textOf } from "./page-helpers.mjs";

const LANGS = ["en", "zh-CN"];
const APPROVED = {
  en: {
    noscript: "Showing 10,000 conversations a day, 3 turns each, Claude Sonnet 5.5.",
    perMonth: "Per month, 30 days",
    haikuNote: "Haiku 4.5 can’t cache a prompt this short, so this figure equals the list price.",
    fineHaiku:
      "Haiku 4.5 can’t cache a prompt this short (minimum 4,096 tokens), so its two figures match. Cache writes are not counted.",
  },
  "zh-CN": {
    noscript: "当前显示：每天 10,000 次对话、每次 3 轮、Claude Sonnet 5.5。",
    perMonth: "每月，按 30 天算",
    haikuNote: "Haiku 4.5 缓存不了这么短的提示词，所以这里和按标价算的结果相同。",
    fineHaiku:
      "Haiku 4.5 缓存不了这么短的提示词（最低 4,096 token），所以它的两种口径相同。缓存写入费用没有计入。",
  },
};
const pages = buildPages();
const pricing = JSON.parse(readFileSync(`${REAL_WEB}/data/pricing.json`, "utf8"));

function editJson(webDir, file, change) {
  const path = `${webDir}/data/${file}`;
  const doc = JSON.parse(readFileSync(path, "utf8"));
  change(doc);
  writeFileSync(path, JSON.stringify(doc));
}

const section = (built, lang = "en") => built.doc(lang).querySelector("#savings");
const out = (built, name, lang = "en") => textOf(section(built, lang).querySelector(`[data-out="${name}"]`));
const widths = (root) =>
  [...root.querySelectorAll("[data-role=stop]")].map((row) =>
    [...row.querySelectorAll("i")].map((bar) => Number(/--w:([\d.]+)/.exec(bar.getAttribute("style"))[1])),
  );
const labels = (root) =>
  [...root.querySelectorAll("[data-role=stop]")].map((row) => textOf(row.querySelector(".og-sl")));
const amounts = (row) => [...row.querySelectorAll("[data-v]")].map(textOf);

describe("figure three, with no script", () => {
  it("shows the default scenario: 444 M tokens, $888 at list price, $88.81 with caching", () => {
    expect(out(pages, "tokens")).toBe("444 M");
    expect(out(pages, "usd-list")).toBe("$888");
    expect(out(pages, "usd-cache")).toBe("$88.81");
    expect([out(pages, "p-list"), out(pages, "p-cache")]).toEqual(["$2.00", "$0.20"]);
    expect(out(pages, "tokens", "zh-CN")).toBe("4.44 亿");
    expect(out(pages, "usd-list", "zh-CN")).toBe("$888");
  });

  it("names the tiles and the recipe from the copy in both languages", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const root = section(pages, lang);
      expect(textOf(root.querySelector("h2")), lang).toBe(copy["savings.title"]);
      expect([...root.querySelectorAll(".og-tn")].map(textOf), lang).toEqual([copy["calc.list_price"], copy["calc.cached"]]);
      expect(textOf(root.querySelector(".og-tag")), lang).toBe(copy["calc.tag"]);
      expect(textOf(root.querySelector(".og-calc h3")), lang).toBe(`${copy["calc.title"]} ${copy["calc.tag"]}`);
    }
  });

  it("derives 507 × 0.97 ≈ 493 from the data, rounding only for display", () => {
    for (const lang of LANGS) {
      const cards = [...section(pages, lang).querySelectorAll(".og-rc")];
      expect(cards.map((card) => textOf(card.querySelector("b"))), lang).toEqual(["507", "0.97", "≈ 493"]);
    }
    expect(textOf(section(pages).querySelector(".og-rc em"))).toBe("526 − 19");
    const copy = readCopy("en");
    expect([...section(pages).querySelectorAll(".og-rc span")].map(textOf)).toEqual([
      copy["savings.per_call"],
      copy["savings.calls_per_turn"],
      copy["savings.per_turn"],
    ]);
  });

  it("draws one row per chart stop, widths relative to the biggest, two bars each", () => {
    const root = section(pages);
    expect(labels(root)).toEqual(["100", "1,000", "10,000", "100,000", "1,000,000"]);
    const bars = widths(root);
    expect(bars.map(([list]) => list)).toEqual([0.0001, 0.001, 0.01, 0.1, 1]);
    expect(bars[4]).toEqual([1, 0.1]);
    const rows = [...root.querySelectorAll("[data-role=stop]")];
    expect(rows.map(amounts)).toEqual([
      ["$8.88", "$0.89"],
      ["$88.81", "$8.88"],
      ["$888", "$88.81"],
      ["$8,881", "$888"],
      ["$88,815", "$8,881"],
    ]);
  });

  it("tells assistive tech which bar is which without a legend", () => {
    const copy = readCopy("en");
    const row = section(pages).querySelector("[data-role=stop]");
    expect([...row.querySelectorAll(".og-sb b")].map(textOf)).toEqual([
      `${copy["calc.list_price"]}: $8.88`,
      `${copy["calc.cached"]}: $0.89`,
    ]);
    expect(section(pages).querySelector('[class*="legend"]')).toBeNull();
    expect(section(pages).querySelector(".og-per")).toBeNull();
  });

  it("keeps the your-scenario row hidden until a script shows it", () => {
    const you = section(pages).querySelector("[data-role=you]");
    expect(you.hasAttribute("hidden")).toBe(true);
    expect(textOf(you.querySelector(".og-sl"))).toBe(readCopy("en")["calc.scenario"]);
  });

  it("hides the controls and says which scenario is on show, with 3 turns", () => {
    for (const lang of LANGS) {
      const root = section(pages, lang);
      expect(root.querySelector("[data-role=controls]").hasAttribute("hidden"), lang).toBe(true);
      expect(textOf(root.querySelector("[data-role=nojs-note]")), lang).toBe(APPROVED[lang].noscript);
    }
  });

  it("prepares the controls: stop 6 of 12, turn 3 of 10, Sonnet checked, labelled and grouped", () => {
    const root = section(pages);
    const day = root.querySelector("#og-s-day");
    const turns = root.querySelector("#og-s-turns");
    expect([day, turns].map((node) => [node.type, node.min, node.max, node.value])).toEqual([
      ["range", "0", "12", "6"],
      ["range", "1", "10", "3"],
    ]);
    expect(day.getAttribute("aria-valuetext")).toBe("10,000");
    expect(root.querySelector('label[for="og-s-day"] output').getAttribute("for")).toBe("og-s-day");
    const radios = [...root.querySelectorAll('input[name="og-model"]')];
    expect(radios.map((radio) => [radio.value, radio.checked])).toEqual([
      ["sonnet-5-5", true],
      ["opus-5-5", false],
      ["haiku-4-5", false],
    ]);
    expect(textOf(root.querySelector("fieldset legend"))).toBe(readCopy("en")["calc.model"]);
    expect([...root.querySelectorAll(".og-opt")].map(textOf)).toEqual(["Sonnet 5.5", "Opus 5.5", "Haiku 4.5"]);
  });
});

describe("the caching reminder and the Haiku note", () => {
  it("puts the reminder right under the two result cards and outside the fold", () => {
    for (const lang of LANGS) {
      const root = section(pages, lang);
      const note = root.querySelector(".og-cachenote");
      expect(textOf(note), lang).toBe(readCopy(lang)["calc.caching_note"]);
      expect(note.previousElementSibling.className).toBe("og-tiles");
      expect(note.closest("details")).toBeNull();
    }
  });

  it("holds the approved note for Haiku, hidden while Sonnet is on show", () => {
    for (const lang of LANGS) {
      const note = section(pages, lang).querySelector("[data-out=same-price]");
      expect(note.hasAttribute("hidden"), lang).toBe(true);
      expect(textOf(note), lang).toBe(APPROVED[lang].haikuNote);
      expect(textOf(note), lang).not.toMatch(/PLACEHOLDER/);
    }
  });

  it("shows the note, and the same figure twice, when Haiku is the default", () => {
    const built = buildPages((webDir) => editJson(webDir, "pricing.json", (doc) => (doc.default = "haiku-4-5")));
    expect(out(built, "usd-list")).toBe("$444");
    expect(out(built, "usd-cache")).toBe("$444");
    expect(section(built).querySelector("[data-out=same-price]").hasAttribute("hidden")).toBe(false);
    expect(section(built).querySelector('input[value="haiku-4-5"]').checked).toBe(true);
  });
});

describe("the fold", () => {
  const closed = (lang) => section(pages, lang).querySelector("details");

  it("is closed by default and holds the price table and the five small prints", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const fold = closed(lang);
      expect(fold.hasAttribute("open"), lang).toBe(false);
      expect(textOf(fold.querySelector("summary")), lang).toBe(copy["method.title"]);
      expect([...fold.querySelectorAll(".og-fine li")].map(textOf), lang).toEqual(
        ["what_if", "caching", "haiku", "input_only", "no_speed_claim"].map((key) =>
          key === "haiku" ? APPROVED[lang].fineHaiku : copy[`fine.${key}`],
        ),
      );
    }
  });

  it("lists the three prices from pricing.json and marks the default model", () => {
    const rows = [...closed("en").querySelectorAll("tbody tr")];
    expect(rows.map((row) => [...row.children].map(textOf))).toEqual([
      ["Claude Sonnet 5.5", "$2.00", "$0.20"],
      ["Claude Opus 5.5", "$4.00", "$0.20"],
      ["Claude Haiku 4.5", "$1.00", "$0.10"],
    ]);
    expect(rows.map((row) => row.dataset.selected)).toEqual(["true", "false", "false"]);
    expect(textOf(closed("en").querySelector(".og-figcap"))).toContain(pricing.accessed);
  });

  it("keeps everything else visible: only the reminder and the cards sit outside it", () => {
    const outside = section(pages).cloneNode(true);
    outside.querySelector("details").remove();
    expect(textOf(outside)).not.toContain(readCopy("en")["fine.what_if"]);
    expect(textOf(outside)).toContain(readCopy("en")["calc.caching_note"]);
  });
});

describe("the page follows its data", () => {
  it("re-prices when pricing.json changes: Opus as default at 5 dollars, dearer cache read", () => {
    const built = buildPages((webDir) =>
      editJson(webDir, "pricing.json", (doc) => {
        doc.default = "opus-5-5";
        doc.models[1].input = 5;
        doc.models[1].cache_read = 0.5;
      }),
    );
    expect(out(built, "usd-list")).toBe("$2,220");
    expect(out(built, "usd-cache")).toBe("$222");
    expect([out(built, "p-list"), out(built, "p-cache")]).toEqual(["$5.00", "$0.50"]);
    const rows = [...section(built).querySelectorAll("tbody tr")];
    expect([...rows[1].children].map(textOf)).toEqual(["Claude Opus 5.5", "$5.00", "$0.50"]);
    expect(rows.map((row) => row.dataset.selected)).toEqual(["false", "true", "false"]);
  });

  it("re-counts when the benchmarks change: 600.4 saved per turn, 0.5 calls per turn", () => {
    const built = buildPages((webDir) =>
      editJson(webDir, "benchmarks.json", (doc) => {
        doc.composition.saved_per_turn = 600.4;
        doc.composition.calls_per_case = 0.5;
      }),
    );
    const cards = [...section(built).querySelectorAll(".og-rc b")].map(textOf);
    expect(cards).toEqual(["507", "0.50", "≈ 600"]);
    expect(out(built, "tokens")).toBe("540 M");
    expect(out(built, "usd-list")).toBe("$1,081");
  });

  it("draws as many rows as there are chart stops", () => {
    const built = buildPages((webDir) =>
      editJson(webDir, "pricing.json", (doc) => {
        doc.calculator.chart_stops = [1000, 10000];
      }),
    );
    expect(labels(section(built))).toEqual(["1,000", "10,000"]);
    expect(widths(section(built))[0]).toEqual([0.1, 0.01]);
  });

  it("refuses a default volume that is not a slider stop", () => {
    expect(() =>
      buildPages((webDir) => editJson(webDir, "pricing.json", (doc) => (doc.calculator.default_per_day = 1234))),
    ).toThrow(/1234 conversations a day is not one of the slider stops/);
  });
});

describe("what the section does not say", () => {
  it("has no accuracy figure, no red line and no speed claim outside the approved disclaimer", () => {
    for (const lang of LANGS) {
      const root = section(pages, lang).cloneNode(true);
      root.querySelector(".og-fine li:last-child").remove();
      expect(textOf(root), lang).not.toMatch(/accura|准确|red.?line|红线|faster|更快/i);
    }
  });

  it("styles a stacked layout on a narrow screen and a quiet one for reduced motion", () => {
    const css = pages.css();
    expect(css).toMatch(/@media \(max-width:820px\)\{[^@]*\.og-calc\{grid-template-columns:1fr[;}]/);
    expect(css).toMatch(/@media \(prefers-reduced-motion:reduce\)\{[^}]*transition:none!important/);
    expect(css).toMatch(/\.og-srow\[hidden\]/);
    expect(css).toMatch(/\.og-ctl>label/);
    expect(css).not.toMatch(/\.og-ctl label/);
  });

  it("paints bars and swatches with theme tokens, never a fixed colour", () => {
    const html = pages.html("en");
    const start = html.indexOf('id="savings"');
    const fragment = html.slice(start, html.indexOf("</section>", start));
    expect(fragment).not.toMatch(/#[0-9A-Fa-f]{3,8}\b/);
    expect(fragment).not.toMatch(/fill="|stroke="/);
  });
});

describe("the words that repeat a number or a model name from the data", () => {
  it("read exactly as approved while the data is unchanged", () => {
    for (const lang of LANGS) {
      const label = textOf(section(pages, lang).querySelector(".og-saved .og-lbl2"));
      expect(label, lang).toBe(`${readCopy(lang)["calc.tokens_saved"]} · ${APPROVED[lang].perMonth}`);
    }
  });

  it("follow the data when it changes: volume, default model, days and the Haiku limit", () => {
    const built = buildPages((webDir) =>
      editJson(webDir, "pricing.json", (doc) => {
        doc.calculator.default_per_day = 5000;
        doc.calculator.days_per_month = 31;
        doc.default = "opus-5-5";
        doc.models[2].short = "Haiku 4.6";
        doc.models[2].min_cacheable = 8192;
      }),
    );
    const en = section(built, "en");
    expect(textOf(en.querySelector("[data-role=nojs-note]"))).toBe(
      "Showing 5,000 conversations a day, 3 turns each, Claude Opus 5.5.",
    );
    expect(textOf(en.querySelector(".og-saved .og-lbl2"))).toContain("Per month, 31 days");
    expect([...en.querySelectorAll(".og-fine li")].map(textOf)[2]).toBe(
      "Haiku 4.6 can’t cache a prompt this short (minimum 8,192 tokens), so its two figures match. Cache writes are not counted.",
    );
    expect(textOf(section(built, "zh-CN").querySelector("[data-role=nojs-note]"))).toBe(
      "当前显示：每天 5,000 次对话、每次 3 轮、Claude Opus 5.5。",
    );
    expect(textOf(section(built, "zh-CN").querySelector(".og-saved .og-lbl2"))).toContain("每月，按 31 天算");
  });

  it("fail the build when a copy placeholder is left without a value", () => {
    expect(() =>
      buildPages((webDir) => {
        const path = `${webDir}/sections/30-fig-savings.html`;
        writeFileSync(path, readFileSync(path, "utf8").replace("|model=savings.modelName", ""));
      }),
    ).toThrow(/\{model\}/);
  });
});

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REAL_WEB, buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const LANGS = ["en", "zh-CN"];
const SMALL_MODEL_SENTENCE =
  "We picked a small model (1.7 billion parameters) on purpose: our hardware is limited, and this size is the compromise that lets us train and serve it ourselves.";
const MODEL_NAME = "Qwen3 1.7B";
const MU_ARXIV = "https://arxiv.org/abs/2304.08467";
const SHOPIFY_ARTICLE = "https://shopify.engineering/gisting";

const grid = (lang) => pages.doc(lang).querySelector("#rules .og-a3");
const card = (lang) => grid(lang).querySelector(".og-train");
const links = JSON.parse(readFileSync(join(REAL_WEB, "data", "links.json"), "utf8"));

describe("the rules block and the training card", () => {
  it("sit side by side in one two-column grid, the two folded cards on the left", () => {
    for (const lang of LANGS) {
      const [left, right] = grid(lang).children;
      expect(left.classList.contains("og-a3l"), lang).toBe(true);
      expect(left.querySelectorAll(":scope > details"), lang).toHaveLength(2);
      expect(right.classList.contains("og-train"), lang).toBe(true);
      expect(grid(lang).children, lang).toHaveLength(2);
    }
  });

  it("stacks into one column on narrow screens", () => {
    const css = pages.css();
    expect(css).toMatch(/@media \(max-width:820px\)\{[^}]*\.og-a3\{grid-template-columns:1fr\}/);
  });
});

describe("the training card", () => {
  it("has the approved title and three steps in order: teacher, distil, filter and test", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      expect(textOf(card(lang).querySelector("h3")), lang).toBe(copy["train.title"]);
      const steps = [...card(lang).querySelectorAll(".og-steps > li")];
      expect(steps.map((step) => textOf(step.querySelector("b"))), lang).toEqual([
        copy["train.teacher"],
        copy["train.distil"],
        copy["train.filter"],
      ]);
      expect(steps.map((step) => textOf(step.querySelector("b + p"))), lang).toEqual([
        copy["train.teacher_text"],
        copy["train.distil_text"],
        copy["train.filter_text"],
      ]);
      expect(steps.map((step) => textOf(step.querySelector(".og-sn"))), lang).toEqual(["1", "2", "3"]);
    }
  });

  it("says that only the 16 gist tokens are trained: 16 × 2048 = 32,768", () => {
    const text = textOf(card("en").querySelectorAll(".og-steps > li")[1]);
    expect(text).toContain("16 × 2048 = 32,768");
    expect(textOf(card("zh-CN").querySelectorAll(".og-steps > li")[1])).toContain("16 × 2048 = 32,768");
  });

  it("proves the model itself did not change: the fingerprint line, with a check mark", () => {
    for (const lang of LANGS) {
      const proof = card(lang).querySelector(".og-steps .og-proof");
      expect(textOf(proof), lang).toBe(readCopy(lang)["train.fingerprint"]);
      expect(proof.querySelector("svg").getAttribute("aria-hidden"), lang).toBe("true");
    }
    expect(readCopy("zh-CN")["train.fingerprint"]).toBe("模型参数指纹：训练前后一致");
  });

  it("counts the rules before and after from the data, not from typed numbers", () => {
    const steps = [...card("en").querySelectorAll(".og-steps > li")];
    expect(textOf(steps[0].querySelector(".og-num"))).toBe("526 tokens");
    expect(textOf(steps[1].querySelector(".og-num"))).toBe("19 tokens");
    expect(card("en").querySelectorAll(".og-gt i")).toHaveLength(16);
  });

  it("keeps every drawing out of the reading order", () => {
    for (const lang of LANGS) {
      for (const selector of [".og-doc", ".og-gt", ".og-rl", ".og-why svg", ".og-tic"]) {
        for (const node of card(lang).querySelectorAll(selector)) {
          expect(node.getAttribute("aria-hidden"), `${lang} ${selector}`).toBe("true");
        }
      }
    }
  });

  it("holds the approved small-model sentence word for word in English", () => {
    expect(readCopy("en")["train.small_model"]).toBe(SMALL_MODEL_SENTENCE);
    expect(textOf(card("en").querySelector(".og-why span"))).toBe(SMALL_MODEL_SENTENCE);
    expect(textOf(card("zh-CN").querySelector(".og-why span"))).toBe(readCopy("zh-CN")["train.small_model"]);
  });

  it("hides the write-up link and keeps the Shopify credit while the research link is empty", () => {
    expect(links.research_article).toBe("");
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const row = card(lang).querySelector(".og-trl");
      expect(row.querySelector(".og-btn"), lang).toBeNull();
      expect(row.children, lang).toHaveLength(1);
      expect(textOf(row), lang).toBe(`${copy["train.credit"]} ${copy["train.credit_link"]}`);
      expect(pages.html(lang), lang).not.toContain(copy["train.writeup"]);
    }
  });

  it("links the write-up from the research-article link file once it has an address", () => {
    const address = "https://www.myagenthubs.com/research/gisting";
    const linked = buildPages((webDir) => writeFileSync(join(webDir, "data", "links.json"), JSON.stringify({ research_article: address })));
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const row = linked.doc(lang).querySelector("#rules .og-a3 .og-train .og-trl");
      const [writeup, credit] = [...row.children];
      expect(textOf(writeup), lang).toBe(copy["train.writeup"]);
      expect(writeup.getAttribute("href"), lang).toBe(address);
      expect(textOf(credit), lang).toBe(`${copy["train.credit"]} ${copy["train.credit_link"]}`);
      const source = credit.querySelector("a");
      expect(source.getAttribute("href"), lang).toBe(SHOPIFY_ARTICLE);
      expect(source.getAttribute("rel"), lang).toContain("noopener");
      expect(textOf(source), lang).toBe("shopify.engineering/gisting");
    }
  });

  it("names Wingate et al. 2022 as the first proposal and Mu et al. 2023 as the development, with the arXiv link", () => {
    for (const lang of LANGS) {
      const refs = card(lang).querySelector(".og-refs");
      const text = textOf(refs);
      expect(text, lang).toContain("Wingate");
      expect(text, lang).toContain("Mu");
      expect(text.indexOf("Wingate"), lang).toBeLessThan(text.indexOf("Mu"));
      expect(text, lang).toContain("2022");
      expect(text, lang).toContain("2023");
      const paper = refs.querySelector("a");
      expect(paper.getAttribute("href"), lang).toBe(MU_ARXIV);
      expect(paper.getAttribute("rel"), lang).toContain("noopener");
      expect(textOf(paper), lang).toBe("arXiv:2304.08467");
    }
  });

  it("never credits Mu et al. with inventing the idea", () => {
    const invented = /(Mu|Mu et al\.?)[^.]{0,40}(invented|first proposed|originated)|(invented|first proposed|originated)[^.]{0,40}Mu\b/i;
    for (const lang of LANGS) {
      expect(readCopy(lang)["train.refs"], lang).not.toMatch(invented);
    }
    expect("Mu et al. first proposed it").toMatch(invented);
  });

  it("publishes the approved citation line", () => {
    for (const lang of LANGS) {
      expect(readCopy(lang)["train.refs"], lang).not.toMatch(/PLACEHOLDER/);
    }
  });

  it("shows no accuracy figure and no red-line number, and names no machine", () => {
    for (const lang of LANGS) {
      const text = textOf(card(lang));
      expect(text, lang).not.toMatch(/%|accuracy|准确率|\b0 \/ \d|\bMac\b|faster|更快/i);
      expect(text, lang).not.toMatch(/\d+ \/ \d+/);
    }
  });
});

describe("Qwen3 1.7B", () => {
  it("is named in the hero fact strip, the training card and the agent node of figure one", () => {
    for (const lang of LANGS) {
      const doc = pages.doc(lang);
      const places = {
        hero: doc.querySelector(".og-facts"),
        training: card(lang),
        figure: [...doc.querySelectorAll("#real .og-node")].find((node) => textOf(node).includes(readCopy(lang)["real.agent"])),
      };
      for (const [name, place] of Object.entries(places)) {
        expect(textOf(place), `${lang} ${name}`).toContain(MODEL_NAME);
      }
    }
  });
});

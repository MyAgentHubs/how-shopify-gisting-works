import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();

describe("the hero", () => {
  it("carries the approved English title, subtitle and three buttons", () => {
    const copy = readCopy("en");
    const doc = pages.doc("en");
    const titles = [...doc.querySelectorAll("h1")];
    expect(titles).toHaveLength(1);
    expect(textOf(titles[0])).toBe(copy["hero.title"]);
    expect(textOf(titles[0])).toBe("OpenGisting — Shopify’s Gisting, reproduced in the open");
    const lead = textOf(doc.querySelector(".og-hero .og-lead"));
    expect(lead).toBe(copy["hero.subtitle"]);
    expect(lead).toContain("16 tokens");
    const buttons = [...doc.querySelectorAll(".og-hero .og-cta a")];
    expect(buttons.map((a) => [textOf(a), a.getAttribute("href")])).toEqual([
      [copy["hero.cta_try"], "#agent"],
      [copy["hero.cta_real"], "#real"],
      [copy["hero.cta_writeup"], "https://shopify.engineering/gisting"],
    ]);
  });

  it("says the order note once in the hero and gives the three states a legend", () => {
    const copy = readCopy("en");
    const doc = pages.doc("en");
    expect(textOf(doc.querySelector(".og-hero .og-lead2"))).toBe(copy["chat.note_orders"]);
    const rows = [...doc.querySelectorAll(".og-stamps li")];
    expect(rows.map((row) => textOf(row))).toEqual([
      `${copy["state.real"]} ${copy["state.real_legend"]}`,
      `${copy["state.test"]} ${copy["state.test_legend"]}`,
      `${copy["state.demo"]} ${copy["state.demo_legend"]}`,
    ]);
    expect(rows.map((row) => row.querySelector(".og-mk").className)).toEqual([
      "og-mk og-real",
      "og-mk og-test",
      "og-mk og-demo",
    ]);
  });

  it("has a fact strip of four cells that starts with the model name", () => {
    for (const lang of ["en", "zh-CN"]) {
      const copy = readCopy(lang);
      const cells = [...pages.doc(lang).querySelectorAll(".og-facts li")].map(textOf);
      expect(cells, lang).toEqual([
        copy["fact.model"],
        copy["fact.gist_tokens"],
        copy["fact.rules"],
        copy["fact.open_source"],
      ]);
      expect(cells[0]).toBe("Qwen3 1.7B");
    }
    expect([...pages.doc("en").querySelectorAll(".og-facts li")].map(textOf)).toEqual([
      "Qwen3 1.7B",
      "16 gist tokens",
      "rules 526 → 19 tokens",
      "open source (in preparation)",
    ]);
  });

  it("shows open source as plain text, never as a link or a button", () => {
    for (const lang of ["en", "zh-CN"]) {
      const doc = pages.doc(lang);
      const copy = readCopy(lang);
      const tag = doc.querySelector(".og-tag");
      expect(tag.tagName).toBe("SPAN");
      expect(textOf(tag)).toBe(copy["hero.open_source"]);
      expect(tag.closest("a,button")).toBeNull();
      expect(pages.html(lang)).not.toMatch(/github\.com/i);
    }
  });

  it("renders the Chinese page in Chinese with the same structure", () => {
    const copy = readCopy("zh-CN");
    const doc = pages.doc("zh-CN");
    expect(textOf(doc.querySelector("h1"))).toBe(copy["hero.title"]);
    expect(doc.querySelectorAll(".og-facts li")).toHaveLength(4);
    expect(doc.querySelectorAll(".og-stamps li")).toHaveLength(3);
  });

  it("brings no site header of its own, on any page", () => {
    for (const lang of ["en", "zh-CN", "ja", "ko"]) {
      const html = pages.html(lang);
      expect(html, lang).not.toContain("header.mh-global");
      expect(html).not.toContain("mh-global");
      expect(html).not.toContain("<header");
    }
  });

  it("is also the first thing on the ja and ko pages, in English", () => {
    for (const lang of ["ja", "ko"]) {
      expect(textOf(pages.doc(lang).querySelector("h1"))).toBe(readCopy("en")["hero.title"]);
    }
  });
});

describe("hooks that www rewrites", () => {
  const hits = (doc) => doc.querySelectorAll(".hero .eyebrow, .eyebrow").length;

  it("never pairs a hero ancestor with an eyebrow, in markup or in style", () => {
    for (const lang of ["en", "zh-CN", "ja", "ko"]) {
      expect(hits(pages.doc(lang)), lang).toBe(0);
    }
    expect(pages.css()).not.toMatch(/\.hero[^{}]*\.eyebrow/);
  });

  it("sees the pairing when a page has it", () => {
    const bad = new JSDOM('<section class="hero"><p class="eyebrow">x</p></section>');
    expect(hits(bad.window.document)).toBe(1);
  });
});

import { describe, expect, it } from "vitest";
import { buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const LANGS = ["en", "zh-CN"];
const KEYS = [
  "privacy.ip",
  "privacy.counters",
  "privacy.totals",
  "privacy.chat",
  "privacy.not_collected",
  "privacy.processors",
  "privacy.turnstile",
  "privacy.logs",
];
const RETIRED = /Benchmarks/i;

const section = (lang) => pages.doc(lang).querySelector("#privacy");
const cards = (lang) => [...section(lang).querySelectorAll(".og-pv > li")];

describe("the privacy block", () => {
  it("is numbered, headed by the approved sentence and labelled by it", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      expect(textOf(section(lang).querySelector(".og-kicker")), lang).toBe("6");
      const heading = section(lang).querySelector("h2");
      expect(textOf(heading), lang).toBe(copy["privacy.title"]);
      expect(section(lang).getAttribute("aria-labelledby"), lang).toBe(heading.id);
    }
    expect(readCopy("en")["privacy.title"]).toBe("What OpenGisting keeps, and what it doesn’t.");
  });

  it("has one card for each privacy key, word for word and in the approved order", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      expect(cards(lang).map((card) => textOf(card.querySelector("p"))), lang).toEqual(
        KEYS.map((key) => copy[key]),
      );
    }
  });

  it("puts the bot-check card right after the processors card", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const texts = cards(lang).map((card) => textOf(card.querySelector("p")));
      expect(texts.indexOf(copy["privacy.turnstile"]), lang).toBe(texts.indexOf(copy["privacy.processors"]) + 1);
    }
  });

  it("gives each card a text-free icon that screen readers skip", () => {
    for (const lang of LANGS) {
      expect(cards(lang), lang).toHaveLength(KEYS.length);
      for (const card of cards(lang)) {
        const icon = card.querySelector(".og-pic");
        expect(icon.getAttribute("aria-hidden"), lang).toBe("true");
        expect(icon.querySelectorAll("svg"), lang).toHaveLength(1);
        expect(textOf(icon), lang).toBe("");
        expect(icon.querySelector("svg").getAttribute("focusable"), lang).toBe("false");
        expect(card.children, lang).toHaveLength(2);
      }
    }
  });

  it("does not use the retired Benchmarks name anywhere on the page", () => {
    for (const lang of LANGS) {
      expect(pages.html(lang), lang).not.toMatch(RETIRED);
    }
    expect("See the Benchmarks block").toMatch(RETIRED);
    expect("benchmarks").toMatch(RETIRED);
  });

  it("lays the cards in two columns, one on a narrow screen", () => {
    const css = pages.css();
    expect(css).toMatch(/\.og-pv\{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
    expect(css).toMatch(/@media \(max-width:820px\)\{[^}]*\.og-pv\{grid-template-columns:minmax\(0,1fr\)\}/);
  });
});

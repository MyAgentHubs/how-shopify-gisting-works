import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REAL_WEB, buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const LANGS = ["en", "zh-CN"];
const SHOPIFY_ARTICLE = "https://shopify.engineering/gisting";
const ORIGIN = "https://www.myagenthubs.com";
const DISCLAIMER_EN =
  "Independent reproduction of Shopify Engineering’s Gisting method. Not affiliated with Shopify.";
const SEVEN_DIVIDERS = 7;

const footer = (lang) => pages.doc(lang).querySelector("body > footer");
const noticeOf = (code) =>
  JSON.parse(readFileSync(join(REAL_WEB, "copy", `${code}.json`), "utf8")).strings["page.notice"];

describe("the page footer", () => {
  it("is written without any words of its own: the template and the fragment hold only tags and directives", () => {
    for (const file of ["index.html", "footer.html"]) {
      const source = readFileSync(join(REAL_WEB, file), "utf8");
      const words = source
        .replace(/<[^>]*>/g, "")
        .replace(/\{\{[^{}]*\}\}/g, "")
        .replace(/%[A-Z_]+%/g, "")
        .trim();
      expect(words, file).toBe("");
    }
  });

  it("sits after the main content as the page footer, with the MyAgentHubs brand link kept", () => {
    for (const lang of LANGS) {
      const doc = pages.doc(lang);
      expect(footer(lang), lang).not.toBeNull();
      expect(doc.querySelector("main footer"), lang).toBeNull();
      expect(doc.querySelector("main").nextElementSibling, lang).toBe(doc.querySelector("body > footer"));
      const brand = doc.querySelectorAll("body > footer a.mh-footer-brand");
      expect(brand, lang).toHaveLength(1);
      expect(brand[0].getAttribute("href"), lang).toBe(`${ORIGIN}/`);
      expect(textOf(brand[0]), lang).toBe("MyAgentHubs");
    }
  });

  it("carries the approved disclaimer, in the page language", () => {
    for (const lang of LANGS) {
      const note = footer(lang).querySelector(".og-disc");
      expect(textOf(note), lang).toBe(readCopy(lang)["footer.disclaimer"]);
    }
    expect(textOf(footer("en").querySelector(".og-disc"))).toBe(DISCLAIMER_EN);
    expect(textOf(footer("en").querySelector(".og-disc"))).toMatch(/^Independent reproduction .* Not affiliated with Shopify\.$/);
  });

  it("says the code is being prepared in a plain span, with no repository link anywhere", () => {
    for (const lang of LANGS) {
      const tag = footer(lang).querySelector(".og-soon");
      expect(tag.tagName, lang).toBe("SPAN");
      expect(textOf(tag), lang).toBe(readCopy(lang)["hero.open_source"]);
      expect(tag.closest("a"), lang).toBeNull();
      expect(pages.html(lang), lang).not.toMatch(/github\.com/i);
    }
    expect(textOf(footer("en").querySelector(".og-soon"))).toBe("Open source: being prepared");
  });

  it("links Shopify's write-up and the privacy heading", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const links = [...footer(lang).querySelectorAll("a:not(.mh-footer-brand)")];
      expect(links.map((a) => [textOf(a), a.getAttribute("href")]), lang).toEqual([
        [copy["hero.cta_writeup"], SHOPIFY_ARTICLE],
        [copy["privacy.title"], "#privacy"],
      ]);
      expect(links[0].getAttribute("rel"), lang).toContain("noopener");
      expect(textOf(pages.doc(lang).querySelector("#privacy h2")), lang).toBe(copy["privacy.title"]);
    }
  });

  it("keeps every footer link at least 44 px tall", () => {
    const css = pages.css();
    expect(css).toMatch(/\.og-ftr a\{[^}]*min-height:44px/);
  });
});

describe("the language notice on ja and ko", () => {
  it("is exactly one line, before the main content, in its own language", () => {
    for (const code of ["ja", "ko"]) {
      const doc = pages.doc(code);
      const notices = doc.querySelectorAll(".page-notice");
      expect(notices, code).toHaveLength(1);
      expect(textOf(notices[0]), code).toBe(noticeOf(code));
      expect(notices[0].getAttribute("lang"), code).toBe(code);
      expect(notices[0].getAttribute("role"), code).toBe("note");
      expect(notices[0].nextElementSibling, code).toBe(doc.querySelector("main"));
      expect(notices[0].textContent, code).not.toMatch(/\n/);
    }
  });

  it("is absent from the English and Chinese pages", () => {
    for (const lang of LANGS) {
      expect(pages.doc(lang).querySelectorAll(".page-notice"), lang).toHaveLength(0);
    }
  });

  it("is a calm tinted strip with the strong text colour, wrapping on a narrow screen", () => {
    const rule = pages.css().match(/\.page-notice\{([^}]*)\}/)[1];
    expect(rule).toContain("background:var(--accent-soft)");
    expect(rule).toContain("color:var(--ink)");
    expect(rule).not.toContain("position:fixed");
    expect(rule).not.toContain("position:sticky");
  });
});

describe("the page without scripts", () => {
  it("hides the chat window and the example buttons, and says the chat needs scripts", () => {
    for (const lang of LANGS) {
      const link = pages.doc(lang).querySelector("head noscript link");
      expect(link.getAttribute("rel"), lang).toBe("stylesheet");
      expect(link.getAttribute("href"), lang).toBe("/opengisting/noscript.css");
      const note = pages.doc(lang).querySelector("#agent noscript .og-nochat");
      expect(textOf(note), lang).toBe(readCopy(lang)["chat.noscript"]);
    }
  });

  it("ships a stylesheet that hides the window, the examples, and the sample-order list, and nothing else", () => {
    const css = readFileSync(join(pages.outDir, "opengisting", "noscript.css"), "utf8");
    expect(css.trim()).toBe(".og-win,.og-ex,.og-more{display:none}");
  });

  it.each(["en", "zh-CN", "ja", "ko"])("covers the built sample-order list with the shipped noscript rule in %s", (lang) => {
    const details = pages.doc(lang).querySelector("details.og-more");
    expect(details, lang).not.toBeNull();
    const css = readFileSync(join(pages.outDir, "opengisting", "noscript.css"), "utf8");
    const selectors = css.trim().split("{display:none}")[0].split(",");
    expect(selectors, lang).toContain(".og-more");
    expect(details.matches(".og-more"), lang).toBe(true);
  });

  it("publishes the approved chat sentence", () => {
    for (const lang of LANGS) {
      expect(readCopy(lang)["chat.noscript"], lang).not.toMatch(/PLACEHOLDER/);
    }
  });

  it("shows the calculator at its default scenario, already worked out, with the controls hidden", () => {
    for (const lang of LANGS) {
      const doc = pages.doc(lang);
      const note = doc.querySelector("[data-role=nojs-note]");
      expect(note.hasAttribute("hidden"), lang).toBe(false);
      expect(textOf(note), lang).toMatch(/10,000/);
      expect(doc.querySelector("[data-role=controls]").hasAttribute("hidden"), lang).toBe(true);
      expect(textOf(doc.querySelector("[data-out=usd-list]")), lang).toMatch(/^\$\d/);
    }
  });
});

describe("the narrow screen", () => {
  it("lets no page-level box force a sideways scroll: every wrapper clips or shrinks", () => {
    const css = pages.css();
    expect(css).toMatch(/\.og-wrap\{[^}]*max-width:1080px/);
    expect(css).toMatch(/@media \(max-width:820px\)\{[^}]*\.og-wrap\{padding:0 20px\}/);
    expect(css).toMatch(/\.og-ftr\{[^}]*flex-wrap:wrap/);
  });

  it("draws a panda divider between every pair of blocks and after the last", () => {
    for (const lang of LANGS) {
      expect(pages.doc(lang).querySelectorAll("main .og-divider"), lang).toHaveLength(SEVEN_DIVIDERS);
      expect(pages.doc(lang).querySelector("main").lastElementChild.classList.contains("og-divider"), lang).toBe(true);
    }
  });

  it("makes the model radios cover their whole label so the touch target is 44 px", () => {
    const rule = pages.css().match(/\.og-opt input\{([^}]*)\}/)[1];
    expect(rule).toMatch(/inset:-1px/);
    expect(rule).toMatch(/width:calc\(100% \+ 2px\)/);
  });
});

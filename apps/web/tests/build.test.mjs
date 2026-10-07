import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { DRAFT_MARKER, assembleHtml, isApproved, noticeHtml } from "../scripts/assemble.mjs";
import { readProduct } from "../scripts/product.mjs";
import { buildSite } from "../scripts/site.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const PRODUCTION = "js/apps/web/src/main.js";
const PREVIEW = "js/apps/web/preview/main.js";
const TEMPLATE =
  '<html lang="%LANG%">%HEAD%<meta content="%COPY_STATUS%">%DRAFT_BANNER%%NOTICE%<script src="%ASSETS%%ENTRY%"><a href="%ORIGIN%/">%BRAND%</a>';
const NAME = "OpenGisting";
const PAGE = {
  entry: "a.js",
  assets: "/x/",
  lang: "en",
  head: "<title>T</title>",
  notice: "",
  brand: "B",
  origin: "https://o.example",
};
const scratch = [];

function workspace() {
  const root = mkdtempSync(join(tmpdir(), "web-build-"));
  scratch.push(root);
  return root;
}

function copyOfWeb() {
  const webDir = join(workspace(), "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  return webDir;
}

function setStatus(webDir, language, status) {
  const path = join(webDir, "copy", `${language}.json`);
  const document = JSON.parse(readFileSync(path, "utf8"));
  writeFileSync(path, JSON.stringify({ ...document, status }));
}

function build(webDir, entry = PRODUCTION) {
  const outDir = join(workspace(), "out");
  const result = buildSite({ webDir, outDir, entry });
  return {
    ...result,
    html: readFileSync(join(outDir, "opengisting", "index.html"), "utf8"),
    outDir,
  };
}

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("assembleHtml", () => {
  it("marks the page as a draft unless every copy file is approved", () => {
    expect(assembleHtml(TEMPLATE, { ...PAGE, statuses: ["approved", "approved"] })).not.toContain(
      DRAFT_MARKER,
    );
    expect(
      assembleHtml(TEMPLATE, { ...PAGE, statuses: ["approved", "awaiting_user_confirmation"] }),
    ).toContain(DRAFT_MARKER);
    expect(assembleHtml(TEMPLATE, { ...PAGE, statuses: [] })).toContain(DRAFT_MARKER);
  });

  it("escapes the brand, the origin and the asset path it writes into the page", () => {
    const html = assembleHtml(TEMPLATE, {
      ...PAGE,
      statuses: ["approved"],
      brand: 'A&B "<i>"',
      origin: 'https://o.example/"><i>',
      assets: '/x"><i>/',
    });
    expect(html).toContain("A&amp;B &quot;&lt;i&gt;&quot;");
    expect(html).toContain('href="https://o.example/&quot;&gt;&lt;i&gt;/"');
    expect(html).toContain('src="/x&quot;&gt;&lt;i&gt;/a.js"');
    expect(html).not.toContain("<i>");
  });

  it("escapes the statuses it names in the banner and the status meta", () => {
    const html = assembleHtml(TEMPLATE, { ...PAGE, statuses: ['x"><i>'] });
    expect(html).not.toContain("<i>");
  });

  it("treats anything other than the exact word approved as not approved", () => {
    for (const status of ["Approved", "approved ", "approve", "", "awaiting_user_confirmation"]) {
      expect(isApproved([status])).toBe(false);
    }
  });

  it("puts the marker in a visible banner that names the status", () => {
    const html = assembleHtml(TEMPLATE, { ...PAGE, statuses: ["awaiting_user_confirmation"] });
    expect(html).toContain('class="draft-banner"');
    expect(html).toContain("awaiting_user_confirmation");
  });

  it("fills every page token once and leaves none behind", () => {
    const html = assembleHtml(TEMPLATE, { ...PAGE, statuses: ["approved"] });
    expect(html).not.toMatch(/%[A-Z_]+%/);
    expect(html).toBe(
      '<html lang="en"><title>T</title><meta content="approved"><script src="/x/a.js"><a href="https://o.example/">B</a>',
    );
  });

  it("does not expand a token found inside a value", () => {
    const html = assembleHtml(TEMPLATE, { ...PAGE, head: "%LANG%", statuses: ["approved"] });
    expect(html).toContain('<html lang="en">%LANG%<meta');
  });

  it("refuses a shell token it has no value for", () => {
    for (const template of ["%NOPE%", "<p>%BRAD%</p>"]) {
      expect(() => assembleHtml(template, { ...PAGE, statuses: ["approved"] }), template).toThrow(
        /%(NOPE|BRAD)%/,
      );
    }
  });

  it("refuses a copy directive left in the shell", () => {
    expect(() =>
      assembleHtml("<p>{{copy:hero.title}}</p>", { ...PAGE, statuses: ["approved"] }),
    ).toThrow(/\{\{copy:hero\.title\}\}/);
  });
});

describe("noticeHtml", () => {
  it("escapes the language tag it writes into the lang attribute", () => {
    const html = noticeHtml(
      { copyFallback: "en", htmlLang: 'ja"><i>' },
      { lang: "ja", strings: { "page.notice": "n" } },
    );
    expect(html).toContain('lang="ja&quot;&gt;&lt;i&gt;"');
    expect(html).not.toContain("<i>");
  });
});

describe("readProduct", () => {
  function productWith(change) {
    const webDir = copyOfWeb();
    const path = join(webDir, "product.json");
    writeFileSync(path, JSON.stringify(change(JSON.parse(readFileSync(path, "utf8")))));
    return webDir;
  }

  function without(object, key) {
    return Object.fromEntries(Object.entries(object).filter(([name]) => name !== key));
  }

  it("reads the product name, slug, origin and language table from product.json", () => {
    const product = readProduct(REAL_WEB);
    expect(product.name).toBe(NAME);
    expect(product.slug).toBe("opengisting");
    expect(product.origin).toBe("https://www.myagenthubs.com");
    expect(product.languages.map((language) => language.code)).toEqual(["en", "zh-CN", "ja", "ko"]);
    expect(product.languages.filter((language) => language.indexed).map((l) => l.code)).toEqual([
      "en",
      "zh-CN",
    ]);
  });

  it("refuses a product file with a missing or empty name", () => {
    expect(() => readProduct(productWith((p) => without(p, "name")))).toThrow(/name/);
    expect(() => readProduct(productWith((p) => ({ ...p, name: " " })))).toThrow(/name/);
  });

  it("refuses a language entry that lacks a field or a boolean indexed flag", () => {
    const broken = (change) =>
      productWith((p) => ({ ...p, languages: [change(p.languages[0]), ...p.languages.slice(1)] }));
    expect(() => readProduct(broken((l) => without(l, "htmlLang")))).toThrow(/htmlLang/);
    expect(() => readProduct(broken((l) => ({ ...l, indexed: "yes" })))).toThrow(/indexed/);
  });

  it("refuses a copy fallback that names no language in the table or the language itself", () => {
    const fallback = (value) =>
      productWith((p) => ({
        ...p,
        languages: p.languages.map((l) => (l.code === "ja" ? { ...l, copyFallback: value } : l)),
      }));
    expect(() => readProduct(fallback("fr"))).toThrow(/copyFallback/);
    expect(() => readProduct(fallback("ja"))).toThrow(/copyFallback/);
    expect(() => readProduct(fallback(7))).toThrow(/copyFallback/);
  });

  it("refuses a product file without a brand", () => {
    expect(() => readProduct(productWith((p) => without(p, "brand")))).toThrow(/brand/);
  });

  it("refuses an og image template that has no {lang} slot", () => {
    expect(() => readProduct(productWith((p) => ({ ...p, ogImage: "/og/fixed.png" })))).toThrow(
      /ogImage/,
    );
    expect(() => readProduct(productWith((p) => without(p, "ogImage")))).toThrow(/ogImage/);
  });

  it("refuses a slug that is not a plain lowercase path segment", () => {
    for (const slug of ["..", "../..", "a/../..", ".", "a/b", "A", "-a", "a b", ""]) {
      expect(() => readProduct(productWith((p) => ({ ...p, slug }))), slug).toThrow(/slug/);
    }
  });

  it("refuses a table whose language codes repeat", () => {
    const webDir = productWith((p) => ({ ...p, languages: [p.languages[0], p.languages[0]] }));
    expect(() => readProduct(webDir)).toThrow(/duplicate/);
  });
});

describe("buildSite", () => {
  it("marks the build of the committed copy as a draft exactly while a language is unapproved", () => {
    const { html, statuses } = build(REAL_WEB);
    expect(statuses).toHaveLength(readdirSync(join(REAL_WEB, "copy")).length);
    expect(html.includes(DRAFT_MARKER)).toBe(!isApproved(statuses));
  });

  it("drops the marker once every language is approved", () => {
    const webDir = copyOfWeb();
    for (const language of ["en", "zh-CN", "ja", "ko"]) {
      setStatus(webDir, language, "approved");
    }
    expect(build(webDir).html).not.toContain(DRAFT_MARKER);
  });

  it("keeps the marker while a single language is still waiting", () => {
    const webDir = copyOfWeb();
    for (const language of ["en", "zh-CN", "ja"]) {
      setStatus(webDir, language, "approved");
    }
    setStatus(webDir, "ko", "awaiting_user_confirmation");
    expect(build(webDir).html).toContain(DRAFT_MARKER);
  });

  it("refuses a copy file without a status", () => {
    const webDir = copyOfWeb();
    writeFileSync(join(webDir, "copy", "ko.json"), JSON.stringify({ lang: "ko", strings: {} }));
    expect(() => build(webDir)).toThrow(/status/);
  });

  it("points the page at the production or the preview entry", () => {
    expect(build(REAL_WEB, PRODUCTION).html).toContain(`src="/opengisting/${PRODUCTION}"`);
    expect(build(REAL_WEB, PREVIEW).html).toContain(`src="/opengisting/${PREVIEW}"`);
  });

  it("publishes the style next to the page, and no copy files", () => {
    const shared = join(build(REAL_WEB).outDir, "opengisting");
    expect(readdirSync(shared)).not.toContain("copy");
    expect(readdirSync(shared)).toContain("style.css");
  });

  it("keeps benchmarks, source files and non-JSON files out of the public output", () => {
    const webDir = copyOfWeb();
    const unwanted = ["benchmarks_v2.json", "pricing_source.json", "notes.txt"];
    for (const name of unwanted) {
      writeFileSync(join(webDir, "data", name), "{}");
    }
    const shipped = readdirSync(join(build(webDir).outDir, "opengisting", "data"));
    for (const name of ["benchmarks.json", "benchmarks_source.json", ...unwanted]) {
      expect(shipped).not.toContain(name);
    }
  });

  it("ships a template that names no English prose outside the copy files", () => {
    const template = readFileSync(join(REAL_WEB, "index.html"), "utf8");
    const withoutTags = template
      .replace(/<[^>]*>/g, "")
      .replace(/%[A-Z_]+%/g, "")
      .trim();
    expect(withoutTags).toBe("");
  });
});

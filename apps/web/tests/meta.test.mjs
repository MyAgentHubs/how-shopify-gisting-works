import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { readCopyDocs, resolveCopy } from "../scripts/copy-resolve.mjs";
import { pageHead } from "../scripts/meta.mjs";
import { pagePath, readProduct } from "../scripts/product.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const product = readProduct(REAL_WEB);
const docs = readCopyDocs(REAL_WEB);
const ORIGIN = "https://www.myagenthubs.com";

function headOf(code, { draft = false, release = true, changeProduct = (p) => p, changeCopy = (c) => c } = {}) {
  const p = changeProduct(product);
  const language = p.languages.find((entry) => entry.code === code);
  return pageHead({ product: p, language, copy: changeCopy(resolveCopy(p, docs, code)), draft, release });
}

const alternates = (head) =>
  [...head.matchAll(/<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">/g)].map((m) => [
    m[1],
    m[2],
  ]);
const metaContent = (head, attribute, name) =>
  head.match(new RegExp(`<meta ${attribute}="${name}" content="([^"]*)">`))?.[1];
const canonical = (head) => head.match(/<link rel="canonical" href="([^"]+)">/)?.[1];

describe("pageHead for the indexed languages", () => {
  it("gives the English page the approved title and description", () => {
    const head = headOf("en");
    expect(head).toContain("<title>OpenGisting: Shopify’s Gisting, reproduced in the open</title>");
    expect(metaContent(head, "name", "description")).toBe(
      "Your entire support rulebook in 16 tokens, on a live order-tracking agent. An independent reproduction of Shopify Engineering’s Gisting; try it with test orders.",
    );
    expect(metaContent(head, "property", "og:title")).toBe(
      "OpenGisting — Shopify’s Gisting, reproduced in the open",
    );
    expect(metaContent(head, "property", "og:description")).toBe(
      metaContent(head, "name", "description"),
    );
  });

  it("gives the Chinese page its own title", () => {
    expect(headOf("zh-CN")).toContain("<title>OpenGisting：开源复现 Shopify 的 Gisting</title>");
  });

  it("writes exactly en, zh-Hans and x-default as hreflang, on both pages", () => {
    const expected = [
      ["en", `${ORIGIN}/opengisting/`],
      ["zh-Hans", `${ORIGIN}/zh-CN/opengisting/`],
      ["x-default", `${ORIGIN}/opengisting/`],
    ];
    expect(alternates(headOf("en"))).toEqual(expected);
    expect(alternates(headOf("zh-CN"))).toEqual(expected);
  });

  it("points the canonical at the page itself and leaves robots alone", () => {
    expect(canonical(headOf("en"))).toBe(`${ORIGIN}/opengisting/`);
    expect(canonical(headOf("zh-CN"))).toBe(`${ORIGIN}/zh-CN/opengisting/`);
    expect(headOf("en")).not.toContain("robots");
    expect(headOf("zh-CN")).not.toContain("robots");
  });

  it("points og:url at the canonical and og:image at the language image", () => {
    const zh = headOf("zh-CN");
    expect(metaContent(zh, "property", "og:url")).toBe(canonical(zh));
    expect(metaContent(zh, "property", "og:image")).toBe(`${ORIGIN}/og/og-opengisting-zh-CN.png`);
    expect(metaContent(headOf("en"), "property", "og:image")).toBe(
      `${ORIGIN}/og/og-opengisting-en.png`,
    );
    expect(metaContent(zh, "name", "twitter:card")).toBe("summary_large_image");
    expect(metaContent(zh, "property", "og:site_name")).toBe("OpenGisting");
  });
});

describe("pageHead escapes what the product table gives it", () => {
  const odd = { name: 'Open & "Gisting" <b>', origin: 'https://x.example/"><i>' };
  const changeProduct = (p) => ({ ...p, ...odd });

  it("escapes the site name, the canonical, og:url and og:image", () => {
    const head = headOf("en", { changeProduct });
    expect(metaContent(head, "property", "og:site_name")).toBe("Open &amp; &quot;Gisting&quot; &lt;b&gt;");
    expect(head).not.toContain("<i>");
    expect(head).not.toMatch(/"><i/);
    for (const link of head.match(/(?:href|content)="https:\/\/x\.example\/[^"]*"/g)) {
      expect(link).toContain("&quot;&gt;&lt;i&gt;");
    }
  });
});

describe("pageHead for the languages that are not indexed", () => {
  it("writes no hreflang and a noindex, with a canonical at the page itself", () => {
    for (const code of ["ja", "ko"]) {
      const head = headOf(code);
      expect(alternates(head), code).toEqual([]);
      expect(head).not.toContain("hreflang");
      expect(metaContent(head, "name", "robots")).toBe("noindex");
      expect(canonical(head)).toBe(`${ORIGIN}/${code}/opengisting/`);
    }
  });

  it("reuses the English title and the English share image", () => {
    const head = headOf("ja");
    expect(head).toContain("<title>OpenGisting: Shopify’s Gisting, reproduced in the open</title>");
    expect(metaContent(head, "property", "og:image")).toBe(`${ORIGIN}/og/og-opengisting-en.png`);
  });
});

describe("pageHead follows the product table", () => {
  it("adds a language to the hreflang set once it is indexed, and drops its noindex", () => {
    const changeProduct = (p) => ({
      ...p,
      languages: p.languages.map((l) => (l.code === "ja" ? { ...l, indexed: true } : l)),
    });
    const head = headOf("en", { changeProduct });
    expect(alternates(head).map(([code]) => code)).toEqual(["en", "zh-Hans", "ja", "x-default"]);
    expect(headOf("ja", { changeProduct })).not.toContain("noindex");
  });

  it("builds page paths from the prefix and the slug", () => {
    expect(product.languages.map((l) => pagePath(product, l))).toEqual([
      "/opengisting/",
      "/zh-CN/opengisting/",
      "/ja/opengisting/",
      "/ko/opengisting/",
    ]);
  });
});

describe("pageHead drafts and bad input", () => {
  it("marks a draft in the title and in a build-state meta, and only then", () => {
    const draft = headOf("en", { draft: true });
    expect(draft).toContain("<title>[DRAFT] OpenGisting: ");
    expect(metaContent(draft, "name", "build-state")).toBe("draft");
    expect(headOf("en")).not.toContain("build-state");
    expect(headOf("en")).not.toContain("[DRAFT]");
  });

  it("stamps the build-state meta on every page unless the build is a release", () => {
    for (const code of ["en", "zh-CN", "ja", "ko"]) {
      const stamped = headOf(code, { release: false });
      expect(metaContent(stamped, "name", "build-state"), code).toBe("draft");
      expect(stamped).not.toContain("[DRAFT]");
      expect(headOf(code, { release: true }), code).not.toContain("build-state");
    }
  });

  it("escapes markup in copy text", () => {
    const changeCopy = (copy) => ({
      ...copy,
      strings: { ...copy.strings, "meta.title": `A "b" <i> & c`, "meta.description": `x"y` },
    });
    const head = headOf("en", { changeCopy });
    expect(head).toContain("<title>A &quot;b&quot; &lt;i&gt; &amp; c</title>");
    expect(metaContent(head, "name", "description")).toBe("x&quot;y");
  });

  it("fails on a missing meta key and names it", () => {
    const strip = (key) => (copy) => ({
      ...copy,
      strings: Object.fromEntries(Object.entries(copy.strings).filter(([name]) => name !== key)),
    });
    for (const key of ["meta.title", "meta.og_title", "meta.description"]) {
      expect(() => headOf("zh-CN", { changeCopy: strip(key) })).toThrow(new RegExp(key));
    }
  });

  it("refuses a product table without a root-path language for x-default", () => {
    const changeProduct = (p) => ({
      ...p,
      languages: p.languages.map((l) => (l.code === "en" ? { ...l, prefix: "en" } : l)),
    });
    expect(() => headOf("zh-CN", { changeProduct })).toThrow(/x-default/);
  });
});

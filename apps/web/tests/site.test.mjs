import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { readProduct } from "../scripts/product.mjs";
import { buildSite } from "../scripts/site.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const ENTRY = "js/apps/web/src/main.js";
const ORIGIN = "https://www.myagenthubs.com";
const NOTICES = {
  ja: "この言語版は準備中です。英語版を表示しています。",
  ko: "이 언어 버전은 준비 중입니다. 영어 버전을 표시합니다.",
};
const PAGES = {
  en: "opengisting",
  "zh-CN": "zh-CN/opengisting",
  ja: "ja/opengisting",
  ko: "ko/opengisting",
};
const roots = [];
let outDir = "";

function fixtureWeb() {
  const root = mkdtempSync(join(tmpdir(), "site-"));
  roots.push(root);
  const webDir = join(root, "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  return { root, webDir };
}

function page(code) {
  return readFileSync(join(outDir, PAGES[code], "index.html"), "utf8");
}

const alternates = (html) =>
  [...html.matchAll(/<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">/g)].map((m) => m[1]);
const canonical = (html) => html.match(/<link rel="canonical" href="([^"]+)">/)?.[1];

beforeAll(() => {
  const { root, webDir } = fixtureWeb();
  outDir = join(root, "out");
  buildSite({ webDir, outDir, entry: ENTRY });
});

afterAll(() => {
  for (const root of roots) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("the compiled scripts", () => {
  function seededBuild(options) {
    const { root, webDir } = fixtureWeb();
    const out = join(root, "out");
    const emitted = join(out, "opengisting", "js", "apps", "web");
    for (const [dir, file] of [["copy", "en.json"], ["preview", "main.js"], ["fakes", "fake-gateway.js"], ["src", "main.js"]]) {
      mkdirSync(join(emitted, dir), { recursive: true });
      writeFileSync(join(emitted, dir, file), "");
    }
    buildSite({ webDir, outDir: out, entry: ENTRY, ...options });
    return (dir) => existsSync(join(emitted, dir));
  }

  it("do not carry the copy file that tsc emits for the type of the copy keys", () => {
    expect(seededBuild({})("copy")).toBe(false);
    expect(seededBuild({ preview: true })("copy")).toBe(false);
  });

  it("leave the preview script and the fake gateway out unless the build is a preview", () => {
    const plain = seededBuild({});
    expect([plain("preview"), plain("fakes"), plain("src")]).toEqual([false, false, true]);
    const preview = seededBuild({ preview: true });
    expect([preview("preview"), preview("fakes"), preview("src")]).toEqual([true, true, true]);
  });
});

describe("the built layout", () => {
  it("has one page per language at its own path and the shared assets once", () => {
    for (const code of Object.keys(PAGES)) {
      expect(existsSync(join(outDir, PAGES[code], "index.html")), code).toBe(true);
    }
    expect(readdirSync(outDir).sort()).toEqual(["ja", "ko", "opengisting", "zh-CN"]);
    expect(readdirSync(join(outDir, "opengisting")).sort()).toEqual([
      "data",
      "index.html",
      "noscript.css",
      "shopify-orders.webp",
      "style.css",
    ]);
    for (const prefix of ["zh-CN", "ja", "ko"]) {
      expect(readdirSync(join(outDir, prefix, "opengisting"))).toEqual(["index.html"]);
    }
  });

  it("states a html lang that matches the path, and links assets by absolute path", () => {
    const langs = { en: "en", "zh-CN": "zh-CN", ja: "ja", ko: "ko" };
    for (const [code, lang] of Object.entries(langs)) {
      const html = page(code);
      expect(html, code).toContain(`<html lang="${lang}">`);
      expect(html).toContain('href="/opengisting/style.css"');
      expect(html).toContain(`src="/opengisting/${ENTRY}"`);
    }
  });
});

describe("the pages carry no site chrome of their own", () => {
  it("has no www header, language menu, inline header style or language links", () => {
    for (const code of Object.keys(PAGES)) {
      const html = page(code);
      expect(html, code).not.toContain("mh-global");
      expect(html).not.toContain("mh-language");
      expect(html).not.toContain("<header");
      expect(html).not.toMatch(/<details\b(?![^>]*class="og-)/);
      expect(html).not.toContain("<style");
      expect(html).not.toMatch(/<a\b[^>]*hreflang/);
      expect(html).not.toContain("?lang=");
    }
    expect(readFileSync(join(outDir, "opengisting", "style.css"), "utf8")).not.toMatch(
      /mh-global|mh-language/,
    );
  });

  it("keeps the footer brand link for www to import", () => {
    for (const code of Object.keys(PAGES)) {
      expect(page(code), code).toContain(
        `<a class="mh-footer-brand" href="${ORIGIN}/">MyAgentHubs</a>`,
      );
    }
  });

  it("has no runtime language negotiation in the boot code", () => {
    const boot = readFileSync(join(REAL_WEB, "src", "boot.ts"), "utf8");
    expect(boot).not.toMatch(/navigator|location\.search|URLSearchParams/);
  });

  it("loads runtime files from the same root the build writes them to", () => {
    const boot = readFileSync(join(REAL_WEB, "src", "boot.ts"), "utf8");
    expect(boot).toContain(`ASSET_ROOT = "/${readProduct(REAL_WEB).slug}/"`);
  });
});

describe("canonical, hreflang and robots", () => {
  it("gives en and zh-CN a self canonical and exactly en, zh-Hans, x-default", () => {
    for (const code of ["en", "zh-CN"]) {
      const html = page(code);
      expect(canonical(html), code).toBe(`${ORIGIN}/${PAGES[code]}/`);
      expect(alternates(html)).toEqual(["en", "zh-Hans", "x-default"]);
      expect(html).not.toContain('name="robots"');
    }
  });

  it("gives ja and ko a self canonical, noindex and no hreflang at all", () => {
    for (const code of ["ja", "ko"]) {
      const html = page(code);
      expect(canonical(html), code).toBe(`${ORIGIN}/${PAGES[code]}/`);
      expect(html).toContain('<meta name="robots" content="noindex">');
      expect(html).not.toContain("hreflang");
    }
  });
});

describe("the language notice", () => {
  it("appears once on ja and ko in their own language, and nowhere else", () => {
    for (const [code, notice] of Object.entries(NOTICES)) {
      const html = page(code);
      expect(html.split(notice), code).toHaveLength(2);
      expect(html).toContain(`<p class="page-notice" role="note" lang="${code}">${notice}</p>`);
    }
    for (const code of ["en", "zh-CN"]) {
      expect(page(code), code).not.toContain("page-notice");
    }
  });

  it("is the only difference between the ja and ko body and the English body", () => {
    const bodyOf = (html) => html.slice(html.indexOf("<body"), html.indexOf("</body>"));
    const noticeLine = /<p class="page-notice"[^>]*>[^<]*<\/p>/;
    const english = bodyOf(page("en"));
    for (const code of Object.keys(NOTICES)) {
      const body = bodyOf(page(code));
      expect(body, code).toMatch(noticeLine);
      expect(body.replace(noticeLine, ""), code).toBe(english);
    }
  });

  it("is left out of a page whose language has no notice text yet", () => {
    const { root, webDir } = fixtureWeb();
    const path = join(webDir, "copy", "ja.json");
    const doc = JSON.parse(readFileSync(path, "utf8"));
    delete doc.strings["page.notice"];
    writeFileSync(path, JSON.stringify(doc));
    const bare = join(root, "bare");
    buildSite({ webDir, outDir: bare, entry: ENTRY });
    expect(readFileSync(join(bare, "ja", "opengisting", "index.html"), "utf8")).not.toContain(
      "page-notice",
    );
  });

  it("escapes markup in the notice text", () => {
    const { root, webDir } = fixtureWeb();
    const path = join(webDir, "copy", "ko.json");
    const doc = JSON.parse(readFileSync(path, "utf8"));
    doc.strings["page.notice"] = "<script>x</script>";
    writeFileSync(path, JSON.stringify(doc));
    const escaped = join(root, "escaped");
    buildSite({ webDir, outDir: escaped, entry: ENTRY });
    const html = readFileSync(join(escaped, "ko", "opengisting", "index.html"), "utf8");
    expect(html).toContain("&lt;script&gt;x&lt;/script&gt;");
  });
});

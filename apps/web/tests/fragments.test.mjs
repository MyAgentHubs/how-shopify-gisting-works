import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readCopyDocs, resolveCopy } from "../scripts/copy-resolve.mjs";
import { assembleSections, renderFragment } from "../scripts/fragments.mjs";

const PRODUCT = {
  languages: [
    { code: "en", copyFallback: null },
    { code: "zh-CN", copyFallback: null },
    { code: "ja", copyFallback: "en" },
  ],
};
const DOCS = {
  en: { status: "approved", lang: "en", strings: { "a.title": "Hello", "a.note": "Only English" } },
  "zh-CN": { status: "approved", lang: "zh-CN", strings: { "a.title": "你好" } },
  ja: { status: "approved", lang: "ja", strings: { "page.notice": "準備中" } },
};
const scratch = [];

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function sectionsDir(files) {
  const dir = mkdtempSync(join(tmpdir(), "sections-"));
  scratch.push(dir);
  mkdirSync(join(dir, "sections"));
  for (const [name, source] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, "sections", name)), { recursive: true });
    writeFileSync(join(dir, "sections", name), source);
  }
  return join(dir, "sections");
}

const copyOf = (strings) => ({ lang: "en", strings });

describe("renderFragment", () => {
  it("replaces copy directives with the language text", () => {
    const html = renderFragment({ file: "x.html", source: "<h1>{{copy:a.title}}</h1>" }, copyOf({ "a.title": "Hi" }));
    expect(html).toBe("<h1>Hi</h1>");
  });

  it("names the file and the key when a key is missing", () => {
    const fragment = { file: "10-hero.html", source: "<p>{{copy:nope.key}}</p>" };
    expect(() => renderFragment(fragment, copyOf({}))).toThrow(/10-hero\.html.*nope\.key/);
  });

  it("escapes markup characters in copy text", () => {
    const strings = { k: `<b>"Tom" & 'Jerry'</b>` };
    const html = renderFragment({ file: "x.html", source: "{{copy:k}}" }, copyOf(strings));
    expect(html).toBe("&lt;b&gt;&quot;Tom&quot; &amp; &#39;Jerry&#39;&lt;/b&gt;");
  });

  it("refuses copy text whose {turns} placeholder was given no fill", () => {
    const fragment = { file: "x.html", source: "{{copy:k}}" };
    expect(() => renderFragment(fragment, copyOf({ k: "{turns} turns, {n}" }))).toThrow(/x\.html.*key k.*\{turns\}/);
  });

  it("does not expand directives found inside copy text", () => {
    const html = renderFragment({ file: "x.html", source: "{{copy:k}}" }, copyOf({ k: "{{copy:k}}" }));
    expect(html).toBe("{{copy:k}}");
  });

  it("treats a key that only exists on every object as missing, never as copy", () => {
    for (const key of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      const fragment = { file: "x.html", source: `{{copy:${key}}}` };
      expect(() => renderFragment(fragment, copyOf({ k: "v" })), key).toThrow(/missing copy key/);
    }
  });

  it("refuses a directive of an unknown kind", () => {
    const fragment = { file: "x.html", source: "{{cpoy:k}}" };
    expect(() => renderFragment(fragment, copyOf({ k: "v" }))).toThrow(/x\.html.*cpoy/);
  });
});

describe("assembleSections", () => {
  it("joins the fragments in file name order and ignores other files", () => {
    const dir = sectionsDir({
      "20-b.html": "<b>{{copy:k}}</b>",
      "10-a.html": "<a>{{copy:k}}</a>",
      "notes.txt": "ignored",
    });
    expect(assembleSections(dir, copyOf({ k: "x" }))).toBe("<a>x</a>\n<b>x</b>");
  });

  it("fails on a missing key in any fragment", () => {
    const dir = sectionsDir({ "10-a.html": "{{copy:gone}}" });
    expect(() => assembleSections(dir, copyOf({}))).toThrow(/10-a\.html.*gone/);
  });
});

describe("the include directive", () => {
  it("puts a shared part into the page and trims its final newline", () => {
    const dir = sectionsDir({
      "10-a.html": "<i>{{include:mark}}</i>|<b>{{include:mark}}</b>",
      "parts/mark.html": "<svg></svg>\n",
    });
    expect(assembleSections(dir, copyOf({}))).toBe("<i><svg></svg></i>|<b><svg></svg></b>");
  });

  it("renders copy and data directives inside the part with the page's own context", () => {
    const dir = sectionsDir({
      "10-a.html": "{{include:row}}",
      "parts/row.html": "<p>{{copy:k}} {{data:numbers.n|int}}</p>",
    });
    expect(assembleSections(dir, copyOf({ k: "x" }), { numbers: { n: 1234 } })).toBe("<p>x 1,234</p>");
  });

  it("does not list parts as sections of their own", () => {
    const dir = sectionsDir({ "10-a.html": "A", "parts/mark.html": "PART" });
    expect(assembleSections(dir, copyOf({}))).toBe("A");
  });

  it("names the fragment and the part when the part is missing", () => {
    const dir = sectionsDir({ "10-a.html": "{{include:gone}}" });
    expect(() => assembleSections(dir, copyOf({}))).toThrow(/10-a\.html.*gone/);
  });

  it("names the part when a copy key inside it is missing", () => {
    const dir = sectionsDir({ "10-a.html": "{{include:row}}", "parts/row.html": "{{copy:nope}}" });
    expect(() => assembleSections(dir, copyOf({}))).toThrow(/row.*nope/);
  });

  it("refuses a part that includes itself, directly or through another", () => {
    const loop = sectionsDir({ "10-a.html": "{{include:a}}", "parts/a.html": "{{include:b}}", "parts/b.html": "{{include:a}}" });
    expect(() => assembleSections(loop, copyOf({}))).toThrow(/cycle/);
  });

  it("refuses a part name that climbs out of the parts folder", () => {
    const dir = sectionsDir({ "10-a.html": "{{include:../10-a}}" });
    expect(() => assembleSections(dir, copyOf({}))).toThrow(/part name/);
  });

  it("needs a parts folder to include from", () => {
    expect(() => renderFragment({ file: "x.html", source: "{{include:a}}" }, copyOf({}))).toThrow(/x\.html.*parts/);
  });
});

describe("readCopyDocs", () => {
  it("keys the committed copy files by their declared language", () => {
    const webDir = join(dirname(fileURLToPath(import.meta.url)), "..");
    const docs = readCopyDocs(webDir);
    expect(Object.keys(docs).sort()).toEqual(["en", "ja", "ko", "zh-CN"]);
    expect(docs["zh-CN"].lang).toBe("zh-CN");
  });
});

describe("resolveCopy", () => {
  it("gives en and zh-CN their own complete strings only", () => {
    expect(resolveCopy(PRODUCT, DOCS, "zh-CN").strings).toEqual({ "a.title": "你好" });
    expect(resolveCopy(PRODUCT, DOCS, "en").strings).toEqual(DOCS.en.strings);
  });

  it("falls ja back to en and lets the small override win", () => {
    const { strings, lang } = resolveCopy(PRODUCT, DOCS, "ja");
    expect(lang).toBe("ja");
    expect(strings).toEqual({ ...DOCS.en.strings, "page.notice": "準備中" });
  });

  it("makes a key missing from ja render the English text", () => {
    const copy = resolveCopy(PRODUCT, DOCS, "ja");
    const html = renderFragment({ file: "x.html", source: "{{copy:a.note}}" }, copy);
    expect(html).toBe("Only English");
  });

  it("refuses a language that is not in the product table or has no copy file", () => {
    expect(() => resolveCopy(PRODUCT, DOCS, "fr")).toThrow(/fr/);
    expect(() => resolveCopy(PRODUCT, { en: DOCS.en }, "zh-CN")).toThrow(/zh-CN/);
  });
});

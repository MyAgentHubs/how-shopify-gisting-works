import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { assembleSections, renderFragment } from "../scripts/fragments.mjs";
import { FORMAT_NAMES, formatValue } from "../src/format.ts";

const scratch = [];
const copyOf = (strings, lang = "en") => ({ lang, strings });
const DATA = {
  numbers: { n: 1234, ratio: 0.97321, tiny: 0.00004 },
  list: { name: "<Sonnet>", on: true, off: false, rows: [{ id: "a", v: 1 }, { id: "b", v: 20 }], one: { id: "solo" } },
};

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function pages(files) {
  const root = mkdtempSync(join(tmpdir(), "directives-"));
  scratch.push(root);
  mkdirSync(join(root, "sections", "parts"), { recursive: true });
  for (const [name, source] of Object.entries(files)) {
    writeFileSync(join(root, "sections", name), source);
  }
  return join(root, "sections");
}

const render = (source, data = DATA, strings = {}) => renderFragment({ file: "x.html", source }, copyOf(strings), data);

describe("the extra number formats", () => {
  it("round to cents, four decimals or a plain whole number", () => {
    expect(formatValue("decimal", 0.97321, "en")).toBe("0.97");
    expect(formatValue("decimal", 1234.5, "en")).toBe("1,234.50");
    expect(formatValue("ratio", 0.1, "en")).toBe("0.1000");
    expect(formatValue("ratio", 0.00004, "en")).toBe("0.0000");
    expect(formatValue("plain", 12, "en")).toBe("12");
    expect(FORMAT_NAMES).toContain("ratio");
  });

  it("refuse negative or non-finite input like every other format", () => {
    for (const format of ["decimal", "ratio", "plain"]) {
      expect(() => formatValue(format, -0.5, "en"), format).toThrow(TypeError);
      expect(() => formatValue(format, Number.NaN, "en"), format).toThrow(TypeError);
    }
  });
});

describe("the text and flag directives", () => {
  it("write a data value as escaped text", () => {
    expect(render("<i>{{text:list.name}}</i> {{text:numbers.n}} {{text:list.on}}")).toBe("<i>&lt;Sonnet&gt;</i> 1234 true");
  });

  it("refuse an object, a missing path and a malformed directive", () => {
    expect(() => render("{{text:list.rows}}")).toThrow(/x\.html.*list\.rows.*text/);
    expect(() => render("{{text:list.gone}}")).toThrow(/no data at list\.gone/);
    expect(() => render("{{text:list.name}}", null)).toThrow(/without a data context/);
  });

  it("emit a word only when the flag is true", () => {
    expect(render("<input {{flag:list.on|checked}}>|<input {{flag:list.off|checked}}>")).toBe("<input checked>|<input >");
  });

  it("refuse a flag that is not a boolean or a word with markup in it", () => {
    expect(() => render("{{flag:numbers.n|checked}}")).toThrow(/x\.html.*numbers\.n.*true or false/);
    expect(() => render('{{flag:list.on|a" onclick="x}}')).toThrow(/flag word/);
    expect(() => render("{{flag:list.on}}")).toThrow(/path\|word/);
  });
});

describe("filling a copy placeholder", () => {
  it("puts a formatted data number where the placeholder stands", () => {
    const html = render("{{copy:k|turns=numbers.n}}", DATA, { k: "{turns} turns, <b>" });
    expect(html).toBe("1,234 turns, &lt;b&gt;");
  });

  it("refuses a placeholder the text does not have", () => {
    expect(() => render("{{copy:k|days=numbers.n}}", DATA, { k: "{turns} turns" })).toThrow(/x\.html.*k.*\{days\}/);
  });

  it("refuses a fill without a data context or a malformed fill", () => {
    expect(() => render("{{copy:k|turns=numbers.n}}", null, { k: "{turns}" })).toThrow(/without a data context/);
    expect(() => render("{{copy:k|turns}}", DATA, { k: "{turns}" })).toThrow(/name=path/);
  });
});

describe("the each and with directives", () => {
  it("render a part once per item, with the item as data under item", () => {
    const dir = pages({
      "10-a.html": "<ul>{{each:list.rows|row}}</ul>",
      "parts/row.html": "<li>{{text:item.id}} {{data:item.v|int}} {{data:numbers.n|int}}</li>\n",
    });
    expect(assembleSections(dir, copyOf({}), DATA)).toBe("<ul><li>a 1 1,234</li>\n<li>b 20 1,234</li></ul>");
  });

  it("render a part once for a single object", () => {
    const dir = pages({ "10-a.html": "{{with:list.one|row}}", "parts/row.html": "[{{text:item.id}}]" });
    expect(assembleSections(dir, copyOf({}), DATA)).toBe("[solo]");
  });

  it("let a part include another part and still see the item", () => {
    const dir = pages({
      "10-a.html": "{{each:list.rows|outer}}",
      "parts/outer.html": "<p>{{include:inner}}</p>",
      "parts/inner.html": "{{text:item.id}}",
    });
    expect(assembleSections(dir, copyOf({}), DATA)).toBe("<p>a</p>\n<p>b</p>");
  });

  it("let include name its part by a data path, so each item can choose its own part", () => {
    const dir = pages({
      "10-a.html": "{{each:pick.rows|outer}}",
      "parts/outer.html": "<p>{{include:item.part}}</p>",
      "parts/one.html": "1:{{text:item.id}}",
      "parts/two.html": "2:{{text:item.id}}",
    });
    const data = { pick: { rows: [{ id: "a", part: "one" }, { id: "b", part: "two" }] } };
    expect(assembleSections(dir, copyOf({}), data)).toBe("<p>1:a</p>\n<p>2:b</p>");
  });

  it("refuse an include path that is missing or that names no valid part", () => {
    expect(() => render("{{include:list.nope}}")).toThrow(/no data at list\.nope/);
    expect(() => render("{{include:list.rows}}")).toThrow(/part name/);
    expect(() => render("{{include:list.on}}")).toThrow(/part name/);
  });

  it("refuse each on something that is not a list and with on a list", () => {
    const dir = pages({ "10-a.html": "{{each:list.one|row}}", "parts/row.html": "x" });
    expect(() => assembleSections(dir, copyOf({}), DATA)).toThrow(/10-a\.html.*each needs a list at list\.one/);
    const other = pages({ "10-a.html": "{{with:list.rows|row}}", "parts/row.html": "x" });
    expect(() => assembleSections(other, copyOf({}), DATA)).toThrow(/10-a\.html.*with needs an object at list\.rows/);
  });

  it("refuse a missing part, a missing path, a malformed argument and a missing data context", () => {
    const dir = pages({ "10-a.html": "{{each:list.rows|gone}}" });
    expect(() => assembleSections(dir, copyOf({}), DATA)).toThrow(/10-a\.html.*gone/);
    expect(() => render("{{each:list.nope|row}}")).toThrow(/no data at list\.nope/);
    expect(() => render("{{each:list.rows}}")).toThrow(/path\|part/);
    expect(() => render("{{each:list.rows|row}}", null)).toThrow(/without a data context/);
  });

  it("name the part when a path inside it is wrong", () => {
    const dir = pages({ "10-a.html": "{{each:list.rows|row}}", "parts/row.html": "{{text:item.nope}}" });
    expect(() => assembleSections(dir, copyOf({}), DATA)).toThrow(/parts\/row\.html.*item\.nope/);
  });
});

describe("the when directive", () => {
  const data = { link: { full: "https://x.test/a", empty: "" }, list: DATA.list };

  it("renders its part for text and leaves nothing behind for an empty string", () => {
    const dir = pages({ "10-a.html": "<p>{{when:link.full|row}}{{when:link.empty|row}}</p>", "parts/row.html": "<a>{{text:link.full}}</a>" });
    expect(assembleSections(dir, copyOf({}), data)).toBe("<p><a>https://x.test/a</a></p>");
  });

  it("refuses a path that is missing, not text, or malformed", () => {
    expect(() => renderFragment({ file: "x.html", source: "{{when:link.nope|row}}" }, copyOf({}), data)).toThrow(/no data at link\.nope/);
    expect(() => renderFragment({ file: "x.html", source: "{{when:list.on|row}}" }, copyOf({}), data)).toThrow(/when needs text at list\.on/);
    expect(() => renderFragment({ file: "x.html", source: "{{when:link.full}}" }, copyOf({}), data)).toThrow(/path\|part/);
  });
});

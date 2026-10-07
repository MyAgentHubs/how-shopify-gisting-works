import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { FORMAT_NAMES, formatValue } from "../src/format.ts";
import { renderFragment } from "../scripts/fragments.mjs";
import {
  RUNTIME_BLOCK_ID,
  buildDataContext,
  lookupPath,
  pickNumbers,
  readLinks,
  readRuntimeKeys,
  readTurnstile,
  runtimeBlock,
} from "../scripts/prerender.mjs";
import { buildSite } from "../scripts/site.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const GOLDEN = JSON.parse(readFileSync(join(REAL_WEB, "tests/fixtures/format-golden.json"), "utf8"));
const ENTRY = "js/apps/web/src/main.js";
const PAGES = ["opengisting", "zh-CN/opengisting", "ja/opengisting", "ko/opengisting"];
const BLOCK = new RegExp(`<script type="application/json" id="${RUNTIME_BLOCK_ID}">(.*?)</script>`);
const scratch = [];

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function workspace() {
  const root = mkdtempSync(join(tmpdir(), "prerender-"));
  scratch.push(root);
  return root;
}

function copyOfWeb() {
  const webDir = join(workspace(), "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  return webDir;
}

function writeJson(path, value) {
  writeFileSync(path, JSON.stringify(value));
}

function editKeys(webDir, change) {
  const path = join(webDir, "data", "runtime_keys.json");
  const keys = JSON.parse(readFileSync(path, "utf8"));
  writeJson(path, change(keys));
}

function allFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? allFiles(join(entry.parentPath, entry.name)) : [join(entry.parentPath, entry.name)],
  );
}

const copyOf = (lang, strings = {}) => ({ lang, strings });
const fragment = (source) => ({ file: "30-fig.html", source });

describe("number formatters", () => {
  it("give the same text as fmt_tokens and fmt_usd of the design draft on every golden row", () => {
    expect(GOLDEN.length).toBeGreaterThan(400);
    for (const row of GOLDEN) {
      expect(formatValue(row.format, row.input, row.lang), JSON.stringify(row)).toBe(row.expected);
    }
  });

  it("match the headline figures of the page", () => {
    const monthly = 10000 * 3 * 30 * ((526 - 19) * (908 / 933));
    expect(formatValue("tokens", monthly, "en")).toBe("444 M");
    expect(formatValue("tokens", monthly, "zh-CN")).toBe("4.44 亿");
    expect(formatValue("usd", (monthly / 1e6) * 2, "en")).toBe("$888");
    expect(formatValue("usd", (monthly / 1e6) * 0.2, "en")).toBe("$88.81");
  });

  it("round exact ties to even, as Python does", () => {
    expect(formatValue("tokens", 1_125_000, "en")).toBe("1.12 M");
    expect(formatValue("usd", 0.125, "en")).toBe("$0.12");
    expect(formatValue("int", 2.5, "en")).toBe("2");
    expect(formatValue("int", 3.5, "en")).toBe("4");
  });

  it("refuse an unknown format or a value that is not a plain non-negative number", () => {
    expect(FORMAT_NAMES).toEqual(["int", "tokens", "usd", "usd3", "decimal", "ratio", "plain"]);
    expect(() => formatValue("percent", 1, "en")).toThrow(/unknown format percent/);
    for (const bad of ["12", Number.NaN, Number.POSITIVE_INFINITY, -1, null, undefined]) {
      expect(() => formatValue("int", bad, "en"), String(bad)).toThrow(TypeError);
    }
  });
});

describe("data directives", () => {
  const data = { numbers: { rules: 526, big: 444_060_000 }, extra: { price: 88.805 } };

  it("render a formatted number from the data context", () => {
    const source = "<b>{{data:numbers.rules|int}}</b> {{data:numbers.big|tokens}} {{data:extra.price|usd}}";
    expect(renderFragment(fragment(source), copyOf("en"), data)).toBe("<b>526</b> 444 M $88.81");
    expect(renderFragment(fragment("{{data:numbers.big|tokens}}"), copyOf("zh-CN"), data)).toBe("4.44 亿");
    expect(renderFragment(fragment("{{data:numbers.big|tokens}}"), copyOf("ja"), data)).toBe("444 M");
  });

  it("fail with the file name when the path, format or context is wrong", () => {
    const render = (source, context = data) => () => renderFragment(fragment(source), copyOf("en"), context);
    expect(render("{{data:numbers.nope|int}}")).toThrow(/30-fig\.html.*no data at numbers\.nope/);
    expect(render("{{data:numbers.rules|percent}}")).toThrow(/30-fig\.html.*unknown format percent/);
    expect(render("{{data:numbers.rules}}")).toThrow(/30-fig\.html.*path\|format/);
    expect(render("{{data:numbers.rules|int|usd}}")).toThrow(/path\|format/);
    expect(render("{{data:numbers.rules|int}}", null)).toThrow(/without a data context/);
  });

  it("resolve own properties only", () => {
    expect(lookupPath(data, "numbers.rules")).toBe(526);
    for (const path of ["constructor", "numbers.__proto__", "numbers.rules.toFixed"]) {
      expect(() => lookupPath(data, path), path).toThrow(/no data at/);
    }
  });

  it("keep fill placeholders and copy directives working beside data directives", () => {
    const strings = { k: "{turns} turns" };
    const source = "{{copy:k|turns=numbers.rules}} / {{data:numbers.rules|int}}";
    const html = renderFragment(fragment(source), copyOf("en", strings), data);
    expect(html).toBe("526 turns / 526");
  });
});

describe("the data context", () => {
  const numbers = { rules: 526 };

  it("hands the numbers to a registered provider and exposes its result by name", () => {
    const providers = { calc: ({ numbers: given, lang }) => ({ twice: given.rules * 2, lang: lang.length }) };
    const context = buildDataContext({ numbers, providers, lang: "en" });
    expect(lookupPath(context, "calc.twice")).toBe(1052);
    expect(lookupPath(context, "numbers.rules")).toBe(526);
    expect(buildDataContext({ numbers, providers: {}, lang: "en" })).toEqual({ numbers });
  });

  it("refuses a provider that would replace the numbers namespace", () => {
    expect(() => buildDataContext({ numbers, providers: { numbers: () => ({}) }, lang: "en" })).toThrow(
      /collides/,
    );
  });
});

describe("runtime keys", () => {
  function webWith(keys) {
    const webDir = join(workspace(), "web");
    mkdirSync(join(webDir, "data"), { recursive: true });
    writeJson(join(webDir, "data", "runtime_keys.json"), keys);
    return webDir;
  }

  it("point at numbers outside the red-line data", () => {
    const keys = readRuntimeKeys(REAL_WEB);
    expect(keys.copy.length).toBeGreaterThan(0);
    for (const path of Object.values(keys.numbers)) {
      expect(path.startsWith("red_lines")).toBe(false);
    }
  });

  it("reject a number path into red_lines, a duplicate key or a malformed list", () => {
    const redLine = { copy: [], numbers: { x: "red_lines.0.results.gist.raw.failures" } };
    expect(() => readRuntimeKeys(webWith(redLine))).toThrow(/withheld data red_lines/);
    expect(() => readRuntimeKeys(webWith({ copy: ["a", "a"], numbers: {} }))).toThrow(/duplicate/);
    expect(() => readRuntimeKeys(webWith({ copy: [1], numbers: {} }))).toThrow(/list of strings/);
    expect(() => readRuntimeKeys(webWith({ copy: [], numbers: [] }))).toThrow(/numbers must map/);
    expect(() => readRuntimeKeys(webWith({ copy: [], numbers: { x: "" } }))).toThrow(/path string/);
  });

  it("pick only finite numbers from the benchmarks", () => {
    const benchmarks = { a: { n: 5, s: "5", bad: null } };
    expect(pickNumbers(benchmarks, { five: "a.n" })).toEqual({ five: 5 });
    expect(() => pickNumbers(benchmarks, { x: "a.s" })).toThrow(/not a finite number/);
    expect(() => pickNumbers(benchmarks, { x: "a.bad" })).toThrow(/not a finite number/);
    expect(() => pickNumbers(benchmarks, { x: "a.missing" })).toThrow(/no data at/);
  });
});

describe("the runtime data block", () => {
  const keys = { copy: ["ui.send"] };
  const copy = copyOf("en", { "ui.send": "Send </script><b>&", "ui.other": "not listed" });

  it("holds the listed keys only, and cannot close its own script tag", () => {
    const turnstile = { sitekey: "k", action: "a" };
    const html = runtimeBlock({ keys, copy, numbers: { rules: 526 }, pricing: { default: "m" }, turnstile });
    expect(html.match(/<\/script>/g)).toHaveLength(1);
    const payload = JSON.parse(BLOCK.exec(html)[1]);
    expect(payload).toEqual({
      lang: "en",
      copy: { "ui.send": "Send </script><b>&" },
      numbers: { rules: 526 },
      pricing: { default: "m" },
      turnstile,
    });
    expect(html).not.toContain("ui.other");
  });

  it("reads the sitekey and action from runtime.json and refuses a file without either", () => {
    const webDir = copyOfWeb();
    const { turnstile } = JSON.parse(readFileSync(join(REAL_WEB, "data", "runtime.json"), "utf8"));
    expect(readTurnstile(webDir)).toEqual(turnstile);
    writeJson(join(webDir, "data", "runtime.json"), { turnstile: { sitekey: "k", action: "", extra: 1 } });
    expect(() => readTurnstile(webDir)).toThrow(/turnstile\.action/);
    writeJson(join(webDir, "data", "runtime.json"), {});
    expect(() => readTurnstile(webDir)).toThrow(/turnstile\.sitekey/);
  });

  it("reads the link file, lets the research link be empty or missing, and refuses a link that is not text", () => {
    const webDir = copyOfWeb();
    expect(readLinks(webDir)).toEqual({ research_article: "" });
    writeJson(join(webDir, "data", "links.json"), { research_article: "https://x.test/a" });
    expect(readLinks(webDir)).toEqual({ research_article: "https://x.test/a" });
    writeJson(join(webDir, "data", "links.json"), {});
    expect(readLinks(webDir)).toEqual({ research_article: "" });
    writeJson(join(webDir, "data", "links.json"), { research_article: 5 });
    expect(() => readLinks(webDir)).toThrow(/research_article must be a string/);
    writeJson(join(webDir, "data", "links.json"), []);
    expect(() => readLinks(webDir)).toThrow(/must map a name to a link/);
  });

  it("does not take a key that every object has for a copy string", () => {
    expect(() => runtimeBlock({ keys: { copy: ["toString"] }, copy, numbers: {}, pricing: {} })).toThrow(
      /runtime key toString is missing/,
    );
  });

  it("fails loudly when a listed key is missing from the copy", () => {
    expect(() => runtimeBlock({ keys: { copy: ["ui.nope"] }, copy, numbers: {}, pricing: {} })).toThrow(
      /runtime key ui\.nope is missing/,
    );
  });
});

describe("the built pages", () => {
  function build(webDir, providers = {}) {
    const outDir = join(workspace(), "out");
    buildSite({ webDir, outDir, entry: ENTRY, providers });
    return outDir;
  }

  const read = (outDir, page) => readFileSync(join(outDir, page, "index.html"), "utf8");

  it("carry exactly the whitelisted runtime keys and numbers in every language", () => {
    const outDir = build(copyOfWeb());
    const keys = readRuntimeKeys(REAL_WEB);
    for (const page of PAGES) {
      const payload = JSON.parse(BLOCK.exec(read(outDir, page))[1]);
      expect(Object.keys(payload).sort(), page).toEqual(["copy", "lang", "numbers", "pricing", "turnstile"]);
      expect(Object.keys(payload.copy).sort(), page).toEqual([...keys.copy].sort());
      expect(Object.keys(payload.numbers).sort(), page).toEqual(Object.keys(keys.numbers).sort());
    }
    const pricing = JSON.parse(readFileSync(join(REAL_WEB, "data", "pricing.json"), "utf8"));
    expect(JSON.parse(BLOCK.exec(read(outDir, "opengisting"))[1]).pricing).toEqual(pricing);
    const { turnstile } = JSON.parse(readFileSync(join(REAL_WEB, "data", "runtime.json"), "utf8"));
    for (const page of PAGES) {
      expect(JSON.parse(BLOCK.exec(read(outDir, page))[1]).turnstile, page).toEqual(turnstile);
    }
    const zh = JSON.parse(BLOCK.exec(read(outDir, "zh-CN/opengisting"))[1]);
    expect(zh.copy["ui.error"]).toBe(JSON.parse(readFileSync(join(REAL_WEB, "copy", "zh-CN.json"), "utf8")).strings["ui.error"]);
  });

  it("never ship the red lines, in any file", () => {
    const outDir = build(copyOfWeb());
    const metrics = JSON.parse(readFileSync(join(REAL_WEB, "data", "benchmarks.json"), "utf8")).red_lines.map(
      (line) => line.metric,
    );
    expect(metrics.length).toBeGreaterThan(0);
    for (const file of allFiles(outDir)) {
      const text = readFileSync(file, "utf8");
      for (const needle of ["red_lines", ...metrics]) {
        expect(text, `${file} ${needle}`).not.toContain(needle);
      }
    }
  });

  it("render section fragments with data from the benchmarks and from a provider", () => {
    const webDir = copyOfWeb();
    rmSync(join(webDir, "sections"), { recursive: true, force: true });
    mkdirSync(join(webDir, "sections"));
    writeFileSync(
      join(webDir, "sections", "20-fig.html"),
      '<p id="n">{{data:numbers.rulesFull|int}} to {{data:numbers.rulesGist|int}}, {{data:calc.month|tokens}}</p>',
    );
    const providers = { calc: ({ numbers }) => ({ month: numbers.rulesFull * 1e6 }) };
    const outDir = build(webDir, providers);
    expect(read(outDir, "opengisting")).toContain('<p id="n">526 to 19, 526 M</p>');
    expect(read(outDir, "zh-CN/opengisting")).toContain('<p id="n">526 to 19, 5.26 亿</p>');
    expect(read(outDir, "ja/opengisting")).toContain('<p id="n">526 to 19, 526 M</p>');
  });

  it("follow the benchmarks file when its numbers change", () => {
    const webDir = copyOfWeb();
    rmSync(join(webDir, "sections"), { recursive: true, force: true });
    mkdirSync(join(webDir, "sections"));
    writeFileSync(join(webDir, "sections", "20-fig.html"), "<p>{{data:numbers.rulesFull|int}}</p>");
    const path = join(webDir, "data", "benchmarks.json");
    const benchmarks = JSON.parse(readFileSync(path, "utf8"));
    benchmarks.tokens.full.rules_tokens_per_call = 612;
    benchmarks.composition.full_call_tokens = 612 + benchmarks.composition.tools_tokens_per_call + benchmarks.composition.chat_tokens_per_call;
    benchmarks.composition.saved_per_call = 612 - benchmarks.tokens.gist.rules_tokens_per_call;
    writeJson(path, benchmarks);
    expect(read(build(webDir), "opengisting")).toContain("<p>612</p>");
  });

  it("fail the build for a whitelisted number under red_lines, a missing copy key or a bad path", () => {
    const withRedLine = copyOfWeb();
    editKeys(withRedLine, (keys) => ({ ...keys, numbers: { x: "red_lines.0.min_cases" } }));
    expect(() => build(withRedLine)).toThrow(/withheld data red_lines/);
    const withMissingKey = copyOfWeb();
    editKeys(withMissingKey, (keys) => ({ ...keys, copy: [...keys.copy, "ui.nope"] }));
    expect(() => build(withMissingKey)).toThrow(/ui\.nope/);
    const withBadPath = copyOfWeb();
    editKeys(withBadPath, (keys) => ({ ...keys, numbers: { x: "tokens.nope" } }));
    expect(() => build(withBadPath)).toThrow(/no data at tokens\.nope/);
  });

  it("keep the key list itself out of the public output", () => {
    const outDir = build(copyOfWeb());
    expect(readdirSync(join(outDir, "opengisting", "data"))).not.toContain("runtime_keys.json");
  });
});

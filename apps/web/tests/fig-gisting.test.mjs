import { readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { buildPages, readCopy, textOf } from "./page-helpers.mjs";

const LANGS = ["en", "zh-CN"];
const pages = buildPages();
const FIXTURE = {
  rulesFull: 612,
  rulesGist: 21,
  tools: 400,
  chat: 50,
  fullCall: 1062,
  gistCall: 471,
  saved: 591,
};
const changed = buildPages((webDir) => editBenchmarks(webDir, FIXTURE));

function editBenchmarks(webDir, values) {
  const path = `${webDir}/data/benchmarks.json`;
  const doc = JSON.parse(readFileSync(path, "utf8"));
  doc.tokens.full.rules_tokens_per_call = values.rulesFull;
  doc.tokens.gist.rules_tokens_per_call = values.rulesGist;
  doc.composition.tools_tokens_per_call = values.tools;
  doc.composition.chat_tokens_per_call = values.chat;
  doc.composition.full_call_tokens = values.fullCall;
  doc.composition.gist_call_tokens = values.gistCall;
  doc.composition.saved_per_call = values.saved;
  writeFileSync(path, JSON.stringify(doc));
}

const section = (built, lang = "en") => built.doc(lang).querySelector("#gisting");
const bigs = (built, lang = "en") =>
  [...section(built, lang).querySelectorAll(".og-big")].map((node) => node.firstChild.textContent);
const bars = (built) =>
  [...section(built).querySelectorAll(".og-cbar")].map((bar) =>
    [...bar.children].map((part) => Number(/flex:(\d+) /.exec(part.getAttribute("style"))[1])),
  );
const chip = (built) => textOf(section(built).querySelector(".og-chip"));
const legend = (built) => [...section(built).querySelectorAll(".og-cleg li")].map(textOf);

describe("figure two, the rulebook against the trained tokens", () => {
  it("shows 526 → 19 for the rules and 968 → 461 for a whole call", () => {
    for (const lang of LANGS) {
      expect(bigs(pages, lang), lang).toEqual(["526", "19"]);
    }
    expect(chip(pages)).toBe("968 → 461");
    expect([...section(pages).querySelectorAll(".og-tot")].map(textOf)).toEqual(["968", "461"]);
  });

  it("lists the parts with tools 395, chat history 47 and the 507 saved", () => {
    const copy = readCopy("en");
    expect(legend(pages)).toEqual([
      `${copy["ui.part_rules"]} 526 → 19`,
      `${copy["ui.part_tools"]} 395`,
      `${copy["ui.part_history"]} 47`,
      `${copy["gisting.ghost"]}: 507`,
    ]);
    expect(copy["gisting.ghost"]).toBe("rules no longer read");
  });

  it("takes every number from the data: change the benchmarks and the page follows", () => {
    expect(bigs(changed)).toEqual(["612", "21"]);
    expect(chip(changed)).toBe("1,062 → 471");
    const copy = readCopy("en");
    expect(legend(changed)).toEqual([
      `${copy["ui.part_rules"]} 612 → 21`,
      `${copy["ui.part_tools"]} 400`,
      `${copy["ui.part_history"]} 50`,
      `${copy["gisting.ghost"]}: 591`,
    ]);
    expect(bars(changed)).toEqual([
      [612, 400, 50],
      [21, 400, 50, 591],
    ]);
  });

  it("shrinks only the rules segment: tools and history keep their size in both bars", () => {
    const [full, gist] = bars(pages);
    expect(full).toEqual([526, 395, 47]);
    expect(gist.slice(0, 1)).toEqual([19]);
    expect(gist.slice(1, 3)).toEqual(full.slice(1));
    expect(gist[3]).toBe(507);
    expect(gist.reduce((a, b) => a + b)).toBe(full.reduce((a, b) => a + b));
  });

  it("names each bar for assistive tech with its sum", () => {
    const labels = [...section(pages).querySelectorAll(".og-cbar")].map((bar) => [
      bar.getAttribute("role"),
      bar.getAttribute("aria-label"),
    ]);
    const copy = readCopy("en");
    expect(labels).toEqual([
      ["img", `${copy["ui.mode_full"]}: 526 + 395 + 47 = 968`],
      ["img", `${copy["ui.mode_gist"]}: 19 + 395 + 47 = 461`],
    ]);
  });

  it("carries the compressed heading, caption and ghost label in both languages", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const root = section(pages, lang);
      expect(textOf(root.querySelector("h2")), lang).toBe(copy["gisting.title"]);
      expect(textOf(root.querySelector("figcaption"))).toBe(copy["gisting.caption"]);
      expect(textOf(root.querySelector(".og-claim"))).toBe(copy["gisting.claim"]);
    }
    expect(textOf(section(pages).querySelector("h2"))).toBe(
      "Gisting: a few trained tokens replace the rulebook",
    );
    expect(textOf(section(pages).querySelector("figcaption"))).toBe(
      "Average call across 933 test cases. Only the fixed rules shrink.",
    );
  });

  it("draws sixteen trained tiles and three framing tiles for the nineteen tokens", () => {
    const art = section(pages).querySelectorAll(".og-art");
    expect(art[1].querySelectorAll(".og-tile")).toHaveLength(16);
    expect(art[1].querySelectorAll(".og-tile-ghost")).toHaveLength(3);
    expect(art[0].querySelectorAll(".og-doc-line").length).toBeGreaterThan(10);
    for (const node of art) {
      expect(node.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("states a token count only, with no accuracy or red-line figure", () => {
    for (const lang of LANGS) {
      const root = section(pages, lang);
      const text = textOf(root);
      expect(text, lang).not.toMatch(/accura|准确|red.?line|红线|faster|更快/i);
      expect(text, lang).not.toContain("%");
      expect(root.querySelector(".og-cut"), lang).toBeNull();
    }
  });

  it("paints the art with theme tokens, never a fixed colour", () => {
    const html = pages.html("en");
    const fragment = html.slice(html.indexOf('id="gisting"'), html.indexOf("</section>", html.indexOf('id="gisting"')));
    expect(fragment).not.toMatch(/#[0-9A-Fa-f]{3,8}\b/);
    expect(fragment).not.toMatch(/fill="|stroke="/);
    expect(pages.css()).toMatch(/\.og-tile\{fill:var\(--accent\)\}/);
  });

  it("rejects benchmark numbers whose parts do not add up", () => {
    expect(() => buildPages((webDir) => editBenchmarks(webDir, { ...FIXTURE, fullCall: 1000 }))).toThrow(
      /composition: full call is 1000 but its parts add up to 1062/,
    );
    expect(() => buildPages((webDir) => editBenchmarks(webDir, { ...FIXTURE, saved: 500 }))).toThrow(
      /composition: fixed rules before and after/,
    );
  });

  it("stacks on a narrow screen and keeps the bars inside their row", () => {
    const css = pages.css();
    expect(css).toMatch(/@media \(max-width:820px\)\{[^@]*\.og-cmp\{grid-template-columns:1fr\}/);
    expect(css).toMatch(/\.og-cbar\{display:flex;[^}]*min-width:0/);
  });
});

describe("the proportions of the call bars", () => {
  const BIG = { rulesFull: 1526, rulesGist: 21, tools: 400, chat: 50, fullCall: 1976, gistCall: 471, saved: 1505 };

  it("are written as plain numbers a style rule can read, even above a thousand", () => {
    const built = buildPages((webDir) => editBenchmarks(webDir, BIG));
    const styles = [...section(built).querySelectorAll(".og-cbar i")].map((part) => part.getAttribute("style"));
    expect(styles.slice(0, 3)).toEqual(["flex:1526 1 0%", "flex:400 1 0%", "flex:50 1 0%"]);
    expect(styles.join("|")).not.toContain(",");
  });
});

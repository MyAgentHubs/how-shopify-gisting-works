import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { readRules, rulesProvider } from "../scripts/rules.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const scratch = [];

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function webWith(change = () => {}) {
  const root = mkdtempSync(join(tmpdir(), "rules-data-"));
  scratch.push(root);
  const webDir = join(root, "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  change(webDir);
  return webDir;
}

function edit(webDir, file, change) {
  const path = join(webDir, "data", file);
  const document = JSON.parse(readFileSync(path, "utf8"));
  change(document);
  writeFileSync(path, JSON.stringify(document));
}

describe("readRules", () => {
  it("gives the rules text and every tool with its state and the part that draws its marker", () => {
    const rules = readRules(webWith());
    const published = JSON.parse(readFileSync(join(REAL_WEB, "data", "public_rules.json"), "utf8"));
    expect(rules.text).toBe(published.rules);
    expect(rules.tools.map((tool) => [tool.name, tool.state, tool.mark])).toEqual([
      ["handoff_to_human", "demo", "mark-demo"],
      ["lookup_order", "real", "mark-real"],
      ["send_shipping_reminder", "demo", "mark-demo"],
    ]);
    expect(rules.tools[1].description).toBe(published.tools[1].description);
  });

  it("refuses a tool without a state, a state that is neither real nor demo, and a state for no tool", () => {
    expect(() => readRules(webWith((dir) => edit(dir, "tool_states.json", (d) => delete d.lookup_order)))).toThrow(
      /lookup_order has no state/,
    );
    expect(() => readRules(webWith((dir) => edit(dir, "tool_states.json", (d) => (d.lookup_order = "live"))))).toThrow(
      /lookup_order.*real or demo/,
    );
    expect(() => readRules(webWith((dir) => edit(dir, "tool_states.json", (d) => (d.ghost = "demo"))))).toThrow(
      /ghost is not a tool/,
    );
  });

  it("refuses public rules that are malformed", () => {
    expect(() => readRules(webWith((dir) => edit(dir, "public_rules.json", (d) => (d.rules = 1))))).toThrow(TypeError);
    expect(() => readRules(webWith((dir) => edit(dir, "public_rules.json", (d) => (d.tools = [{ name: "x" }]))))).toThrow(
      TypeError,
    );
  });
});

describe("rulesProvider", () => {
  const rules = { text: "t", tools: [] };
  const copy = (badge) => ({ lang: "en", strings: { "rules.badge": badge } });

  it("splits the size badge of the copy into its two ends", () => {
    expect(rulesProvider({ rules, copy: copy("526 → 19 tokens") }).badge).toEqual({ from: "526", to: "19 tokens" });
    expect(rulesProvider({ rules, copy: copy("526 → 19 token") }).badge.to).toBe("19 token");
  });

  it("refuses a badge without exactly one arrow, and a missing rules block", () => {
    expect(() => rulesProvider({ rules, copy: copy("526 to 19") })).toThrow(/rules\.badge/);
    expect(() => rulesProvider({ rules, copy: copy("1 → 2 → 3") })).toThrow(/rules\.badge/);
    expect(() => rulesProvider({ rules, copy: { lang: "en", strings: {} } })).toThrow(/rules\.badge/);
    expect(() => rulesProvider({ rules: null, copy: copy("1 → 2") })).toThrow(TypeError);
  });
});

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildPages } from "./page-helpers.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const PROMPTS = join(REAL_WEB, "..", "..", "prompts");
const MIN_SNIPPET = 12;
const MIN_CHECKED = 50;

function allFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? allFiles(join(entry.parentPath, entry.name)) : [join(entry.parentPath, entry.name)],
  );
}

function leaves(value) {
  if (typeof value === "string") {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(leaves);
  }
  return value !== null && typeof value === "object" ? Object.values(value).flatMap(leaves) : [];
}

const readJson = (...parts) => JSON.parse(readFileSync(join(...parts), "utf8"));
const PRIVATE_NAMES = readJson(REAL_WEB, "scripts", "verify-rules.json").private_names;

describe("what the build keeps private", () => {
  const { outDir } = buildPages();
  const published = allFiles(outDir)
    .filter((file) => !file.endsWith(".png"))
    .map((file) => readFileSync(file, "utf8"))
    .join("\n");
  const rules = readJson(REAL_WEB, "data", "public_rules.json");
  const shown = [
    rules.rules,
    ...rules.tools.flatMap((tool) => [tool.description, tool.parameters]),
    ...["en", "zh-CN"].flatMap((lang) => Object.values(readJson(REAL_WEB, "copy", `${lang}.json`).strings)),
  ].join("\n");

  it("names no policy or word list file", () => {
    for (const name of PRIVATE_NAMES) {
      expect(published, name).not.toContain(name);
    }
  });

  it("carries no phrase from the agent policy or any word list that the page does not already say", () => {
    const privateFiles = readdirSync(PROMPTS).filter((name) => name.endsWith(".json"));
    expect(privateFiles).toContain("agent_policy.json");
    let checked = 0;
    for (const name of privateFiles) {
      for (const phrase of leaves(readJson(PROMPTS, name))) {
        if (phrase.length >= MIN_SNIPPET && !shown.includes(phrase)) {
          checked += 1;
          expect(published, `${name}: ${phrase}`).not.toContain(phrase);
        }
      }
    }
    expect(checked).toBeGreaterThan(MIN_CHECKED);
  });
});

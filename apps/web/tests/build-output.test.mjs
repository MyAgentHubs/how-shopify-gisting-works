import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { buildPages } from "./page-helpers.mjs";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const TSC = createRequire(import.meta.url).resolve("typescript/bin/tsc");
const BUILD_CONFIG = join(REPO, "apps", "web", "tsconfig.build.json");
const LANGS = ["en", "zh-CN", "ja", "ko"];
const FORBIDDEN = /benchmarks\.json|red_lines|Benchmarks/;
const DATA_PATH = /["'`]\/?(?:opengisting\/)?(data\/[\w.-]+\.json)["'`]/g;
const COPY_PATH = /["'`][^"'`]*\bcopy\/[^"'`]*\.json/;
const scratch = [];

afterAll(() => {
  for (const dir of scratch.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function compiledJs() {
  const out = mkdtempSync(join(tmpdir(), "js-"));
  scratch.push(out);
  execFileSync(process.execPath, [TSC, "-p", BUILD_CONFIG, "--outDir", out], { cwd: REPO, stdio: "pipe" });
  return readdirSync(out, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
    .map((entry) => join(entry.parentPath, entry.name));
}

function offences(source) {
  return [
    ...(FORBIDDEN.test(source) ? ["names the benchmarks data or the red lines"] : []),
    ...(COPY_PATH.test(source) ? ["asks for a copy file"] : []),
  ];
}

const pages = buildPages();
const files = compiledJs();

describe("the built page and its scripts", () => {
  it("never request benchmarks.json or name the red lines, in any script or page", () => {
    expect(files.length).toBeGreaterThan(5);
    for (const file of files) {
      expect(offences(readFileSync(file, "utf8")), file).toEqual([]);
    }
    for (const lang of LANGS) {
      expect(pages.html(lang), lang).not.toMatch(FORBIDDEN);
    }
  });

  it("catches a script that asks for the benchmarks or a copy file", () => {
    expect(offences('fetch("/opengisting/data/benchmarks.json")')).toHaveLength(1);
    expect(offences("const red_lines = []")).toHaveLength(1);
    expect(offences('loadJson(`copy/${lang}.json`)')).toHaveLength(1);
    expect(offences('loadJson("data/limits.json")')).toEqual([]);
  });

  it("ask only for data files the build publishes, so nothing 404s", () => {
    const published = readdirSync(join(pages.outDir, "opengisting", "data"));
    const asked = new Set(files.flatMap((file) => [...readFileSync(file, "utf8").matchAll(DATA_PATH)].map((match) => match[1])));
    expect(asked.size).toBeGreaterThan(0);
    for (const path of asked) {
      expect(published, path).toContain(path.replace("data/", ""));
    }
  });

  it("point at the entry script and the style sheet, and carry the runtime block", () => {
    const html = pages.html("en");
    const entry = /<script type="module" src="([^"]+)"/.exec(html)?.[1];
    expect(entry).toBe("/opengisting/js/apps/web/src/main.js");
    const root = join(pages.outDir, "opengisting");
    expect(existsSync(join(root, "style.css"))).toBe(true);
    expect(html).toContain('id="runtime-data"');
  });
});

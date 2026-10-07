import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { buildSite, clearOutput } from "../scripts/site.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const scripts = JSON.parse(readFileSync(join(REAL_WEB, "..", "..", "package.json"), "utf8")).scripts;
const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function stale(outDir, relative) {
  const path = join(outDir, relative);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, "old");
}

describe("a build into a folder that already has output", () => {
  it("removes what an earlier build left, and keeps only the compiled scripts", () => {
    const root = mkdtempSync(join(tmpdir(), "clean-out-"));
    roots.push(root);
    const outDir = join(root, "out");
    for (const relative of [
      "opengisting/data/benchmarks.json",
      "opengisting/old.css",
      "ja/gone/index.html",
      "stale.txt",
      "opengisting/js/apps/web/src/main.js",
    ]) {
      stale(outDir, relative);
    }
    buildSite({ webDir: REAL_WEB, outDir, entry: "js/apps/web/src/main.js" });
    for (const relative of ["opengisting/data/benchmarks.json", "opengisting/old.css", "ja/gone", "stale.txt"]) {
      expect(existsSync(join(outDir, relative)), relative).toBe(false);
    }
    expect(readFileSync(join(outDir, "opengisting/js/apps/web/src/main.js"), "utf8")).toBe("old");
    expect(existsSync(join(outDir, "opengisting", "index.html"))).toBe(true);
  });
});

describe("a slug that points outside the output folder", () => {
  it("is refused before anything is deleted", () => {
    const root = mkdtempSync(join(tmpdir(), "clean-out-"));
    roots.push(root);
    const outDir = join(root, "nested", "out");
    stale(outDir, "keep-inside.txt");
    stale(root, "keep-outside.txt");
    stale(join(root, "nested"), "keep-sibling.txt");
    for (const slug of ["..", "../..", "a/../.."]) {
      expect(() => clearOutput(outDir, slug), slug).toThrow(/outside/);
    }
    for (const path of [join(outDir, "keep-inside.txt"), join(root, "keep-outside.txt"), join(root, "nested", "keep-sibling.txt")]) {
      expect(existsSync(path), path).toBe(true);
    }
  });
});

describe("the build scripts", () => {
  it("each start by emptying the output folder, so compiled scripts are fresh as well", () => {
    for (const name of ["web:build", "web:build:preview", "web:build:release"]) {
      expect(scripts[name], name).toMatch(/^rm -rf dist\/web && /);
    }
  });
});

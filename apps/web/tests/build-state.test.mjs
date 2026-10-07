import { cpSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { buildSite } from "../scripts/site.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const ENTRY = "js/apps/web/src/main.js";
const PAGES = ["opengisting", "zh-CN/opengisting", "ja/opengisting", "ko/opengisting"];
const STAMP = '<meta name="build-state" content="draft">';
const scripts = JSON.parse(readFileSync(join(REAL_WEB, "..", "..", "package.json"), "utf8")).scripts;
const roots = [];

function build(options) {
  const root = mkdtempSync(join(tmpdir(), "build-state-"));
  roots.push(root);
  const webDir = join(root, "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  const outDir = join(root, "out");
  buildSite({ webDir, outDir, entry: ENTRY, ...options });
  return (page) => readFileSync(join(outDir, page, "index.html"), "utf8");
}

afterAll(() => {
  for (const root of roots) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("the build-state meta", () => {
  it("is on every page of a build that is not asked to be a release", () => {
    const read = build({});
    for (const page of PAGES) {
      expect(read(page), page).toContain(STAMP);
    }
  });

  it("is on every page of a preview build too, since the preview is the default build", () => {
    const read = build({ release: false });
    for (const page of PAGES) {
      expect(read(page), page).toContain(STAMP);
    }
  });

  it("is on no page of a release build of approved copy", () => {
    const read = build({ release: true });
    for (const page of PAGES) {
      expect(read(page), page).not.toContain("build-state");
    }
  });

  it("is requested for release only by the release script", () => {
    expect(scripts["web:build:release"]).toContain("cli.mjs --release");
    expect(scripts["web:build:release"]).toMatch(/verify-output\.mjs --release$/);
    expect(scripts["web:build"]).not.toContain("--release");
    expect(scripts["web:build:preview"]).not.toContain("--release");
    expect(scripts["web:build:preview"]).toContain("--preview");
  });

  it("is never traded for a visible banner on an approved build", () => {
    expect(build({})("opengisting")).not.toContain("draft-banner");
  });
});

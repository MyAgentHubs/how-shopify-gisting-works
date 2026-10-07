import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { assembleStyles } from "../scripts/styles.mjs";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const scratch = [];

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function webWith(files) {
  const webDir = mkdtempSync(join(tmpdir(), "styles-"));
  scratch.push(webDir);
  mkdirSync(join(webDir, "styles"));
  for (const [name, css] of Object.entries(files)) {
    writeFileSync(join(webDir, "styles", name), css);
  }
  return webDir;
}

describe("assembleStyles", () => {
  it("joins the slices in file name order and ignores other files", () => {
    const webDir = webWith({ "20-b.css": "b{}", "10-a.css": "a{}", "notes.txt": "x{}" });
    expect(assembleStyles(webDir)).toBe("a{}\nb{}\n");
  });

  it("builds the committed slices as their plain concatenation, tokens first, the element base second and no leftovers", () => {
    const read = (name) => readFileSync(join(REAL_WEB, "styles", name), "utf8");
    const names = readdirSync(join(REAL_WEB, "styles")).sort();
    expect(names[0]).toBe("00-tokens.css");
    expect(names[1]).toBe("02-base.css");
    expect(names.filter((name) => /legacy/.test(name))).toEqual([]);
    expect(assembleStyles(REAL_WEB)).toBe(names.map(read).join(""));
  });

  it("carries the element base that the sections rely on", () => {
    const css = assembleStyles(REAL_WEB);
    for (const rule of ["*{box-sizing:border-box}", "body{margin:0", "[hidden]{display:none!important}", ":focus-visible{"]) {
      expect(css, rule).toContain(rule);
    }
  });

  it("starts with light-only design tokens", () => {
    const tokens = readFileSync(join(REAL_WEB, "styles", "00-tokens.css"), "utf8");
    expect(tokens).toMatch(/^:root\{/);
    expect(tokens).not.toContain("prefers-color-scheme");
    expect(tokens).not.toContain("--teal");
  });

  it("ships the light theme only", () => {
    const css = assembleStyles(REAL_WEB);
    expect(css).not.toContain("prefers-color-scheme");
    expect(css).toContain(":root{color-scheme:light}");
    expect(css).not.toMatch(/color-scheme:\s*light\s+dark/);
  });

  it("refuses a slice that carries the www header chrome, naming the file", () => {
    for (const css of [
      "header.mh-global{top:0}",
      ".mh-brand{color:red}",
      ".mh-language{margin:0}",
      "x .mh-shell{gap:1px}",
    ]) {
      const webDir = webWith({ "10-ok.css": "a{}", "20-bad.css": css });
      expect(() => assembleStyles(webDir), css).toThrow(/20-bad\.css/);
    }
  });

  it("lets a slice style the footer brand link that www imports", () => {
    const webDir = webWith({ "10-a.css": ".mh-footer-brand{color:red}" });
    expect(assembleStyles(webDir)).toBe(".mh-footer-brand{color:red}\n");
  });

  it("refuses an empty styles directory", () => {
    expect(() => assembleStyles(webWith({}))).toThrow(/no style slices/);
  });
});

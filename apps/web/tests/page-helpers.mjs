import { cpSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { afterAll } from "vitest";
import { buildSite } from "../scripts/site.mjs";

export const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const ENTRY = "js/apps/web/src/main.js";
const PAGES = { en: "opengisting", "zh-CN": "zh-CN/opengisting", ja: "ja/opengisting", ko: "ko/opengisting" };
const roots = [];

function webCopy(change = () => {}) {
  const root = mkdtempSync(join(tmpdir(), "page-"));
  roots.push(root);
  const webDir = join(root, "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  change(webDir);
  return { root, webDir };
}

export function buildPages(change) {
  const { root, webDir } = webCopy(change);
  const outDir = join(root, "out");
  buildSite({ webDir, outDir, entry: ENTRY });
  return {
    outDir,
    html: (lang) => readFileSync(join(outDir, PAGES[lang], "index.html"), "utf8"),
    css: () => readFileSync(join(outDir, "opengisting", "style.css"), "utf8"),
    doc: (lang) => new JSDOM(readFileSync(join(outDir, PAGES[lang], "index.html"), "utf8")).window.document,
  };
}

export function readCopy(lang) {
  return JSON.parse(readFileSync(join(REAL_WEB, "copy", `${lang}.json`), "utf8")).strings;
}

export const textOf = (node) => node.textContent.replace(/\s+/g, " ").trim();

afterAll(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

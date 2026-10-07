import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
export const TODAY = new Date("2026-10-06T00:00:00Z");
export const REAL_EMAIL = "abcdefghij@orders.example.com";
export const REAL_SITEKEY = "0x4AAAAAAAabcdefghijklmn";
export const REAL_LINK = "https://www.myagenthubs.com/research/gisting";
const scratch = [];

export function cleanUpScratch() {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
}

export function readJson(webDir, relative) {
  return JSON.parse(readFileSync(join(webDir, relative), "utf8"));
}

export function editJson(webDir, relative, change) {
  const document = readJson(webDir, relative);
  change(document);
  writeFileSync(join(webDir, relative), JSON.stringify(document));
}

export function clearedWeb() {
  const root = mkdtempSync(join(tmpdir(), "release-lock-"));
  scratch.push(root);
  const webDir = join(root, "web");
  cpSync(REAL_WEB, webDir, { recursive: true });
  editJson(webDir, "data/example_orders.json", (document) => {
    for (const row of document.examples) {
      if ("email" in row) {
        row.email = REAL_EMAIL;
      }
    }
  });
  editJson(webDir, "data/runtime.json", (document) => {
    document.turnstile.sitekey = REAL_SITEKEY;
  });
  editJson(webDir, "data/links.json", (document) => {
    for (const key of Object.keys(document)) {
      document[key] = REAL_LINK;
    }
  });
  editJson(webDir, "data/pricing.json", (document) => {
    document.accessed = "2026-10-05";
  });
  return webDir;
}

export const reasons = (findings) => findings.map((finding) => `${finding.file}: ${finding.reason}`);

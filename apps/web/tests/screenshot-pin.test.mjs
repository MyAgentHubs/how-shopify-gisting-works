import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildPages, REAL_WEB } from "./page-helpers.mjs";

const pin = JSON.parse(readFileSync(join(REAL_WEB, "data/screenshot_pin.json"), "utf8"));
const { languages } = JSON.parse(readFileSync(join(REAL_WEB, "product.json"), "utf8"));
const pages = buildPages();

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function webpDimensions(bytes) {
  expect(bytes.toString("ascii", 0, 4)).toBe("RIFF");
  expect(bytes.toString("ascii", 8, 16)).toBe("WEBPVP8 ");
  expect([...bytes.subarray(23, 26)]).toEqual([0x9d, 0x01, 0x2a]);
  return { width: bytes.readUInt16LE(26) & 0x3fff, height: bytes.readUInt16LE(28) & 0x3fff };
}

function imageProblems(doc) {
  const image = doc.querySelector("img.og-moreimg");
  if (!image) return ["missing image"];
  const problems = ["width", "height"].filter((key) => image.getAttribute(key) !== String(pin[key]));
  if (!image.getAttribute("src")?.endsWith(pin.file)) problems.push("src");
  return problems;
}

describe("pinned store screenshot", () => {
  it("pins the source hash and real lossy VP8 dimensions", () => {
    const bytes = readFileSync(join(REAL_WEB, "assets", pin.file));
    expect(sha256(bytes)).toBe(pin.sha256);
    expect(webpDimensions(bytes)).toEqual({ width: pin.width, height: pin.height });
  });

  it.each(languages.map(({ code }) => code))("pins the image attributes in %s", (lang) => {
    expect(imageProblems(pages.doc(lang))).toEqual([]);
  });

  it("pins the built screenshot hash", () => {
    expect(sha256(readFileSync(join(pages.outDir, "opengisting", pin.file)))).toBe(pin.sha256);
  });

  it("detects a wrong width in a copy of a built page", () => {
    const doc = pages.doc(languages[0].code).cloneNode(true);
    expect(imageProblems(doc)).toEqual([]);
    doc.querySelector("img.og-moreimg").setAttribute("width", String(pin.width + 1));
    expect(imageProblems(doc)).toEqual(["width"]);
  });
});

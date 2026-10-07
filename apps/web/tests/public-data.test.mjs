import { readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildPages } from "./page-helpers.mjs";

const PUBLISHED = ["limits.json", "runtime.json"];

describe("the data directory of a built page", () => {
  it("publishes only the two files the page and the www import need", () => {
    const pages = buildPages();
    expect(readdirSync(join(pages.outDir, "opengisting", "data")).sort()).toEqual(PUBLISHED);
  });

  it("does not publish a file that nobody listed, whatever its name", () => {
    const pages = buildPages((webDir) => {
      for (const name of ["surprise.json", "notes.txt", "limits-backup.json", "internal_source.json"]) {
        writeFileSync(join(webDir, "data", name), "{}");
      }
    });
    expect(readdirSync(join(pages.outDir, "opengisting", "data")).sort()).toEqual(PUBLISHED);
  });
});

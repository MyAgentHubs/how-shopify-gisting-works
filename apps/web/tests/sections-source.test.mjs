import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REAL_WEB } from "./page-helpers.mjs";

const DIR = join(REAL_WEB, "sections");
const files = readdirSync(DIR).filter((name) => name.endsWith(".html"));
const parts = readdirSync(join(DIR, "parts")).map((name) => join("parts", name));

function visibleLetters(source) {
  return source
    .replace(/<svg\b[\s\S]*?<\/svg>/g, "")
    .replace(/<code>[^<]*<\/code>/g, "")
    .replace(/\{\{[^{}]*\}\}/g, "")
    .replace(/<[^>]*>/g, "")
    .match(/\p{L}+/gu);
}

describe("section fragments", () => {
  it("exist, in order, starting with the hero", () => {
    expect(files.length).toBeGreaterThan(0);
    expect(files[0]).toBe("00-hero.html");
  });

  it("hold no readable words of their own: every sentence comes from a copy key", () => {
    for (const name of files) {
      expect(visibleLetters(readFileSync(join(DIR, name), "utf8")), name).toBeNull();
    }
  });

  it("keeps shared parts in their own folder, each holding no words of its own", () => {
    expect(parts).toContain(join("parts", "panda-divider.html"));
    for (const name of parts) {
      expect(name).toMatch(/\.html$/);
      expect(visibleLetters(readFileSync(join(DIR, name), "utf8")), name).toBeNull();
    }
  });

  it("see words that someone typed into a fragment", () => {
    expect(visibleLetters("<p>Hello {{copy:a}}</p>")).toEqual(["Hello"]);
    expect(visibleLetters("<p>你好</p>")).toEqual(["你好"]);
    expect(visibleLetters("<p>{{copy:a}} 19 → 16</p>")).toBeNull();
  });
});

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "styles", "50-chat.css"),
  "utf8",
);
const REDUCED_BLOCK = /@media \(prefers-reduced-motion:reduce\)\{[^{}]*\{[^{}]*\}[^{}]*\}/;
const HOVER_BLOCK = /@media \(hover:hover\)\{((?:[^{}]*\{[^{}]*\})*)[^{}]*\}/;

describe("the example card hover motion", () => {
  it("sits inside a hover-capable media query so a tap on a touch screen does not leave it stuck", () => {
    const block = HOVER_BLOCK.exec(css)?.[1] ?? "";
    expect(block).toMatch(/\.og-exbtn:hover\{[^}]*translateY/);
    expect(block).toMatch(/\.og-exbtn:hover \.og-exgo\{[^}]*translateX/);
  });

  it("appears nowhere outside that media query except in the reduced motion override", () => {
    const outside = css.replace(HOVER_BLOCK, "").replace(REDUCED_BLOCK, "");
    expect(outside).not.toMatch(/\.og-exbtn:hover/);
  });

  it("is still cancelled by a press and by reduced motion", () => {
    expect(css).toMatch(/\.og-exbtn:active\{transform:none\}/);
    expect(css).toMatch(/@media \(prefers-reduced-motion:reduce\)\{[^}]*\.og-exbtn:hover[^}]*transform:none/);
  });
});

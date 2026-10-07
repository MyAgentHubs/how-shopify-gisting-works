import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildPages } from "./page-helpers.mjs";

const edit = (file, change) => (webDir) => {
  const path = join(webDir, file);
  writeFileSync(path, change(readFileSync(path, "utf8")));
};
const HERO = "sections/00-hero.html";
const TITLE = "{{copy:hero.title}}";

describe("a directive that did not render", () => {
  it.each([
    ["spaces inside the braces", "{{ copy:hero.title }}"],
    ["a missing closing brace", "{{copy:hero.title}"],
    ["a missing colon", "{{copy hero.title}}"],
    ["empty braces", "{{}}"],
    ["a lone closing pair", "oops }}"],
    ["a template token", "%UNFILLED_TOKEN%"],
  ])("fails the build in a section: %s", (_name, junk) => {
    expect(() => buildPages(edit(HERO, (source) => source.replace(TITLE, `${TITLE} ${junk}`)))).toThrow(
      /sections: .*left over/,
    );
  });

  it.each(["{{ copy:footer.x }}", "%FOOTER_LEFT%"])("fails the build in the footer: %s", (junk) => {
    expect(() => buildPages(edit("footer.html", (source) => `${source}\n${junk}`))).toThrow(
      /footer: .*left over/,
    );
  });

  it("does not look inside the runtime data", () => {
    const html = buildPages(
      edit("copy/en.json", (source) => source.replace('"ui.error": "', '"ui.error": "{{kept}} %KEPT% ')),
    ).html("en");
    expect(html).toContain("{{kept}}");
  });
});

import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyZh from "../copy/zh-CN.json";
import states from "../data/tool_states.json";
import rulesSource from "../sections/50-rules.html?raw";
import rulesStyle from "../styles/60-rules.css?raw";
import { buildPages } from "./page-helpers.mjs";
import { publicRules } from "./support.ts";

const MIN_SNIPPET = 12;
const LABEL: Record<string, string> = { real: copyEn.strings["state.real"], demo: copyEn.strings["state.demo"] };
const pages = buildPages();
const sectionOf = (lang: string): Element => {
  const section = new DOMParser().parseFromString(pages.html(lang), "text/html").querySelector("#rules");
  if (section === null) {
    throw new Error(`no #rules section in ${lang}`);
  }
  return section;
};
const textOf = (node: Element | null): string => (node?.textContent ?? "").replace(/\s+/g, " ").trim();

describe("the rules block", () => {
  it("has a numbered eyebrow, the main title and the size badge, in both languages", () => {
    for (const [lang, copy] of [["en", copyEn], ["zh-CN", copyZh]] as const) {
      const section = sectionOf(lang);
      expect(textOf(section.querySelector(".og-kicker")), lang).toBe(`5 · ${copy.strings["rules.eyebrow"]}`);
      expect(textOf(section.querySelector("h2")), lang).toBe(copy.strings["rules.heading"]);
      const [from, to] = [...section.querySelectorAll(".og-nbadge [aria-hidden] b")].map(textOf);
      expect(`${from ?? ""} → ${to ?? ""}`, lang).toBe(copy.strings["rules.badge"]);
      expect(textOf(section.querySelector(".og-nbadge .og-vh")), lang).toBe(copy.strings["rules.badge"]);
    }
    expect(copyEn.strings["rules.eyebrow"]).toBe("What Gisting compresses");
    expect(copyEn.strings["rules.heading"]).toBe("The full service rules");
    expect(copyEn.strings["rules.badge"]).toBe("526 → 19 tokens");
  });

  it("introduces itself with one merged sentence about security, and no separate fine print", () => {
    const section = sectionOf("en");
    expect(textOf(section.querySelector(".og-sintro"))).toBe(copyEn.strings["rules.intro"]);
    expect(section.querySelectorAll(".og-sintro")).toHaveLength(1);
    expect(section.querySelector(".og-sfine")).toBeNull();
  });

  it("holds the full rules, word for word, in a folded card", () => {
    const card = sectionOf("en").querySelector("details") ?? sectionOf("en");
    expect(card.hasAttribute("open")).toBe(false);
    expect(textOf(card.querySelector("summary"))).toContain(copyEn.strings["rules.open"]);
    expect(textOf(card.querySelector("summary small"))).toBe(copyEn.strings["rules.badge"]);
    expect(card.querySelector("pre")?.textContent).toBe(publicRules.rules);
  });

  it("holds the three tools, in a folded card, with the tools intro and their count", () => {
    const card = sectionOf("en").querySelectorAll("details")[1] ?? sectionOf("en");
    expect(card.hasAttribute("open")).toBe(false);
    expect(textOf(card.querySelector("summary small"))).toBe("3");
    expect(textOf(card.querySelector(".og-in > p"))).toBe(copyEn.strings["tools.intro"]);
    expect(card.querySelectorAll(".og-tl > li")).toHaveLength(3);
  });

  it("shows each tool word for word, marked Real or Demo", () => {
    const tools = [...sectionOf("en").querySelectorAll(".og-tl > li")];
    expect(tools.map((tool) => tool.className)).toEqual(["og-demo", "og-real", "og-demo"]);
    publicRules.tools.forEach((expected, index) => {
      const tool = tools[index] ?? sectionOf("en");
      const state = states[expected.name as keyof typeof states];
      expect(tool.querySelector("code")?.textContent).toBe(expected.name);
      expect(tool.querySelector("p")?.textContent).toBe(expected.description);
      expect(tool.querySelector("pre")?.textContent).toBe(expected.parameters);
      expect(textOf(tool.querySelector(".og-mk"))).toBe(LABEL[state]);
    });
  });

  it("is written from the data, not typed into the section", () => {
    expect(rulesSource).not.toContain(publicRules.rules.slice(0, MIN_SNIPPET * 2));
    for (const tool of publicRules.tools) {
      expect(rulesSource).not.toContain(tool.description);
    }
  });

  it("follows the language of the page but keeps the rules text as the model sees it", () => {
    const section = sectionOf("zh-CN");
    expect(textOf(section.querySelector(".og-sintro"))).toBe(copyZh.strings["rules.intro"]);
    expect(section.querySelector("pre")?.textContent).toBe(publicRules.rules);
  });
});

describe("the rules block's stylesheet", () => {
  it("uses colour tokens only, and its own og- class names", () => {
    expect(rulesStyle).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(rulesStyle).not.toMatch(/(^|[},\s])\.(?!og-)[a-z]/);
  });

  it("keeps the folded cards at a 44px touch target", () => {
    expect(rulesStyle).toMatch(/\.og-dtl>summary\{[^}]*min-height:56px/);
  });
});

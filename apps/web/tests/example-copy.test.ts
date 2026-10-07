import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyZh from "../copy/zh-CN.json";
import { mount } from "./support.ts";

const HELP_KEY = "chat.examples_help";
const HINT_KEYS = [
  "try.example.in_transit_hint",
  "try.example.unfulfilled_hint",
  "try.example.human_hint",
];

function cards(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>(".og-exbtn")];
}

describe("the example cards", () => {
  it("each carry a label and a subtitle", () => {
    mount();
    expect(cards()).toHaveLength(11);
    for (const card of cards()) {
      expect(card.querySelector("b")?.textContent.trim()).toBeTruthy();
      expect(card.querySelector("span")?.textContent.trim()).toBeTruthy();
    }
  });

  it("sit under a line that says what a click does", () => {
    mount();
    const help = document.getElementById("og-ex-h");
    expect(help?.textContent).toBe(copyEn.strings[HELP_KEY as keyof typeof copyEn.strings]);
    expect(document.querySelector(".og-ex")?.getAttribute("aria-describedby")).toBe("og-ex-h");
  });
});

describe("the example-card copy", () => {
  it("has the help line and all three subtitles in en and zh-CN", () => {
    for (const file of [copyEn, copyZh]) {
      const strings = file.strings as Record<string, string>;
      for (const key of [HELP_KEY, ...HINT_KEYS]) {
        expect(strings[key]?.trim(), `${file.lang} ${key}`).toBeTruthy();
      }
    }
  });
});

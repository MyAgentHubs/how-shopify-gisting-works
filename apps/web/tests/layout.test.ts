import { describe, expect, it } from "vitest";
import chatStyle from "../styles/50-chat.css?raw";
import { NARROW_QUERY } from "../src/layout.ts";
import { media, mount, query } from "./support.ts";

function hood(): HTMLDetailsElement {
  const node = query('[data-role="hood"]');
  if (!(node instanceof HTMLDetailsElement)) {
    throw new TypeError("the panel is a details element");
  }
  return node;
}

describe("the Under the hood panel's layout", () => {
  it("is open beside the chat on a wide screen", () => {
    mount();
    expect(hood().open).toBe(true);
  });

  it("starts closed on a narrow screen and opens from its summary line", () => {
    mount({ matchMedia: media(true).matchMedia });
    expect(hood().open).toBe(false);
    query('[data-role="hood"] > summary').click();
    expect(hood().open).toBe(true);
  });

  it("keeps the panel and the chat log in the page on both layouts", () => {
    for (const narrow of [false, true]) {
      mount({ matchMedia: media(narrow).matchMedia });
      expect(document.querySelector('[data-role="hood"] [data-role="panel-body"]')).not.toBeNull();
      expect(document.querySelector('[data-role="log"]')).not.toBeNull();
    }
  });

  it("puts the summary line, with the prompt sizes, inside the summary element", () => {
    mount();
    expect(query('[data-role="hood"] > summary [data-role="drawer-summary"]')).not.toBeNull();
  });
});

describe("the chat stylesheet", () => {
  it("stacks the window at the same breakpoint as the script", () => {
    const width = /max-width: (\d+)px/.exec(NARROW_QUERY)?.[1];
    expect(chatStyle).toContain(`@media (max-width:${width ?? "?"}px)`);
  });

  it("gives the composer and its button a 44px touch target on a narrow screen", () => {
    expect(chatStyle).toMatch(/\.og-composer input,\.og-btn-app\{min-height:44px\}/);
    expect(chatStyle).toMatch(/\.og-exbtn\{[^}]*min-height:44px/);
  });
});

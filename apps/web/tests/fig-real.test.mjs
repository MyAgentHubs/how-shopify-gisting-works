import verifyRules from "../scripts/verify-rules.json" with { type: "json" };
import { describe, expect, it } from "vitest";
import { buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const LANGS = ["en", "zh-CN"];

function figure(lang) {
  return pages.doc(lang).querySelector("#real");
}

function nodeNamed(lang, name) {
  const found = [...figure(lang).querySelectorAll(".og-node")].filter((node) =>
    textOf(node.querySelector("b")).includes(name),
  );
  expect(found, name).toHaveLength(1);
  return found[0];
}

describe("figure one, the request chain", () => {
  it("has the three zones, in order, with their labels", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const zones = [...figure(lang).querySelectorAll(".og-zone")];
      expect(zones.map((zone) => textOf(zone.querySelector(".og-zlabel"))), lang).toEqual([
        copy["real.zone_door"],
        copy["real.zone_agent"],
        copy["real.zone_tools"],
      ]);
    }
  });

  it("lists the three states as a legend and marks every system node with one", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const legend = [...figure(lang).querySelectorAll(".og-legend .og-mk")].map(textOf);
      expect(legend, lang).toEqual([copy["state.real"], copy["state.test"], copy["state.demo"]]);
      for (const node of figure(lang).querySelectorAll(".og-node:not(.og-plain)")) {
        const kind = [...node.classList].find((name) => /^og-(real|test|demo)$/.test(name));
        expect(textOf(node.querySelector(".og-mk")), textOf(node)).toBe(
          copy[`state.${kind.slice(3)}`],
        );
      }
    }
  });

  it("writes the model name in bold inside the agent node, in both languages", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const agent = nodeNamed(lang, copy["real.agent"]);
      const bold = agent.querySelector("small b");
      expect(textOf(bold)).toBe("Qwen3 1.7B");
      expect(textOf(agent.querySelector("small"))).toBe(
        `${copy["fact.model"]}${copy["real.agent_tail"]}`,
      );
    }
  });

  it("lets lookup_order reach the Shopify Admin API and stops the two demo tools", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      const tools = figure(lang).querySelector(".og-tools");
      const rows = [...tools.querySelectorAll(".og-node")].map((node) => [
        textOf(node.querySelector("code")),
        [...node.classList].find((name) => /^og-(real|demo)$/.test(name)),
        node.getAttribute("data-continues"),
      ]);
      expect(rows, lang).toEqual([
        ["lookup_order", "og-real", "true"],
        ["handoff_to_human", "og-demo", "false"],
        ["send_shipping_reminder", "og-demo", "false"],
      ]);
      const after = tools.nextElementSibling;
      expect(after.classList.contains("og-vl")).toBe(true);
      expect(textOf(after)).toBe(copy["real.arrow_label"]);
      const pair = after.nextElementSibling;
      expect(pair.classList.contains("og-pair")).toBe(true);
      const [shopify, arrow, store] = pair.children;
      expect(textOf(shopify.querySelector("b"))).toBe(copy["real.shopify"]);
      expect(shopify.classList.contains("og-real")).toBe(true);
      expect(arrow.classList.contains("og-hl")).toBe(true);
      expect(textOf(store.querySelector("b"))).toBe(copy["real.store"]);
      expect(store.classList.contains("og-test")).toBe(true);
    }
  });

  it("says the demo tools are called for real only once, and drops the retired lines", () => {
    for (const lang of LANGS) {
      const copy = readCopy(lang);
      expect(textOf(figure(lang)).split(copy["real.demo_tool_sub"]), lang).toHaveLength(2);
      expect(copy["real.store_sub"]).toBeUndefined();
    }
    const html = pages.html("en");
    expect(html).not.toContain("Every order here is test data");
    expect(html).not.toContain("Every order here");
  });

  it("names both exceptions in the caption instead of calling everything real", () => {
    for (const lang of LANGS) {
      const caption = textOf(figure(lang).querySelector("figcaption"));
      expect(caption).toBe(readCopy(lang)["real.caption"]);
    }
    expect(textOf(figure("en").querySelector("figcaption"))).toMatch(
      /except the store’s orders \(test data\) and two demo tools/,
    );
  });

  it("hides every icon from assistive tech and names the chain", () => {
    for (const lang of LANGS) {
      const section = figure(lang);
      for (const svg of section.querySelectorAll("svg")) {
        expect(svg.getAttribute("aria-hidden"), lang).toBe("true");
      }
      expect(section.getAttribute("aria-labelledby")).toBe("og-t-real");
      expect(section.querySelector("#og-t-real").tagName).toBe("H2");
      const chain = section.querySelector(".og-chain");
      expect(chain.getAttribute("role")).toBe("group");
      expect(section.querySelector(`#${chain.getAttribute("aria-labelledby")}`)).not.toBeNull();
    }
  });

  it("separates the states by border style as well as colour and label", () => {
    const css = pages.css();
    expect(css).toMatch(/\.og-node\.og-real\{border:1\.5px solid/);
    expect(css).toMatch(/\.og-node\.og-test\{border:1\.5px dashed/);
    expect(css).toMatch(/\.og-node\.og-demo\{border:1\.5px dotted/);
  });

  it("keeps the hardware and hosting details out of the figure", () => {
    for (const lang of LANGS) {
      expect(textOf(figure(lang)), lang).not.toMatch(new RegExp(verifyRules.forbidden.map(({ pattern }) => pattern).join("|"), "i"));
    }
  });

  it("stacks into one column on a narrow screen, with no fixed widths that could overflow", () => {
    const css = pages.css();
    expect(css).toMatch(/@media \(max-width:820px\)\{[^@]*\.og-chain\{grid-template-columns:1fr\}/);
    expect(css).not.toMatch(/\.og-(chain|zone|node|tools|pair)\{[^}]*\bwidth:\d+px/);
  });
});

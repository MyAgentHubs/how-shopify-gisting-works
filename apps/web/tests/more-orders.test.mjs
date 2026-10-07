import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fill } from "../src/copy.ts";
import { verifyOutput } from "../scripts/verify-output.mjs";
import { countVisibleWords } from "../scripts/visible-words.mjs";
import { buildPages, readCopy, REAL_WEB } from "./page-helpers.mjs";

const { orders } = JSON.parse(readFileSync(join(REAL_WEB, "data/public_orders.json"), "utf8"));
const rules = JSON.parse(readFileSync(join(REAL_WEB, "scripts/verify-rules.json"), "utf8"));
const pages = buildPages();

function checkOrders(lang, copy) {
  const doc = pages.doc(lang);
  const details = doc.querySelector("details.og-more");
  expect(doc.querySelectorAll("details.og-more")).toHaveLength(1);
  expect(details.hasAttribute("open")).toBe(false);
  expect(details.previousElementSibling.classList.contains("og-win")).toBe(true);
  expect(details.parentElement.id).toBe("agent");
  expect(details.querySelector("summary").textContent).toBe(copy["try.more.title"]);
  expect(details.children[1].tagName).toBe("P");
  expect(details.children[1].textContent).toBe(copy["try.more.note"]);
  expect(details.children[2].tagName).toBe("DIV");
  expect(details.children[2].classList.contains("og-moregrid")).toBe(true);
  expect(details.children[3].tagName).toBe("IMG");
  const buttons = [...details.querySelectorAll("button.og-morebtn")];
  expect(buttons).toHaveLength(8);
  expect(buttons.map((button) => button.querySelector("span").textContent)).toEqual(orders.map((row) => row.order));
  for (const [index, button] of buttons.entries()) {
    const row = orders[index];
    expect(button.type).toBe("button");
    expect(button.classList.contains("og-exbtn")).toBe(true);
    expect(button.querySelector("b").textContent).toBe(copy[row.label_key]);
    expect(button.dataset.prefill).toBe(fill(copy["chat.prefill_order"], { order: row.order, email: row.email }));
    expect(button.querySelector("svg").getAttribute("aria-hidden")).toBe("true");
  }
  const image = details.querySelector("img");
  expect(image.getAttribute("src")).toBe("/opengisting/shopify-orders.webp");
  expect(image.getAttribute("width")).toBe("1688");
  expect(image.getAttribute("height")).toBe("883");
  expect(image.getAttribute("loading")).toBe("lazy");
  expect(image.getAttribute("decoding")).toBe("async");
  expect(image.getAttribute("alt")).toBe(copy["try.more.alt"]);
}

describe("collapsed sample orders", () => {
  it.each(["en", "zh-CN"])("renders the whitelist and localized copy in %s", (lang) => {
    checkOrders(lang, readCopy(lang));
  });

  it.each(["ja", "ko"])("falls back to English for new copy in %s", (lang) => {
    const own = readCopy(lang);
    const copy = { ...readCopy("en"), ...own };
    checkOrders(lang, copy);
    for (const key of Object.keys(readCopy("en")).filter((key) => key.startsWith("try.more."))) {
      expect(own[key]).toBeUndefined();
      expect(copy[key]).toBe(readCopy("en")[key]);
    }
  });

  it("copies the screenshot unchanged and passes word and output gates", () => {
    const asset = join(pages.outDir, "opengisting/shopify-orders.webp");
    expect(existsSync(asset)).toBe(true);
    expect(readFileSync(asset)).toEqual(readFileSync(join(REAL_WEB, "assets/shopify-orders.webp")));
    expect(countVisibleWords(pages.html("en"), rules.word_scope_ids).total).toBeLessThanOrEqual(rules.max_visible_words);
    expect(verifyOutput({ outDir: pages.outDir })).toEqual([]);
  });
});

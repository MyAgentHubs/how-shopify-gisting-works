import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { publicOrdersProvider, readPublicOrders } from "../scripts/public-orders.mjs";
import { buildPages, readCopy, REAL_WEB } from "./page-helpers.mjs";

const orders = readPublicOrders(REAL_WEB);
const scratch = [];

function ordersDirectory(rows) {
  const webDir = mkdtempSync(join(tmpdir(), "public-orders-"));
  scratch.push(webDir);
  mkdirSync(join(webDir, "data"));
  mkdirSync(join(webDir, "scripts"));
  writeFileSync(
    join(webDir, "scripts", "verify-rules.json"),
    readFileSync(join(REAL_WEB, "scripts", "verify-rules.json")),
  );
  writeFileSync(join(webDir, "data/public_orders.json"), JSON.stringify({ orders: rows }));
  return webDir;
}

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("public order build validation", () => {
  it("reads the row count from the supplied web directory", () => {
    const rows = orders.slice(0, 1);
    const webDir = ordersDirectory(rows);
    const path = join(webDir, "scripts", "verify-rules.json");
    const rules = JSON.parse(readFileSync(path, "utf8"));
    rules.public_order_count = rows.length;
    writeFileSync(path, JSON.stringify(rules));
    expect(readPublicOrders(webDir)).toEqual(rows);
  });

  it.each([7, 9])("rejects %s rows", (count) => {
    const rows = Array.from({ length: count }, (_, index) => orders[index % orders.length]);
    expect(() => readPublicOrders(ordersDirectory(rows))).toThrow(
      new RangeError(`data/public_orders.json: orders must contain exactly 8 rows; got ${count}`),
    );
  });

  it.each([
    ["order", undefined],
    ["email", undefined],
    ["email", ""],
    ["order", " "],
    ["email", " "],
    ["order", 1234],
    ["email", null],
  ])("rejects an invalid %s value %s", (field, value) => {
    const rows = orders.map((row, index) => index === 0 ? { ...row, [field]: value } : row);
    expect(() => readPublicOrders(ordersDirectory(rows))).toThrow(
      new TypeError(`data/public_orders.json: row 1 ${field} must be a non-empty string`),
    );
  });

  it.each(["en", "zh-CN", "ja", "ko"])("rejects an unfilled placeholder when building %s", (lang) => {
    expect(() => buildPages((webDir) => {
      const path = join(webDir, "copy", `${lang}.json`);
      const copy = JSON.parse(readFileSync(path, "utf8"));
      copy.strings["chat.prefill_order"] += " {missing}";
      writeFileSync(path, JSON.stringify(copy));
    })).toThrow(new RangeError(
      `data/public_orders.json: row 1 chat.prefill_order contains unfilled placeholders in the ${lang} copy`,
    ));
  });

  it.each(["{", "}"])("rejects a remaining %s in the final prefill", (brace) => {
    const copy = { lang: "en", strings: readCopy("en") };
    const rows = orders.map((row, index) => index === 0 ? { ...row, email: `${row.email}${brace}` } : row);
    expect(() => publicOrdersProvider({ copy, publicOrders: rows })).toThrow(new RangeError(
      "data/public_orders.json: row 1 chat.prefill_order contains unfilled placeholders in the en copy",
    ));
  });
});

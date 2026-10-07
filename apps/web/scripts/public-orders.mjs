import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fill } from "../src/copy.ts";
import { copyString } from "./copy-resolve.mjs";

const ORDERS_FILE = "data/public_orders.json";
const PREFILL_KEY = "chat.prefill_order";

function validateRow(row, index) {
  for (const field of ["order", "email"]) {
    if (typeof row?.[field] !== "string" || row[field].trim() === "") {
      throw new TypeError(`${ORDERS_FILE}: row ${index + 1} ${field} must be a non-empty string`);
    }
  }
}

export function readPublicOrders(webDir) {
  const rules = JSON.parse(readFileSync(join(webDir, "scripts", "verify-rules.json"), "utf8"));
  const { orders } = JSON.parse(readFileSync(join(webDir, ORDERS_FILE), "utf8"));
  if (!Array.isArray(orders)) {
    throw new TypeError(`${ORDERS_FILE}: orders must be a list`);
  }
  if (orders.length !== rules.public_order_count) {
    throw new RangeError(
      `${ORDERS_FILE}: orders must contain exactly ${rules.public_order_count} rows; got ${orders.length}`,
    );
  }
  orders.forEach(validateRow);
  return orders;
}

function requireKey(copy, key) {
  const text = copyString(copy, key);
  if (text === undefined) {
    throw new RangeError(`${ORDERS_FILE}: copy key ${key} is missing from the ${copy.lang} copy`);
  }
  return text;
}

export function publicOrdersProvider({ copy, publicOrders }) {
  return publicOrders.map((row, index) => {
    const prefill = fill(requireKey(copy, PREFILL_KEY), { order: row.order, email: row.email });
    if (prefill.includes("{") || prefill.includes("}")) {
      throw new RangeError(
        `${ORDERS_FILE}: row ${index + 1} ${PREFILL_KEY} contains unfilled placeholders in the ${copy.lang} copy`,
      );
    }
    return { id: row.id, label: requireKey(copy, row.label_key), order: row.order, prefill };
  });
}

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { URL } from "node:url";
import { JSDOM } from "jsdom";

const RULES = JSON.parse(readFileSync(new URL("./verify-rules.json", import.meta.url), "utf8"));

function readAllowedRows(webDir) {
  const publicRows = JSON.parse(readFileSync(join(webDir, "data", "public_orders.json"), "utf8")).orders;
  const examples = JSON.parse(readFileSync(join(webDir, "data", "example_orders.json"), "utf8")).examples;
  return [...publicRows, ...examples];
}

export function readAllowedOrders(webDir) {
  return new Set(readAllowedRows(webDir).filter((row) => row.order).map((row) => row.order));
}

export function readAllowedEmails(webDir) {
  return new Set(readAllowedRows(webDir).filter((row) => row.email)
    .map((row) => row.email.normalize("NFKC").toLowerCase()));
}

export function emailProblems(text, allowed, name) {
  const emails = new Set((text.normalize("NFKC").match(new RegExp(RULES.order_email, "gi")) ?? [])
    .map((email) => email.toLowerCase()));
  return [...emails].filter((email) => !allowed.has(email))
    .map((email) => `${name}: email ${email} is not in the public or example orders`);
}

function prefillOrders(text) {
  const normalized = text.normalize("NFKC").replace(new RegExp(RULES.order_email, "gi"), " ");
  return (normalized.match(new RegExp(RULES.prefill_order, "g")) ?? [])
    .map((order) => `#${order.replace("#", "").trim()}`);
}

export function prefillProblems(html, allowed, name) {
  const dom = new JSDOM(html);
  const orders = new Set([...dom.window.document.querySelectorAll("[data-prefill]")]
    .flatMap((element) => prefillOrders(element.getAttribute("data-prefill"))));
  dom.window.close();
  return [...orders].filter((order) => !allowed.has(order))
    .map((order) => `${name}: data-prefill order ${order} is not in the public or example orders`);
}

import { readdirSync } from "node:fs";
import { join } from "node:path";
import { comparable, readJson, readLock } from "./lock-config.mjs";
import { readProduct } from "./product.mjs";

const EXAMPLES_FILE = "data/example_orders.json";
const PUBLIC_ORDERS_FILE = "data/public_orders.json";
const RUNTIME_FILE = "data/runtime.json";
const LINKS_FILE = "data/links.json";
const PRICING_FILE = "data/pricing.json";
const COPY_DIR = "copy";
const APPROVED = "approved";
const REVIEW_PASSED = ["approved_draft", "done"];
const MS_PER_DAY = 86_400_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

const unreadable = (file) => [{ file, reason: "cannot be read as JSON" }];
const isPlainObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function orderEmailFindings(file, key, document, { email_shape: shape, placeholder_email: placeholder }) {
  if (document === null || !Array.isArray(document[key])) {
    return unreadable(file);
  }
  return document[key]
    .filter((row) => isPlainObject(row) && "order" in row)
    .flatMap((row) => {
      const email = row.email;
      if (typeof email !== "string" || !shape.test(email)) {
        return [{ file, reason: `the email of ${row.order} is not a demo email address` }];
      }
      return placeholder.test(email)
        ? [{ file, reason: `the email of ${row.order} is still the placeholder` }]
        : [];
    });
}

function emailFindings(webDir, patterns) {
  return [
    ...orderEmailFindings(EXAMPLES_FILE, "examples", readJson(webDir, EXAMPLES_FILE), patterns),
    ...orderEmailFindings(PUBLIC_ORDERS_FILE, "orders", readJson(webDir, PUBLIC_ORDERS_FILE), patterns),
  ];
}

function sitekeyFindings(webDir, { sitekey_shape: shape, test_sitekey: testKey }) {
  const document = readJson(webDir, RUNTIME_FILE);
  if (document === null) {
    return unreadable(RUNTIME_FILE);
  }
  const sitekey = document.turnstile?.sitekey;
  if (typeof sitekey !== "string" || sitekey === "") {
    return [{ file: RUNTIME_FILE, reason: "there is no sitekey" }];
  }
  if (!shape.test(sitekey)) {
    return [{ file: RUNTIME_FILE, reason: "the sitekey is not shaped like a Turnstile site key" }];
  }
  return testKey.test(sitekey) ? [{ file: RUNTIME_FILE, reason: "the sitekey is a Cloudflare test key" }] : [];
}

function linkFindings(webDir, { patterns, requiredLinks }) {
  const document = readJson(webDir, LINKS_FILE);
  if (!isPlainObject(document)) {
    return unreadable(LINKS_FILE);
  }
  const missing = requiredLinks.filter((name) => !Object.hasOwn(document, name));
  const found = missing.map((name) => ({ file: LINKS_FILE, reason: `${name} is missing` }));
  const unready = ([, value]) =>
    value !== "" &&
    (typeof value !== "string" || !patterns.link_shape.test(value) || patterns.placeholder_link.test(value));
  return [
    ...found,
    ...Object.entries(document)
      .filter(unready)
      .map(([name]) => ({ file: LINKS_FILE, reason: `${name} is still a placeholder link` })),
  ];
}

function dayNumber(date) {
  return Math.floor(date.getTime() / MS_PER_DAY);
}

function priceFindings({ webDir, today, maxAgeDays }) {
  const document = readJson(webDir, PRICING_FILE);
  if (document === null) {
    return unreadable(PRICING_FILE);
  }
  const accessed = document.accessed;
  const when = typeof accessed === "string" && DATE.test(accessed) ? new Date(`${accessed}T00:00:00Z`) : null;
  if (when === null || Number.isNaN(when.getTime()) || when.toISOString().slice(0, 10) !== accessed) {
    return [{ file: PRICING_FILE, reason: "accessed is not a YYYY-MM-DD date" }];
  }
  const age = dayNumber(today) - dayNumber(when);
  if (age < 0) {
    return [{ file: PRICING_FILE, reason: `accessed ${accessed} is in the future` }];
  }
  return age > maxAgeDays
    ? [{ file: PRICING_FILE, reason: `accessed ${accessed} is ${age} days old, the limit is ${maxAgeDays}` }]
    : [];
}

function stringFindings(file, strings, pattern) {
  if (!isPlainObject(strings)) {
    return [{ file, reason: "has no strings" }];
  }
  return Object.entries(strings).flatMap(([key, value]) => {
    if (typeof value !== "string") {
      return [{ file, reason: `${key} is not a string` }];
    }
    return pattern.test(comparable(value)) ? [{ file, reason: `${key} is still a placeholder` }] : [];
  });
}

function copyFileFindings({ file, document, pattern, needsReview }) {
  const found = [];
  if (document.status !== APPROVED) {
    found.push({ file, reason: `status is ${document.status}, not ${APPROVED}` });
  }
  if (needsReview && !REVIEW_PASSED.includes(document.native_review)) {
    const state = document.native_review ?? "missing";
    found.push({ file, reason: `native_review is ${state}, not ${REVIEW_PASSED.join(" or ")}` });
  }
  return [...found, ...stringFindings(file, document.strings, pattern)];
}

function copyFindings(webDir, pattern) {
  const reviewed = readProduct(webDir)
    .languages.filter((language) => language.copyFallback !== null)
    .map((language) => `${language.code}.json`);
  const names = readdirSync(join(webDir, COPY_DIR)).filter((name) => name.endsWith(".json")).sort();
  return names.flatMap((name) => {
    const file = `${COPY_DIR}/${name}`;
    const document = readJson(webDir, file);
    return isPlainObject(document)
      ? copyFileFindings({ file, document, pattern, needsReview: reviewed.includes(name) })
      : unreadable(file);
  });
}

export function releaseFindings({ webDir, today }) {
  const { maxAgeDays, requiredLinks, patterns } = readLock(webDir);
  return [
    ...emailFindings(webDir, patterns),
    ...sitekeyFindings(webDir, patterns),
    ...linkFindings(webDir, { patterns, requiredLinks }),
    ...priceFindings({ webDir, today, maxAgeDays }),
    ...copyFindings(webDir, patterns.placeholder_copy),
  ];
}

export function blockedMessage(findings) {
  const lines = findings.map((finding) => `- ${finding.file}: ${finding.reason}`);
  const noun = findings.length === 1 ? "thing" : "things";
  return `release blocked: ${findings.length} ${noun} must change before launch\n${lines.join("\n")}\n`;
}

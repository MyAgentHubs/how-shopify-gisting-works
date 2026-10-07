import { readFileSync } from "node:fs";
import { join } from "node:path";
import { copyString } from "./copy-resolve.mjs";

const KEYS_FILE = "data/runtime_keys.json";
const BENCHMARKS_FILE = "data/benchmarks.json";
const PRICING_FILE = "data/pricing.json";
const RUNTIME_FILE = "data/runtime.json";
const LINKS_FILE = "data/links.json";
const OPTIONAL_LINKS = ["research_article"];
const WITHHELD_ROOTS = ["red_lines"];
const NUMBERS_NAMESPACE = "numbers";
const PATH_SEPARATOR = ".";
const JSON_ESCAPES = new Map([
  ["<", "\\u003c"],
  [">", "\\u003e"],
  ["&", "\\u0026"],
  ["\u2028", "\\u2028"],
  ["\u2029", "\\u2029"],
]);

export const RUNTIME_BLOCK_ID = "runtime-data";

export function lookupPath(data, path) {
  let node = data;
  for (const segment of path.split(PATH_SEPARATOR)) {
    if (node === null || typeof node !== "object" || !Object.hasOwn(node, segment)) {
      throw new RangeError(`no data at ${path}`);
    }
    node = node[segment];
  }
  return node;
}

function requireStringList(value, label) {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new TypeError(`${KEYS_FILE}: ${label} must be a list of strings`);
  }
  if (new Set(value).size !== value.length) {
    throw new TypeError(`${KEYS_FILE}: ${label} has a duplicate entry`);
  }
}

function checkNumberPath(name, path) {
  if (typeof path !== "string" || path === "") {
    throw new TypeError(`${KEYS_FILE}: numbers.${name} must be a path string`);
  }
  const root = path.split(PATH_SEPARATOR)[0];
  if (WITHHELD_ROOTS.includes(root)) {
    throw new RangeError(`${KEYS_FILE}: numbers.${name} points into withheld data ${root}`);
  }
}

export function readRuntimeKeys(webDir) {
  const keys = JSON.parse(readFileSync(join(webDir, KEYS_FILE), "utf8"));
  requireStringList(keys.copy, "copy");
  if (keys.numbers === null || typeof keys.numbers !== "object" || Array.isArray(keys.numbers)) {
    throw new TypeError(`${KEYS_FILE}: numbers must map a name to a path in benchmarks.json`);
  }
  for (const [name, path] of Object.entries(keys.numbers)) {
    checkNumberPath(name, path);
  }
  return keys;
}

export function readBenchmarks(webDir) {
  return JSON.parse(readFileSync(join(webDir, BENCHMARKS_FILE), "utf8"));
}

export function readPricing(webDir) {
  return JSON.parse(readFileSync(join(webDir, PRICING_FILE), "utf8"));
}

export function readLinks(webDir) {
  const links = JSON.parse(readFileSync(join(webDir, LINKS_FILE), "utf8"));
  if (links === null || typeof links !== "object" || Array.isArray(links)) {
    throw new TypeError(`${LINKS_FILE}: must map a name to a link`);
  }
  for (const [name, value] of Object.entries(links)) {
    if (typeof value !== "string") {
      throw new TypeError(`${LINKS_FILE}: ${name} must be a string`);
    }
  }
  return { ...Object.fromEntries(OPTIONAL_LINKS.map((name) => [name, ""])), ...links };
}

export function readTurnstile(webDir) {
  const { sitekey, action } = JSON.parse(readFileSync(join(webDir, RUNTIME_FILE), "utf8")).turnstile ?? {};
  for (const [name, value] of Object.entries({ sitekey, action })) {
    if (typeof value !== "string" || value === "") {
      throw new TypeError(`${RUNTIME_FILE}: turnstile.${name} must be a non-empty string`);
    }
  }
  return { sitekey, action };
}

export function pickNumbers(benchmarks, numberPaths) {
  const picked = {};
  for (const [name, path] of Object.entries(numberPaths)) {
    const value = lookupPath(benchmarks, path);
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new TypeError(`${BENCHMARKS_FILE}: ${path} is not a finite number`);
    }
    picked[name] = value;
  }
  return picked;
}

export function buildDataContext({ numbers, providers, lang, pricing = null, copy = null, examples = [], publicOrders = [], assetsBase = "", rules = null, links = null }) {
  const context = { [NUMBERS_NAMESPACE]: numbers };
  for (const [name, provide] of Object.entries(providers)) {
    if (Object.hasOwn(context, name)) {
      throw new RangeError(`data provider ${name} collides with an existing namespace`);
    }
    context[name] = provide({ numbers, lang, pricing, copy, examples, publicOrders, assetsBase, rules, links });
  }
  return context;
}

function inlineJson(value) {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, (char) => JSON_ESCAPES.get(char));
}

export function runtimeBlock({ keys, copy, numbers, pricing, turnstile }) {
  const strings = {};
  for (const key of keys.copy) {
    const value = copyString(copy, key);
    if (value === undefined) {
      throw new RangeError(`${copy.lang}: runtime key ${key} is missing from the copy`);
    }
    strings[key] = value;
  }
  const payload = inlineJson({ lang: copy.lang, copy: strings, numbers, pricing, turnstile });
  return `<script type="application/json" id="${RUNTIME_BLOCK_ID}">${payload}</script>`;
}

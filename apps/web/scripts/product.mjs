import { readFileSync } from "node:fs";
import { join } from "node:path";

const PRODUCT_FILE = "product.json";
const PRODUCT_STRINGS = ["name", "slug", "origin", "brand", "ogImage"];
const SLUG_SHAPE = /^[a-z0-9][a-z0-9-]*$/;
const LANG_TOKEN = "{lang}";
const LANGUAGE_STRINGS = ["code", "htmlLang", "hreflang"];

function requireString(value, label) {
  if (typeof value !== "string") {
    throw new TypeError(`${PRODUCT_FILE}: ${label} must be a string`);
  }
  return value;
}

function requireText(value, label) {
  if (requireString(value, label).trim() === "") {
    throw new TypeError(`${PRODUCT_FILE}: ${label} must not be empty`);
  }
}

function checkLanguage(language, index) {
  const at = `languages[${index}]`;
  for (const key of LANGUAGE_STRINGS) {
    requireText(language[key], `${at}.${key}`);
  }
  requireString(language.prefix, `${at}.prefix`);
  if (typeof language.indexed !== "boolean") {
    throw new TypeError(`${PRODUCT_FILE}: ${at}.indexed must be a boolean`);
  }
}

function checkFallback({ code, copyFallback }, codes) {
  const valid = copyFallback === null || (codes.includes(copyFallback) && copyFallback !== code);
  if (!valid) {
    throw new TypeError(
      `${PRODUCT_FILE}: ${code}.copyFallback must be null or another language code`,
    );
  }
}

export function readProduct(webDir) {
  const product = JSON.parse(readFileSync(join(webDir, PRODUCT_FILE), "utf8"));
  for (const key of PRODUCT_STRINGS) {
    requireText(product[key], key);
  }
  if (!SLUG_SHAPE.test(product.slug)) {
    throw new TypeError(`${PRODUCT_FILE}: slug must match ${SLUG_SHAPE}`);
  }
  if (!product.ogImage.includes(LANG_TOKEN)) {
    throw new TypeError(`${PRODUCT_FILE}: ogImage must contain ${LANG_TOKEN}`);
  }
  if (!Array.isArray(product.languages) || product.languages.length === 0) {
    throw new TypeError(`${PRODUCT_FILE}: languages must be a non-empty array`);
  }
  product.languages.forEach(checkLanguage);
  const codes = product.languages.map((language) => language.code);
  if (new Set(codes).size !== codes.length) {
    throw new TypeError(`${PRODUCT_FILE}: duplicate language code in ${codes.join(", ")}`);
  }
  product.languages.forEach((language) => {
    checkFallback(language, codes);
  });
  return product;
}

export function pagePath(product, language) {
  return `/${[language.prefix, product.slug].filter((part) => part !== "").join("/")}/`;
}

export function ogImagePath(product, language) {
  return product.ogImage.replace(LANG_TOKEN, language.copyFallback ?? language.code);
}

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const COPY_DIR = "copy";

export function copyString(copy, key) {
  return Object.hasOwn(copy.strings, key) ? copy.strings[key] : undefined;
}

export function readCopyDocs(webDir) {
  const docs = {};
  for (const name of readdirSync(join(webDir, COPY_DIR)).filter((file) => file.endsWith(".json"))) {
    const doc = JSON.parse(readFileSync(join(webDir, COPY_DIR, name), "utf8"));
    docs[doc.lang] = doc;
  }
  return docs;
}

function docFor(docs, code) {
  const doc = docs[code];
  if (doc === undefined) {
    throw new RangeError(`no copy file for language ${code}`);
  }
  return doc;
}

export function resolveCopy(product, docs, code) {
  const language = product.languages.find((entry) => entry.code === code);
  if (language === undefined) {
    throw new RangeError(`language ${code} is not in the product table`);
  }
  const own = docFor(docs, code);
  const base = language.copyFallback === null ? {} : docFor(docs, language.copyFallback).strings;
  return { status: own.status, lang: code, strings: { ...base, ...own.strings } };
}

import { readFileSync } from "node:fs";
import { join } from "node:path";

const LOCK_FILE = "data/release_lock.json";
const PATTERN_FLAGS = {
  email_shape: "",
  placeholder_email: "i",
  sitekey_shape: "",
  test_sitekey: "i",
  link_shape: "",
  placeholder_link: "i",
  placeholder_copy: "i",
};

export function readJson(webDir, file) {
  try {
    return JSON.parse(readFileSync(join(webDir, file), "utf8"));
  } catch {
    return null;
  }
}

export function comparable(text) {
  return text.normalize("NFKC").replace(/\p{Cf}/gu, "");
}

function compile(lock, key, flags) {
  if (typeof lock[key] !== "string" || lock[key] === "") {
    throw new TypeError(`${LOCK_FILE}: ${key} must be a pattern string`);
  }
  try {
    return new RegExp(lock[key], flags);
  } catch {
    throw new TypeError(`${LOCK_FILE}: ${key} must be a valid pattern`);
  }
}

export function readLock(webDir) {
  const lock = readJson(webDir, LOCK_FILE);
  if (lock === null) {
    throw new TypeError(`${LOCK_FILE}: cannot be read as JSON`);
  }
  if (!Number.isInteger(lock.price_max_age_days) || lock.price_max_age_days < 0) {
    throw new TypeError(`${LOCK_FILE}: price_max_age_days must be a non-negative integer`);
  }
  if (!Array.isArray(lock.required_links) || lock.required_links.some((name) => typeof name !== "string")) {
    throw new TypeError(`${LOCK_FILE}: required_links must be a list of link names`);
  }
  const patterns = {};
  for (const [key, flags] of Object.entries(PATTERN_FLAGS)) {
    patterns[key] = compile(lock, key, flags);
  }
  return { maxAgeDays: lock.price_max_age_days, requiredLinks: lock.required_links, patterns };
}

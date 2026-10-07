import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fill } from "../src/copy.ts";
import { copyString } from "./copy-resolve.mjs";

const EXAMPLES_FILE = "data/example_orders.json";
const ORDER_PREFILL_KEY = "chat.prefill_order";
const PLAIN_PREFILL_KEY = "chat.prefill_human";
const HINT_SUFFIX = "_hint";

export function readExamples(webDir) {
  const { examples } = JSON.parse(readFileSync(join(webDir, EXAMPLES_FILE), "utf8"));
  if (!Array.isArray(examples)) {
    throw new TypeError(`${EXAMPLES_FILE}: examples must be a list`);
  }
  return examples;
}

function requireKey(copy, key) {
  const text = copyString(copy, key);
  if (text === undefined) {
    throw new RangeError(`${EXAMPLES_FILE}: copy key ${key} is missing from the ${copy.lang} copy`);
  }
  return text;
}

function prefillFor(example, copy) {
  const hasOrder = typeof example.order === "string";
  if (hasOrder !== (typeof example.email === "string")) {
    throw new TypeError(`${EXAMPLES_FILE}: example ${example.id} needs both order and email, or neither`);
  }
  if (!hasOrder) {
    return requireKey(copy, PLAIN_PREFILL_KEY);
  }
  return fill(requireKey(copy, ORDER_PREFILL_KEY), { order: example.order, email: example.email });
}

export function examplesProvider({ copy, examples }) {
  return examples.map((example) => ({
    id: example.id,
    label: requireKey(copy, example.label_key),
    hint: copyString(copy, `${example.label_key}${HINT_SUFFIX}`) ?? "",
    prefill: prefillFor(example, copy),
  }));
}

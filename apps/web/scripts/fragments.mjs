import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fill } from "../src/copy.ts";
import { formatValue } from "../src/format.ts";
import { copyString } from "./copy-resolve.mjs";
import { lookupPath } from "./prerender.mjs";

const DIRECTIVE = /\{\{(\w+):([^{}]*)\}\}/g;
const LEFTOVER = /\{\{|\}\}|%[A-Z_]+%/;
const FORMAT_SEPARATOR = "|";
const DATA_PATH = /^\w+(\.\w+)+$/;
const UNFILLED = /\{\w+\}/;
const FILL_SEPARATOR = "=";
const FILL_FORMAT = "int";
const PART_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const FLAG_WORD = /^[a-z]+$/;
const PARTS_DIR = "parts";
const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

function requireData({ file, data, what }) {
  if (data === null) {
    throw new RangeError(`${file}: ${what} used without a data context`);
  }
}

function resolve({ file, data, path }) {
  requireData({ file, data, what: `data path ${path}` });
  try {
    return lookupPath(data, path);
  } catch (error) {
    throw new RangeError(`${file}: ${error.message}`, { cause: error });
  }
}

function fillCopy({ file, key, text, fill: spec, copy, data }) {
  const [name, path, ...extra] = spec.split(FILL_SEPARATOR);
  if (path === undefined || extra.length > 0) {
    throw new RangeError(`${file}: copy fill must be name${FILL_SEPARATOR}path, got ${spec}`);
  }
  const placeholder = `{${name}}`;
  if (!text.includes(placeholder)) {
    throw new RangeError(`${file}: copy key ${key} has no ${placeholder} to fill`);
  }
  const found = resolve({ file, data, path });
  const value = typeof found === "string" ? found : formatValue(FILL_FORMAT, found, copy.lang);
  return fill(text, { [name]: value });
}

function copyDirective({ file, argument, copy, data }) {
  const [key, ...fills] = argument.split(FORMAT_SEPARATOR);
  let text = copyString(copy, key);
  if (text === undefined) {
    throw new RangeError(`${file}: missing copy key ${key}`);
  }
  for (const entry of fills) {
    text = fillCopy({ file, key, text, fill: entry, copy, data });
  }
  const unfilled = UNFILLED.exec(text);
  if (unfilled !== null) {
    throw new RangeError(`${file}: copy key ${key} still has ${unfilled[0]} after its fills`);
  }
  return escapeHtml(text);
}

function dataDirective({ file, argument, copy, data }) {
  const [path, format, ...extra] = argument.split(FORMAT_SEPARATOR);
  if (format === undefined || extra.length > 0) {
    throw new RangeError(`${file}: data directive needs path|format, got ${argument}`);
  }
  const value = resolve({ file, data, path });
  try {
    return escapeHtml(formatValue(format, value, copy.lang));
  } catch (error) {
    throw new RangeError(`${file}: ${error.message}`, { cause: error });
  }
}

function textDirective({ file, argument: path, data }) {
  const value = resolve({ file, data, path });
  if (!["string", "number", "boolean"].includes(typeof value)) {
    throw new RangeError(`${file}: ${path} cannot be written as text`);
  }
  return escapeHtml(String(value));
}

function flagDirective({ file, argument, data }) {
  const [path, word, ...extra] = argument.split(FORMAT_SEPARATOR);
  if (word === undefined || extra.length > 0) {
    throw new RangeError(`${file}: flag needs path${FORMAT_SEPARATOR}word, got ${argument}`);
  }
  if (!FLAG_WORD.test(word)) {
    throw new RangeError(`${file}: flag word ${word} may hold lowercase letters only`);
  }
  const value = resolve({ file, data, path });
  if (typeof value !== "boolean") {
    throw new RangeError(`${file}: flag ${path} must be true or false`);
  }
  return value ? word : "";
}

function readPart({ file, name, parts }) {
  if (!PART_NAME.test(name)) {
    throw new RangeError(`${file}: part name ${name} may hold lowercase letters, digits and dashes only`);
  }
  try {
    return readFileSync(join(parts.dir, `${name}.html`), "utf8").replace(/\n$/, "");
  } catch (error) {
    throw new RangeError(`${file}: cannot read ${PARTS_DIR}/${name}.html`, { cause: error });
  }
}

function renderPart({ file, name, copy, data, parts }) {
  if (parts === null) {
    throw new RangeError(`${file}: part ${name} needs a ${PARTS_DIR} folder`);
  }
  if (parts.stack.includes(name)) {
    throw new RangeError(`${file}: include cycle ${[...parts.stack, name].join(" → ")}`);
  }
  const source = readPart({ file, name, parts });
  const inner = { dir: parts.dir, stack: [...parts.stack, name] };
  return renderFragment({ file: `${PARTS_DIR}/${name}.html`, source }, copy, data, inner);
}

function includeDirective({ file, argument, copy, data, parts }) {
  const name = DATA_PATH.test(argument) ? resolve({ file, data, path: argument }) : argument;
  if (typeof name !== "string") {
    throw new RangeError(`${file}: include path ${argument} must hold a part name`);
  }
  return renderPart({ file, name, copy, data, parts });
}

function splitPartArgument({ file, kind, argument }) {
  const [path, name, ...extra] = argument.split(FORMAT_SEPARATOR);
  if (name === undefined || extra.length > 0) {
    throw new RangeError(`${file}: ${kind} needs path${FORMAT_SEPARATOR}part, got ${argument}`);
  }
  return { path, name };
}

function eachDirective({ file, argument, copy, data, parts }) {
  const { path, name } = splitPartArgument({ file, kind: "each", argument });
  const items = resolve({ file, data, path });
  if (!Array.isArray(items)) {
    throw new RangeError(`${file}: each needs a list at ${path}`);
  }
  return items.map((item) => renderPart({ file, name, copy, data: { ...data, item }, parts })).join("\n");
}

function withDirective({ file, argument, copy, data, parts }) {
  const { path, name } = splitPartArgument({ file, kind: "with", argument });
  const item = resolve({ file, data, path });
  if (item === null || typeof item !== "object" || Array.isArray(item)) {
    throw new RangeError(`${file}: with needs an object at ${path}`);
  }
  return renderPart({ file, name, copy, data: { ...data, item }, parts });
}

function whenDirective({ file, argument, copy, data, parts }) {
  const { path, name } = splitPartArgument({ file, kind: "when", argument });
  const value = resolve({ file, data, path });
  if (typeof value !== "string") {
    throw new RangeError(`${file}: when needs text at ${path}`);
  }
  return value === "" ? "" : renderPart({ file, name, copy, data, parts });
}

const DIRECTIVES = new Map([
  ["copy", copyDirective],
  ["data", dataDirective],
  ["text", textDirective],
  ["flag", flagDirective],
  ["include", includeDirective],
  ["each", eachDirective],
  ["with", withDirective],
  ["when", whenDirective],
]);

export function renderFragment({ file, source }, copy, data = null, parts = null) {
  return source.replace(DIRECTIVE, (_whole, kind, argument) => {
    const handler = DIRECTIVES.get(kind);
    if (handler === undefined) {
      throw new RangeError(`${file}: unknown directive ${kind}`);
    }
    return handler({ file, argument, copy, data, parts });
  });
}

export function requireRendered(label, html) {
  const leftover = LEFTOVER.exec(html);
  if (leftover !== null) {
    const around = html.slice(Math.max(0, leftover.index - 20), leftover.index + 40).replace(/\s+/g, " ");
    throw new RangeError(`${label}: markup left over after rendering near "${around}"`);
  }
  return html;
}

export function assembleSections(sectionsDir, copy, data = null) {
  const parts = { dir: join(sectionsDir, PARTS_DIR), stack: [] };
  return readdirSync(sectionsDir)
    .filter((name) => name.endsWith(".html"))
    .sort()
    .map((file) =>
      renderFragment({ file, source: readFileSync(join(sectionsDir, file), "utf8") }, copy, data, parts),
    )
    .join("\n");
}

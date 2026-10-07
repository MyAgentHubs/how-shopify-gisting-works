import { readFileSync } from "node:fs";
import { join } from "node:path";
import { copyString } from "./copy-resolve.mjs";

const RULES_FILE = "data/public_rules.json";
const STATES_FILE = "data/tool_states.json";
const STATES = ["real", "demo"];
const MARK_PREFIX = "mark-";
const BADGE_KEY = "rules.badge";
const BADGE_SEPARATOR = " → ";

function readJson(webDir, file) {
  return JSON.parse(readFileSync(join(webDir, file), "utf8"));
}

function requireTool(tool) {
  const { name, description, parameters } = tool ?? {};
  if (![name, description, parameters].every((field) => typeof field === "string")) {
    throw new TypeError(`${RULES_FILE}: every tool needs a name, a description and parameters as text`);
  }
}

function toolWithState(tool, states) {
  const state = states[tool.name];
  if (state === undefined) {
    throw new RangeError(`${STATES_FILE}: ${tool.name} has no state`);
  }
  if (!STATES.includes(state)) {
    throw new RangeError(`${STATES_FILE}: ${tool.name} must be ${STATES.join(" or ")}, got ${String(state)}`);
  }
  return { name: tool.name, description: tool.description, parameters: tool.parameters, state, mark: `${MARK_PREFIX}${state}` };
}

export function readRules(webDir) {
  const published = readJson(webDir, RULES_FILE);
  const states = readJson(webDir, STATES_FILE);
  if (typeof published.rules !== "string" || !Array.isArray(published.tools)) {
    throw new TypeError(`${RULES_FILE}: needs rules as text and a list of tools`);
  }
  published.tools.forEach(requireTool);
  const names = published.tools.map((tool) => tool.name);
  for (const name of Object.keys(states)) {
    if (!names.includes(name)) {
      throw new RangeError(`${STATES_FILE}: ${name} is not a tool in ${RULES_FILE}`);
    }
  }
  return { text: published.rules, tools: published.tools.map((tool) => toolWithState(tool, states)) };
}

export function rulesProvider({ rules, copy }) {
  if (rules === null) {
    throw new TypeError("the rules provider needs the public rules");
  }
  const [from, to, ...extra] = (copyString(copy, BADGE_KEY) ?? "").split(BADGE_SEPARATOR);
  if (to === undefined || extra.length > 0) {
    throw new RangeError(`${copy.lang}: ${BADGE_KEY} must read "<from>${BADGE_SEPARATOR}<to>"`);
  }
  return { ...rules, badge: { from, to } };
}

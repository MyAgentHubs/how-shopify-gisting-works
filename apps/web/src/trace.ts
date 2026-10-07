import type { PublicTrace } from "../../../contracts/public_trace.generated.ts";

export type { PublicTrace };

type Tool = PublicTrace["tools"][number];
type Knowledge = PublicTrace["knowledge"][number];

const OUTCOMES: readonly Tool["outcome"][] = ["completed", "unavailable", "locked"];
const METHODS: readonly Knowledge["method"][] = ["bm25"];
const KB_ID = /^kb-[a-z0-9]+(?:-[a-z0-9]+)*$/u;
const MAX_KB_ID_LENGTH = 64;
const MAX_KNOWLEDGE = 3;

export type Fields = Readonly<Record<string, unknown>>;

export function isFields(value: unknown): value is Fields {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function parseTool(raw: unknown): Tool | null {
  if (!isFields(raw)) {
    return null;
  }
  const { tool, order_number: orderNumber, outcome } = raw;
  const known = OUTCOMES.find((candidate) => candidate === outcome);
  const orderOk = orderNumber === null || typeof orderNumber === "string";
  if (typeof tool !== "string" || !orderOk || known === undefined) {
    return null;
  }
  return { tool, order_number: orderNumber, outcome: known };
}

function parseKnowledge(raw: unknown): Knowledge | null {
  if (!isFields(raw)) {
    return null;
  }
  const { id, method } = raw;
  const known = METHODS.find((candidate) => candidate === method);
  if (
    typeof id !== "string" ||
    id.length > MAX_KB_ID_LENGTH ||
    !KB_ID.test(id) ||
    known === undefined
  ) {
    return null;
  }
  return { id, method: known };
}

function parseKnowledgeList(raw: readonly unknown[]): Knowledge[] | null {
  if (raw.length > MAX_KNOWLEDGE) {
    return null;
  }
  const parsed = raw.map(parseKnowledge);
  const found = parsed.filter((entry): entry is Knowledge => entry !== null);
  const distinct = new Set(found.map((entry) => entry.id));
  return found.length === parsed.length && distinct.size === found.length ? found : null;
}

function parseTokens(raw: unknown): PublicTrace["tokens"] | null {
  if (!isFields(raw)) {
    return null;
  }
  const rules = count(raw["rules"]);
  const tools = count(raw["tools"]);
  const history = count(raw["history"]);
  const toolResults = count(raw["tool_results"]);
  const total = count(raw["total"]);
  if (
    rules === null ||
    tools === null ||
    history === null ||
    toolResults === null ||
    total === null
  ) {
    return null;
  }
  return { rules, tools, history, tool_results: toolResults, total };
}

function parseLatency(raw: unknown): PublicTrace["latency"] | null {
  if (!isFields(raw)) {
    return null;
  }
  const first = count(raw["first_token_ms"]);
  const total = count(raw["total_ms"]);
  return first === null || total === null ? null : { first_token_ms: first, total_ms: total };
}

export function parsePublicTrace(raw: unknown): PublicTrace | null {
  if (!isFields(raw) || !Array.isArray(raw["tools"]) || !Array.isArray(raw["knowledge"])) {
    return null;
  }
  const tools = (raw["tools"] as unknown[]).map(parseTool);
  const knowledge = parseKnowledgeList(raw["knowledge"] as unknown[]);
  const tokens = parseTokens(raw["tokens"]);
  const latency = parseLatency(raw["latency"]);
  if (tools.includes(null) || knowledge === null || tokens === null || latency === null) {
    return null;
  }
  return { tools: tools as Tool[], knowledge, tokens, latency };
}

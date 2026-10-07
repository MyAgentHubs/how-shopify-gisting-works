import type { ChatOutcome, ChatRequest, Gateway } from "../src/gateway.ts";
import type { PublicTrace } from "../src/trace.ts";

export type Script = (request: ChatRequest) => ChatOutcome;

export interface FakeGateway extends Gateway {
  readonly requests: readonly ChatRequest[];
}

const GIST_RULES_TOKENS = 19;
const FULL_RULES_TOKENS = 526;
const TOOL_SCHEMA_TOKENS = 120;
const HISTORY_TOKENS_PER_CHAR = 0.25;
const FIRST_TOKEN_MS = 900;
const TOTAL_MS = 1800;
const ORDER_NUMBER = /#\d{3,5}/;

function traceFor(request: ChatRequest): PublicTrace {
  const rules = request.mode === "full" ? FULL_RULES_TOKENS : GIST_RULES_TOKENS;
  const history = Math.ceil(request.message.length * HISTORY_TOKENS_PER_CHAR);
  const order = ORDER_NUMBER.exec(request.message)?.[0] ?? null;
  return {
    tools:
      order === null ? [] : [{ tool: "lookup_order", order_number: order, outcome: "completed" }],
    knowledge: [],
    tokens: {
      rules,
      tools: TOOL_SCHEMA_TOKENS,
      history,
      tool_results: 0,
      total: rules + TOOL_SCHEMA_TOKENS + history,
    },
    latency: { first_token_ms: FIRST_TOKEN_MS, total_ms: TOTAL_MS },
  };
}

function previewScript(request: ChatRequest): ChatOutcome {
  return {
    kind: "reply",
    answer: `[fake gateway, ${request.mode}] ${request.message}`,
    trace: traceFor(request),
  };
}

export function fakeGateway(script: Script = previewScript): FakeGateway {
  const requests: ChatRequest[] = [];
  return {
    requests,
    chat(request) {
      requests.push(request);
      return Promise.resolve(script(request));
    },
  };
}

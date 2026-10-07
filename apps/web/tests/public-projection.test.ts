import { describe, expect, it } from "vitest";
import gatewayLimits from "../../gateway/limits.json";
import type { Fetcher } from "../src/gateway.ts";
import { httpGateway } from "../src/gateway.ts";
import type { PublicTrace } from "../src/trace.ts";
import {
  CANARY,
  TRACE,
  compareButton,
  compareOut,
  flush,
  inputBox,
  mount,
  query,
  say,
} from "./support.ts";

const LEAKY_BODY = {
  answer: "Your order is on its way.",
  internal: {
    backend_id: CANARY,
    fallback_reason: CANARY,
    tool_calls: [{ name: "lookup_order", result: `{"canary":"${CANARY}"}` }],
    guard: { events: [{ status: "mismatch", missing: [CANARY] }] },
  },
  trace: {
    ...TRACE,
    result_type: "NotFound",
    session_id: CANARY,
    tools: [{ ...TRACE.tools[0], result_type: "Mismatch", cache_hit: true, detail: CANARY }],
    knowledge: [{ ...TRACE.knowledge[0], title: CANARY, answer: CANARY, score: 9.5 }],
  },
};

function leakyGateway(body: unknown = LEAKY_BODY): ReturnType<typeof httpGateway> {
  const fetcher: Fetcher = () => Promise.resolve(Response.json(body));
  return httpGateway(fetcher);
}

function pageText(): string {
  return `${document.body.innerHTML}\n${document.body.textContent}`;
}

describe("the Under the hood panel", () => {
  it("never renders an internal field the gateway let through", async () => {
    mount({ gateway: leakyGateway() });
    await say("where is order #1042");
    expect(query('[data-role="log"]').textContent).toContain("Your order is on its way.");
    expect(pageText()).not.toContain(CANARY);
    for (const word of [
      "mismatch",
      "NotFound",
      "Mismatch",
      "cache_hit",
      "backend_id",
      "fallback_reason",
    ]) {
      expect(pageText()).not.toContain(word);
    }
  });

  it("keeps the canary out of the compare view as well", async () => {
    mount({ gateway: leakyGateway() });
    await say("where is order #1042");
    compareButton().click();
    await flush();
    expect(compareOut().hidden).toBe(false);
    expect(pageText()).not.toContain(CANARY);
  });

  it("reads one phrase for every lookup outcome, never the outcome itself", async () => {
    for (const outcome of ["completed", "unavailable", "locked"] as const) {
      const trace: PublicTrace = {
        ...TRACE,
        tools: [{ tool: "lookup_order", order_number: "#1042", outcome }],
      };
      mount({ gateway: leakyGateway({ answer: "ok", trace }) });
      await say("#1042");
      const body = query('[data-role="panel-body"]');
      expect(body.textContent).toContain("result returned");
      expect(body.textContent).not.toMatch(/unavailable|locked|completed/);
    }
  });

  it("shows the output check as done and nothing more", async () => {
    mount({ gateway: leakyGateway() });
    await say("hello");
    expect(query(".og-done").textContent).toBe("done");
    expect(document.querySelector(".mk, .fb")).toBeNull();
  });

  it("shows only the parts the public trace carries", async () => {
    mount({ gateway: leakyGateway() });
    await say("hello");
    const cells = [...document.querySelectorAll(".og-ptab td")].map((cell) => cell.textContent.trim());
    expect(cells).toEqual([
      "Fixed rules · Full rules 526",
      "19",
      "Tools",
      "120",
      "Chat history",
      "40",
      "Total input",
      "179",
    ]);
  });

  it("limits what the page shows of a lookup to the tool name, the order number and a fixed mask", async () => {
    mount({ gateway: leakyGateway() });
    await say("hello");
    expect(query(".og-tcall").textContent).toBe("lookup_order(#1042, •••)result returned");
  });

  it("shows no part of an email the visitor typed, and never what came back", async () => {
    mount({ gateway: leakyGateway() });
    await say("My email is jane.doe@example.com, order #1042");
    const body = query('[data-role="panel-body"]');
    expect(body.textContent).toContain("lookup_order(#1042, •••)");
    expect(body.textContent).not.toContain("jane");
    expect(body.innerHTML).not.toContain("jane.doe@example.com");
    expect(body.textContent).not.toMatch(/verified|matched|exists|not found/i);
  });

  it("looks the same for a lookup that found nothing and one that found an order", async () => {
    const outcomes = ["completed", "unavailable", "locked"] as const;
    const panels: string[] = [];
    for (const outcome of outcomes) {
      const trace: PublicTrace = {
        ...TRACE,
        tools: [{ tool: "lookup_order", order_number: "#1042", outcome }],
      };
      mount({ gateway: leakyGateway({ answer: "ok", trace }) });
      await say("jane.doe@example.com #1042");
      panels.push(query('[data-role="panel-body"]').innerHTML);
    }
    expect(new Set(panels).size).toBe(1);
  });
});

describe("the page limits", () => {
  it("send one message at a time and stop at the session limit", async () => {
    const page = mount();
    for (let sent = 0; sent < gatewayLimits.maxMessagesPerSession + 2; sent += 1) {
      await say(`message ${String(sent)}`);
    }
    expect(page.gateway.requests).toHaveLength(gatewayLimits.maxMessagesPerSession);
    expect(inputBox().disabled).toBe(true);
  });

  it("never send an empty or over-long message", async () => {
    const page = mount();
    await say("   ");
    await say("x".repeat(gatewayLimits.maxMessageChars + 1));
    expect(page.gateway.requests).toHaveLength(0);
    await say("x".repeat(gatewayLimits.maxMessageChars));
    expect(page.gateway.requests).toHaveLength(1);
  });
});

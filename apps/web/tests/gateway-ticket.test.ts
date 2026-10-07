import { describe, expect, it } from "vitest";
import type { Fetcher } from "../src/gateway.ts";
import { httpGateway } from "../src/gateway.ts";
import { TRACE } from "./support.ts";
import { FRESH } from "./ticket-support.ts";

const BASE = { sessionId: "session-abcdef01", message: "hello", mode: "gist", timeoutMs: 30000 } as const;

function replying(body: unknown, headers: Record<string, string> = {}): {
  readonly fetcher: Fetcher;
  readonly bodies: unknown[];
} {
  const bodies: unknown[] = [];
  const fetcher: Fetcher = (_url, init) => {
    bodies.push(JSON.parse(typeof init?.body === "string" ? init.body : "null"));
    return Promise.resolve(Response.json(body, { headers }));
  };
  return { fetcher, bodies };
}

const ANSWER = { answer: "hi", trace: TRACE };
const REPLAY = { served_by: "replay", reason: "quota", turns: [] };

describe("httpGateway and the chat ticket", () => {
  it("sends the token alone when there is no ticket", async () => {
    const { fetcher, bodies } = replying(ANSWER);
    await httpGateway(fetcher).chat({ ...BASE, turnstileToken: "tok" });
    expect(Object.keys(bodies[0] as object).sort()).toEqual(["message", "mode", "session_id", "turnstile_token"]);
  });

  it("sends the ticket alone, with no turnstile_token key at all", async () => {
    const { fetcher, bodies } = replying(ANSWER);
    await httpGateway(fetcher).chat({ ...BASE, ticket: FRESH });
    expect(bodies[0]).toEqual({ session_id: BASE.sessionId, message: "hello", mode: "gist", ticket: FRESH });
  });

  it("never sends an empty credential", async () => {
    const { fetcher, bodies } = replying(ANSWER);
    await httpGateway(fetcher).chat({ ...BASE, turnstileToken: "tok", ticket: "" });
    expect(Object.keys(bodies[0] as object)).not.toContain("ticket");
  });

  it("reads the ticket from the x-gisting-ticket header of an answer and of a replay", async () => {
    const headers = { "x-gisting-ticket": FRESH };
    const answered = await httpGateway(replying(ANSWER, headers).fetcher).chat({ ...BASE, turnstileToken: "t" });
    const replayed = await httpGateway(replying(REPLAY, headers).fetcher).chat({ ...BASE, turnstileToken: "t" });
    expect(answered).toMatchObject({ kind: "reply", ticket: FRESH });
    expect(replayed).toMatchObject({ kind: "replay", ticket: FRESH });
  });

  it("leaves the ticket out when the header is missing or not in the agreed shape", async () => {
    const shapes = ["", "1.12.short", `2.1800000000.${"A".repeat(43)}`, `1.0123.${"A".repeat(43)}`, `1.12345678901.${"A".repeat(43)}`, `1.12.${"A".repeat(42)}+`, `1.12.${"A".repeat(42)}`, `1.12.${"A".repeat(44)}`, `${FRESH}, ${FRESH}`];
    for (const value of shapes) {
      const outcome = await httpGateway(replying(ANSWER, { "x-gisting-ticket": value }).fetcher).chat({ ...BASE, turnstileToken: "t" });
      expect(outcome.kind === "reply" && "ticket" in outcome).toBe(false);
    }
    const exact = await httpGateway(replying(ANSWER, { "x-gisting-ticket": `1.12.${"A".repeat(43)}` }).fetcher).chat({ ...BASE, turnstileToken: "t" });
    expect(exact).toMatchObject({ ticket: `1.12.${"A".repeat(43)}` });
    const none = await httpGateway(replying(ANSWER).fetcher).chat({ ...BASE, turnstileToken: "t" });
    expect("ticket" in none).toBe(false);
  });
});

import { describe, expect, it, vi } from "vitest";
import limitsJson from "../data/limits.json";
import { role } from "../src/dom.ts";
import type { Fetcher, ReplayTurn } from "../src/gateway.ts";
import { httpGateway } from "../src/gateway.ts";
import { compare, flush, mount, query, reply, say } from "./support.ts";

const QUICK_TIMEOUT_MS = 20;
const GIVE_UP_MS = 1000;

const silent: Fetcher = (_url, init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => {
      reject(new Error("aborted"));
    });
  });

const sendButton = (): HTMLButtonElement => role(document, "send", HTMLButtonElement);

describe("a send that cannot finish", () => {
  it("frees the send button and shows the one plain error when the chat request never answers", async () => {
    mount({
      gateway: httpGateway(silent),
      limits: { ...limitsJson, chatRequestMs: QUICK_TIMEOUT_MS },
    });
    await say("hey");
    expect(sendButton().disabled).toBe(true);
    await vi.waitFor(
      () => {
        expect(sendButton().disabled).toBe(false);
      },
      { timeout: GIVE_UP_MS },
    );
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("network");
    expect(sendButton().disabled).toBe(false);
  });

  it("frees the send button when showing the outcome throws", async () => {
    const broken = { kind: "replay", reason: "quota", turns: null as unknown as ReplayTurn[] } as const;
    mount({ outcomes: [broken, reply("fine")] });
    await say("hey");
    await flush();
    expect(sendButton().disabled).toBe(false);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("unexpected");
    await say("again");
    expect(query('[data-role="log"]').textContent).toContain("fine");
  });

  it("frees the compare button when showing the full answer throws", async () => {
    const broken = { ...reply("full"), trace: null } as unknown as ReturnType<typeof reply>;
    mount({ outcomes: [reply("gist"), broken] });
    await say("hey");
    await compare();
    await flush();
    expect(sendButton().disabled).toBe(false);
    expect(query('[data-role="log"] [data-reason]').getAttribute("data-reason")).toBe("unexpected");
  });
});

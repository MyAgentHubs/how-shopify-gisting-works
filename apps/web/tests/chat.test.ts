import { describe, expect, it } from "vitest";
import copyEn from "../copy/en.json";
import copyJa from "../copy/ja.json";
import { parseCopy, text } from "../src/copy.ts";
import {
  FULL_TRACE,
  TRACE,
  compare,
  compareButton,
  compareOut,
  english,
  flush,
  inputBox,
  mount,
  query,
  reply,
  say,
} from "./support.ts";

function log(): string {
  return query('[data-role="log"]').textContent;
}

describe("the chat", () => {
  it("fills the page from the copy file and sets the language", () => {
    mount();
    expect(query(".og-wbar b").textContent).toBe(text(english, "ui.chat_title"));
    expect(document.documentElement.lang).toBe("en");
    expect(document.querySelectorAll("[data-copy]:empty")).toHaveLength(0);
    expect(query('[data-role="input"]').getAttribute("placeholder")).toBe(
      text(english, "ui.placeholder"),
    );
  });

  it("uses the language of the copy it was given", async () => {
    const copy = parseCopy({ ...copyJa, strings: { ...copyEn.strings, "ui.error": "エラー" } });
    mount({ copy, outcomes: [{ kind: "failed", status: 500, reason: "http" }] });
    await say("hello");
    expect(log()).toContain("エラー");
  });

  it("runs in Gist mode by default and says so", async () => {
    const page = mount();
    expect(query(".og-mode").textContent).toBe("Gist mode");
    await say("hello");
    expect(page.gateway.requests[0]).toMatchObject({
      mode: "gist",
      message: "hello",
      sessionId: "session-abcdef01",
    });
  });

  it("shows the question and the answer, then the turn in the panel", async () => {
    mount();
    await say("where is order #1042");
    expect(log()).toContain("where is order #1042");
    expect(log()).toContain("Answer one");
    expect(query('[data-role="panel-body"]').textContent).toContain("lookup_order(#1042, •••)");
    expect(inputBox().value).toBe("");
  });

  it("keeps the one-line summary to the prompt sizes, the full size worked out from the rules blocks", async () => {
    mount();
    expect(query('[data-role="drawer-summary"]').textContent).toBe("");
    await say("hello");
    expect(query('[data-role="drawer-summary"]').textContent).toBe(
      "Prompt 179 vs 686 tokens",
    );
  });

  it("names no serving backend, in the panel or in the summary", async () => {
    mount();
    await say("hello");
    expect(document.querySelector(".served")).toBeNull();
    expect(query('[data-role="panel-body"]').textContent).not.toMatch(/served by|backup/i);
  });

  it("tells the visitor once when the request fails, without a reason", async () => {
    mount({ outcomes: [{ kind: "failed", status: 502, reason: "http" }] });
    await say("hello");
    expect(log()).toContain(text(english, "ui.error"));
    expect(log()).not.toContain("502");
  });

  it("shows a verification error when the turnstile token cannot be had", async () => {
    mount({ check: { warm: () => undefined, reset: () => undefined, token: () => Promise.reject(new Error("no widget")) } });
    await say("hello");
    expect(log()).toContain(text(english, "ui.checkFailed"));
  });

  it("plays the pre-recorded conversation, labelled, when the quota is used up", async () => {
    const turns = [
      { role: "user", content: "Where is my parcel?" },
      { role: "assistant", content: "Recorded answer" },
    ] as const;
    mount({ outcomes: [{ kind: "replay", reason: "quota", turns }] });
    await say("hello");
    expect(query(".og-replay-banner").textContent).toBe(text(english, "replay.banner"));
    expect(query(".og-replay-label").textContent).toBe(text(english, "replay.label"));
    expect(log()).toContain("Recorded answer");
  });

  it("says the demo is offline, not that the quota is used up, when the server is unavailable", async () => {
    const turns = [{ role: "assistant", content: "Recorded answer" }] as const;
    mount({ outcomes: [{ kind: "replay", reason: "offline", turns }] });
    await say("hello");
    expect(query(".og-replay-banner").textContent).toBe(text(english, "replay.banner_offline"));
    expect(query(".og-replay-banner").textContent).not.toBe(text(english, "replay.banner"));
    expect(query(".og-replay-label").textContent).toBe(text(english, "replay.label"));
    expect(log()).toContain("Recorded answer");
  });

  it("still shows the banner when the recording is empty", async () => {
    mount({ outcomes: [{ kind: "replay", reason: "offline", turns: [] }] });
    await say("hello");
    expect(query(".og-replay-banner").textContent).toBe(text(english, "replay.banner_offline"));
  });

  it("limits the input to the gateway's message length", () => {
    mount();
    expect(inputBox().maxLength).toBe(300);
  });
});

describe("Compare with Full rules", () => {
  it("explains itself in the shortened note, three runs per chat", () => {
    mount();
    expect(query(".og-hhelp").textContent).toBe(
      "Runs this turn again with the full rules, answers side by side. 3 per chat.",
    );
    expect(query(".og-hhelp").textContent).toBe(text(english, "hood.compare.body"));
  });

  it("is off until a turn has been answered", async () => {
    mount();
    expect(compareButton().disabled).toBe(true);
    await say("hello");
    expect(compareButton().disabled).toBe(false);
  });

  it("re-asks the same message in full mode and shows both answers", async () => {
    const page = mount({ outcomes: [reply("Gist answer"), reply("Full answer", FULL_TRACE)] });
    await say("hello");
    await compare();
    expect(page.gateway.requests[1]).toMatchObject({
      mode: "full",
      message: "hello",
      sessionId: "session-abcdef01",
    });
    const out = compareOut();
    expect(out.hidden).toBe(false);
    expect(out.textContent).toContain("Gist answer");
    expect(out.textContent).toContain("Full answer");
    expect(out.textContent).toContain("686");
    expect(query('[data-role="drawer-summary"]').textContent).toBe(
      "Prompt 179 vs 686 tokens",
    );
  });

  it("counts down from three and then stops", async () => {
    const page = mount({ outcomes: [reply("a"), reply("b", FULL_TRACE)] });
    expect(query('[data-role="compare-left"]').textContent).toBe(
      "3 of 3 comparisons left in this chat",
    );
    await say("hello");
    await compare();
    expect(query('[data-role="compare-left"]').textContent).toBe(
      "2 of 3 comparisons left in this chat",
    );
    await compare();
    await compare();
    expect(query('[data-role="compare-left"]').textContent).toBe(
      "0 of 3 comparisons left in this chat",
    );
    expect(compareButton().disabled).toBe(true);
    await compare();
    expect(page.gateway.requests.filter((request) => request.mode === "full")).toHaveLength(3);
  });

  it("clears the comparison when the next answer arrives", async () => {
    mount({ outcomes: [reply("a"), reply("b", FULL_TRACE), reply("c")] });
    await say("one");
    await compare();
    await say("two");
    expect(compareOut().hidden).toBe(true);
    expect(query('[data-role="drawer-summary"]').textContent).toBe("Prompt 179 vs 686 tokens");
  });

  it("keeps the first answer when the full run fails", async () => {
    mount({ outcomes: [reply("kept"), { kind: "failed", status: 429, reason: "http" }] });
    await say("hello");
    await compare();
    expect(compareOut().hidden).toBe(true);
    expect(query('[data-role="log"]').textContent).toContain("kept");
    expect(query('[data-role="log"]').textContent).toContain(text(english, "ui.error"));
    await flush();
    expect(query('[data-role="compare"]').textContent).toBe(text(english, "hood.compare.title"));
  });
});

describe("the summary of a turn", () => {
  it("uses the token total of the public trace", async () => {
    mount({ outcomes: [reply("a", { ...TRACE, tokens: { ...TRACE.tokens, total: 1234 } })] });
    await say("hello");
    expect(query('[data-role="drawer-summary"]').textContent).toContain("Prompt 1,234 vs");
  });
});

describe("a failed send", () => {
  const reasons = (): (string | null)[] =>
    [...document.querySelectorAll('[data-role="log"] [data-reason]')].map((node) => node.getAttribute("data-reason"));
  const errorLines = (): (string | null)[] =>
    [...document.querySelectorAll('[data-role="log"] [data-reason]')].map((node) => node.textContent);
  const refusing = (): Error => new Error("boom");

  it("shows the same plain error whatever went wrong, and records the kind on the line", async () => {
    const cases = [
      ["http", { outcomes: [{ kind: "failed", status: 500, reason: "http" }] }],
      ["malformed", { outcomes: [{ kind: "failed", status: 200, reason: "malformed" }] }],
      ["network", { outcomes: [{ kind: "failed", status: 0, reason: "network" }] }],
      ["unexpected", { gateway: { chat: () => Promise.reject(refusing()) } }],
    ] as const;
    for (const [reason, overrides] of cases) {
      mount(overrides);
      await say("hello");
      expect(errorLines(), reason).toEqual([text(english, "ui.error")]);
      expect(reasons(), reason).toEqual([reason]);
    }
  });

  it("records the kind on the line of a failed comparison too", async () => {
    mount({ outcomes: [reply("kept"), { kind: "failed", status: 429, reason: "http" }] });
    await say("hello");
    await compare();
    expect(errorLines()).toEqual([text(english, "ui.error")]);
    expect(reasons()).toEqual(["http"]);
  });
});

import { describe, expect, it } from "vitest";
import { limits } from "../src/limits";
import { parseChatRequest } from "../src/validate";
import { chatRequest } from "./support";

describe("parseChatRequest", () => {
  it("defaults the mode to gist", async () => {
    const result = await parseChatRequest(chatRequest(), limits);
    expect(result.ok && result.value.mode).toBe("gist");
  });

  it("accepts the full mode", async () => {
    const result = await parseChatRequest(chatRequest({ mode: "full" }), limits);
    expect(result.ok && result.value.mode).toBe("full");
  });

  it.each(["FULL", "", "rules", 1, null, true])("rejects the mode %j", async (mode) => {
    const result = await parseChatRequest(chatRequest({ mode }), limits);
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "InvalidRequest" },
    });
  });

  it("accepts a message of exactly the maximum length", async () => {
    const result = await parseChatRequest(chatRequest({ message: "a".repeat(300) }), limits);
    expect(result.ok).toBe(true);
  });

  it("rejects a message one character over the maximum", async () => {
    const result = await parseChatRequest(chatRequest({ message: "a".repeat(301) }), limits);
    expect(result).toEqual({ ok: false, error: { kind: "TooLong", max: 300 } });
  });

  it("counts characters, not UTF-16 units", async () => {
    const result = await parseChatRequest(chatRequest({ message: "😀".repeat(300) }), limits);
    expect(result.ok).toBe(true);
  });

  it("rejects a body larger than the byte limit before parsing", async () => {
    const request = chatRequest({
      turnstile_token: "x".repeat(limits.maxBodyBytes),
    });
    const result = await parseChatRequest(request, limits);
    expect(result).toEqual({
      ok: false,
      error: { kind: "TooLong", max: limits.maxBodyBytes },
    });
  });

  it.each([
    ["not json", "{"],
    ["an array", "[]"],
    ["a string", '"hi"'],
  ])("rejects a body that is %s", async (_name, body) => {
    const request = new Request("https://gateway.example.test/api/chat", {
      method: "POST",
      body,
    });
    const result = await parseChatRequest(request, limits);
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "InvalidRequest" },
    });
  });

  it.each([
    ["session_id", undefined],
    ["message", 5],
    ["turnstile_token", null],
  ])("rejects a missing or mistyped %s", async (name, value) => {
    const result = await parseChatRequest(chatRequest({ [name]: value }), limits);
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "InvalidRequest" },
    });
  });

  it.each(["short", "has space in it", "../../etc/passwd", "a".repeat(65)])(
    "rejects the session id %j",
    async (sessionId) => {
      const result = await parseChatRequest(chatRequest({ session_id: sessionId }), limits);
      expect(result).toMatchObject({
        ok: false,
        error: { kind: "InvalidRequest" },
      });
    },
  );

  it.each([{ message: "   " }, { turnstile_token: "" }])("rejects empty %j", async (override) => {
    const result = await parseChatRequest(chatRequest(override), limits);
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "InvalidRequest" },
    });
  });
});

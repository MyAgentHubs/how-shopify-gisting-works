import { describe, expect, it } from "vitest";
import { turnstilePolicy } from "../src/turnstile-policy";
import { requestVerdict, verifyTurnstile } from "../src/turnstile";
import type { Fetcher } from "../src/types";
import { GOOD_ACTION, GOOD_HOSTNAME, POLICY, SITEVERIFY, bodyOf, routedFetcher, verdict } from "./support";

const never: Fetcher = (_url, init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => {
      reject(new DOMException("timed out", "TimeoutError"));
    });
  });

describe("verifyTurnstile", () => {
  it("accepts a token that siteverify approves and sends only secret and token", async () => {
    const { fetcher, calls } = routedFetcher({ [SITEVERIFY]: verdict(true) });
    const result = await verifyTurnstile(fetcher, "sec", "tok", 1000, POLICY);
    expect(result.ok).toBe(true);
    expect(calls[0] === undefined ? "" : bodyOf(calls[0])).toBe("secret=sec&response=tok");
  });

  it("rejects a token that siteverify refuses", async () => {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: verdict(false) });
    const result = await verifyTurnstile(fetcher, "sec", "tok", 1000, POLICY);
    expect(result).toEqual({ ok: false, error: { kind: "TurnstileFailed", reason: "rejected" } });
  });

  it("fails when siteverify does not answer in time", async () => {
    const result = await verifyTurnstile(never, "sec", "tok", 20, POLICY);
    expect(result).toEqual({ ok: false, error: { kind: "TurnstileFailed", reason: "timeout" } });
  });

  it("fails when siteverify is unreachable", async () => {
    const down: Fetcher = () => Promise.reject(new Error("network"));
    const result = await verifyTurnstile(down, "sec", "tok", 1000, POLICY);
    expect(result).toEqual({ ok: false, error: { kind: "TurnstileFailed", reason: "unavailable" } });
  });

  it("treats a success body on any status other than 200 as unavailable", async () => {
    const body = { success: true, hostname: GOOD_HOSTNAME, action: GOOD_ACTION };
    const created = routedFetcher({ [SITEVERIFY]: () => Response.json(body, { status: 201 }) });
    const result = await verifyTurnstile(created.fetcher, "s", "t", 1000, POLICY);
    expect(result).toEqual({ ok: false, error: { kind: "TurnstileFailed", reason: "unavailable" } });
  });

  it("fails on an HTTP 500 even when the body says success for the right hostname and action", async () => {
    const body = { success: true, hostname: GOOD_HOSTNAME, action: GOOD_ACTION };
    const broken = routedFetcher({ [SITEVERIFY]: () => Response.json(body, { status: 500 }) });
    const result = await verifyTurnstile(broken.fetcher, "s", "t", 1000, POLICY);
    expect(result).toEqual({ ok: false, error: { kind: "TurnstileFailed", reason: "unavailable" } });
  });

  it("fails on a non-200 answer and on a body that is not JSON", async () => {
    const error = routedFetcher({ [SITEVERIFY]: () => new Response("x", { status: 500 }) });
    const garbled = routedFetcher({ [SITEVERIFY]: () => new Response("not json") });
    expect((await verifyTurnstile(error.fetcher, "s", "t", 1000, POLICY)).ok).toBe(false);
    expect((await verifyTurnstile(garbled.fetcher, "s", "t", 1000, POLICY)).ok).toBe(false);
  });
});

describe("requestVerdict", () => {
  async function verdictFor(body: unknown) {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: () => Response.json(body) });
    return requestVerdict(fetcher, "sec", "tok", 1000);
  }

  it("parses success, hostname, action and error codes from the siteverify answer", async () => {
    const result = await verdictFor({
      success: false,
      hostname: "www.example.test",
      action: "gisting-chat",
      "error-codes": ["timeout-or-duplicate"],
    });
    expect(result).toEqual({
      ok: true,
      value: {
        success: false,
        hostname: "www.example.test",
        action: "gisting-chat",
        errorCodes: ["timeout-or-duplicate"],
      },
    });
  });

  it("siteverify_without_hostname_is_parsed_and_left_to_the_policy", async () => {
    const result = await verdictFor({ success: true });
    expect(result).toEqual({ ok: true, value: { success: true, errorCodes: [] } });
  });

  it("siteverify_success_must_be_the_boolean_true", async () => {
    for (const success of ["true", 1, null, undefined]) {
      const result = await verdictFor({ success });
      expect(result).toMatchObject({ ok: true, value: { success: false } });
    }
  });

  it("ignores hostname, action and error codes of the wrong type", async () => {
    const result = await verdictFor({
      success: true,
      hostname: 7,
      action: ["x"],
      "error-codes": "oops",
    });
    expect(result).toEqual({ ok: true, value: { success: true, errorCodes: [] } });
  });

  it("keeps only string error codes", async () => {
    const result = await verdictFor({ success: false, "error-codes": ["a", 1, null, "b"] });
    expect(result).toMatchObject({ ok: true, value: { errorCodes: ["a", "b"] } });
  });

  it("fails with a typed error on a body that is not an object", async () => {
    for (const body of [null, "yes", 3, []]) {
      expect(await verdictFor(body)).toEqual({
        ok: false,
        error: { kind: "TurnstileFailed", reason: "unavailable" },
      });
    }
  });

  it("fails with a typed error on a non-200 answer, a body that is not JSON, and a network error", async () => {
    const status = routedFetcher({ [SITEVERIFY]: () => new Response("x", { status: 500 }) });
    const garbled = routedFetcher({ [SITEVERIFY]: () => new Response("not json") });
    const down: Fetcher = () => Promise.reject(new Error("network"));
    const expected = { ok: false, error: { kind: "TurnstileFailed", reason: "unavailable" } };
    expect(await requestVerdict(status.fetcher, "s", "t", 1000)).toEqual(expected);
    expect(await requestVerdict(garbled.fetcher, "s", "t", 1000)).toEqual(expected);
    expect(await requestVerdict(down, "s", "t", 1000)).toEqual(expected);
  });
});

describe("verifyTurnstile policy", () => {
  async function outcome(body: unknown) {
    const { fetcher } = routedFetcher({ [SITEVERIFY]: () => Response.json(body) });
    return verifyTurnstile(fetcher, "sec", "tok", 1000, POLICY);
  }

  const rejected = (reason: string) => ({
    ok: false,
    error: expect.objectContaining({ kind: "TurnstileFailed", reason }) as unknown,
  });

  it("accepts a verdict whose hostname and action both match", async () => {
    expect(await outcome({ success: true, hostname: GOOD_HOSTNAME, action: GOOD_ACTION })).toEqual({
      ok: true,
      value: true,
    });
  });

  it("compares the hostname without regard to case", async () => {
    const hostname = GOOD_HOSTNAME.toUpperCase();
    expect((await outcome({ success: true, hostname, action: GOOD_ACTION })).ok).toBe(true);
  });

  it("refuses a token issued for another hostname", async () => {
    const body = { success: true, hostname: "evil.example.test", action: GOOD_ACTION };
    expect(await outcome(body)).toEqual(rejected("hostname_mismatch"));
  });

  it("refuses the allowed hostname with a trailing dot", async () => {
    const body = { success: true, hostname: `${GOOD_HOSTNAME}.`, action: GOOD_ACTION };
    expect(await outcome(body)).toEqual(rejected("hostname_mismatch"));
  });

  it("refuses a hostname that only contains or extends an allowed one", async () => {
    for (const hostname of [`${GOOD_HOSTNAME}.evil.test`, `evil.${GOOD_HOSTNAME}`, ` ${GOOD_HOSTNAME}`]) {
      const body = { success: true, hostname, action: GOOD_ACTION };
      expect(await outcome(body)).toEqual(rejected("hostname_mismatch"));
    }
  });

  it("refuses a token issued for another action", async () => {
    const body = { success: true, hostname: GOOD_HOSTNAME, action: "login" };
    expect(await outcome(body)).toEqual(rejected("action_mismatch"));
  });

  it("refuses an action that differs only in case", async () => {
    const body = { success: true, hostname: GOOD_HOSTNAME, action: GOOD_ACTION.toUpperCase() };
    expect(await outcome(body)).toEqual(rejected("action_mismatch"));
  });

  it("siteverify_without_hostname_or_action_is_refused", async () => {
    expect(await outcome({ success: true })).toEqual(rejected("hostname_missing"));
  });

  it("refuses a missing hostname alone and a missing action alone", async () => {
    expect(await outcome({ success: true, action: GOOD_ACTION })).toEqual(rejected("hostname_missing"));
    expect(await outcome({ success: true, hostname: GOOD_HOSTNAME })).toEqual(rejected("action_mismatch"));
  });

  it("treats a hostname of the wrong type as missing", async () => {
    const body = { success: true, hostname: [GOOD_HOSTNAME], action: GOOD_ACTION };
    expect(await outcome(body)).toEqual(rejected("hostname_missing"));
  });

  it("names the observed hostname when it does not match", async () => {
    const body = { success: true, hostname: "evil.example.test", action: GOOD_ACTION };
    expect(await outcome(body)).toMatchObject({ error: { detail: "evil.example.test" } });
  });

  it("carries siteverify's error codes when it says no", async () => {
    const body = { success: false, "error-codes": ["timeout-or-duplicate", "invalid-input-response"] };
    expect(await outcome(body)).toMatchObject({
      error: { reason: "rejected", detail: "timeout-or-duplicate,invalid-input-response" },
    });
  });

  it("leaves the detail out when siteverify gives no error codes", async () => {
    expect(await outcome({ success: false })).toEqual({
      ok: false,
      error: { kind: "TurnstileFailed", reason: "rejected" },
    });
  });

  it("keeps only well-formed error codes in the detail", async () => {
    const body = { success: false, "error-codes": ["ok-code", "has space\nnewline", "x".repeat(100)] };
    expect(await outcome(body)).toMatchObject({ error: { detail: "ok-code" } });
  });

  it("replaces non-printable characters in the observed hostname", async () => {
    const body = { success: true, hostname: "evil\n.test\u0000", action: GOOD_ACTION };
    expect(await outcome(body)).toMatchObject({ error: { detail: "evil?.test?" } });
  });

  it("caps the observed hostname in the detail", async () => {
    const body = { success: true, hostname: "a".repeat(500), action: GOOD_ACTION };
    const result = await outcome(body);
    const detail = !result.ok && result.error.kind === "TurnstileFailed" ? result.error.detail : "";
    expect(detail?.length).toBe(253);
  });

  it("reports rejected, not a mismatch, when siteverify itself says no", async () => {
    const body = { success: false, hostname: "evil.example.test", action: "login" };
    expect(await outcome(body)).toEqual(rejected("rejected"));
  });

  it("accepts an extra hostname only when the policy lists it", async () => {
    const body = { success: true, hostname: "preview.example.test", action: GOOD_ACTION };
    expect((await outcome(body)).ok).toBe(false);
    const { fetcher } = routedFetcher({ [SITEVERIFY]: () => Response.json(body) });
    const wider = turnstilePolicy(["preview.example.test"]);
    expect((await verifyTurnstile(fetcher, "sec", "tok", 1000, wider)).ok).toBe(true);
  });
});

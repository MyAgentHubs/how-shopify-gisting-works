import { describe, expect, it } from "vitest";
import type { Mode } from "../src/gateway.ts";
import { accumulate, emptyMeter, fullEquivalent } from "../src/meter.ts";
import type { MeterConstants, MeterState } from "../src/meter.ts";
import type { PublicTrace } from "../src/trace.ts";
import { TRACE } from "./support.ts";

const CONSTANTS: MeterConstants = { rulesFull: 526, rulesGist: 19 };

function traceWith(rules: number, total: number): PublicTrace {
  return { ...TRACE, tokens: { ...TRACE.tokens, rules, total } };
}

function run(trace: PublicTrace, mode: Mode, state: MeterState = emptyMeter()): MeterState {
  return accumulate(state, trace, mode, CONSTANTS);
}

describe("accumulate", () => {
  it("counts one call per gist rules block and saves 507 tokens on each", () => {
    const state = run(traceWith(38, 500), "gist");
    expect(state).toEqual({ calls: 2, gistUsed: 500, fullWould: 500 + 1014 });
    expect(state.fullWould - state.gistUsed).toBe(1014);
  });

  it("adds up across turns", () => {
    const first = run(traceWith(19, 300), "gist");
    const second = run(traceWith(38, 500), "gist", first);
    expect(second).toEqual({ calls: 3, gistUsed: 800, fullWould: 800 + 3 * 507 });
  });

  it("skips a turn whose rules tokens are not a whole number of gist blocks", () => {
    expect(run(traceWith(20, 500), "gist")).toEqual(emptyMeter());
  });

  it("skips compare turns served in full mode", () => {
    expect(run(traceWith(526, 900), "full")).toEqual(emptyMeter());
  });

  it("skips a turn answered by code without any model call, and does not fail", () => {
    expect(run(traceWith(0, 0), "gist")).toEqual(emptyMeter());
  });

  it("leaves the previous state untouched", () => {
    const before = run(traceWith(19, 300), "gist");
    run(traceWith(19, 300), "gist", before);
    expect(before).toEqual({ calls: 1, gistUsed: 300, fullWould: 300 + 507 });
  });

  it("refuses constants that cannot describe a saving", () => {
    const state = emptyMeter();
    const trace = traceWith(19, 300);
    expect(() => accumulate(state, trace, "gist", { rulesFull: 526, rulesGist: 0 })).toThrow(
      TypeError,
    );
    expect(() => accumulate(state, trace, "gist", { rulesFull: 19, rulesGist: 19 })).toThrow(
      TypeError,
    );
    expect(() => accumulate(state, trace, "gist", { rulesFull: 526, rulesGist: 18.5 })).toThrow(
      TypeError,
    );
  });
});

describe("fullEquivalent", () => {
  it("adds 507 tokens and 526 rule tokens for every gist rules block in the call", () => {
    expect(fullEquivalent(traceWith(19, 179), CONSTANTS)).toEqual({ rules: 526, total: 686 });
    expect(fullEquivalent(traceWith(38, 500), CONSTANTS)).toEqual({ rules: 1052, total: 1514 });
  });

  it("has no answer for a call with no gist rules block or a part of one", () => {
    expect(fullEquivalent(traceWith(0, 0), CONSTANTS)).toBeNull();
    expect(fullEquivalent(traceWith(20, 500), CONSTANTS)).toBeNull();
    expect(fullEquivalent(traceWith(526, 900), CONSTANTS)).toBeNull();
  });

  it("refuses constants that cannot describe a saving", () => {
    expect(() => fullEquivalent(traceWith(19, 300), { rulesFull: 19, rulesGist: 19 })).toThrow(TypeError);
  });
});

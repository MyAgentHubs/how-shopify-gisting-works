import type { Mode } from "./gateway.ts";
import type { PublicTrace } from "./trace.ts";

export interface MeterConstants {
  readonly rulesFull: number;
  readonly rulesGist: number;
}

export interface MeterState {
  readonly calls: number;
  readonly gistUsed: number;
  readonly fullWould: number;
}

export function emptyMeter(): MeterState {
  return { calls: 0, gistUsed: 0, fullWould: 0 };
}

function savedPerCall(constants: MeterConstants): number {
  const { rulesFull, rulesGist } = constants;
  if (!Number.isInteger(rulesGist) || !Number.isInteger(rulesFull) || rulesGist < 1) {
    throw new TypeError("rules token constants must be positive integers");
  }
  if (rulesFull <= rulesGist) {
    throw new TypeError("the full rules must be longer than the gist rules");
  }
  return rulesFull - rulesGist;
}

function callsOf(trace: PublicTrace, constants: MeterConstants): number | null {
  const calls = trace.tokens.rules / constants.rulesGist;
  return Number.isInteger(calls) && calls >= 1 ? calls : null;
}

export function fullEquivalent(
  trace: PublicTrace,
  constants: MeterConstants,
): { readonly rules: number; readonly total: number } | null {
  const saved = savedPerCall(constants);
  const calls = callsOf(trace, constants);
  if (calls === null) {
    return null;
  }
  return { rules: calls * constants.rulesFull, total: trace.tokens.total + calls * saved };
}

export function accumulate(
  state: MeterState,
  trace: PublicTrace,
  mode: Mode,
  constants: MeterConstants,
): MeterState {
  const full = fullEquivalent(trace, constants);
  const calls = callsOf(trace, constants);
  if (mode !== "gist" || full === null || calls === null) {
    return state;
  }
  return {
    calls: state.calls + calls,
    gistUsed: state.gistUsed + trace.tokens.total,
    fullWould: state.fullWould + full.total,
  };
}

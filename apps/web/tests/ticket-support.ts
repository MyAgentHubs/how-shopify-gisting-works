import { vi } from "vitest";
import { fakeGateway } from "../fakes/fake-gateway.ts";
import type { FakeGateway } from "../fakes/fake-gateway.ts";
import type { ChatOutcome, ChatRequest } from "../src/gateway.ts";
import type { HumanCheck } from "../src/turnstile.ts";
import { reply } from "./support.ts";

const MAC = "A".repeat(43);
const MS_PER_SECOND = 1000;

export function pinClock(): void {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Math.floor(Date.now() / MS_PER_SECOND) * MS_PER_SECOND);
}

export function ticketExpiringIn(seconds: number, mac: string = MAC): string {
  return `1.${String(Math.floor(Date.now() / MS_PER_SECOND) + seconds)}.${mac}`;
}

export const FRESH = ticketExpiringIn(1800);

export function countingCheck(): HumanCheck & { readonly calls: () => number } {
  let calls = 0;
  return {
    warm: () => undefined, reset: () => undefined,
    token: () => {
      calls += 1;
      return Promise.resolve(`token-${String(calls)}`);
    },
    calls: () => calls,
  };
}

export type Step = (request: ChatRequest) => ChatOutcome;

export function stepping(steps: readonly Step[]): FakeGateway {
  let index = 0;
  return fakeGateway((request) => {
    const step = steps[Math.min(index, steps.length - 1)];
    index += 1;
    return step?.(request) ?? reply("fallback");
  });
}

export const answer =
  (text: string, ticket?: string): Step =>
  () => ({ ...reply(text), ...(ticket === undefined ? {} : { ticket }) });

export const forbidden: Step = () => ({ kind: "failed", status: 403, reason: "http" });
export const broken: Step = () => ({ kind: "failed", status: 500, reason: "http" });

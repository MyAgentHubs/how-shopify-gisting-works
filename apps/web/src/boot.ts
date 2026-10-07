import { mountApp } from "./app.ts";
import type { Gateway } from "./gateway.ts";
import { readRuntime } from "./runtime.ts";
import { newSessionId, parseLimits } from "./session.ts";
import type { CheckWaits, HumanCheck, TurnstileConfig } from "./turnstile.ts";

export interface BootEnv {
  readonly gateway: Gateway;
  readonly humanCheck: (config: TurnstileConfig, waits: CheckWaits) => HumanCheck;
}

const ASSET_ROOT = "/opengisting/";

async function loadJson(name: string): Promise<unknown> {
  const path = `${ASSET_ROOT}${name}`;
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`cannot load ${path}: ${String(response.status)}`);
  }
  return (await response.json()) as unknown;
}

export async function boot(env: BootEnv): Promise<void> {
  const { copy, meter, turnstile, pricing } = readRuntime(document);
  const limits = parseLimits(await loadJson("data/limits.json"));
  mountApp(document, {
    gateway: env.gateway,
    check: env.humanCheck(turnstile, {
      waitMs: limits.humanCheckWaitMs,
      interactiveMs: limits.humanCheckInteractiveMs,
    }),
    copy,
    meter,
    pricing,
    limits,
    matchMedia: (query) => window.matchMedia(query),
    newSessionId,
  });
}

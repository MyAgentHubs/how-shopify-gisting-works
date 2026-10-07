import type { PublicRules } from "../../../contracts/public_rules.generated.ts";
import limitsJson from "../data/limits.json";
import publicRulesJson from "../data/public_rules.json";
import copyEn from "../copy/en.json";
import type { AppDeps } from "../src/app.ts";
import { role } from "../src/dom.ts";
import { mountApp } from "../src/app.ts";
import type { Copy } from "../src/copy.ts";
import { parseCopy } from "../src/copy.ts";
import type { ChatOutcome, ChatRequest, Gateway } from "../src/gateway.ts";
import { NARROW_QUERY } from "../src/layout.ts";
import { readRuntime } from "../src/runtime.ts";
import type { PublicTrace } from "../src/trace.ts";
import type { CheckWaits, HumanCheck, TurnstileConfig } from "../src/turnstile.ts";
import { buildPages } from "./page-helpers.mjs";

const builtEnglishPage = new DOMParser().parseFromString(buildPages().html("en"), "text/html");

export const CANARY = "CANARY-7f3a9c1e";
export const publicRules: PublicRules = publicRulesJson;
export const english: Copy = parseCopy(copyEn);

export const TRACE: PublicTrace = {
  tools: [{ tool: "lookup_order", order_number: "#1042", outcome: "completed" }],
  knowledge: [{ id: "kb-ship-standard", method: "bm25" }],
  tokens: { rules: 19, tools: 120, history: 40, tool_results: 0, total: 179 },
  latency: { first_token_ms: 900, total_ms: 1800 },
};

export const FULL_TRACE: PublicTrace = {
  ...TRACE,
  tokens: { rules: 526, tools: 120, history: 40, tool_results: 0, total: 686 },
};

export function reply(answer: string, trace: PublicTrace = TRACE): ChatOutcome {
  return { kind: "reply", answer, trace };
}

export interface Media {
  readonly matchMedia: (query: string) => MediaQueryList;
  setMobile(mobile: boolean): void;
}

export function media(mobile: boolean): Media {
  let current = mobile;
  const listeners: (() => void)[] = [];
  const list = (query: string): MediaQueryList => {
    const queryList = {
      get matches() {
        return query === NARROW_QUERY && current;
      },
      addEventListener: (_type: string, listener: () => void) => listeners.push(listener),
    };
    return queryList as unknown as MediaQueryList;
  };
  return {
    matchMedia: list,
    setMobile(next) {
      current = next;
      listeners.forEach((listener) => {
        listener();
      });
    },
  };
}

function scripted(outcomes: readonly ChatOutcome[]): Gateway & { requests: ChatRequest[] } {
  const requests: ChatRequest[] = [];
  let index = 0;
  return {
    requests,
    chat(request) {
      requests.push(request);
      const outcome = outcomes[Math.min(index, outcomes.length - 1)];
      index += 1;
      return Promise.resolve(outcome ?? { kind: "failed", status: 0, reason: "network" });
    },
  };
}

export interface Page {
  readonly gateway: Gateway & { requests: ChatRequest[] };
  readonly media: Media;
  readonly deps: AppDeps;
}

export function fixedToken(token: string): HumanCheck {
  return { warm: () => undefined, reset: () => undefined, token: () => Promise.resolve(token) };
}

export function mount(
  overrides: Partial<AppDeps> & {
    outcomes?: readonly ChatOutcome[];
    humanCheck?: (config: TurnstileConfig, waits: CheckWaits) => HumanCheck;
  } = {},
): Page {
  document.documentElement.innerHTML = builtEnglishPage.documentElement.innerHTML;
  document.documentElement.lang = builtEnglishPage.documentElement.lang;
  const { outcomes, humanCheck, ...rest } = overrides;
  const runtime = readRuntime(document);
  const gateway = scripted(outcomes ?? [reply("Answer one"), reply("Answer two")]);
  const pageMedia = media(false);
  const deps: AppDeps = {
    gateway,
    copy: runtime.copy,
    pricing: runtime.pricing,
    limits: limitsJson,
    meter: { rulesFull: 526, rulesGist: 19 },
    matchMedia: pageMedia.matchMedia,
    newSessionId: () => "session-abcdef01",
    check: humanCheck?.(runtime.turnstile, {
      waitMs: limitsJson.humanCheckWaitMs,
      interactiveMs: limitsJson.humanCheckInteractiveMs,
    }) ?? fixedToken("token"),
    ...rest,
  };
  mountApp(document, deps);
  return { gateway, media: pageMedia, deps };
}

export async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

export function query(selector: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(selector);
  if (node === null) {
    throw new Error(`no element matches ${selector}`);
  }
  return node;
}

export function inputBox(): HTMLInputElement {
  return role(document, "input", HTMLInputElement);
}

export function compareButton(): HTMLButtonElement {
  return role(document, "compare", HTMLButtonElement);
}

export function compareOut(): HTMLElement {
  return role(document, "compare-out", HTMLElement);
}

export function submitMessage(message: string): void {
  inputBox().value = message;
  role(document, "form", HTMLFormElement).dispatchEvent(
    new Event("submit", { bubbles: true, cancelable: true }),
  );
}

export async function say(message: string): Promise<void> {
  submitMessage(message);
  await flush();
}

export async function compare(): Promise<void> {
  compareButton().click();
  await flush();
}

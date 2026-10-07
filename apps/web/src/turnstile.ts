import { role } from "./dom.ts";

export const TURNSTILE_SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js";

const INTERACTION_ONLY = "interaction-only";
const MANUAL = "manual";

export interface TurnstileConfig {
  readonly sitekey: string;
  readonly action: string;
}

export interface WidgetOptions {
  readonly sitekey: string;
  readonly action: string;
  readonly appearance: typeof INTERACTION_ONLY;
  readonly "refresh-expired": typeof MANUAL;
  readonly callback: (token: string) => void;
  readonly "error-callback": () => void;
  readonly "expired-callback": () => void;
  readonly "timeout-callback": () => void;
  readonly "before-interactive-callback": () => void;
  readonly "after-interactive-callback": () => void;
}

export interface TurnstileApi {
  render(container: HTMLElement, options: WidgetOptions): string | undefined;
  reset(widgetId: string): void;
  remove(widgetId: string): void;
}

export interface HumanCheck {
  warm(): void;
  reset(): void;
  token(): Promise<string>;
}

export type ScriptLoader = (src: string) => Promise<void>;

export interface CheckWaits {
  readonly waitMs: number;
  readonly interactiveMs: number;
}

interface Parts extends CheckWaits {
  readonly container: HTMLElement;
  readonly config: TurnstileConfig;
  readonly api: () => TurnstileApi | undefined;
  readonly load: ScriptLoader;
}

interface Waiter {
  readonly resolve: (token: string) => void;
  readonly reject: (reason: Error) => void;
  readonly arm: (ms: number) => void;
}

function withTimeout(task: Promise<void>, ms: number): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error("the Turnstile script did not load in time"));
    }, ms);
    task.then(resolve, reject).finally(() => {
      clearTimeout(timer);
    });
  });
}

class WidgetCheck implements HumanCheck {
  private readonly parts: Parts;
  private script: Promise<void> | null = null;
  private widget: Promise<string> | null = null;
  private widgetId: string | null = null;
  private held: string | null = null;
  private spent = false;
  private broken = false;
  private interactive = false;
  private readonly waiters: Waiter[] = [];

  constructor(parts: Parts) {
    this.parts = parts;
  }

  warm(): void {
    void this.start()
      .then(() => {
        this.refreshIfSpent();
      })
      .catch(() => undefined);
  }

  async token(): Promise<string> {
    await this.start();
    if (this.broken) {
      this.broken = false;
      this.reset();
    }
    this.refreshIfSpent();
    const held = this.held;
    if (held !== null) {
      this.held = null;
      this.spent = true;
      return held;
    }
    return this.wait();
  }

  private refreshIfSpent(): void {
    if (this.spent) {
      this.reset();
    }
  }

  private start(): Promise<string> {
    this.script ??= withTimeout(this.parts.load(TURNSTILE_SCRIPT_URL), this.parts.waitMs).catch(
      (error: unknown) => {
        this.script = null;
        throw error;
      },
    );
    this.widget ??= this.script
      .then(() => this.render())
      .catch((error: unknown) => {
        this.widget = null;
        throw error;
      });
    return this.widget;
  }

  private render(): string {
    const api = this.parts.api();
    if (api === undefined) {
      throw new TypeError("the Turnstile script left no turnstile object on the page");
    }
    const { sitekey, action } = this.parts.config;
    const id = api.render(this.parts.container, {
      sitekey,
      action,
      appearance: INTERACTION_ONLY,
      "refresh-expired": MANUAL,
      callback: (token) => {
        this.deliver(token);
      },
      "error-callback": () => {
        this.fail();
      },
      "expired-callback": () => {
        this.expired();
      },
      "timeout-callback": () => {
        this.fail();
      },
      "before-interactive-callback": () => {
        this.setInteractive(true);
      },
      "after-interactive-callback": () => {
        this.setInteractive(false);
      },
    });
    if (id === undefined) {
      throw new TypeError("Turnstile did not return a widget id");
    }
    this.widgetId = id;
    return id;
  }

  private expired(): void {
    this.held = null;
    if (!this.spent) {
      this.reset();
      return;
    }
    this.interactive = false;
    this.spent = false;
    const id = this.widgetId;
    this.widgetId = null;
    this.widget = null;
    if (id !== null) {
      this.parts.api()?.remove(id);
    }
  }

  reset(): void {
    this.held = null;
    this.broken = false;
    this.interactive = false;
    this.spent = false;
    const id = this.widgetId;
    if (id !== null) {
      this.parts.api()?.reset(id);
    }
  }

  private deliver(token: string): void {
    const waiter = this.waiters.shift();
    if (waiter === undefined) {
      this.held = token;
      return;
    }
    this.spent = true;
    waiter.resolve(token);
  }

  private fail(): void {
    this.interactive = false;
    this.held = null;
    this.broken = true;
    for (const waiter of this.waiters.splice(0)) {
      waiter.reject(new Error("the human check failed"));
    }
  }

  private setInteractive(interactive: boolean): void {
    this.interactive = interactive;
    for (const waiter of this.waiters) {
      waiter.arm(this.limit());
    }
  }

  private limit(): number {
    return this.interactive ? this.parts.interactiveMs : this.parts.waitMs;
  }

  private expire(waiter: Waiter): void {
    this.waiters.splice(this.waiters.indexOf(waiter), 1);
    this.reset();
    waiter.reject(new Error("the human check timed out"));
  }

  private wait(): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const waiter: Waiter = {
        resolve: (token) => {
          clearTimeout(timer);
          resolve(token);
        },
        reject: (reason) => {
          clearTimeout(timer);
          reject(reason);
        },
        arm: (ms) => {
          clearTimeout(timer);
          timer = setTimeout(() => {
            this.expire(waiter);
          }, ms);
        },
      };
      waiter.arm(this.limit());
      this.waiters.push(waiter);
    });
  }
}

export function createHumanCheck(parts: Parts): HumanCheck {
  return new WidgetCheck(parts);
}

export function injectScript(doc: Document): ScriptLoader {
  return (src) =>
    new Promise<void>((resolve, reject) => {
      const script = doc.createElement("script");
      script.src = src;
      script.async = true;
      script.defer = true;
      script.addEventListener("load", () => {
        resolve();
      });
      script.addEventListener("error", () => {
        reject(new Error(`${src} could not be loaded`));
      });
      doc.head.append(script);
    });
}

type Host = Window & { turnstile?: TurnstileApi };

export function browserHumanCheck(
  doc: Document,
  win: Window,
): (config: TurnstileConfig, waits: CheckWaits) => HumanCheck {
  return (config, waits) =>
    createHumanCheck({
      container: role(doc, "turnstile", HTMLElement),
      config,
      ...waits,
      api: () => (win as Host).turnstile,
      load: injectScript(doc),
    });
}

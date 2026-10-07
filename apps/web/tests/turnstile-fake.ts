import type { TurnstileApi, WidgetOptions } from "../src/turnstile.ts";

interface FakeWidget {
  readonly container: HTMLElement;
  readonly options: WidgetOptions;
}

export function fakeTurnstile(): {
  readonly api: TurnstileApi;
  readonly widgets: FakeWidget[];
  readonly resets: string[];
  readonly removed: string[];
  solve(token: string): void;
  fail(): void;
  expire(): void;
  stall(): void;
  interact(): void;
  interactDone(): void;
} {
  const widgets: FakeWidget[] = [];
  const resets: string[] = [];
  const removed: string[] = [];
  const last = (): WidgetOptions => {
    const widget = widgets.at(-1);
    if (widget === undefined) {
      throw new Error("nothing rendered");
    }
    return widget.options;
  };
  return {
    widgets,
    resets,
    removed,
    api: {
      render(container, options) {
        widgets.push({ container, options });
        return `widget-${String(widgets.length)}`;
      },
      reset(id) {
        resets.push(id);
      },
      remove(id) {
        removed.push(id);
      },
    },
    solve: (token) => {
      last().callback(token);
    },
    fail: () => {
      last()["error-callback"]();
    },
    expire: () => {
      last()["expired-callback"]();
    },
    stall: () => {
      last()["timeout-callback"]();
    },
    interact: () => {
      last()["before-interactive-callback"]();
    },
    interactDone: () => {
      last()["after-interactive-callback"]();
    },
  };
}

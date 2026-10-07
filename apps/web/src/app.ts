import type { ControllerDeps } from "./controller.ts";
import { Controller } from "./controller.ts";
import { collectElements } from "./elements.ts";
import { bindExamples } from "./examples.ts";
import { collapseWhenNarrow } from "./layout.ts";

export interface AppDeps extends ControllerDeps {
  readonly matchMedia: (query: string) => MediaQueryList;
}

export function mountApp(doc: Document, deps: AppDeps): void {
  const els = collectElements(doc);
  const controller = new Controller(deps, els);
  els.input.maxLength = deps.limits.maxMessageChars;
  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    void controller.submit();
  });
  const warm = (): void => {
    controller.warm();
  };
  els.input.addEventListener("focus", warm);
  els.compare.addEventListener("click", () => void controller.compare());
  bindExamples(doc, els.input, warm, deps.limits.exampleFlashMs);
  collapseWhenNarrow(els.hood, deps.matchMedia);
  controller.refresh();
}

import { role } from "./dom.ts";

export interface Elements {
  readonly log: HTMLElement;
  readonly form: HTMLFormElement;
  readonly input: HTMLInputElement;
  readonly send: HTMLButtonElement;
  readonly body: HTMLElement;
  readonly hood: HTMLDetailsElement;
  readonly summary: HTMLElement;
  readonly compare: HTMLButtonElement;
  readonly left: HTMLElement;
  readonly out: HTMLElement;
  readonly meter: HTMLElement;
}

export function collectElements(doc: Document): Elements {
  return {
    log: role(doc, "log", HTMLElement),
    form: role(doc, "form", HTMLFormElement),
    input: role(doc, "input", HTMLInputElement),
    send: role(doc, "send", HTMLButtonElement),
    body: role(doc, "panel-body", HTMLElement),
    hood: role(doc, "hood", HTMLDetailsElement),
    summary: role(doc, "drawer-summary", HTMLElement),
    compare: role(doc, "compare", HTMLButtonElement),
    left: role(doc, "compare-left", HTMLElement),
    out: role(doc, "compare-out", HTMLElement),
    meter: role(doc, "meter", HTMLElement),
  };
}

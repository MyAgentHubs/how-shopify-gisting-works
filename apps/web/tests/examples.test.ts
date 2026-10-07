import { describe, expect, it } from "vitest";
import examples from "../data/example_orders.json";
import { bindExamples } from "../src/examples.ts";
import { flush, inputBox, mount, query } from "./support.ts";

const ORDER_QUESTION = (order: string, email: string): string =>
  `Where is my order ${order}? My email is ${email}.`;
const HUMAN_REQUEST = "I'd like to talk to a human agent about my purchase.";
const [IN_TRANSIT, UNFULFILLED] = examples.examples;

function buttons(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>(".og-exbtn")];
}

function press(index: number): void {
  const button = buttons()[index];
  if (button === undefined) {
    throw new RangeError(`no example button at ${String(index)}`);
  }
  button.click();
}

function countSubmits(): () => number {
  let submits = 0;
  document.addEventListener("submit", () => {
    submits += 1;
  });
  return () => submits;
}

describe("the example buttons", () => {
  it("put the order question with its number and email into the box", () => {
    mount();
    expect(IN_TRANSIT?.email).toBeDefined();
    press(0);
    expect(inputBox().value).toBe(ORDER_QUESTION("#1006", IN_TRANSIT?.email ?? ""));
    press(1);
    expect(inputBox().value).toBe(ORDER_QUESTION("#1022", UNFULFILLED?.email ?? ""));
  });

  it("put the human request, as written, into the box", () => {
    mount();
    press(2);
    expect(inputBox().value).toBe(HUMAN_REQUEST);
  });

  it("replace what was typed and move the focus to the box", () => {
    mount();
    inputBox().value = "half a thought";
    press(2);
    expect(inputBox().value).toBe(HUMAN_REQUEST);
    expect(document.activeElement).toBe(inputBox());
  });

  it("fill the box and never send: no submit event, no request to the gateway", async () => {
    const page = mount();
    const submits = countSubmits();
    for (const index of [0, 1, 2]) {
      press(index);
    }
    await flush();
    expect(submits()).toBe(0);
    expect(page.gateway.requests).toHaveLength(0);
    expect(query('[data-role="log"]').children).toHaveLength(0);
  });

  it("stay within the message limit the box enforces", () => {
    const page = mount();
    for (const index of [0, 1, 2]) {
      press(index);
      expect(Array.from(inputBox().value).length).toBeLessThanOrEqual(page.deps.limits.maxMessageChars);
    }
  });

  it("do nothing to a page without them", () => {
    mount();
    const empty = document.createElement("div");
    expect(() => {
      bindExamples(empty, inputBox(), () => undefined, 1);
    }).not.toThrow();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import publicOrders from "../data/public_orders.json";
import limits from "../data/limits.json";
import { inputBox, mount, say } from "./support.ts";

function buttons(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>(".og-morebtn")];
}

afterEach(() => {
  vi.useRealTimers();
});

describe("more sample orders on the built page", () => {
  it.each(publicOrders.orders)("prefills $order without sending", (row) => {
    vi.useFakeTimers();
    const page = mount();
    const cards = buttons();
    expect(cards).toHaveLength(8);
    const card = cards.find((button) => button.querySelector("span")?.textContent === row.order);
    expect(card).toBeDefined();
    document.querySelector("details.og-more")?.setAttribute("open", "");
    card?.click();
    expect(inputBox().value).toBe(card?.dataset["prefill"]);
    expect(inputBox().value).toContain(row.order);
    expect(inputBox().value).toContain(row.email);
    expect(document.activeElement).toBe(inputBox());
    expect(inputBox().classList.contains("og-filled")).toBe(true);
    expect(page.gateway.requests).toHaveLength(0);
    vi.advanceTimersByTime(limits.exampleFlashMs);
    expect(inputBox().classList.contains("og-filled")).toBe(false);
  });

  it("ignores all eight buttons once the real chat is full", async () => {
    const warm = vi.fn();
    const page = mount({
      limits: { ...limits, maxMessages: 1 },
      check: { warm, reset: () => undefined, token: () => Promise.resolve("token") },
    });
    await say("only message");
    expect(inputBox().disabled).toBe(true);
    warm.mockClear();
    vi.useFakeTimers();
    const focus = document.activeElement;
    expect(buttons()).toHaveLength(8);
    for (const card of buttons()) {
      card.click();
      expect(inputBox().value).toBe("");
      expect(inputBox().classList.contains("og-filled")).toBe(false);
      expect(document.activeElement).toBe(focus);
    }
    vi.advanceTimersByTime(limits.exampleFlashMs);
    expect(inputBox().classList.contains("og-filled")).toBe(false);
    expect(warm).not.toHaveBeenCalled();
    expect(page.gateway.requests).toHaveLength(1);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import limits from "../data/limits.json";
import { parseLimits } from "../src/session.ts";
import { inputBox, mount, say } from "./support.ts";

const FILLED = "og-filled";

function cards(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>(".og-exbtn")];
}

afterEach(() => {
  vi.useRealTimers();
});

describe("clicking an example card", () => {
  it("fills the box and marks it as filled for the flash time, then clears the mark", () => {
    vi.useFakeTimers();
    mount();
    const card = cards()[0];
    card?.click();
    expect(inputBox().value).toBe(card?.dataset["prefill"]);
    expect(inputBox().classList.contains(FILLED)).toBe(true);
    vi.advanceTimersByTime(limits.exampleFlashMs - 1);
    expect(inputBox().classList.contains(FILLED)).toBe(true);
    vi.advanceTimersByTime(1);
    expect(inputBox().classList.contains(FILLED)).toBe(false);
  });

  it("restarts the flash when another card is clicked before the first one ends", () => {
    vi.useFakeTimers();
    mount();
    cards()[0]?.click();
    vi.advanceTimersByTime(limits.exampleFlashMs - 100);
    cards()[1]?.click();
    vi.advanceTimersByTime(200);
    expect(inputBox().classList.contains(FILLED)).toBe(true);
    vi.advanceTimersByTime(limits.exampleFlashMs);
    expect(inputBox().classList.contains(FILLED)).toBe(false);
  });
});

describe("clicking an example card once the chat is full", () => {
  async function fullChat(): Promise<ReturnType<typeof vi.fn>> {
    const warm = vi.fn();
    mount({
      limits: { ...limits, maxMessages: 1 },
      check: { warm, reset: () => undefined, token: () => Promise.resolve("token") },
    });
    await say("only message");
    expect(inputBox().disabled).toBe(true);
    warm.mockClear();
    return warm;
  }

  it("leaves the box empty and unmarked, and does not wake the bot check", async () => {
    const warm = await fullChat();
    cards()[0]?.click();
    expect(inputBox().value).toBe("");
    expect(inputBox().classList.contains(FILLED)).toBe(false);
    expect(warm).not.toHaveBeenCalled();
  });

  it("starts no flash that could mark the box later", async () => {
    const warm = await fullChat();
    vi.useFakeTimers();
    cards()[0]?.click();
    vi.advanceTimersByTime(limits.exampleFlashMs);
    expect(inputBox().classList.contains(FILLED)).toBe(false);
    expect(warm).not.toHaveBeenCalled();
  });
});

describe("the example cards", () => {
  it("each hold a decorative arrow hidden from assistive technology", () => {
    mount();
    expect(cards()).toHaveLength(11);
    for (const card of cards()) {
      const arrow = card.querySelector(".og-exgo");
      expect(arrow?.getAttribute("aria-hidden")).toBe("true");
      expect(arrow?.tagName.toLowerCase()).toBe("svg");
      expect(arrow?.textContent).toBe("");
    }
  });
});

describe("the flash time", () => {
  it("is a positive integer the page limits accept", () => {
    expect(parseLimits(limits).exampleFlashMs).toBe(limits.exampleFlashMs);
    expect(() => parseLimits({ ...limits, exampleFlashMs: 0 })).toThrow(TypeError);
  });
});

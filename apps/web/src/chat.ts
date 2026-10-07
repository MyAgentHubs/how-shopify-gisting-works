import type { Copy, CopyKey } from "./copy.ts";
import { text } from "./copy.ts";
import { el } from "./dom.ts";
import type { FailureReason, ReplayReason, ReplayTurn } from "./gateway.ts";

export type Speaker = "user" | "bot" | "sys";

const SPEAKER_CLASS: Readonly<Record<Speaker, string>> = {
  user: "og-u",
  bot: "og-b",
  sys: "og-s",
};

export function addMessage(log: HTMLElement, speaker: Speaker, content: string): void {
  log.append(el("div", { class: `og-cm ${SPEAKER_CLASS[speaker]}` }, content));
  log.scrollTop = log.scrollHeight;
}

export function showTyping(log: HTMLElement, label: string): void {
  log.setAttribute("aria-busy", "true");
  if (log.querySelector(".og-typing") !== null) {
    return;
  }
  log.append(el("div", {
    class: "og-cm og-b og-typing", role: "status", "aria-label": label,
  }, el("span"), el("span"), el("span")));
  log.scrollTop = log.scrollHeight;
}

export function hideTyping(log: HTMLElement): void {
  log.querySelector(".og-typing")?.remove();
  log.removeAttribute("aria-busy");
}

export function addError(log: HTMLElement, content: string, reason: FailureReason): void {
  log.append(el("div", { class: `og-cm ${SPEAKER_CLASS.sys}`, "data-reason": reason }, content));
  log.scrollTop = log.scrollHeight;
}

export function addCheckError(log: HTMLElement, copy: Copy, retry: (button: HTMLButtonElement) => void): void {
  const button = el("button", { type: "button", class: "og-btn-app og-sec2" }, text(copy, "ui.checkRetry"));
  button.addEventListener("click", () => {
    retry(button);
  });
  log.append(el("div", { class: "og-cm og-s", "data-reason": "check" },
    el("p", {}, text(copy, "ui.checkFailed")), button));
  log.scrollTop = log.scrollHeight;
}

const BANNER_BY_REASON: Readonly<Record<ReplayReason, CopyKey>> = {
  quota: "replay.banner",
  offline: "replay.banner_offline",
};

export function addReplay(
  log: HTMLElement,
  copy: Copy,
  reason: ReplayReason,
  turns: readonly ReplayTurn[],
): void {
  log.append(
    el(
      "div",
      { class: "og-replay", role: "status" },
      el("p", { class: "og-replay-banner" }, text(copy, BANNER_BY_REASON[reason])),
      el("p", { class: "og-replay-label" }, text(copy, "replay.label")),
    ),
  );
  for (const turn of turns) {
    addMessage(log, turn.role === "user" ? "user" : "bot", turn.content);
  }
}

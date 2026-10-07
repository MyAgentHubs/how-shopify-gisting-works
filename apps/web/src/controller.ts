import { addCheckError, addError, addMessage, addReplay, hideTyping, showTyping } from "./chat.ts";
import { comparesLeftText, renderCompare } from "./compare.ts";
import type { Pricing } from "../../../contracts/pricing.generated.ts";
import type { Copy } from "./copy.ts";
import { text } from "./copy.ts";
import type { Elements } from "./elements.ts";
import type { ChatOutcome, Gateway, Mode } from "./gateway.ts";
import type { MeterConstants, MeterState } from "./meter.ts";
import { accumulate, emptyMeter } from "./meter.ts";
import { renderMeter } from "./meter-view.ts";
import type { TurnView } from "./panel.ts";
import { drawerSummary, renderPanel } from "./panel.ts";
import type { Session, UiLimits } from "./session.ts";
import type { HumanCheck } from "./turnstile.ts";
import { ticketIfUsable } from "./ticket.ts";
import { canSend, comparesLeft, createSession } from "./session.ts";

export interface ControllerDeps {
  readonly gateway: Gateway;
  readonly copy: Copy;
  readonly limits: UiLimits;
  readonly meter: MeterConstants;
  readonly pricing: Pricing;
  readonly newSessionId: () => string;
  readonly check: HumanCheck;
}

type Reply = Extract<ChatOutcome, { kind: "reply" }>;

type Credential = { readonly ticket: string } | { readonly turnstileToken: string };

const NO_RESPONSE = 0;
const FORBIDDEN = 403;

function isRefusal(outcome: ChatOutcome): boolean {
  return outcome.kind === "failed" && outcome.reason === "http" && outcome.status === FORBIDDEN;
}

export class Controller {
  private readonly deps: ControllerDeps;
  private readonly els: Elements;
  private readonly session: Session;
  private turn: TurnView | null = null;
  private lastMessage = "";
  private lastAnswer = "";
  private total: MeterState = emptyMeter();
  private busy = false;

  constructor(deps: ControllerDeps, els: Elements) {
    this.deps = deps;
    this.els = els;
    this.session = createSession(deps.newSessionId());
    const duration = `${String(deps.limits.busyAnimationMs)}ms`;
    els.log.style.setProperty("--og-busy-duration", duration);
    els.send.style.setProperty("--og-busy-duration", duration);
  }

  refresh(): void {
    const { copy, limits, meter } = this.deps;
    const { body, summary, left, compare, send, input } = this.els;
    const remaining = comparesLeft(this.session, limits);
    renderPanel(body, copy, this.turn, meter);
    renderMeter(this.els.meter, this.total, copy, this.deps.pricing);
    summary.textContent = drawerSummary(copy, this.turn, meter);
    left.textContent = comparesLeftText(copy, remaining, limits.maxCompares);
    compare.disabled = this.busy || this.turn === null || remaining === 0;
    send.disabled = this.busy;
    if (this.busy) {
      send.setAttribute("aria-busy", "true");
    } else {
      send.removeAttribute("aria-busy");
    }
    input.readOnly = this.busy;
    input.disabled = this.session.messages >= limits.maxMessages;
  }

  async submit(): Promise<void> {
    const message = this.els.input.value;
    if (this.busy || !canSend(this.session, this.deps.limits, message)) {
      return;
    }
    this.els.input.value = "";
    this.session.messages += 1;
    addMessage(this.els.log, "user", message);
    await this.runSubmit(message);
  }

  private async runSubmit(message: string): Promise<void> {
    this.busy = true;
    this.lastMessage = message;
    showTyping(this.els.log, text(this.deps.copy, "ui.typing"));
    this.refresh();
    const outcome = await this.ask(message, "gist");
    this.conclude(() => {
      this.finishSubmit(outcome, message);
    });
    if (!this.els.input.disabled) {
      this.els.input.focus();
    }
  }

  async compare(): Promise<void> {
    const turn = this.turn;
    if (this.busy || turn === null || comparesLeft(this.session, this.deps.limits) === 0) {
      return;
    }
    this.busy = true;
    this.session.compares += 1;
    showTyping(this.els.log, text(this.deps.copy, "ui.typing"));
    this.els.compare.textContent = text(this.deps.copy, "ui.compare_running");
    this.refresh();
    const outcome = await this.ask(this.lastMessage, "full");
    this.conclude(() => {
      this.finishCompare(turn, outcome);
    });
  }

  warm(): void {
    if (ticketIfUsable(this.session.ticket, Date.now(), this.deps.limits.ticketMarginMs) === null) {
      this.deps.check.warm();
    }
  }

  private async ask(message: string, mode: Mode): Promise<ChatOutcome> {
    const { ticketMarginMs } = this.deps.limits;
    const ticket = ticketIfUsable(this.session.ticket, Date.now(), ticketMarginMs);
    this.session.ticket = ticket;
    if (ticket !== null) {
      const outcome = await this.send(message, mode, { ticket });
      if (!isRefusal(outcome)) {
        return outcome;
      }
      this.session.ticket = null;
    }
    return this.askWithToken(message, mode);
  }

  private async askWithToken(message: string, mode: Mode): Promise<ChatOutcome> {
    let turnstileToken: string;
    try {
      turnstileToken = await this.deps.check.token();
    } catch {
      return { kind: "failed", status: NO_RESPONSE, reason: "check" };
    }
    return this.send(message, mode, { turnstileToken });
  }

  private async send(message: string, mode: Mode, credential: Credential): Promise<ChatOutcome> {
    let outcome: ChatOutcome;
    try {
      outcome = await this.deps.gateway.chat({
        sessionId: this.session.id,
        message,
        ...credential,
        mode,
        timeoutMs: this.deps.limits.chatRequestMs,
      });
    } catch {
      return { kind: "failed", status: NO_RESPONSE, reason: "unexpected" };
    }
    if (outcome.kind === "failed") {
      return outcome;
    }
    const { ticket, ...rest } = outcome;
    this.session.ticket = ticket ?? this.session.ticket;
    return rest;
  }

  private conclude(finish: () => void): void {
    hideTyping(this.els.log);
    try {
      finish();
    } catch {
      addError(this.els.log, text(this.deps.copy, "ui.error"), "unexpected");
    } finally {
      this.busy = false;
      this.refresh();
      this.warm();
    }
  }

  private accept(reply: Reply): void {
    this.turn = { trace: reply.trace };
    this.lastAnswer = reply.answer;
    this.total = accumulate(this.total, reply.trace, "gist", this.deps.meter);
    this.els.out.hidden = true;
    addMessage(this.els.log, "bot", reply.answer);
  }

  private retry(message: string, button: HTMLButtonElement): void {
    if (this.busy) {
      return;
    }
    button.remove();
    this.busy = true;
    try {
      this.deps.check.reset();
    } catch {
      this.conclude(() => {
        this.finishSubmit({ kind: "failed", status: NO_RESPONSE, reason: "check" }, message);
      });
      return;
    }
    this.session.ticket = null;
    void this.runSubmit(message);
  }

  private finishSubmit(outcome: ChatOutcome, message: string): void {
    if (outcome.kind === "reply") {
      this.accept(outcome);
    } else if (outcome.kind === "replay") {
      addReplay(this.els.log, this.deps.copy, outcome.reason, outcome.turns);
    } else if (outcome.reason === "check") {
      addCheckError(this.els.log, this.deps.copy, (button) => {
        this.retry(message, button);
      });
    } else {
      addError(this.els.log, text(this.deps.copy, "ui.error"), outcome.reason);
    }
  }

  private finishCompare(turn: TurnView, outcome: ChatOutcome): void {
    const { copy } = this.deps;
    this.els.compare.textContent = text(copy, "hood.compare.title");
    if (outcome.kind === "reply") {
      const gist = { answer: this.lastAnswer, trace: turn.trace };
      renderCompare(this.els.out, copy, gist, outcome);
    } else {
      addError(this.els.log, text(copy, "ui.error"), outcome.kind === "failed" ? outcome.reason : "unexpected");
    }
  }
}

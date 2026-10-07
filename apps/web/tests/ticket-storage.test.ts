import { afterEach, describe, expect, it, vi } from "vitest";
import { FRESH, answer, countingCheck, stepping } from "./ticket-support.ts";
import { mount, say } from "./support.ts";

const SECRET_PART = FRESH.split(".")[2] ?? "";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("where the chat ticket lives", () => {
  it("starts every page with no ticket, so a new session sends its token", async () => {
    const gateway = stepping([answer("one", FRESH)]);
    mount({ gateway, check: countingCheck() });
    await say("one");
    await say("two");
    expect(gateway.requests[1]?.ticket).toBe(FRESH);
    const fresh = stepping([answer("again")]);
    const check = countingCheck();
    mount({ gateway: fresh, check, newSessionId: () => "session-other-01" });
    await say("hi");
    expect(fresh.requests[0]?.ticket).toBeUndefined();
    expect(fresh.requests[0]?.turnstileToken).toBe("token-1");
    expect(check.calls()).toBe(1);
  });

  it("never writes the ticket to localStorage, sessionStorage, a cookie, the address or the page", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const cookie = vi.spyOn(document, "cookie", "set");
    const gateway = stepping([answer("one", FRESH)]);
    mount({ gateway, check: countingCheck() });
    await say("one");
    await say("two");
    expect(gateway.requests[1]?.ticket).toBe(FRESH);
    expect(setItem).not.toHaveBeenCalled();
    expect(cookie).not.toHaveBeenCalled();
    expect(JSON.stringify(Object.entries(localStorage))).not.toContain(SECRET_PART);
    expect(JSON.stringify(Object.entries(sessionStorage))).not.toContain(SECRET_PART);
    expect(document.cookie).not.toContain(SECRET_PART);
    expect(location.href).not.toContain(SECRET_PART);
    expect(document.documentElement.outerHTML).not.toContain(SECRET_PART);
  });

  it("keeps the ticket out of window.name and the history state", async () => {
    mount({ gateway: stepping([answer("one", FRESH)]), check: countingCheck() });
    await say("one");
    await say("two");
    expect(window.name).not.toContain(SECRET_PART);
    expect(JSON.stringify(history.state)).not.toContain(SECRET_PART);
  });

  it("keeps the ticket out of the console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((name) =>
      vi.spyOn(console, name).mockImplementation(() => undefined),
    );
    mount({ gateway: stepping([answer("one", FRESH)]), check: countingCheck() });
    await say("one");
    await say("two");
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET_PART);
    }
  });
});

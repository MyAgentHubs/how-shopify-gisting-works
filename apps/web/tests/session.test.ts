import { afterEach, describe, expect, it, vi } from "vitest";
import gatewayLimits from "../../gateway/limits.json";
import { newSessionId } from "../src/session.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("newSessionId", () => {
  it("fits the id pattern the gateway accepts", () => {
    expect(newSessionId()).toMatch(new RegExp(gatewayLimits.sessionIdPattern));
  });

  it("differs from one call to the next", () => {
    expect(newSessionId()).not.toBe(newSessionId());
  });

  it("works on a page that is not a secure context, where crypto.randomUUID does not exist", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (array: Uint8Array) => array.fill(171),
    });
    expect(newSessionId()).toMatch(new RegExp(gatewayLimits.sessionIdPattern));
  });
});

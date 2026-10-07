import { describe, expect, it } from "vitest";
import runtimeData from "../../web/data/runtime.json";
import policyData from "../turnstile.json";

describe("the page and the gateway agree on Turnstile", () => {
  it("the action the page asks for is the action the gateway expects", () => {
    expect(runtimeData.turnstile.action).toBe(policyData.action);
  });
});

import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { envWithout, MemoryCounter, completeEnv } from "./support";
import { extraHostnames, turnstilePolicy } from "../src/turnstile-policy";
import policyData from "../turnstile.json";

describe("turnstilePolicy", () => {
  it("accepts only the production hostname when no extra hostnames are set", () => {
    expect([...turnstilePolicy([]).hostnames]).toEqual(["www.myagenthubs.com"]);
    expect(turnstilePolicy([]).action).toBe("gisting-chat");
  });

  it("adds the extra hostnames to the production one", () => {
    const policy = turnstilePolicy(["preview.example.test"]);
    expect([...policy.hostnames].sort()).toEqual(["preview.example.test", "www.myagenthubs.com"]);
  });
});

describe("the production hostnames", () => {
  it("are bare lowercase hostnames that the extra-hostname rules would keep as they are", () => {
    expect(extraHostnames(policyData.hostnames.join(","))).toEqual(policyData.hostnames);
  });
});

describe("extraHostnames", () => {
  it.each([undefined, "", "   ", " , ,"])("is empty for %j", (raw) => {
    expect(extraHostnames(raw)).toEqual([]);
  });

  it("splits on commas, trims and lowercases", () => {
    expect(extraHostnames(" Preview.Example.test ,b.example.test,")).toEqual([
      "preview.example.test",
      "b.example.test",
    ]);
  });

  it("accepts a label of 63 characters and labels with inner hyphens", () => {
    const long = `${"a".repeat(63)}.test`;
    expect(extraHostnames(`${long},a-b.c-d.test,localhost`)).toEqual([long, "a-b.c-d.test", "localhost"]);
  });

  it.each([7, 0, true, false, null, ["a.example.test"], { host: "a.example.test" }])(
    "refuses a value that is not text: %j",
    (raw) => {
      expect(extraHostnames(raw)).toBeNull();
    },
  );

  it.each([
    "*.example.test",
    "https://preview.example.test",
    "preview.example.test/path",
    "preview.example.test:8788",
    "preview example.test",
    "-bad.example.test",
    "good.example.test,*",
    "a..b",
    "a.-b",
    "a-.b",
    "a.b.",
    ".a.b",
    "\u212Aevil.test",
    "caf\u00e9.test",
    `${"a".repeat(64)}.test`,
  ])("refuses %j instead of guessing", (raw) => {
    expect(extraHostnames(raw)).toBeNull();
  });
});

describe("loadConfig with extra Turnstile hostnames", () => {
  it("has the production hostname alone when the variable is not set", () => {
    const config = loadConfig(completeEnv(new MemoryCounter()));
    expect(config.ok && [...config.value.turnstilePolicy.hostnames]).toEqual([
      "www.myagenthubs.com",
    ]);
  });

  it("reads the extra hostnames from the environment", () => {
    const env = { ...completeEnv(new MemoryCounter()), GISTING_TURNSTILE_EXTRA_HOSTNAMES: "a.example.test" };
    const config = loadConfig(env);
    expect(config.ok && config.value.turnstilePolicy.hostnames.has("a.example.test")).toBe(true);
  });

  it("fails closed and names the variable when it holds something that is not a hostname", () => {
    const env = { ...completeEnv(new MemoryCounter()), GISTING_TURNSTILE_EXTRA_HOSTNAMES: "*" };
    expect(loadConfig(env)).toEqual({
      ok: false,
      error: { kind: "ConfigMissing", missing: ["GISTING_TURNSTILE_EXTRA_HOSTNAMES"] },
    });
  });

  it.each([7, true, ["a.example.test"], { host: "a.example.test" }])(
    "answers ConfigMissing, not an exception, for a non-text variable: %j",
    (value) => {
      const env = { ...completeEnv(new MemoryCounter()), GISTING_TURNSTILE_EXTRA_HOSTNAMES: value };
      expect(loadConfig(env)).toEqual({
        ok: false,
        error: { kind: "ConfigMissing", missing: ["GISTING_TURNSTILE_EXTRA_HOSTNAMES"] },
      });
    },
  );

  it("keeps the other required names failing as before", () => {
    const config = loadConfig(envWithout("GISTING_IP_SALT", new MemoryCounter()));
    expect(config).toMatchObject({ ok: false, error: { missing: ["GISTING_IP_SALT"] } });
  });
});

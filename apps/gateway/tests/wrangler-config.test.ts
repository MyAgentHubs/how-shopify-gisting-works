import { describe, expect, it } from "vitest";
import worker from "../counter-worker/wrangler.json";
import pages from "../wrangler.pages.sample.json";

const [binding, ...others] = pages.durable_objects.bindings;
const SECRET_NAMES = /account_id|api_token|secret|zone_id|salt|token|password|key/i;

describe("the Wrangler sample files", () => {
  it("declare the counter class with the SQLite backend, which the free plan requires", () => {
    expect(worker.exports).toEqual({
      CounterObject: { type: "durable-object", storage: "sqlite" },
    });
  });

  it("bind that class into Pages once, under the name the gateway reads, from the named Worker", () => {
    expect(others).toEqual([]);
    expect(binding?.name).toBe("GISTING_COUNTER");
    expect(binding?.class_name).toBe("CounterObject");
    expect(binding?.script_name).toBe(worker.name);
  });

  it("keep the counter Worker off the public internet", () => {
    expect(worker.workers_dev).toBe(false);
    expect(worker.preview_urls).toBe(false);
  });

  it("carry no account id, token or secret", () => {
    for (const file of [worker, pages]) {
      expect(JSON.stringify(file)).not.toMatch(SECRET_NAMES);
    }
  });

  it.each(["GISTING_IP_SALT", "api_key", "auth_token", "db_password", "client_secret", "ACCOUNT_ID"])(
    "recognise %s as a secret-like field name",
    (name) => {
      expect(name).toMatch(SECRET_NAMES);
    },
  );

  it.each(["GISTING_COUNTER", "CounterObject", "gisting-counter", "script_name", "class_name"])(
    "do not mistake the binding name %s for a secret",
    (name) => {
      expect(name).not.toMatch(SECRET_NAMES);
    },
  );
});

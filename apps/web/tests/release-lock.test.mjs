import { spawnSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";
import { afterEach, describe, expect, it } from "vitest";
import { releaseFindings } from "../scripts/release-lock.mjs";
import {
  REAL_WEB,
  TODAY,
  cleanUpScratch,
  clearedWeb,
  editJson,
  readJson,
  reasons,
} from "./lock-helpers.mjs";

const CLI = join(REAL_WEB, "scripts", "release-check.mjs");

afterEach(cleanUpScratch);

describe("releaseFindings", () => {
  it("finds nothing when every placeholder is cleared and the price is fresh", () => {
    expect(releaseFindings({ webDir: clearedWeb(), today: TODAY })).toEqual([]);
  });

  it("names each order whose example email is still the placeholder", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/example_orders.json", (document) => {
      document.examples[0].email = "xxxxxxxxxx@orders.example.com";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/example_orders.json: the email of #1006 is still the placeholder",
    ]);
  });

  it.each([
    ["xxxxxxxxxx@orders.example.com", "is still the placeholder"],
    ["customer@example.com", "is not a demo email address"],
  ])("blocks a public order with email %s", (email, reason) => {
    const webDir = clearedWeb();
    editJson(webDir, "data/public_orders.json", (document) => {
      document.orders[0].order = "#public-order";
      document.orders[0].email = email;
    });
    expect(releaseFindings({ webDir, today: TODAY })).toEqual([
      { file: "data/public_orders.json", reason: `the email of #public-order ${reason}` },
    ]);
  });

  it.each(["{", "{}", '{"orders":{}}', "null"])("fails closed for malformed public orders %s", (content) => {
    const webDir = clearedWeb();
    writeFileSync(join(webDir, "data/public_orders.json"), content);
    expect(releaseFindings({ webDir, today: TODAY })).toEqual([
      { file: "data/public_orders.json", reason: "cannot be read as JSON" },
    ]);
  });

  it("lists example email findings before public email findings", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/example_orders.json", (document) => {
      document.examples[0].email = "xxxxxxxxxx@orders.example.com";
    });
    editJson(webDir, "data/public_orders.json", (document) => {
      document.orders[0].order = "#public-order";
      document.orders[0].email = "xxxxxxxxxx@orders.example.com";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/example_orders.json: the email of #1006 is still the placeholder",
      "data/public_orders.json: the email of #public-order is still the placeholder",
    ]);
  });

  it("flags a Cloudflare test sitekey and a missing sitekey", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/runtime.json", (document) => {
      document.turnstile.sitekey = "1x00000000000000000000AA";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/runtime.json: the sitekey is a Cloudflare test key",
    ]);
    editJson(webDir, "data/runtime.json", (document) => {
      delete document.turnstile.sitekey;
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/runtime.json: there is no sitekey",
    ]);
  });

  it("flags a research link that is still a placeholder", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/links.json", (document) => {
      document.research_article = "#pending-research-article";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/links.json: research_article is still a placeholder link",
    ]);
  });

  it("flags prices accessed more than the allowed days ago, and unreadable dates", () => {
    const webDir = clearedWeb();
    const limit = readJson(webDir, "data/release_lock.json").price_max_age_days;
    const onTheLimit = new Date(TODAY.getTime() - limit * 86_400_000).toISOString().slice(0, 10);
    const pastTheLimit = new Date(TODAY.getTime() - (limit + 1) * 86_400_000)
      .toISOString()
      .slice(0, 10);
    editJson(webDir, "data/pricing.json", (document) => {
      document.accessed = onTheLimit;
    });
    expect(releaseFindings({ webDir, today: TODAY })).toEqual([]);
    editJson(webDir, "data/pricing.json", (document) => {
      document.accessed = pastTheLimit;
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      `data/pricing.json: accessed ${pastTheLimit} is ${limit + 1} days old, the limit is ${limit}`,
    ]);
    editJson(webDir, "data/pricing.json", (document) => {
      document.accessed = "last week";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/pricing.json: accessed is not a YYYY-MM-DD date",
    ]);
  });

  it("flags a copy file that is not approved and a copy string that is still a placeholder", () => {
    const webDir = clearedWeb();
    editJson(webDir, "copy/zh-CN.json", (document) => {
      document.status = "awaiting_user_confirmation";
    });
    editJson(webDir, "copy/en.json", (document) => {
      document.strings["hero.title"] = "[PLACEHOLDER: Haiku cache note]";
    });
    expect(reasons(releaseFindings({ webDir, today: TODAY })).sort()).toEqual([
      "copy/en.json: hero.title is still a placeholder",
      "copy/zh-CN.json: status is awaiting_user_confirmation, not approved",
    ]);
  });

  it("fails closed when a checked file cannot be read", () => {
    const webDir = clearedWeb();
    rmSync(join(webDir, "data", "runtime.json"));
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual([
      "data/runtime.json: cannot be read as JSON",
    ]);
  });

  it("refuses a lock file whose pattern does not compile", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/release_lock.json", (document) => {
      document.test_sitekey = "([";
    });
    expect(() => releaseFindings({ webDir, today: TODAY })).toThrow(/test_sitekey/);
  });

  it("refuses a lock file that lacks a shape pattern, since an empty pattern would accept everything", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/release_lock.json", (document) => {
      delete document.email_shape;
    });
    expect(() => releaseFindings({ webDir, today: TODAY })).toThrow(/email_shape/);
  });
});

describe("the release-check command", () => {
  const run = (webDir) => spawnSync(process.execPath, [CLI, webDir], { encoding: "utf8" });

  it("exits 0 and stays silent when everything is cleared", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/pricing.json", (document) => {
      document.accessed = new Date().toISOString().slice(0, 10);
    });
    const result = run(webDir);
    expect([result.status, result.stdout, result.stderr]).toEqual([0, "", ""]);
  });

  it("exits 1 and lists every blocker on its own line", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/runtime.json", (document) => {
      document.turnstile.sitekey = "2x00000000000000000000AB";
    });
    editJson(webDir, "data/links.json", (document) => {
      document.research_article = "#pending-research-article";
    });
    editJson(webDir, "data/pricing.json", (document) => {
      document.accessed = new Date().toISOString().slice(0, 10);
    });
    const result = run(webDir);
    expect(result.status).toBe(1);
    expect(result.stderr.trim().split("\n")).toEqual([
      "release blocked: 2 things must change before launch",
      "- data/runtime.json: the sitekey is a Cloudflare test key",
      "- data/links.json: research_article is still a placeholder link",
    ]);
  });
});

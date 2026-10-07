import { afterEach, describe, expect, it } from "vitest";
import { releaseFindings } from "../scripts/release-lock.mjs";
import {
  REAL_EMAIL,
  REAL_LINK,
  REAL_SITEKEY,
  TODAY,
  cleanUpScratch,
  clearedWeb,
  editJson,
  readJson,
  reasons,
} from "./lock-helpers.mjs";

afterEach(cleanUpScratch);

const findingsAfter = (file, change) => {
  const webDir = clearedWeb();
  editJson(webDir, file, change);
  return reasons(releaseFindings({ webDir, today: TODAY }));
};

const BAD_EMAILS = [
  "xxxxxxxxxx@orders.example.com",
  "XXXXXXXXXX@orders.example.com",
  "xxxxxxxxxx@Orders.Example.com",
  " xxxxxxxxxx@orders.example.com",
  "xxxxxxxxxx@orders.example.com ",
  "xxxxxxxxxx@orders.example.com\n",
  "xxxxxxxxxxx@orders.example.com",
  "xxxxxxxxx@orders.example.com",
  "xxxxxxxxxx@orders.example.com.",
  "xxxxxxxxxx@orders.example.co",
  "yyyyyyyyyy@orders.example.com",
  "ABCDEFGHIJ@orders.example.com",
  "x@x.x",
  "",
  "replace-me@example.com",
  12345,
  null,
];

describe("example emails", () => {
  it("lets a demo-shaped email through", () => {
    expect(findingsAfter("data/example_orders.json", (d) => (d.examples[0].email = REAL_EMAIL))).toEqual([]);
  });

  it.each(BAD_EMAILS)("blocks %j", (email) => {
    const found = findingsAfter("data/example_orders.json", (d) => (d.examples[0].email = email));
    expect(found).toHaveLength(1);
    expect(found[0]).toMatch(/the email of #1006 is (still the placeholder|not a demo email address)/);
  });

  it("blocks an order row that has no email", () => {
    const found = findingsAfter("data/example_orders.json", (d) => delete d.examples[0].email);
    expect(found).toEqual(["data/example_orders.json: the email of #1006 is not a demo email address"]);
  });

  it("checks every order row on its own", () => {
    const found = findingsAfter("data/example_orders.json", (d) => {
      d.examples[0].email = "xxxxxxxxxx@orders.example.com";
      d.examples[1].email = "nope";
    });
    expect(found).toEqual([
      "data/example_orders.json: the email of #1006 is still the placeholder",
      "data/example_orders.json: the email of #1022 is not a demo email address",
    ]);
  });

  it("blocks a file with the examples list renamed", () => {
    const found = findingsAfter("data/example_orders.json", (d) => {
      d.example = d.examples;
      delete d.examples;
    });
    expect(found).toEqual(["data/example_orders.json: cannot be read as JSON"]);
  });
});

const BAD_SITEKEYS = [
  "1x00000000000000000000AA",
  "2x00000000000000000000AB",
  "1x00000000000000000000BB",
  "2x00000000000000000000BB",
  "3x00000000000000000000FF",
  "1X00000000000000000000AA",
  " 1x00000000000000000000AA",
  "1x00000000000000000000AA ",
  "1x00000000000000000000AA\n",
  "1x0000000000000000000AA",
  "1x000000000000000000000AA",
  "4x00000000000000000000AA",
  "1x00000000000000000000A-",
  "",
  "changeme",
  "0x4AAAAAAA",
  " 0x4AAAAAAAabcdefghijklmn",
  "0x4AAAAAAAabcdefghijklmn\n",
  "0X4AAAAAAAabcdefghijklmn",
  12345,
];

describe("the Turnstile site key", () => {
  it("lets a production-shaped key through", () => {
    expect(findingsAfter("data/runtime.json", (d) => (d.turnstile.sitekey = REAL_SITEKEY))).toEqual([]);
  });

  it.each(BAD_SITEKEYS)("blocks %j", (sitekey) => {
    expect(findingsAfter("data/runtime.json", (d) => (d.turnstile.sitekey = sitekey))).toHaveLength(1);
  });

  it("blocks a runtime file without a turnstile block", () => {
    expect(findingsAfter("data/runtime.json", (d) => delete d.turnstile)).toEqual([
      "data/runtime.json: there is no sitekey",
    ]);
  });
});

const BAD_LINKS = [
  "#pending-research-article",
  " #pending-x",
  "#PENDING-x",
  "#pending",
  "#",
  "TBD",
  "todo",
  "javascript:alert(1)",
  "http://example.com/x",
  "https://example.com/TODO",
  "https://www.myagenthubs.com/TBD",
  "https://www.example.com/research",
  "https://a.b.example.org/x",
  "https://user@example.com/x",
  "https://example.com:8080/x",
  "https://www.myagenthubs.com/todo-list",
  "[PLACEHOLDER]",
  "/research/gisting",
  " https://www.myagenthubs.com/research/gisting",
  "https://www.myagenthubs.com/a b",
  null,
  42,
];

const GOOD_LINKS = [
  "https://mastodon.social/@gisting",
  "https://www.myagenthubs.com/research/gisting",
  "https://myexample.com/x",
  "https://www.myagenthubs.com/autodoc",
];

describe("links", () => {
  it("lets an https link through", () => {
    expect(findingsAfter("data/links.json", (d) => (d.research_article = REAL_LINK))).toEqual([]);
  });

  it.each(GOOD_LINKS)("lets %j through, since its host or path only contains a marker as part of a word", (link) => {
    expect(findingsAfter("data/links.json", (d) => (d.research_article = link))).toEqual([]);
  });

  it.each(BAD_LINKS)("blocks %j", (link) => {
    expect(findingsAfter("data/links.json", (d) => (d.research_article = link))).toEqual([
      "data/links.json: research_article is still a placeholder link",
    ]);
  });

  it("blocks a placeholder under a link name nobody asked for", () => {
    expect(findingsAfter("data/links.json", (d) => (d.other = "#pending-x"))).toEqual([
      "data/links.json: other is still a placeholder link",
    ]);
  });

  it("hides rather than blocks an empty link, and a lock that requires nothing lets a missing one through", () => {
    expect(findingsAfter("data/links.json", (d) => (d.research_article = ""))).toEqual([]);
    expect(findingsAfter("data/links.json", (d) => delete d.research_article)).toEqual([]);
  });

  it("blocks a links file that lacks a link the lock requires", () => {
    const webDir = clearedWeb();
    editJson(webDir, "data/release_lock.json", (d) => (d.required_links = ["research_article"]));
    editJson(webDir, "data/links.json", (d) => delete d.research_article);
    expect(reasons(releaseFindings({ webDir, today: TODAY }))).toEqual(["data/links.json: research_article is missing"]);
  });
});

const BAD_COPY = [
  "[PLACEHOLDER] x",
  "[PLACEHOLDER",
  "[PLACEHOLDER for unapproved copy]",
  " [PLACEHOLDER] x",
  "\n[PLACEHOLDER] x",
  "［PLACEHOLDER］ x",
  "[placeholder] x",
  "[Placeholder] x",
  "[ PLACEHOLDER ] x",
  "[\nPLACEHOLDER] x",
  "​[PLACEHOLDER] x",
  "[​PLACEHOLDER] x",
  "[PLACE​HOLDER] x",
  "﻿[PLACEHOLDER] x",
  "Good text. [PLACEHOLDER] more",
  "【PLACEHOLDER】x",
  "【 placeholder 】x",
];

describe("copy strings", () => {
  it.each(BAD_COPY)("blocks %j in both languages", (text) => {
    for (const language of ["en", "zh-CN"]) {
      const found = findingsAfter(`copy/${language}.json`, (d) => (d.strings["hero.title"] = text));
      expect(found).toEqual([`copy/${language}.json: hero.title is still a placeholder`]);
    }
  });

  it("lets the plain word through when it is not a marker", () => {
    expect(findingsAfter("copy/en.json", (d) => (d.strings["hero.title"] = "Type into the placeholder box"))).toEqual([]);
  });

  it.each([["array", ["[PLACEHOLDER]"]], ["number", 5], ["null", null], ["object", { a: 1 }]])(
    "blocks a %s in place of a string",
    (_name, value) => {
      expect(findingsAfter("copy/en.json", (d) => (d.strings["hero.title"] = value))).toEqual([
        "copy/en.json: hero.title is not a string",
      ]);
    },
  );

  it("blocks a copy file without strings", () => {
    expect(findingsAfter("copy/en.json", (d) => delete d.strings)).toEqual(["copy/en.json: has no strings"]);
  });
});

describe("the price date", () => {
  it("blocks a date that is still to come", () => {
    expect(findingsAfter("data/pricing.json", (d) => (d.accessed = "2026-10-07"))).toEqual([
      "data/pricing.json: accessed 2026-10-07 is in the future",
    ]);
  });

  it("lets today through", () => {
    expect(findingsAfter("data/pricing.json", (d) => (d.accessed = "2026-10-06"))).toEqual([]);
  });

  it.each(["2026-02-31", "2026-8-22", "20261005", "2026-10-05T00:00:00Z", "", 20261005])("blocks %j", (accessed) => {
    expect(findingsAfter("data/pricing.json", (d) => (d.accessed = accessed))).toEqual([
      "data/pricing.json: accessed is not a YYYY-MM-DD date",
    ]);
  });
});

describe("native review of the ja and ko notice", () => {
  it.each(["ja", "ko"])("holds the release while %s is pending, missing or not exactly spelled", (language) => {
    const file = `copy/${language}.json`;
    const blocked = (value) => `${file}: native_review is ${value}, not approved_draft or done`;
    const cases = [
      [(d) => (d.native_review = "pending"), blocked("pending")],
      [(d) => (d.native_review = "Done"), blocked("Done")],
      [(d) => (d.native_review = "approved"), blocked("approved")],
      [(d) => delete d.native_review, blocked("missing")],
    ];
    for (const [change, expected] of cases) {
      expect(findingsAfter(file, change)).toEqual([expected]);
    }
  });

  it.each(["ja", "ko"])("lets %s ship as an approved draft or once reviewed", (language) => {
    const file = `copy/${language}.json`;
    expect(readJson(clearedWeb(), file).native_review).toBe("approved_draft");
    for (const state of ["approved_draft", "done"]) {
      expect(findingsAfter(file, (d) => (d.native_review = state))).toEqual([]);
    }
  });

  it("does not ask the English or Chinese copy for a native review", () => {
    expect(findingsAfter("copy/en.json", (d) => delete d.native_review)).toEqual([]);
  });
});

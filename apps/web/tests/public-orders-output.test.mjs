import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { verifyOutput } from "../scripts/verify-output.mjs";
import { buildPages, REAL_WEB } from "./page-helpers.mjs";

const pages = buildPages();
const orders = JSON.parse(readFileSync(join(REAL_WEB, "data", "public_orders.json"), "utf8")).orders;

function withAttribute(path, attribute) {
  const built = buildPages();
  const file = join(built.outDir, path, "index.html");
  const html = readFileSync(file, "utf8");
  writeFileSync(file, html.replace("</main>", `<button ${attribute}></button></main>`));
  return verifyOutput({ outDir: built.outDir });
}

function withPrefill(path, text) {
  return withAttribute(path, `data-prefill="${text}"`);
}

const emailLocations = [
  ["alt attribute", "extra.html", (email) => `<img alt="${email}">`],
  ["body text", "extra.html", (email) => `<body>${email}</body>`],
  ["template", "extra.html", (email) => `<template>${email}</template>`],
  ["script", "extra.html", (email) => `<script>const email = "${email}";</script>`],
  ["comment", "extra.html", (email) => `<!-- ${email} -->`],
  ["JavaScript", "extra.js", (email) => `const email = "${email}";`],
  ["JSON", "extra.json", (email) => JSON.stringify({ email })],
  ["CSS", "extra.css", (email) => `a::after { content: "${email}"; }`],
  ["text", "extra.txt", (email) => email],
  ["XML", "extra.xml", (email) => `<email>${email}</email>`],
  ["full-width text", "extra.html", (email) => Array.from(email, (char) => String.fromCodePoint(char.codePointAt(0) + 65248)).join("")],
  ["uppercase text", "extra.html", (email) => email.toUpperCase()],
];

function withEmail(file, render, email) {
  const built = buildPages();
  writeFileSync(join(built.outDir, file), render(email));
  return verifyOutput({ outDir: built.outDir });
}

describe("public order output whitelist", () => {
  it("contains exactly the eight requested orders in their specified order", () => {
    expect(orders.map((row) => row.order)).toEqual([
      "#1006", "#1097", "#1016", "#1021", "#1084", "#1012", "#1005", "#1022",
    ]);
    for (const row of orders) {
      expect(row.id).toBe(row.scenario.toLowerCase().replaceAll("_", "-"));
      expect(row.label_key).toBe(`try.example.${row.scenario.toLowerCase()}`);
    }
  });

  it("passes a normal build", () => {
    expect(verifyOutput({ outDir: pages.outDir })).toEqual([]);
  });

  it.each(emailLocations)("rejects a foreign email in %s", (_, file, render) => {
    expect(withEmail(file, render, "abcdefghij@orders.example.com")).toEqual([
      `${file}: email abcdefghij@orders.example.com is not in the public or example orders`,
    ]);
  });

  it.each(emailLocations)("allows a public email in %s", (_, file, render) => {
    expect(withEmail(file, render, orders[0].email)).toEqual([]);
  });

  it.each(["1098", "#１０９８", "# 1098"])("rejects an unlisted normalized prefill order %s", (text) => {
    expect(withPrefill("opengisting", text)).toEqual([
      "opengisting/index.html: data-prefill order #1098 is not in the public or example orders",
    ]);
  });

  it.each(["1006", "#１００６", "# 1006"])("allows a normalized public prefill order %s", (text) => {
    expect(withPrefill("opengisting", text)).toEqual([]);
  });

  it("ignores digit runs inside a whitelisted prefill email", () => {
    expect(withPrefill("opengisting", `#1012 ${orders.find((row) => row.order === "#1012").email}`)).toEqual([]);
  });

  it("allows each public order in a prefill", () => {
    expect(withPrefill("opengisting", orders.map((row) => row.order).join(" "))).toEqual([]);
  });

  it.each(["opengisting", "zh-CN/opengisting", "ja/opengisting", "ko/opengisting"])("rejects an unlisted order in %s", (path) => {
    expect(withPrefill(path, "Where is #9999?")).toEqual([
      `${path}/index.html: data-prefill order #9999 is not in the public or example orders`,
    ]);
  });

  it("rejects an unlisted order even after an allowed order in the same prefill", () => {
    expect(withPrefill("opengisting", "#1006 and #9999")).toEqual([
      "opengisting/index.html: data-prefill order #9999 is not in the public or example orders",
    ]);
  });

  it.each(['data-prefill="Where is &#x23;9999?"', 'DATA-PREFILL="#9999"', 'data-prefill=#9999', "data-prefill='&#35;&#57;&#57;&#57;&#57;'"])("checks the browser value of %s", (attribute) => {
    expect(withAttribute("opengisting", attribute)).toEqual([
      "opengisting/index.html: data-prefill order #9999 is not in the public or example orders",
    ]);
  });


  it("also checks an HTML file outside the language page list", () => {
    const built = buildPages();
    writeFileSync(join(built.outDir, "extra.html"), '<button data-prefill="#9999"></button>');
    expect(verifyOutput({ outDir: built.outDir })).toEqual([
      "extra.html: data-prefill order #9999 is not in the public or example orders",
    ]);
  });

  it("includes example orders that are outside the public list", () => {
    let fixtureWeb;
    const built = buildPages((webDir) => {
      fixtureWeb = webDir;
      const file = join(webDir, "data", "example_orders.json");
      const data = JSON.parse(readFileSync(file, "utf8"));
      data.examples[0].order = "#9998";
      writeFileSync(file, JSON.stringify(data));
    });
    expect(built.html("en")).toContain("#9998");
    expect(verifyOutput({ outDir: built.outDir, webDir: fixtureWeb })).toEqual([]);
  });

  it.each(emailLocations)("allows an example-only email in %s", (_, file, render) => {
    let fixtureWeb;
    const email = "klmnopqrst@orders.example.com";
    const built = buildPages((webDir) => {
      fixtureWeb = webDir;
      const dataFile = join(webDir, "data", "example_orders.json");
      const data = JSON.parse(readFileSync(dataFile, "utf8"));
      data.examples[0].email = email;
      writeFileSync(dataFile, JSON.stringify(data));
    });
    writeFileSync(join(built.outDir, file), render(email));
    expect(verifyOutput({ outDir: built.outDir, webDir: fixtureWeb })).toEqual([]);
  });

});

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REAL_WEB, buildPages, readCopy, textOf } from "./page-helpers.mjs";

const pages = buildPages();
const orders = JSON.parse(readFileSync(join(REAL_WEB, "data", "example_orders.json"), "utf8")).examples;
const DEMO_EMAIL = /^[a-z2-7]{10}@orders\.example\.com$/;
const PLACEHOLDER_EMAIL = /^([a-z2-7])\1{9}@/;

const section = (lang) => pages.doc(lang).querySelector("#agent");
const buttons = (lang) => [...section(lang).querySelectorAll(".og-exb .og-exbtn")];

function edited(change) {
  return buildPages((webDir) => {
    const path = join(webDir, "data", "example_orders.json");
    const data = JSON.parse(readFileSync(path, "utf8"));
    change(data.examples);
    writeFileSync(path, JSON.stringify(data));
  });
}

describe("the Try it section", () => {
  it("has the Try the agent title and only two notes: the LLM note and the English-only note", () => {
    for (const lang of ["en", "zh-CN"]) {
      const copy = readCopy(lang);
      const root = section(lang);
      expect(textOf(root.querySelector("h2")), lang).toBe(copy["hero.cta_try"]);
      const notes = [...root.querySelectorAll(".og-notes li")].map(textOf);
      expect(notes, lang).toEqual([copy["chat.note_llm"], copy["hero.language"]]);
      expect(textOf(root), lang).not.toContain(copy["chat.note_orders"]);
    }
  });

  it("offers the three examples in the data file's order, labelled from the copy", () => {
    for (const lang of ["en", "zh-CN"]) {
      const copy = readCopy(lang);
      expect(orders.map((order) => order.label_key)).toEqual([
        "try.example.in_transit",
        "try.example.unfulfilled",
        "try.example.human",
      ]);
      expect(buttons(lang).map((button) => textOf(button.querySelector("b"))), lang).toEqual(
        orders.map((order) => copy[order.label_key]),
      );
    }
    expect(buttons("en").map((button) => textOf(button.querySelector("b")))).toEqual([
      "In transit",
      "Not shipped yet",
      "Talk to a human",
    ]);
  });

  it("prefills the question with the order number and email, and the human request as written", () => {
    for (const lang of ["en", "zh-CN"]) {
      const prefills = buttons(lang).map((button) => button.getAttribute("data-prefill"));
      expect(prefills, lang).toEqual([
        `Where is my order #1006? My email is ${orders[0].email}.`,
        `Where is my order #1022? My email is ${orders[1].email}.`,
        "I'd like to talk to a human agent about my purchase.",
      ]);
    }
  });

  it("gives each button its own hint: track, reminder and hand-off", () => {
    for (const lang of ["en", "zh-CN"]) {
      const copy = readCopy(lang);
      const hints = buttons(lang).map((button) => textOf(button.querySelector("span")));
      expect(hints, lang).toEqual([
        copy["try.example.in_transit_hint"],
        copy["try.example.unfulfilled_hint"],
        copy["try.example.human_hint"],
      ]);
    }
    expect(textOf(buttons("en")[1].querySelector("span"))).toBe("Then say yes to the reminder");
    expect(textOf(buttons("zh-CN")[1].querySelector("span"))).toBe("然后答应发提醒");
  });

  it("still builds while the example email is a placeholder", () => {
    const changed = edited((examples) => {
      examples[0].email = "xxxxxxxxxx@orders.example.com";
    });
    expect(changed.doc("en").querySelector(".og-exbtn").getAttribute("data-prefill")).toContain(
      "xxxxxxxxxx@orders.example.com",
    );
  });

  it("holds a real-looking email in the committed data, not the placeholder", () => {
    for (const order of orders.filter((row) => "email" in row)) {
      expect(order.email).toMatch(DEMO_EMAIL);
      expect(order.email).not.toMatch(PLACEHOLDER_EMAIL);
    }
    expect(buttons("en")[0].getAttribute("data-prefill")).toContain(orders[0].email);
  });

  it("makes the buttons plain buttons that cannot submit anything", () => {
    for (const button of buttons("en")) {
      expect(button.tagName).toBe("BUTTON");
      expect(button.getAttribute("type")).toBe("button");
      expect(button.closest("form")).toBeNull();
    }
  });

  it("follows the data file: a new email or one more example shows up without touching the page", () => {
    const changed = edited((examples) => {
      examples[0].email = "someone@orders.example.com";
      examples.splice(2, 0, { ...examples[1], id: "extra", order: "#1099" });
    });
    const prefills = [...changed.doc("en").querySelectorAll(".og-exb .og-exbtn")].map((button) =>
      button.getAttribute("data-prefill"),
    );
    expect(prefills).toHaveLength(4);
    expect(prefills[0]).toBe("Where is my order #1006? My email is someone@orders.example.com.");
    expect(prefills[2]).toContain("#1099");
  });

  it("escapes what it writes into attributes", () => {
    const changed = edited((examples) => {
      examples[0].email = 'a"><b@orders.example.com';
    });
    const html = changed.html("en");
    expect(html).not.toContain('a"><b@');
    expect(changed.doc("en").querySelector(".og-exbtn").getAttribute("data-prefill")).toContain('a"><b@');
  });

  it("escapes the second example's email too, and the prefill still reads back whole", () => {
    const changed = edited((examples) => {
      examples[1].email = 'q"><i&@orders.example.com';
    });
    expect(changed.html("en")).not.toContain('q"><i&@');
    const second = changed.doc("en").querySelectorAll(".og-exb .og-exbtn")[1];
    expect(second.getAttribute("data-prefill")).toBe('Where is my order #1022? My email is q"><i&@orders.example.com.');
  });

  it("writes an email into the prefill as it is, even when it looks like a replacement pattern", () => {
    const changed = edited((examples) => {
      examples[0].email = "a$&$1b@orders.example.com";
    });
    expect(changed.doc("en").querySelector(".og-exbtn").getAttribute("data-prefill")).toBe(
      "Where is my order #1006? My email is a$&$1b@orders.example.com.",
    );
  });

  it("refuses a label key that only exists on every object", () => {
    expect(() =>
      edited((examples) => {
        examples[0].label_key = "constructor";
      }),
    ).toThrow(/constructor/);
  });

  it("refuses a label key the copy does not have, naming the key", () => {
    expect(() =>
      edited((examples) => {
        examples[0].label_key = "try.example.nowhere";
      }),
    ).toThrow(/try\.example\.nowhere/);
  });

  it("refuses an example with an order but no email, or the other way round", () => {
    expect(() => edited((examples) => delete examples[0].email)).toThrow(/order and email/);
    expect(() => edited((examples) => delete examples[0].order)).toThrow(/order and email/);
  });

  it("puts the chat window title, the mode chip, the log, the composer and the panel in the window", () => {
    for (const lang of ["en", "zh-CN"]) {
      const copy = readCopy(lang);
      const win = section(lang).querySelector(".og-win");
      expect(textOf(win.querySelector(".og-wbar b")), lang).toBe("Gisting Lab Store · Support");
      expect(textOf(win.querySelector(".og-wbar .og-mode"))).toBe(copy["ui.mode_gist"]);
      expect(win.querySelector('[data-role="log"]').getAttribute("role")).toBe("log");
      const input = win.querySelector('input[data-role="input"]');
      expect(input.getAttribute("placeholder")).toBe(copy["ui.placeholder"]);
      expect(textOf(win.querySelector(`label[for="${input.id}"]`))).toBe(copy["ui.message_label"]);
      expect(textOf(win.querySelector('[data-role="send"]'))).toBe(copy["ui.send"]);
      expect(win.querySelector('details[data-role="hood"]')).not.toBeNull();
    }
  });

  it("keeps the old workspace, its notes and the old benchmark titles off the page", () => {
    const html = pages.html("en");
    expect(html).not.toContain("labws");
    expect(html.match(/data-role="log"/g)).toHaveLength(1);
  });

  it("names no accuracy or red-line figures", () => {
    for (const lang of ["en", "zh-CN"]) {
      expect(textOf(section(lang)), lang).not.toMatch(/accuracy|red line|准确率|红线/i);
    }
  });
});

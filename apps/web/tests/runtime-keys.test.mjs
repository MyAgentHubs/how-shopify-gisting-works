import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(WEB, "src");
const keys = JSON.parse(readFileSync(join(WEB, "data", "runtime_keys.json"), "utf8")).copy;
const source = readdirSync(SRC)
  .filter((name) => name.endsWith(".ts"))
  .map((name) => readFileSync(join(SRC, name), "utf8"))
  .join("\n");
const TITLED = /^(hood\.[a-z_]+)\.(?:title|body)$/;

const unused = (list) =>
  list.filter((key) => !source.includes(`"${key}"`) && !source.includes(`"${key.replace(TITLED, "$1")}"`));

describe("the copy keys the page ships to the browser", () => {
  it("are all asked for by a browser script, so none is shipped for nothing", () => {
    expect(unused(keys)).toEqual([]);
  });

  it("catch a key no script asks for", () => {
    expect(unused(["ui.error", "hood.nowhere.title", "hood.nowhere"])).toEqual(["hood.nowhere.title", "hood.nowhere"]);
  });
});

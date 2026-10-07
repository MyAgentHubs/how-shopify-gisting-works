import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const REAL_WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const scratch = [];

afterEach(() => {
  for (const root of scratch.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

const PLACEHOLDER_EMAIL = "xxxxxxxxxx@orders.example.com";
const TEST_SITEKEY = "1x00000000000000000000AA";

function editJson(webDir, name, change) {
  const path = join(webDir, "data", name);
  const data = JSON.parse(readFileSync(path, "utf8"));
  change(data);
  writeFileSync(path, JSON.stringify(data));
}

function withPlaceholders(webDir) {
  editJson(webDir, "example_orders.json", (data) => {
    for (const row of data.examples) {
      if ("email" in row) {
        row.email = PLACEHOLDER_EMAIL;
      }
    }
  });
  editJson(webDir, "runtime.json", (data) => {
    data.turnstile.sitekey = TEST_SITEKEY;
  });
}

function runCli(args = [], change = () => {}) {
  const root = mkdtempSync(join(tmpdir(), "web-cli-"));
  scratch.push(root);
  mkdirSync(join(root, "apps"));
  cpSync(REAL_WEB, join(root, "apps", "web"), { recursive: true });
  change(join(root, "apps", "web"));
  const result = spawnSync(process.execPath, [join(root, "apps", "web", "scripts", "cli.mjs"), ...args], {
    encoding: "utf8",
  });
  return { result, dist: join(root, "dist") };
}

describe("the build command", () => {
  it("refuses a release build while the lock has findings, and writes nothing", () => {
    const { result, dist } = runCli(["--release"], withPlaceholders);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("release blocked");
    expect(result.stderr).toContain("data/example_orders.json: the email of #1006 is still the placeholder");
    expect(result.stderr).toContain("data/example_orders.json: the email of #1022 is still the placeholder");
    expect(result.stderr).toContain("data/runtime.json: the sitekey is a Cloudflare test key");
    expect(existsSync(dist)).toBe(false);
  });

  it("does not block on the committed example emails or the committed sitekey", () => {
    const { result } = runCli(["--release"]);
    expect(result.stderr).not.toContain("data/example_orders.json");
    expect(result.stderr).not.toContain("data/runtime.json");
  });

  it("refuses --preview together with --release, and writes nothing", () => {
    const { result, dist } = runCli(["--preview", "--release"]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--preview and --release cannot be combined");
    expect(existsSync(dist)).toBe(false);
  });

  it("still builds a draft page without any flag", () => {
    const { result, dist } = runCli();
    expect([result.status, result.stderr]).toEqual([0, ""]);
    expect(existsSync(join(dist, "web", "opengisting", "index.html"))).toBe(true);
  });
});

import { dirname, join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { blockedMessage, releaseFindings } from "./release-lock.mjs";
import { buildSite } from "./site.mjs";

const ENTRIES = {
  production: "js/apps/web/src/main.js",
  preview: "js/apps/web/preview/main.js",
};
const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..");
const outDir = join(webDir, "..", "..", "dist", "web");
const preview = process.argv.includes("--preview");
const release = process.argv.includes("--release");

function refuse(message) {
  process.stderr.write(message);
  process.exit(1);
}

if (preview && release) {
  refuse("--preview and --release cannot be combined\n");
}
if (release) {
  const findings = releaseFindings({ webDir, today: new Date() });
  if (findings.length > 0) {
    refuse(blockedMessage(findings));
  }
}

buildSite({ webDir, outDir, entry: preview ? ENTRIES.preview : ENTRIES.production, preview, release });

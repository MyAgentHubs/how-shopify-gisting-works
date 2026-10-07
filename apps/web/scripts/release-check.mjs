import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { blockedMessage, releaseFindings } from "./release-lock.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = process.argv[2] === undefined ? join(here, "..") : resolve(process.argv[2]);
const findings = releaseFindings({ webDir, today: new Date() });

if (findings.length > 0) {
  process.stderr.write(blockedMessage(findings));
  process.exitCode = 1;
}

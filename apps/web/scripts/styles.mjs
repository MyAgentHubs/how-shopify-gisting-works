import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const STYLES_DIR = "styles";
const FORBIDDEN = [/header\.mh-global/, /mh-language/, /\.mh-(?!footer-brand\b)/];

function checkSlice(file, css) {
  const hit = FORBIDDEN.find((pattern) => pattern.test(css));
  if (hit !== undefined) {
    throw new RangeError(`${file}: www header chrome belongs to www, found ${String(hit)}`);
  }
}

export function assembleStyles(webDir) {
  const files = readdirSync(join(webDir, STYLES_DIR))
    .filter((name) => name.endsWith(".css"))
    .sort();
  if (files.length === 0) {
    throw new RangeError(`${STYLES_DIR}: no style slices found`);
  }
  return files
    .map((file) => {
      const css = readFileSync(join(webDir, STYLES_DIR, file), "utf8");
      checkSlice(file, css);
      return css.endsWith("\n") ? css : `${css}\n`;
    })
    .join("");
}

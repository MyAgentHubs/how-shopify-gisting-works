import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { ogImagePath, pagePath, readProduct } from "./product.mjs";
import { emailProblems, prefillProblems, readAllowedEmails, readAllowedOrders } from "./public-orders-output.mjs";
import { countVisibleWords } from "./visible-words.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const WEB_DIR = join(here, "..");
const RULES = JSON.parse(readFileSync(join(here, "verify-rules.json"), "utf8"));
const TEXT_FILE = /\.(?:html|css|js|json|txt|xml)$/;

const attributeValues = (html, pattern) => [...html.matchAll(pattern)].map((match) => match[1]);

function headProblems({ product, language, html, ogDir, release }) {
  const at = `${language.code}`;
  const url = `${product.origin}${pagePath(product, language)}`;
  const problems = [];
  const expect = (ok, what) => {
    if (!ok) {
      problems.push(`${at}: ${what}`);
    }
  };
  expect(new RegExp(`<html lang="${language.htmlLang}"`).test(html), `html lang must be ${language.htmlLang}`);
  expect(attributeValues(html, /<link rel="canonical" href="([^"]*)"/g).join() === url, `canonical must be ${url}`);
  expect(/<title>[^<]+<\/title>/.test(html), "title is empty");
  expect(/<meta name="description" content="[^"]+"/.test(html), "meta description is empty");
  expect((html.match(/<h1\b/g) ?? []).length === 1, "the page needs exactly one h1");
  const hreflangs = attributeValues(html, /<link rel="alternate" hreflang="([^"]*)"/g);
  const wanted = language.indexed
    ? [...product.languages.filter((other) => other.indexed).map((other) => other.hreflang), "x-default"]
    : [];
  expect(hreflangs.join() === wanted.join(), `hreflang must be [${wanted.join(", ")}], found [${hreflangs.join(", ")}]`);
  expect(/<meta name="robots" content="noindex">/.test(html) === !language.indexed, language.indexed ? "an indexed page must not be noindex" : "a page that is not indexed needs noindex");
  const image = attributeValues(html, /<meta property="og:image" content="([^"]*)"/g)[0] ?? "";
  expect(image === `${product.origin}${ogImagePath(product, language)}`, "og:image does not match product.json");
  expect(existsSync(join(ogDir, basename(image))), `og:image file ${basename(image)} is not in the og directory`);
  const draft = new RegExp(`<meta name="${RULES.draft_marker}" content="draft">`).test(html);
  expect(draft === !release, release ? "a release build must not carry the draft marker" : "a non-release build must carry the draft marker");
  expect(!new RegExp(RULES.placeholder).test(html) || !release, "a release build must not carry placeholder copy");
  return problems;
}

function listFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? listFiles(join(entry.parentPath, entry.name)) : [join(entry.parentPath, entry.name)],
  );
}

function strayFileProblems(name, preview) {
  const problems = [];
  if (new RegExp(RULES.stray_copy_file).test(name)) {
    problems.push(`${name}: a copy file must not be published`);
  }
  if (!preview && new RegExp(RULES.preview_only_file).test(name)) {
    problems.push(`${name}: a preview-only script must not ship with a page that does not use it`);
  }
  return problems;
}

function scanProblems(outDir, preview, allowed) {
  const problems = [];
  for (const file of listFiles(outDir)) {
    const name = file.slice(outDir.length + 1);
    problems.push(...strayFileProblems(name, preview));
    if (!TEXT_FILE.test(file)) {
      continue;
    }
    let text = readFileSync(file, "utf8");
    problems.push(...emailProblems(text, allowed.emails, name));
    if (file.endsWith(".html")) {
      problems.push(...prefillProblems(text, allowed.orders, name));
    }
    for (const phrase of RULES.allowed_phrases) {
      text = text.replaceAll(phrase, "");
    }
    for (const rule of [...RULES.forbidden, ...RULES.private_names.map((name) => ({ name: `the private file name ${name}`, pattern: name }))]) {
      if (new RegExp(rule.pattern, rule.flags ?? "").test(text)) {
        problems.push(`${name}: mentions ${rule.name}`);
      }
    }
  }
  return problems;
}

function wordProblems(html) {
  const { total } = countVisibleWords(html, RULES.word_scope_ids);
  return total > RULES.max_visible_words ? [`en: ${total} visible words, the limit is ${RULES.max_visible_words}`] : [];
}

export function verifyOutput({ outDir, webDir = WEB_DIR, release = false }) {
  const product = readProduct(webDir);
  const ogDir = join(webDir, "og");
  const problems = [];
  let enHtml = null;
  for (const language of product.languages) {
    const file = join(outDir, pagePath(product, language), "index.html");
    if (!existsSync(file)) {
      problems.push(`${language.code}: ${file.slice(outDir.length + 1)} was not built`);
      continue;
    }
    const html = readFileSync(file, "utf8");
    enHtml = language.code === "en" ? html : enHtml;
    problems.push(...headProblems({ product, language, html, ogDir, release }));
  }
  const preview = enHtml !== null && new RegExp(RULES.preview_entry).test(enHtml);
  const allowed = { orders: readAllowedOrders(webDir), emails: readAllowedEmails(webDir) };
  problems.push(...scanProblems(outDir, preview, allowed), ...(enHtml === null ? ["en: the English page was not built"] : wordProblems(enHtml)));
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const outDir = resolve(process.argv.slice(2).find((arg) => !arg.startsWith("--")) ?? join(WEB_DIR, "..", "..", "dist", "web"));
  const problems = verifyOutput({ outDir, release: process.argv.includes("--release") });
  if (problems.length > 0) {
    process.stderr.write(`output check failed: ${problems.length} problem(s)\n${problems.map((line) => `- ${line}`).join("\n")}\n`);
    process.exitCode = 1;
  }
}

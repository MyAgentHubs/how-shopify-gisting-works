import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { assembleHtml, isApproved, noticeHtml } from "./assemble.mjs";
import { readPublicOrders } from "./public-orders.mjs";
import { readExamples } from "./examples.mjs";
import { assembleSections, renderFragment, requireRendered } from "./fragments.mjs";
import { readRules } from "./rules.mjs";
import { readCopyDocs, resolveCopy } from "./copy-resolve.mjs";
import { pageHead } from "./meta.mjs";
import { pagePath, readProduct } from "./product.mjs";
import {
  buildDataContext,
  pickNumbers,
  readBenchmarks,
  readLinks,
  readPricing,
  readRuntimeKeys,
  readTurnstile,
  runtimeBlock,
} from "./prerender.mjs";
import { DEFAULT_PROVIDERS } from "./providers.mjs";
import { assembleStyles } from "./styles.mjs";

const COPY_DIR = "copy";
const DATA_DIR = "data";
const SECTIONS_DIR = "sections";
const STYLE_FILE = "style.css";
const NOSCRIPT_FILE = "noscript.css";
const FOOTER_FILE = "footer.html";
const TYPE_ONLY_COPY_DIR = join("js", "apps", "web", "copy");
const PREVIEW_ONLY_DIRS = [join("js", "apps", "web", "preview"), join("js", "apps", "web", "fakes")];
const COMPILED_DIR = "js";
const PUBLIC_DATA = ["limits.json", "runtime.json"];

export function clearOutput(outDir, slug) {
  const shared = join(outDir, slug);
  if (!resolve(shared).startsWith(resolve(outDir) + sep)) {
    throw new RangeError(`slug ${slug} resolves outside the output folder ${outDir}`);
  }
  const stale = (dir, keep) =>
    existsSync(dir) ? readdirSync(dir).filter((name) => name !== keep).map((name) => join(dir, name)) : [];
  for (const path of [...stale(outDir, slug), ...stale(shared, COMPILED_DIR)]) {
    rmSync(path, { recursive: true, force: true });
  }
}

function readStatus(path) {
  const { status } = JSON.parse(readFileSync(path, "utf8"));
  if (typeof status !== "string") {
    throw new TypeError(`${path} has no top-level status string`);
  }
  return status;
}

function writeSharedAssets({ webDir, assetsDir, preview }) {
  mkdirSync(assetsDir, { recursive: true });
  const unwanted = preview ? [TYPE_ONLY_COPY_DIR] : [TYPE_ONLY_COPY_DIR, ...PREVIEW_ONLY_DIRS];
  for (const dir of unwanted) {
    rmSync(join(assetsDir, dir), { recursive: true, force: true });
  }
  mkdirSync(join(assetsDir, DATA_DIR), { recursive: true });
  for (const name of PUBLIC_DATA) {
    copyFileSync(join(webDir, DATA_DIR, name), join(assetsDir, DATA_DIR, name));
  }
  writeFileSync(join(assetsDir, STYLE_FILE), assembleStyles(webDir));
  cpSync(join(webDir, "assets"), assetsDir, { recursive: true });
  cpSync(join(webDir, NOSCRIPT_FILE), join(assetsDir, NOSCRIPT_FILE));
}

function renderSections(webDir, copy, data) {
  const dir = join(webDir, SECTIONS_DIR);
  return requireRendered("sections", existsSync(dir) ? assembleSections(dir, copy, data) : "");
}

function renderLanguage(shared, language) {
  const { webDir, template, product, docs, statuses, entry } = shared;
  const { runtimeKeys, numbers, providers, pricing, examples, publicOrders, turnstile, rules, links } = shared;
  const copy = resolveCopy(product, docs, language.code);
  const draft = !isApproved(statuses);
  const data = buildDataContext({ numbers, providers, lang: language.code, pricing, copy, examples, publicOrders, assetsBase: `/${product.slug}/`, rules, links });
  return assembleHtml(template, {
    statuses,
    entry,
    lang: language.htmlLang,
    head: pageHead({ product, language, copy, draft, release: shared.release }),
    notice: noticeHtml(language, copy),
    runtime: runtimeBlock({ keys: runtimeKeys, copy, numbers, pricing, turnstile }),
    sections: renderSections(webDir, copy, data),
    footer: requireRendered("footer", renderFragment({ file: FOOTER_FILE, source: shared.footer }, copy, data)),
    assets: `/${product.slug}/`,
    origin: product.origin,
    brand: product.brand,
  });
}

export function buildSite({ webDir, outDir, entry, providers = {}, release = false, preview = false }) {
  const statuses = readdirSync(join(webDir, COPY_DIR))
    .filter((name) => name.endsWith(".json"))
    .map((name) => readStatus(join(webDir, COPY_DIR, name)));
  const product = readProduct(webDir);
  const runtimeKeys = readRuntimeKeys(webDir);
  const shared = {
    webDir,
    runtimeKeys,
    numbers: pickNumbers(readBenchmarks(webDir), runtimeKeys.numbers),
    pricing: readPricing(webDir),
    turnstile: readTurnstile(webDir),
    examples: readExamples(webDir),
    publicOrders: readPublicOrders(webDir),
    rules: readRules(webDir),
    links: readLinks(webDir),
    providers: { ...DEFAULT_PROVIDERS, ...providers },
    release,
    template: readFileSync(join(webDir, "index.html"), "utf8"),
    footer: readFileSync(join(webDir, FOOTER_FILE), "utf8"),
    product,
    docs: readCopyDocs(webDir),
    statuses,
    entry,
  };
  clearOutput(outDir, product.slug);
  writeSharedAssets({ webDir, assetsDir: join(outDir, product.slug), preview });
  for (const language of product.languages) {
    const pageDir = join(outDir, pagePath(product, language));
    mkdirSync(pageDir, { recursive: true });
    writeFileSync(join(pageDir, "index.html"), renderLanguage(shared, language));
  }
  return { statuses };
}

import { DRAFT_MARKER } from "./assemble.mjs";
import { copyString } from "./copy-resolve.mjs";
import { escapeHtml } from "./fragments.mjs";
import { ogImagePath, pagePath } from "./product.mjs";

const ROBOTS_NOINDEX = "noindex";
const X_DEFAULT = "x-default";

function metaText(copy, key) {
  const value = copyString(copy, key);
  if (value === undefined) {
    throw new RangeError(`${copy.lang}: missing copy key ${key}`);
  }
  return escapeHtml(value);
}

const named = (name, content) => `<meta name="${name}" content="${content}">`;
const property = (name, content) => `<meta property="${name}" content="${content}">`;

function alternates(product) {
  const root = product.languages.find((language) => language.prefix === "");
  if (root === undefined) {
    throw new RangeError(`no language at the root path to serve as ${X_DEFAULT}`);
  }
  const links = product.languages
    .filter((language) => language.indexed)
    .map((language) => [language.hreflang, language]);
  return [...links, [X_DEFAULT, root]].map(
    ([hreflang, language]) =>
      `<link rel="alternate" hreflang="${escapeHtml(hreflang)}" href="${escapeHtml(product.origin + pagePath(product, language))}">`,
  );
}

export function pageHead({ product, language, copy, draft, release = false }) {
  const title = metaText(copy, "meta.title");
  const description = metaText(copy, "meta.description");
  const url = escapeHtml(`${product.origin}${pagePath(product, language)}`);
  return [
    `<title>${draft ? `[${DRAFT_MARKER}] ` : ""}${title}</title>`,
    named("description", description),
    `<link rel="canonical" href="${url}">`,
    ...(language.indexed ? alternates(product) : [named("robots", ROBOTS_NOINDEX)]),
    property("og:type", "website"),
    property("og:site_name", escapeHtml(product.name)),
    property("og:title", metaText(copy, "meta.og_title")),
    property("og:description", description),
    property("og:url", url),
    property("og:image", escapeHtml(`${product.origin}${ogImagePath(product, language)}`)),
    named("twitter:card", "summary_large_image"),
    ...(draft || !release ? [named("build-state", "draft")] : []),
  ].join("\n");
}

import { copyString } from "./copy-resolve.mjs";
import { escapeHtml } from "./fragments.mjs";

export const DRAFT_MARKER = "DRAFT";
const APPROVED = "approved";
const NOTICE_KEY = "page.notice";
const TOKEN = /%[A-Z_]+%/g;
const SHELL_DIRECTIVE = /\{\{\w+:[^{}]*\}\}/;

export function isApproved(statuses) {
  return statuses.length > 0 && statuses.every((status) => status === APPROVED);
}

function bannerFor(statuses) {
  const detail = escapeHtml([...new Set(statuses)].join(", "));
  return `<div class="draft-banner" role="status" data-draft="true">${DRAFT_MARKER} · ${detail}</div>`;
}

export function noticeHtml(language, copy) {
  const text = language.copyFallback === null ? undefined : copyString(copy, NOTICE_KEY);
  if (text === undefined) {
    return "";
  }
  return `<p class="page-notice" role="note" lang="${escapeHtml(language.htmlLang)}">${escapeHtml(text)}</p>`;
}

export function assembleHtml(template, page) {
  const draft = !isApproved(page.statuses);
  const values = {
    "%LANG%": escapeHtml(page.lang),
    "%HEAD%": page.head,
    "%ASSETS%": escapeHtml(page.assets),
    "%ENTRY%": escapeHtml(page.entry),
    "%ORIGIN%": escapeHtml(page.origin),
    "%BRAND%": escapeHtml(page.brand),
    "%NOTICE%": page.notice,
    "%RUNTIME%": page.runtime,
    "%SECTIONS%": page.sections,
    "%FOOTER%": page.footer,
    "%COPY_STATUS%": escapeHtml([...new Set(page.statuses)].join(",")),
    "%DRAFT_BANNER%": draft ? bannerFor(page.statuses) : "",
  };
  const directive = template.match(SHELL_DIRECTIVE);
  if (directive !== null) {
    throw new RangeError(`the page shell holds a copy directive ${directive[0]}`);
  }
  return template.replace(TOKEN, (token) => {
    if (!Object.hasOwn(values, token)) {
      throw new RangeError(`the page shell holds ${token}, which has no value`);
    }
    return values[token];
  });
}

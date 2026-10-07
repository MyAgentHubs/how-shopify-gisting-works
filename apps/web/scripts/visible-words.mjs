const WORD = /[A-Za-z0-9$≈→×÷.,’'-]+/g;
const CLOSED_DETAILS = /<details(?![^>]*\sopen)[^>]*>\s*(<summary[^>]*>.*?<\/summary>).*?<\/details>/gs;
const NOT_SHOWN = [/<pre\b.*?<\/pre>/gs, /<script\b.*?<\/script>/gs, /<style\b.*?<\/style>/gs, /<noscript\b.*?<\/noscript>/gs];
const NO_SCRIPT_NOTE = /<p class="og-nojs"[^>]*>.*?<\/p>/gs;
const TAG = /<[^>]+>/g;
const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

function sectionOf(html, id) {
  const pattern = new RegExp(`<section\\b[^>]*\\bid="${id}"[^>]*>.*?</section>`, "s");
  const found = pattern.exec(html);
  if (found === null) {
    throw new RangeError(`no section with id ${id}`);
  }
  return found[0];
}

function visibleText(fragment) {
  let text = fragment.replace(CLOSED_DETAILS, "$1").replace(NO_SCRIPT_NOTE, "");
  for (const pattern of NOT_SHOWN) {
    text = text.replace(pattern, "");
  }
  return text.replace(TAG, " ").replace(/&(?:amp|lt|gt|quot|#39);/g, (entity) => ENTITIES[entity]);
}

export function countVisibleWords(html, ids) {
  const perSection = Object.fromEntries(
    ids.map((id) => [id, (visibleText(sectionOf(html, id)).match(WORD) ?? []).length]),
  );
  const total = Object.values(perSection).reduce((sum, count) => sum + count, 0);
  return { perSection, total };
}

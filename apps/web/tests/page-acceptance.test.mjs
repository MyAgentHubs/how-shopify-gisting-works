import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { buildSite } from "../scripts/site.mjs";
import { verifyOutput } from "../scripts/verify-output.mjs";
import { countVisibleWords } from "../scripts/visible-words.mjs";
import { buildPages } from "./page-helpers.mjs";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(WEB, "..", "..");
const TSC = createRequire(import.meta.url).resolve("typescript/bin/tsc");
const EN_PAGE = join("opengisting", "index.html");
const ZH_PAGE = join("zh-CN", "opengisting", "index.html");
const KO_PAGE = join("ko", "opengisting", "index.html");
const IDS = ["top", "real", "gisting", "savings", "agent", "rules"];
const MAX_WORDS = 750;
const scratch = [];

afterAll(() => {
  for (const dir of scratch.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function tempDir(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  scratch.push(dir);
  return dir;
}

const pages = buildPages();

function withChange(change, options = {}) {
  const out = tempDir("bad-");
  cpSync(pages.outDir, out, { recursive: true });
  change(out);
  return verifyOutput({ outDir: out, ...options });
}

const edit = (file, change) => (out) => {
  const path = join(out, file);
  writeFileSync(path, change(readFileSync(path, "utf8")));
};

describe("the output check on a good build", () => {
  it("finds nothing wrong with the four pages and their data", () => {
    expect(verifyOutput({ outDir: pages.outDir })).toEqual([]);
  });

  it("finds nothing wrong beside the compiled scripts, and the type-only copy file tsc emits is not published", () => {
    const out = tempDir("full-");
    execFileSync(process.execPath, [TSC, "-p", join(WEB, "tsconfig.build.json"), "--outDir", join(out, "opengisting", "js")], {
      cwd: REPO,
      stdio: "pipe",
    });
    expect(existsSync(join(out, "opengisting", "js", "apps", "web", "copy", "en.json"))).toBe(true);
    buildSite({ webDir: WEB, outDir: out, entry: "js/apps/web/src/main.js" });
    expect(existsSync(join(out, "opengisting", "js", "apps", "web", "copy"))).toBe(false);
    expect(verifyOutput({ outDir: out })).toEqual([]);
  });

  it("keeps the default visible English words within the limit, counted the way the review page counted", () => {
    const { total, perSection } = countVisibleWords(pages.html("en"), IDS);
    expect(Object.keys(perSection)).toEqual(IDS);
    expect(total).toBeGreaterThan(MAX_WORDS - 200);
    expect(total).toBeLessThanOrEqual(MAX_WORDS);
  });

  it("does not count what is folded, what the help marks hide, or the no-script note", () => {
    const html = '<section id="a"><p>one two</p><details><summary>sum</summary><p>folded words here</p></details><details open><summary>open</summary>shown</details><p class="og-nojs">no script note</p><pre>code code</pre></section>';
    expect(countVisibleWords(html, ["a"]).total).toBe(5);
  });
});

describe("the output check on a broken build", () => {
  it("reports a missing page", () => {
    expect(withChange((out) => rmSync(join(out, KO_PAGE)))).toEqual(["ko: ko/opengisting/index.html was not built"]);
  });

  it("reports a wrong html lang, canonical, title or h1", () => {
    const problems = withChange(
      edit(ZH_PAGE, (html) =>
        html
          .replace('<html lang="zh-CN"', '<html lang="en"')
          .replace(/<link rel="canonical" href="[^"]*">/, '<link rel="canonical" href="https://example.com/">')
          .replace(/<title>[^<]*<\/title>/, "<title></title>")
          .replace("<h1", "<h2"),
      ),
    );
    expect(problems.join("\n")).toMatch(/zh-CN: html lang[\s\S]*canonical[\s\S]*title[\s\S]*exactly one h1/);
  });

  it("reports a missing hreflang on an indexed page and a stray one on a page that is not indexed", () => {
    const dropped = withChange(edit(EN_PAGE, (html) => html.replace(/<link rel="alternate" hreflang="x-default"[^>]*>/, "")));
    expect(dropped).toEqual([expect.stringContaining("en: hreflang must be [en, zh-Hans, x-default], found [en, zh-Hans]")]);
    const stray = withChange(edit(KO_PAGE, (html) => html.replace("</head>", '<link rel="alternate" hreflang="en" href="https://www.myagenthubs.com/opengisting/"></head>')));
    expect(stray).toEqual([expect.stringContaining("ko: hreflang must be []")]);
  });

  it("reports noindex on an indexed page and a page that is not indexed without it", () => {
    const added = withChange(edit(EN_PAGE, (html) => html.replace("</head>", '<meta name="robots" content="noindex"></head>')));
    expect(added).toEqual([expect.stringContaining("an indexed page must not be noindex")]);
    const dropped = withChange(edit(KO_PAGE, (html) => html.replace('<meta name="robots" content="noindex">', "")));
    expect(dropped).toEqual([expect.stringContaining("needs noindex")]);
  });

  it("reports an og image that does not match the product or is not in the og directory", () => {
    const moved = withChange(edit(EN_PAGE, (html) => html.replace("og-opengisting-en.png", "og-missing.png")));
    expect(moved.join("\n")).toMatch(/does not match product\.json[\s\S]*og-missing\.png is not in the og directory/);
  });

  it("wants the draft marker unless the build is a release, and no placeholder copy in a release", () => {
    expect(withChange(edit(EN_PAGE, (html) => html.replace('<meta name="build-state" content="draft">', "")))).toEqual([
      expect.stringContaining("must carry the draft marker"),
    ]);
    const draft = edit(EN_PAGE, (html) => html.replace("</main>", "<p>[PLACEHOLDER] x</p></main>"));
    const release = withChange(draft, { release: true }).join("\n");
    expect(release).toContain("must not carry the draft marker");
    expect(release).toContain("must not carry placeholder copy");
  });

  it("reports the words the page must not say, but lets the approved speed disclaimer through", () => {
    const say = (text) => edit(EN_PAGE, (html) => html.replace("</main>", `<p>${text}</p></main>`));
    for (const text of ["Benchmarks", "red_lines", "built on a Raspberry Pi", "a self-hosted box", "much faster", "quicker replies", "a snappier agent", "lower latency", "低延迟", "提速 30%", "回复加速", "agent_policy"]) {
      expect(withChange(say(text)), text).toEqual([expect.stringContaining(`${EN_PAGE}: mentions`)]);
    }
    const allowed = edit(ZH_PAGE, (html) => html.replace("</main>", "<p>token 变少，不等于我们声称更快。</p></main>"));
    expect(withChange(allowed)).toEqual([]);
    expect(withChange(edit(ZH_PAGE, (html) => html.replace("</main>", "<p>我们更快。</p></main>")))).toHaveLength(1);
  });

  it("reports the www header chrome, a hero eyebrow rule and a published copy file", () => {
    const problems = withChange((out) => {
      writeFileSync(join(out, "opengisting", "style.css"), ".hero .eyebrow{color:red}header.mh-global{top:0}");
      mkdirSync(join(out, "opengisting", "js", "apps", "web", "copy"), { recursive: true });
      writeFileSync(join(out, "opengisting", "js", "apps", "web", "copy", "en.json"), "{}");
    }).join("\n");
    expect(problems).toMatch(/style\.css: mentions a hero eyebrow/);
    expect(problems).toMatch(/style\.css: mentions www header chrome/);
    expect(problems).toMatch(/copy\/en\.json: a copy file must not be published/);
  });

  it("reports a preview script or the fake gateway beside a page that does not use them, but not beside a preview page", () => {
    const seed = (out) => {
      mkdirSync(join(out, "opengisting", "js", "apps", "web", "fakes"), { recursive: true });
      writeFileSync(join(out, "opengisting", "js", "apps", "web", "fakes", "fake-gateway.js"), "");
    };
    expect(withChange(seed)).toEqual([expect.stringContaining("fake-gateway.js: a preview-only script must not ship")]);
    const asPreview = (out) => {
      seed(out);
      edit(EN_PAGE, (html) => html.replace("/js/apps/web/src/main.js", "/js/apps/web/preview/main.js"))(out);
    };
    expect(withChange(asPreview)).toEqual([]);
  });

  it("reports an English page that is over the word limit", () => {
    const filler = Array.from({ length: 100 }, () => "word").join(" ");
    const problems = withChange(edit(EN_PAGE, (html) => html.replace('id="top" aria-labelledby="og-h1">', `id="top" aria-labelledby="og-h1"><p>${filler}</p>`)));
    expect(problems.join("\n")).toMatch(/en: \d+ visible words, the limit is 750/);
  });
});

describe("the copy files", () => {
  it("hold no key that nothing on the page, in the scripts or in the data refers to", () => {
    const keys = Object.keys(JSON.parse(readFileSync(join(WEB, "copy", "en.json"), "utf8")).strings);
    const source = readdirSync(WEB, { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile() && /\.(?:html|ts|mjs|json)$/.test(entry.name))
      .map((entry) => join(entry.parentPath, entry.name))
      .filter((path) => !path.startsWith(join(WEB, "copy")) && !path.startsWith(join(WEB, "tests")))
      .map((path) => readFileSync(path, "utf8"))
      .join("\n");
    expect(keys.filter((key) => !source.includes(key.replace(/_hint$/, "")))).toEqual([]);
  });
});

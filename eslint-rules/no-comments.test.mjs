import { RuleTester } from "eslint";
import { afterAll, describe, it } from "vitest";
import rule from "./no-comments.mjs";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester();
const withExpectError = [{ allowTsExpectError: true }];

tester.run("no-comments", rule, {
  valid: [
    "const a = 1;",
    "const text = '// not a comment';",
    "// eslint-disable-next-line no-console\nconsole.log(1);",
    "// eslint-disable-next-line no-console, no-alert\nconsole.log(1);",
    "// eslint-disable-next-line no-eval\neval('1');",
    { code: "// @ts-expect-error\nconst a = 1;", options: withExpectError },
  ],
  invalid: [
    { code: "// explain\nconst a = 1;", errors: [{ messageId: "comment", line: 1 }] },
    { code: "const a = 1; // trailing", errors: [{ messageId: "comment" }] },
    { code: "/* block */\nconst a = 1;", errors: [{ messageId: "comment" }] },
    { code: "/** doc */\nfunction f() {}", errors: [{ messageId: "comment" }] },
    { code: "/* eslint-disable-next-line no-console */\nconsole.log(1);", errors: [{ messageId: "comment" }] },
    { code: "// eslint-disable-line no-console\nconst a = 1;", errors: [{ messageId: "comment" }] },
    { code: "// eslint-disable-next-line no-console -- because\nconsole.log(1);", errors: [{ messageId: "comment" }] },
    { code: "// @ts-ignore\nconst a = 1;", errors: [{ messageId: "comment" }] },
    { code: "// @ts-expect-error\nconst a = 1;", errors: [{ messageId: "comment" }] },
    { code: "// @ts-expect-error because\nconst a = 1;", options: withExpectError, errors: [{ messageId: "comment" }] },
  ],
});

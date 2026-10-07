import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";
import noComments from "./eslint-rules/no-comments.mjs";

const STORAGE_GLOBALS = ["localStorage", "sessionStorage", "indexedDB", "BroadcastChannel"];
const STORAGE_MESSAGE = "The chat page keeps no state in the browser; hold it in memory only.";

const BAN_TS_DIRECTIVES = {
  "ts-ignore": true,
  "ts-nocheck": true,
  "ts-check": true,
  "ts-expect-error": true,
};

export default defineConfig(
  {
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/*.generated.ts",
      "legacy/**",
      "shopify-app/**",
      "artifacts/**",
      ".venv/**",
      ".claude/**",
    ],
  },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { local: { rules: { "no-comments": noComments } } },
    rules: {
      "max-lines": ["error", { max: 300, skipBlankLines: true, skipComments: true }],
      "max-lines-per-function": ["error", { max: 50, skipBlankLines: true, skipComments: true }],
      complexity: ["error", { max: 10, variant: "modified" }],
      "max-params": ["error", 5],
      "max-depth": ["error", 3],
      "no-empty": "error",
      "no-console": "error",
      "no-magic-numbers": ["error", { ignore: [0, 1, -1], ignoreArrayIndexes: true }],
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/ban-ts-comment": ["error", BAN_TS_DIRECTIVES],
      "local/no-comments": "error",
    },
  },
  {
    files: ["**/*.mjs", "**/*.cjs"],
    extends: [tseslint.configs.disableTypeChecked],
    rules: { "no-magic-numbers": "off" },
  },
  {
    files: ["**/*.cjs"],
    languageOptions: { sourceType: "commonjs" },
  },
  {
    files: ["apps/web/src/**/*.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...STORAGE_GLOBALS.map((name) => ({ name, message: STORAGE_MESSAGE })),
      ],
      "no-restricted-properties": [
        "error",
        ...[...STORAGE_GLOBALS, "cookie"].map((property) => ({ property, message: STORAGE_MESSAGE })),
      ],
    },
  },
  {
    files: ["**/*.test.ts", "**/tests/**/*.ts", "**/*.test.mjs"],
    rules: {
      "max-lines-per-function": "off",
      "no-magic-numbers": "off",
      "@typescript-eslint/ban-ts-comment": [
        "error",
        { ...BAN_TS_DIRECTIVES, "ts-expect-error": false },
      ],
      "local/no-comments": ["error", { allowTsExpectError: true }],
    },
  },
);

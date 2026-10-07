import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "node",
          environment: "node",
          include: [
            "apps/gateway/**/*.test.ts",
            "apps/web/**/*.test.mjs",
            "eslint-rules/**/*.test.mjs",
          ],
        },
      },
      {
        test: {
          name: "web",
          environment: "jsdom",
          css: { include: /.+/ },
          include: ["apps/web/**/*.test.ts"],
        },
      },
    ],
  },
});

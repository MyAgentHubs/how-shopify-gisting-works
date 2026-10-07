module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "not-to-unresolvable",
      severity: "error",
      from: {},
      to: { couldNotResolve: true, pathNot: "^cloudflare:" },
    },
    {
      name: "production-does-not-import-tests-or-fakes",
      severity: "error",
      from: { path: "^apps/", pathNot: "(^|/)tests?/|\\.test\\.ts$|^apps/web/preview/" },
      to: { path: "(^|/)(tests?|fakes?)/|\\.test\\.ts$" },
    },
    {
      name: "web-production-does-not-import-the-preview",
      severity: "error",
      from: { path: "^apps/web/(src|scripts)/" },
      to: { path: "^apps/web/preview/" },
    },
    {
      name: "web-entries-are-not-imported",
      severity: "error",
      from: { path: "^apps/web/" },
      to: { path: "^apps/web/(src/main|preview/main)\\.ts$" },
    },
    {
      name: "gateway-types-import-nothing",
      severity: "error",
      from: { path: "^apps/gateway/src/types\\.ts$" },
      to: { path: "^apps/gateway/src/" },
    },
    {
      name: "gateway-stages-are-independent",
      severity: "error",
      from: {
        path: "^apps/gateway/src/(config|ip|validate|turnstile|turnstile-policy|quota|upstream|replay|respond)\\.ts$",
      },
      to: {
        path: "^apps/gateway/src/(config|ip|validate|turnstile|quota|upstream|replay|respond|handler)\\.ts$",
      },
    },
    {
      name: "only-config-and-turnstile-share-the-turnstile-policy",
      severity: "error",
      from: { path: "^apps/gateway/src/(ip|validate|quota|upstream|replay|respond|handler)\\.ts$" },
      to: { path: "^apps/gateway/src/turnstile-policy\\.ts$" },
    },
    {
      name: "counter-worker-and-pages-side-do-not-import-each-other",
      severity: "error",
      from: { path: "^apps/gateway/(src|functions)/" },
      to: { path: "^apps/gateway/counter-worker/" },
    },
    {
      name: "counter-worker-is-self-contained",
      severity: "error",
      from: { path: "^apps/gateway/counter-worker/" },
      to: { path: "^apps/gateway/(src|functions)/" },
    },
    {
      name: "gateway-core-does-not-import-the-entry",
      severity: "error",
      from: { path: "^apps/gateway/src/" },
      to: { path: "^apps/gateway/functions/" },
    },
  ],
  options: {
    tsConfig: { fileName: "tsconfig.json" },
    doNotFollow: { path: "node_modules" },
    exclude: { path: "\\.generated\\.ts$" },
  },
};

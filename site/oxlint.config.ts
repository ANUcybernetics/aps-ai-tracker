import { defineConfig } from "oxlint";

// Mirrors the benswift-me lint setup, trimmed to the built-in plugins (no extra
// eslint-plugin deps). oxlint does not lint .astro/.svelte, and src/generated is
// machine-written, so all are ignored.
export default defineConfig({
  categories: {
    correctness: "error",
    suspicious: "error",
    perf: "error",
  },
  env: {
    browser: true,
    builtin: true,
    es2024: true,
    node: true,
  },
  ignorePatterns: ["src/generated/**", "dist/**", "**/*.astro", "**/*.svelte"],
  plugins: ["typescript", "import", "unicorn"],
  rules: {
    "no-console": "off",
    eqeqeq: ["error", "always", { null: "ignore" }],
    "import-x/no-self-import": "error",
  },
});

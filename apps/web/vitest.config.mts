import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // tsconfig.json の `paths`（`@/*` → `./src/*`）を解決する。
    tsconfigPaths: true,
    alias: {
      // `import "server-only"` throws by default (its `react-server` export is a
      // no-op). Vitest has no react-server condition, so alias it to the no-op
      // module to let server modules be imported in tests.
      "server-only": fileURLToPath(
        new URL("./node_modules/server-only/empty.js", import.meta.url),
      ),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    // `passWithNoTests` は立てない。**立てずにおくと include glob が壊れてテストを
    // 1 件も拾えなくなったときに gate が落ちて気付ける。**
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    exclude: ["tests/**", "playwright-report/**", "test-results/**"],
    tags: [
      { name: "small" },
      { name: "medium" },
      { name: "large" },
      { name: "smoke" },
      { name: "a11y" },
      { name: "performance" },
    ],
    coverage: {
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/app/api/**", "src/tests/**", "tests/**"],
    },
  },
});

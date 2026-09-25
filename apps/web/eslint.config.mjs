import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import playwright from "eslint-plugin-playwright";
import prettier from "eslint-config-prettier/flat";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright generated artifacts
    "playwright-report/**",
    "playwright/.cache/**",
  ]),
  {
    // registry 生成コード（shadcn/ui + AI Elements）。`npx ai-elements add` /
    // `npx shadcn add` が上書きするため、こちらで手を入れても再生成で消える。
    // 上流の実装に合わせてルールを緩める（自作コードには適用しない）。
    // - react-hooks/refs: code-block.tsx が render 中に ref を読み書きしている
    // - react-hooks/static-components: shimmer.tsx が render 中に component を作る
    // - no-unused-vars: prompt-input.tsx の destructuring で未使用の束縛がある
    files: [
      "src/components/ai-elements/**/*.tsx",
      "src/components/ui/**/*.tsx",
    ],
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/static-components": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    // Playwright の E2E。recommended rules に従って書く（緩和 block は持たない）。
    ...playwright.configs["flat/recommended"],
    files: ["tests/e2e/**/*.ts"],
  },
  {
    // tests/e2e is not React. Playwright's `use` fixture callback trips the
    // react-hooks/rules-of-hooks heuristic (`use(...)`); disable it here.
    files: ["tests/e2e/**/*.ts"],
    rules: {
      "react-hooks/rules-of-hooks": "off",
    },
  },
  // 書式は Prettier が決める。書式と衝突する ESLint の rule を最後に無効化する。
  prettier,
]);

export default eslintConfig;

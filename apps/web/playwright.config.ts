import { defineConfig, devices } from "@playwright/test";

/**
 * gate 用の検証は、この worktree のアプリを必ず新規起動して行う。`PLAYWRIGHT_GATE=1` のとき:
 *   - 既存サーバの reuse を禁止する（別 worktree / main の stale dev server を誤検証しない）。
 *   - dev 用 3000 と衝突しない専用ポート（既定 3100、`PLAYWRIGHT_PORT` で上書き可）で起動する。
 * 通常の inner-loop（`npx playwright test` 直叩き）は 3000 + reuse で高速に回す。
 *
 * **API も一緒に起こす**。smoke は fake モデル
 * （`AGENT_MODEL_MODE=fake`）で回すので、実 LLM も compose の api も要らない。
 *
 * 実行経路は **`make test-e2e` だけ**。通常 gate（`check-all` を含む）の対象外である。
 *
 * **backend の ASGI 入口は Make の `APP_ASGI_APP` を環境変数で受け取る** —— 起動
 * file 名を web 側にも書くと、片方だけ直った状態ができる。
 */
const IS_GATE = !!process.env.PLAYWRIGHT_GATE;

/**
 * API の ASGI 入口（root の `Makefile` の `APP_ASGI_APP`）。
 *
 * **既定値を持たない。** 起動する構成の入口は Make から受け取る。
 * `E2E_DATABASE_URL` と同じく `make test-e2e` 経由を前提にする。
 */
const APP_ASGI_APP = process.env.APP_ASGI_APP;
if (!APP_ASGI_APP) {
  throw new Error(
    "APP_ASGI_APP が未設定です。`make test-e2e` から実行してください" +
      "（起動する ASGI 入口の正本は root の Makefile です）。",
  );
}
const PORT = process.env.PLAYWRIGHT_PORT ?? (IS_GATE ? "3100" : "3000");
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${PORT}`;

/**
 * E2E が書き込む DB。**`make test-e2e` が `app_test` の URL を渡す。**
 *
 * 無ければ**落とす**。`make test-e2e` は `DB_ENV_CONTEXT=test` を宣言するので、
 * API 側の loader（`apps/api/core/environment.py` の `load_test_env()`）は
 * `secrets/test.env` の `DATABASE_URL`（= **app_test**）を置く。ただし
 * `make test-e2e` を経由せず直に起動すると context が未設定で、API は
 * `DB_ENV_CONTEXT` 未設定の RuntimeError か `api` context の `app_dev` に行く。
 * 黙って開発 DB を汚さないよう、ここで明示的に止める。
 *
 * **ここで見られるのは「値が入っているか」まで。** 渡された URL が本当にテスト DB か
 * （= `app_dev` と同じ実体でないか）は **`make test-e2e` の側**が名前で弾く
 * （`_migrate-test-db` の前提条件 `_assert-test-db` → `scripts/common/db_guard.py`）。
 * 判定規則は Make 側に集約する。
 * **`make test-e2e` を経由しない直叩きは歯止めの外**（手で URL を
 * 与える行為なので、明示的な選択として扱う）。
 */
const e2eDatabaseUrl = process.env.E2E_DATABASE_URL;
if (!e2eDatabaseUrl) {
  throw new Error(
    "E2E_DATABASE_URL が未設定です。`make test-e2e` から実行してください" +
      "（直に起動すると API が app_dev に繋がります）。",
  );
}

/**
 * API ポートの**単一の導出元**。gate / inner-loop とも専用ポートを使う。
 *
 * **8000 は compose の api が占有している**ので、そこを掴むと inner-loop の
 * `reuseExistingServer` が**実モデルの api を再利用して** smoke を走らせてしまう
 * （fake に切り替わらないまま緑になる）。`PLAYWRIGHT_API_PORT` が上書き口
 * （Web 側の `PLAYWRIGHT_PORT` と対。別 worktree・並行実行での衝突回避）。
 */
const API_PORT = process.env.PLAYWRIGHT_API_PORT ?? "8100";
const API_BASE_URL = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: "test-results",
  /*
   * 既定の 30 秒では、初回の dev server compile を含む往復が収まらないことがある。
   * 時間の予算は config 側に 1 か所だけ置き、test の中で `test.setTimeout()` を
   * 呼ばない。
   */
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: IS_GATE,
  retries: 0,
  workers: IS_GATE ? 2 : undefined,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
  webServer: [
    {
      // fake モデルの API。`ENVIRONMENT=local` は fake の allowlist と揃える
      // （`apps/api/core/config.py` の `FAKE_MODEL_ALLOWED_ENVIRONMENTS`）。
      command: `uv run uvicorn ${APP_ASGI_APP} --port ${API_PORT}`,
      // readiness は `/health/live`（DB を見ない契約。`apps/api/application.py`）。
      url: `${API_BASE_URL}/health/live`,
      env: {
        DATABASE_URL: e2eDatabaseUrl,
        AGENT_MODEL_MODE: "fake",
        ENVIRONMENT: "local",
        // fake モデルでも `Settings` は構築されるので `LLM_PROFILE` は必須。
        // pin しないと、operator の secrets/api.env に別の provider profile が
        // 設定されている場合、対応する key が無い環境で E2E が起動失敗する。
        // `make test-e2e` 経由では Makefile の pin が同じ値を先に入れるが、
        // `npx playwright test` を直接叩く経路には効かないので両方に置く。
        LLM_PROFILE: "ds4-deepseek-v4-flash-chat",
        /*
         * **実 provider へ接続しない fake プロセス専用の非秘密値**。
         *
         * 画面のモデル選択は request 単位で profile を運ぶが、可用性判定と
         * 503 は `os.environ` の credential を見る（製品側の判定は 1 行も
         * 緩めない）。この値が無いと、operator の OpenAI key が無い環境で
         * Luna が `available: false` になり POST も 503 になるので、
         * DS4 → Luna → DS4 の切替を**本物の API 境界**で確かめられない。
         *
         * `AGENT_MODEL_MODE=fake` なのでどちらの profile でも `FunctionModel` が
         * 返り、`AsyncOpenAI` は 1 個も作られない。`load_api_env()` は既存 OS env を
         * 上書きしないので、この値が `secrets/api.env` の実キーより優先される ——
         * **E2E は operator の credential から独立し、実キーが E2E プロセスへ入らない。**
         *
         * registry の placeholder（`unused`）と別の値でなければ credential 判定を
         * 通らない。実キーらしい値（`sk-` 始まり）にもしないこと。
         */
        OPENAI_API_KEY: "e2e-fake-openai-key",
      },
      reuseExistingServer: !IS_GATE,
      stdout: "pipe",
      cwd: "../..",
      timeout: 120_000,
    },
    {
      // gate: この worktree のアプリを専用ポートで新規起動する（reuse 禁止で衝突回避）。
      // inner-loop: 3000 で起動し、既存 server があれば reuse する。
      command: "npm run web:dev",
      url: BASE_URL,
      reuseExistingServer: !IS_GATE,
      stdout: "pipe",
      cwd: "../..",
      // PORT を webServer に伝播し、next dev が BASE_URL と同じポートで待ち受ける。
      // FASTAPI_BASE_URL は上の fake API に向ける（既定の 8000 = compose の api だと
      // **実モデルに繋がったまま緑になる**）。
      env: {
        PORT,
        FASTAPI_BASE_URL: API_BASE_URL,
      },
      // 初回 next dev のコールドコンパイルを考慮して既定 60s から拡張する。
      timeout: 120_000,
    },
  ],
});

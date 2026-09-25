# フロントエンドテスト

この文書は、webのテストの種類と書き方を決めます。`apps/web/`のテストを書くときに読みます。何をテストし、
何をテストしないかは[テスト規約](../../dev/test-policy.md)、実行するlaneは
[テスト実行マトリクス](../../dev/test-execution-matrix.md)を正本とします。

## VitestとPlaywrightの使い分け

| 種類 | 置き場所 | 確かめること |
|---|---|---|
| Vitest | `src/**/*.test.ts(x)` | component、hook、中継とprofile選択の規則。stateから表示と操作可否への対応 |
| Playwright | `tests/e2e/` | browserでの一連の操作。送信、承認、却下、profileの引き継ぎ |

同じ分岐を両方で確かめません。Vitestで確かめられるものはVitestに置き、Playwrightは実際のbrowserと
APIを通さないと確かめられない流れだけにします。

## Vitest

- `describe`に`{ tags: ["small"] }`を付けます。`make verify-frontend`は`small`のtagだけを実行します
- 環境はjsdomです。jsdomに無いbrowserのAPIは、使うtest fileの中だけで補い、共有のsetup
  （`vitest.setup.ts`）は変えません
- fetchとAPIの応答は、test fileの中で差し替えます。実際のFastAPIには接続しません

## fake modelのE2E

- `make test-e2e`だけで実行します。APIとwebをこのworktreeで新しく起動し、APIは
  `AGENT_MODEL_MODE=fake`でサンプルのfake modelを使います。実providerのcredentialは要りません
- 書き込み先はテスト専用DBです。接続先は`make test-e2e`が渡し、テスト専用DBであることを名前で検査して
  から起動します。直接`npx playwright test`を実行すると、設定が足りずに止まります
- 時間の上限は`playwright.config.ts`だけで決め、testの中で変えません
- 必須の流れを`test.skip`で成功扱いにしません

## coverage

webにはcoverageの閾値を置いていません。閾値を満たすためだけのテストを増やさないためです。

## 確認するコマンド

- 変更後は`make verify-frontend`を実行します
- 画面の流れ、中継、profile選択、承認に関わる変更では`make test-e2e`も実行します

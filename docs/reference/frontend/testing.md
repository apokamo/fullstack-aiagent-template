# フロントエンドテスト

この文書は、webのテストの分類、テストケースの台帳、台帳とテストの突き合わせ、テストの書き方を決めます。
`apps/web/`のテストを書くときと、webのテストケースを追加するときに読みます。何をテストし、何をテストしないかは
[テスト規約](../../dev/test-policy.md)、実行するlaneは[テスト実行マトリクス](../../dev/test-execution-matrix.md)を
正本とします。

## テストの分類

webのテストは、使ってよいresourceでSmall / Medium / Largeに分け、E2Eはそれとは別の軸として扱います。

| 分類 | 使ってよいもの（判定の基準） | 確かめること | 確かめないこと | 道具と置き場所 |
|---|---|---|---|---|
| Small | 1つのprocessだけ。jsdom。fetchとAPIの応答は差し替える | 規則と変換。componentの状態ごとの表示（文言、表示・非表示、押せるかどうか、aria属性、入力チェックの表示、操作したときに呼び出し側へ渡る値）。中継（route handler）の積み替えの規則（upstreamはmock） | 実際に別processと通信すること。ページをまたぐ流れ | Vitest（`src/**/*.test.ts(x)`、`describe`に`tags: ["small"]`） |
| Medium | localhostの別processまで。外部APIは不可。UIを通さない | Next.jsの中継とFastAPI（fake model）の実際のつながり：SSEの素通し、エラーのstatusと固定文言、相関IDとsecurity header、profile一覧の取得 | 画面の表示（Small）。画面の流れ（E2E） | Playwrightの`request` fixture（`tests/e2e/request/`、project `medium`） |
| Large | 制限なし。外部APIも可。UIを通さない | 定義だけ置く（今は該当なし） | — | 置き場所なし |
| E2E | 実browser、Next.js、FastAPI（fake model）、テスト用DB。S/M/Lとは別の軸 | 画面遷移とURLの変化。画面をまたぐ流れ（送信→承認待ち→承認→再開など）。browserでしか起きないこと（streamの表示の進行、実際に送られたrequest、focusの移動）。状態はrole、testid、要素の数、URLで確かめる | 文言（Smallで確かめる）。Smallで確かめた規則の分岐をもう一度確かめること | Playwright（`tests/e2e/ui/`、project `e2e`） |

同じ分岐を複数の分類で確かめません。Smallで確かめられるものはSmallに置き、MediumとE2Eは別processや
実際のbrowserを通さないと確かめられないことだけにします。

Largeには置き場所がありません。台帳のケースが`large`を要求すると、突き合わせの検査は必ず
「テストが無い」で失敗します。

## テストケースの台帳

`apps/web/tests/coverage/frontend-test-cases.yml`が、webのテストケースの唯一の手書きの正本です。

```yaml
cases:
  - id: H1
    feature: home
    category: 状態
    description: "名称、説明、チャットへの導線が表示される"
    kinds: [small]
```

| 項目 | 規則 |
|---|---|
| （top-level） | keyは`cases`だけ。`cases`は空でない配列 |
| `id` | `^[A-Z]+[0-9]+$`。台帳の中で一意 |
| `feature` | `^[a-z][a-z0-9-]*$`。例: `home`、`model-select`、`send`、`send-error`、`approval`、`accessibility` |
| `category` | `画面遷移`、`操作`、`入力チェック`、`APIエラー`、`状態`、`アクセシビリティ`、`データの形`、`秘密値の表示`のどれか |
| `description` | 空でない文字列。確かめる振る舞いを1文で書く |
| `kinds` | `small`、`medium`、`large`、`e2e`から1つ以上、重複なし |

項目はすべて必須です。未知の項目、型の誤り、YAMLとして読めない台帳は検査の失敗になります。
`description`に`: `や`` ` ``を含められるよう、文字列は引用符で囲みます。

台帳に登録するのは、ケースの内容のすべてを今のテストのassertionが確かめているケースだけです。一部しか
確かめていないケースは、足りないテストを追加するときに一緒に登録します。

## テスト側の注釈

- Vitest: テスト名（`it` / `test`の第1引数）の先頭に、空白区切りで1つ以上の`@case:<id>`を置きます。
  `describe`名には付けません

  ```ts
  it("@case:S11 本文と tool 結果を出す", async () => { ... });
  ```

- Playwright: `tag` optionで付けます。titleの中には書きません

  ```ts
  test("承認すると再開する", { tag: ["@case:A1", "@case:A4"] }, async ({ page }) => { ... });
  ```

1つのテストが複数のケースを確かめてかまいません。同じテストに同じidを2回書いても1回として扱います。

ケース→テストの対応表は手で書きません。注釈から導いた対応表は次で出せます。

```bash
uv run python -m scripts.testing.frontend_test_cases --print-map
```

## 台帳とテストの突き合わせ

`make verify-frontend`が`scripts/testing/frontend_test_cases.py`を実行し、台帳と注釈を突き合わせます。
browser、DB、networkは使いません。Vitestは`vitest list`、Playwrightは`playwright test --list`で収集します。
種類は、Vitestは`small`のtagで実行される集合、PlaywrightはprojectName（`e2e` / `medium`）から決まります。

次のどれかで失敗します。

| 条件 | 判定 |
|---|---|
| 必要な種類のテストが無い | ケースの`kinds`の各種類について、その種類の注釈付きテストが1件も無い |
| 注釈のidが台帳に無い | 注釈のケースidが台帳のidの集合に無い |
| idの重複 | 同じ`id`が台帳に2件以上ある |
| 種類が一致しない | 注釈付きテストはあるが、その種類がどれも`kinds`と一致しない |

`kinds`に無い種類のテストが追加であることは失敗にしません。

検査が黙って成功しないよう、次も失敗にします。

- 台帳のschema違反
- `@case:`がVitestのテスト名の先頭以外（途中や`describe`名）にある、または`@case:`の後にidが無い
- 注釈付きのVitestテストが`small`の集合に無い（どのlaneも実行しないテストで台帳を満たせないようにする）
- 収集コマンドの失敗、読めない出力、Vitestが0件、Playwrightの`e2e` / `medium`以外のproject

### 保証の範囲

検査が保証するのは「台帳に載ったケースに、必要な種類の注釈付きテストがあること」までです。台帳にケースが
漏れていないか、注釈を付けたテストが本当にそのケースを確かめているかは、レビューで確かめます。

## ケースを追加する手順

1. 台帳にケースを登録します（`id`、`feature`、`category`、`description`、`kinds`）
2. `kinds`の各種類のテストを書き、`@case:<id>`の注釈を付けます
3. `make verify-frontend`で突き合わせが成功することを確かめます。MediumとE2Eを書いたときは
   `make test-e2e`も実行します

## Vitest（Small）

- `describe`に`{ tags: ["small"] }`を付けます。`make verify-frontend`は`small`のtagだけを実行します
- 環境はjsdomです。jsdomに無いbrowserのAPIは、使うtest fileの中だけで補い、共有のsetup
  （`vitest.setup.ts`）は変えません
- fetchとAPIの応答は、test fileの中で差し替えます。実際のFastAPIには接続しません

## Playwright（MediumとE2E）

- `make test-e2e`だけで実行します。APIとwebをこのworktreeで新しく起動し、APIは
  `AGENT_MODEL_MODE=fake`でサンプルのfake modelを使います。実providerのcredentialは要りません
- projectは置き場所で分けます。`e2e`は`tests/e2e/ui/`を実browserで、`medium`は`tests/e2e/request/`を
  `request` fixtureで実行します。Mediumではbrowserを使いません
- 書き込み先はテスト専用DBです。接続先は`make test-e2e`が渡し、テスト専用DBであることを名前で検査して
  から起動します。直接`npx playwright test`を実行すると、設定が足りずに止まります。一覧の収集
  （`--list`）だけはテストもserverも実行しないので、設定が無くても実行できます
- 時間の上限は`playwright.config.ts`だけで決め、testの中で変えません
- 必須の流れを`test.skip`で成功扱いにしません

## coverage

webにはcoverageの閾値を置いていません。閾値を満たすためだけのテストを増やさないためです。

## 確認するコマンド

| コマンド | 実行するもの |
|---|---|
| `make verify-frontend` | format、lint、型、VitestのSmall、台帳の突き合わせ。変更後に毎回実行します |
| `make test-e2e` | PlaywrightのMedium（`tests/e2e/request/`）とE2E（`tests/e2e/ui/`）。画面の流れ、中継、profile選択、承認に関わる変更と、MediumやE2Eを追加・変更したときに実行します |

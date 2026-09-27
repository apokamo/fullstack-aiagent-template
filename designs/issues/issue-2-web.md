# Issue #2 webのテスト分類と台帳・突き合わせの検査

- Issue: #2（親Epic: #6、後続: #5）
- type: `type:chore`、area: `area:frontend`、`area:workflow`
- base: `origin/main` `3726421358aa714639cc3c7b544b83bf987ac76c`

## 目的と範囲外

webのテストを、使うresourceで分けるSmall / Medium / Largeと、別の軸のE2Eに分類し直す。
テストケースを台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）に書き出し、台帳とテストの注釈を
`make verify-frontend`で機械的に突き合わせる。規約は`docs/reference/frontend/testing.md`に書く。

範囲外（Issue #2の`## 範囲外`）:

- テストの追加と、今のE2Eの文言による確認の置き換え（#5）。今あるテストの**本文**は変えず、注釈だけを付ける
- 画面とbackendの振る舞いの変更。`apps/web/src/`の製品コードと`apps/api/`は変更しない
- kamo2の画面要素の突き合わせ（§6.2）と、`@profile`などのtagによる選択実行

## 保守の対象と不変条件（chore rubric）

| 項目 | 内容 |
|---|---|
| 影響する開発契約 | `make verify-frontend`の中身（突き合わせの検査を追加）、`make test-e2e`の対象（Medium置き場所を追加）、webのテスト分類の規約文書 |
| 利用者から見える不変条件 | 画面・API・backendの振る舞いは変わらない。既存のVitest 51件とPlaywright 3本は本文を変えず、同じ件数で成功し続ける |
| 互換性 | Playwrightのproject名が`chromium`から`e2e`と`medium`に変わる。repository内で`--project chromium`を参照する箇所は無い（`grep -rn chromium`でconfig以外0件） |
| lock・設定 | npm・Pythonの依存は増やさない。YAMLの読み込みは既存のdev依存`pyyaml`を使う。`package-lock.json`と`uv.lock`は変えない |
| migration | 無し。DB、schema、secretに触れない |
| rollback | 通常の`git revert`で戻る。台帳と注釈は検査からしか読まれず、実行時の状態を持たない |

## 根拠にした一次情報

- Issue #2本文の`## 決定事項`（分類表、台帳、突き合わせの4条件、lane、文書、台帳の最初の中身）
- Issue #6の`## ケース一覧`（ID、分類、種類、現状✓/△/✗）と`## 決定事項`
- Issue #5の`## 決定事項`（Mediumは`tests/e2e/request/`に`request` fixtureで書く、など）
- `Makefile`の`verify-frontend` / `_verify-frontend-lane`（374〜386行）、`test-e2e` / `_test-e2e-lane`（322〜331行）、
  `check-all`（413〜424行）
- `apps/web/playwright.config.ts`（`testDir: "./tests/e2e"`、`APP_ASGI_APP`と`E2E_DATABASE_URL`が無いと
  config読み込みで`throw`、project `chromium`は1つ）
- `apps/web/vitest.config.mts`（`include: ["src/**/*.{test,spec}.{ts,tsx}"]`、tag定義）
- 既存テスト: `apps/web/src/**/*.test.ts(x)` 8ファイル、`apps/web/tests/e2e/ui/sample-chat.spec.ts` 3本
- `docs/reference/frontend/testing.md`、`docs/dev/test-policy.md`、`docs/dev/test-execution-matrix.md`、
  `docs/howto/use-template.md`、`docs/dev/documentation-update-criteria.md`
- `pyproject.toml`（`pyyaml>=6.0.3`がdev依存、`testpaths = ["apps/api/tests", "scripts/tests"]`）

### 設計時に確かめた挙動（base SHAのworktreeで実行）

| コマンド | 結果 |
|---|---|
| `cd apps/web && npx vitest list --tagsFilter=small --json` | exit 0。51件。各要素は`{"name", "file"}`だけで、`name`は`describe名 > テスト名`を` > `で連結した文字列。tagは出力されない |
| `cd apps/web && npx vitest list --json` | exit 0、約1.3秒 |
| `cd apps/web && npx playwright test --list`（envなし） | exit 1。`playwright.config.ts`の`APP_ASGI_APP`検査で`throw` |
| `APP_ASGI_APP=x E2E_DATABASE_URL=postgresql://none npx playwright test --list --reporter=json` | exit 0。webServerを起動しない（不正な起動コマンドでも成功）。`config.argv`に`--list`が入る。specごとに`title`、`tags`、`file`（testDirからの相対）、`line`、`tests[].projectName`を持つ |
| `eslint-plugin-playwright`の`valid-test-tags` | tagは`@`始まりであることだけを検査する。`@case:A1`は通る |

## 設計

### 1. テスト分類（Issue #2の分類表をそのまま規約にする）

| 分類 | 道具 | 置き場所 | 検査が判定する種類 |
|---|---|---|---|
| Small | Vitest（jsdom、fetchとAPI応答は差し替え） | `apps/web/src/**/*.test.ts(x)`、`describe`に`tags: ["small"]` | `vitest list --tagsFilter=small`に出るテスト → `small` |
| Medium | Playwrightの`request` fixture（UIを通さない、localhostの別processまで） | `apps/web/tests/e2e/request/` | Playwright project `medium` → `medium` |
| Large | 定義だけ置く | 置き場所なし | 収集しない（台帳が`large`を要求すると、必ず「足りない」で失敗する） |
| E2E | Playwright（実browser） | `apps/web/tests/e2e/ui/` | Playwright project `e2e` → `e2e` |

確かめること・確かめないことは、Issue #2の分類表の文言を`testing.md`へ移す。

### 2. Playwrightの設定（`apps/web/playwright.config.ts`）

- projectを置き場所で分ける。種類の判定はPlaywright自身が付けるproject名から導き、pathの規則を検査側に
  二重に書かない。
  - `{ name: "e2e", testDir: "./tests/e2e/ui", use: { ...devices["Desktop Chrome"] } }`
  - `{ name: "medium", testDir: "./tests/e2e/request" }`（`request` fixtureはbrowserを起動しない）
  - top-levelの`testDir`は削除する。`baseURL`などの`use`、`webServer`、timeout、workersは共通のまま
- 一覧の収集だけのとき（`process.argv.includes("--list")`）は、`APP_ASGI_APP`と`E2E_DATABASE_URL`の
  欠落で`throw`せず、`webServer`を渡さない。`--list`はテストもserverも実行しないので、DBの取り違えの
  歯止めは弱まらない。`--list`でない実行（`npx playwright test`の直叩きを含む）は今までどおり`throw`する。
  dummyのenvを検査から渡す方式は、偽のDB URLを流す手順を正当化するので採らない
- `apps/web/tests/e2e/request/.gitkeep`を置き、Mediumの置き場所をGitで追跡する。テストの中身は#5
- `make test-e2e`は`npm run test:fe:e2e`（= `playwright test`）で全projectを実行するので、Makefileは変えない

### 3. テストケースの台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）

webのテストケースの唯一の手書きの正本。形は次のとおり。

```yaml
cases:
  - id: H1
    feature: home
    category: 状態
    description: 名称、説明、チャットへの導線が表示される
    kinds: [small]
```

| 項目 | 必須 | 規則 |
|---|---|---|
| （top-level） | — | mappingで、keyは`cases`だけ。`cases`は空でない配列 |
| `id` | 必須 | `^[A-Z]+[0-9]+$`。台帳の中で一意。#6のIDをそのまま使う |
| `feature` | 必須 | `^[a-z][a-z0-9-]*$`。#6の節に合わせ、`home`（H）、`model-select`（P）、`send`（S）、`send-error`（E）、`approval`（A）、`accessibility`（X） |
| `category` | 必須 | `画面遷移`、`操作`、`入力チェック`、`APIエラー`、`状態`、`アクセシビリティ`、`データの形`、`秘密値の表示`のどれか |
| `description` | 必須 | 空でない文字列。#6の「ケース」列の文 |
| `kinds` | 必須 | `small`、`medium`、`large`、`e2e`から1つ以上、重複なし |

未知の項目、型の誤り、YAMLとして読めないものは検査の失敗にする。

### 4. テスト側の注釈

- Vitest: テスト名（`it` / `test`の第1引数）の先頭に、空白区切りで1つ以上の`@case:<id>`を置く。
  例: `it("@case:S11 本文と tool 結果を出す", ...)`。複数のidは`it("@case:<id1> @case:<id2> <テスト名>", ...)`と
  並べる（初期台帳には、1つのVitestテストに複数idを付けるものは無い）。`describe`名には付けない
- Playwright: `test(title, { tag: ["@case:A1", "@case:A4"] }, ...)`の`tag`で付ける。Playwrightはtitle中の
  `@...`もtagとして扱うが、規約は`tag` optionに統一する（検査はJSONの`tags`を読むのでどちらでも同じ結果）
- 1つのテストが複数のケースを確かめてよい。同じテストに同じidを2回書いても1回として扱う

### 5. 突き合わせの検査（`scripts/testing/frontend_test_cases.py`）

入口は`uv run python -m scripts.testing.frontend_test_cases`。repository rootから実行し、
`apps/web`をcwdにして次を実行する（browserは起動しない）。

1. `npx --no-install vitest list --json`（全件）
2. `npx --no-install vitest list --tagsFilter=small --json`（`make verify-frontend`が実行する集合）
3. `npx --no-install playwright test --list --reporter=json`

言語はPythonにする。YAMLの読み込みに既存の`pyyaml`を使え、`scripts/`のテストは`make check-all`で毎回
実行される（`docs/dev/test-policy.md`の`scripts/`のテスト）。webへYAMLのnpm依存を足さずに済む。

#### 注釈の読み取り

- Vitest: `name`を最後の` > `で分けた末尾をテスト名とする。テスト名の先頭から、空白区切りで
  `@case:(\S+)`に一致するtokenを続く限り読む。テストの識別は`(file, name)`の組。`file`はrepository root
  からの相対pathで表示する
- Playwright: 入れ子の`suites`を再帰でたどり、各specの`tags`のうち`@case:`で始まるものを読む。
  種類はspecの`tests[].projectName`（`e2e` / `medium`）から決める。表示は`tests/e2e/<file>:<line>`

#### 失敗にする条件

Issue #2の4条件:

| # | 条件 | 判定 |
|---|---|---|
| 1 | 台帳のケースが、必要な種類のテストで1つも書かれていない | ケースの`kinds`の**各**種類について、その種類の注釈付きテストが1件も無い |
| 2 | 注釈のケースidが台帳に無い | 注釈のidが台帳のidの集合に無い |
| 3 | ケースidが台帳の中で重複している | 同じ`id`が2件以上 |
| 4 | テストはあるが、どの種類も台帳の必要な種類と一致しない | 注釈付きテストが1件以上あり、その種類の集合が`kinds`と交わらない。このとき条件1ではなく、この条件のmessageで報告する |

条件1を「各種類に1件以上」と読むのは、初期台帳で`E2E / Small`とするケース（S11、A6）が今どちらの
種類でもテストされており、種類ごとに確かめ忘れを検出できるほうが台帳の目的に合うため（下の判断記録の
仮定1）。台帳の`kinds`に無い種類のテストが追加であることは、Issueの条件に無いので失敗にしない。

検査を成り立たせるための失敗（黙って成功しないため）:

- 台帳のschema違反（上の表）
- `@case:`がVitestのテスト名の先頭の連続したtoken以外の位置にある、または`@case:`の後にidが無い
- 注釈付きのVitestテストが`small`の集合に無い（どのlaneも実行しないテストで台帳を満たせないようにする）
- 収集コマンドのexit codeが0でない、出力がJSONとして読めない、Playwright JSONの`errors`が空でない、
  Vitestの全件が0件、Playwrightのprojectが`e2e` / `medium`以外

messageは1件ずつ1行で、ケースidとテストの位置を含める。1件でもあればexit 1、無ければ件数の要約を出して
exit 0。

#### 対応表

ケース→テストの対応表は手で書かない。`--print-map`を付けると、注釈から導いた対応表（ケースごとに種類と
テストの位置）を標準出力に出す。`make verify-frontend`では付けない。

#### 保証の範囲

保証するのは「台帳に載ったケースに、必要な種類の注釈付きテストがあること」まで。台帳にケースが漏れて
いないか、注釈を付けたテストが本当にそのケースを確かめているかはレビューで確かめる。この限界を
`testing.md`に書く。

#### 構成

- 読み込み・収集結果の解釈・判定は、subprocessを持たない純関数に分ける
  （例: `load_ledger(text) -> (cases, errors)`、`parse_vitest(all_json, small_json)`、
  `parse_playwright(json)`、`check(cases, tests) -> list[str]`）。`main()`だけがsubprocessを実行する
- 型注釈とdocstringは既存の`scripts/testing/lane_record.py`に合わせる

### 6. Makefile

`_verify-frontend-lane`のVitestの後に1段追加する。

```text
<TAB>@echo "→ Checking the frontend test-case ledger..."
<TAB>@uv run python -m scripts.testing.frontend_test_cases
```

（`<TAB>`はMakefileのtab文字）

`test-e2e`、`check-all`は変えない（`check-all`は`verify-frontend`経由で検査を含み、MediumとE2Eは含まない）。

### 7. 台帳の最初の中身と注釈

Issue #2の決定事項「今のテストで確かめられているケースだけを登録する」に従い、#6で✓のケースのうち、
ケース本文の**すべての部分**を今のassertionが確かめている11件だけを登録する。#6で✓でも、本文の一部に
assertionが無いP1、P2、S1、A5は、今のテストで確かめられていない部分がある（実態は△）ので登録しない
（下の「登録しない✓のケース」）。△と✗は#5（A7は#3、E5は#4）でテストと一緒に登録する。

| id | feature | category | kinds | 注釈を付けるテスト |
|---|---|---|---|---|
| H1 | home | 状態 | small | `src/sample/home.test.tsx`「metadata と同じ名称・説明と、チャットへの導線を出す」 |
| P3 | model-select | APIエラー | small | `model-select.test.tsx`「一覧取得に失敗したら理由と再取得導線を出す」 |
| P5 | model-select | 状態 | small | `model-select.test.tsx`「利用不可の選択肢は選べず、理由を文字で添える」 |
| P7 | model-select | 操作 | small | `model-select.test.tsx`「選べる選択肢を選ぶと呼び出し側へ id を渡す」、`src/lib/chat-profiles.test.ts`「select() だけが選択を書き換え、次の送信から効く」 |
| P8 | model-select | 状態 | small | `src/components/chat/model-select.test.tsx`「一覧の取得中・取得失敗・生成中は選べない」（`disabled: true`の分岐） |
| S11 | send | 状態 | e2e, small | E2E「/chat が開き、検索の tool 結果と結論が出る」、`chat-page.test.tsx`「本文と tool 結果を出す」 |
| A1 | approval | 状態 | e2e | E2E「一時メモは承認前に止まり、承認すると…」 |
| A2 | approval | 操作 | small | `chat-page.test.tsx`「承認待ちの tool に出した承認は approved: true を 1 回だけ送る」、`src/components/chat/tool-approval.test.tsx`「押すまでは応答を送らず、承認ボタンは approved: true で応答する」 |
| A3 | approval | 操作 | small | `chat-page.test.tsx`「却下は approved: false を 1 回だけ送る」、`tool-approval.test.tsx`「却下ボタンは approved: false で応答する」 |
| A4 | approval | 画面遷移 | e2e | E2E「一時メモは承認前に止まり、承認すると…」 |
| A6 | approval | データの形 | e2e, small | E2E「一時メモは承認前に止まり、承認すると…」、`chat-profiles.test.ts`「承認再開は元の run の profile を保持する」「A 送信 → B へ変更 → 承認再開は A、続く再試行は B を送る」 |

`description`は#6のケース列の文をそのまま使う。注釈はテスト名の先頭またはPlaywrightの`tag`に足すだけで、
テストの本文、assertion、helperは変えない。

登録した11件は、ケース本文の各部分に対応するassertionがあることを設計時に照合した（例: A4は承認後の
`SAVED_TEXT`の表示と`tool-approval`の0件、S11は`tool-header`の`search_docs`とSmallの`sample-response`）。

#### 登録しない✓のケース（#5で登録する）

| id | 今のテストにあるassertion | 足りない部分 |
|---|---|---|
| P1 | `model-select.test.tsx` 65〜84行: loading中に`model-select`がdisabled | 「読み込み中…」の表示（`model-select.tsx`のplaceholderにあるだけで、assertionが無い） |
| P2 | `chat-page.test.tsx` 118〜129行: 見出し、Submitが押せる、guardが無い | 既定のprofileが選ばれていること（選択値のassertionが無い） |
| S1 | E2E 65〜74行: 応答カード1件と`tool-header`。`chat-page.test.tsx` 131〜139行: assistantの本文。179行以降: `sendMessage`の引数 | 自分の発話が表示されること |
| A5 | E2E 76〜89行: 却下後の文言、`tool-approval`の0件、成功文言の不在 | 同じtool（`save_note`）が再提案されないこと（`tool-header`の件数などのassertionが無い） |

- この4件のテストには`@case:`を付けない。Issue #2はテストの追加が範囲外なので、足りないassertionは
  ここでは足さない
- 後続の担当は#5。#5の完了条件「#6のケース一覧の全ケースが台帳に登録され、`make verify-frontend`の
  突き合わせの検査が成功する」は#6の全ケースを対象にするので、この4件も#5でテストを揃えて登録する
  ことになる。#5の「対象の契約」（✗と△）との対応を明確にするため、この4件は実態が△であることを
  作業報告に記録し、#5の着手時に対象へ含める（Issue本文の書き換えは人が判断する）
- 設計時の照合の限界: #6の✓の判定は人が付けたもので、この設計は現行assertionとの照合で上の4件を
  △と判断した。判定の根拠は上の表の行番号（base SHA `3726421`）

### 8. 文書

| 文書 | 変更 |
|---|---|
| `docs/reference/frontend/testing.md` | 分類表（§1）、置き場所、台帳のschema（§3）、注釈（§4）、突き合わせの失敗条件と保証の範囲（§5）、ケースの追加手順（台帳に登録→テストに注釈→`make verify-frontend`）、`--print-map`、Largeは置き場所が無いこと、`make verify-frontend`と`make test-e2e`の使い分けに書き直す。既存のjsdom、fetch差し替え、E2EのDB・timeout・skipの規則は残す |
| `docs/dev/test-policy.md` | 規模の目安からE2E（2〜3本）の行を削除し、「E2Eの本数は台帳のケースから決まる」と書く。「値、文言…を二重に固定するテスト」の禁止は設定ファイルや定数の値を写すテストが対象で、UIの表示を確かめるテストは対象外だと書く。webの分類は`testing.md`を正本とする旨を層の節に添える |
| `docs/dev/test-execution-matrix.md` | `make verify-frontend`の対象に「テストケース台帳の突き合わせ」を足す。`make test-e2e`の対象を「Medium（`tests/e2e/request/`）とE2E（`tests/e2e/ui/`）」にする |
| `docs/howto/use-template.md` | 画面の置き換えの手順に、台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）と注釈も合わせる旨を足す |

`playwright.config.ts`のファイル先頭のコメント（「smoke」「3本」の記述）も、projectの分割と`--list`の扱いに
合わせて直す。

## 実装の順序（slice）

1. `playwright.config.ts`のproject分割と`--list`の扱い、`tests/e2e/request/.gitkeep`
2. `scripts/testing/frontend_test_cases.py`と`scripts/tests/test_frontend_test_cases.py`
3. 台帳と既存テストへの注釈
4. `Makefile`の`_verify-frontend-lane`
5. 文書

## 検査のテスト（`scripts/tests/test_frontend_test_cases.py`）

`pytestmark = pytest.mark.small`。subprocessもfilesystemも使わず、台帳のtextと収集結果のJSONを組み立てて
純関数に渡す。完了条件の3つは必ず個別のテストにする。

| テスト | 入力 | 期待 |
|---|---|---|
| 台帳から1件消す | 注釈`@case:H1`付きテストがあり、台帳からH1を削除 | 条件2（台帳に無いid）で失敗 |
| 存在しないidを注釈に書く | 注釈`@case:Z9` | 条件2で失敗 |
| idを重複させる | 台帳にH1が2件 | 条件3で失敗 |
| 必要な種類が足りない | `kinds: [e2e, small]`でsmallのテストだけ | 条件1でe2eが足りないと失敗 |
| 種類が一致しない | `kinds: [e2e]`でsmallのテストだけ | 条件4のmessageで失敗 |
| 一致する | 全ケースに必要な種類のテスト | 失敗0件 |
| 注釈の位置 | `@case:`がテスト名の途中、`describe`名、空のid | 失敗 |
| smallでない注釈付きVitest | 全件に有り、small集合に無い | 失敗 |
| schema違反 | 未知の項目、`kinds`が空、未知の`category`、不正な`id` | 失敗 |
| 読み取り | ` > `を含む`describe`の入れ子、Playwrightの入れ子suiteとprojectName | 正しい`(種類, id)`を得る |
| 収集の失敗 | Playwright JSONの`errors`が空でない、Vitest 0件、未知のproject | 失敗 |

## 検証lane

| lane | 要否 | 理由 |
|---|---|---|
| `make verify-frontend` | 必須 | Vitestのテスト名の変更と検査の追加。台帳が成功することを確かめる |
| `make verify-backend` | 必須（inner loop） | `scripts/`のPythonと`scripts/tests/`の追加。lint、型、Small |
| `make verify-docs` | 必須 | 文書4件の変更（`check-all`に含まれる） |
| `make check-all` | 必須（最終） | Issueの完了条件。`gate-backend`、schema、`verify-frontend`、`verify-docs` |
| `make test-e2e` | 必須 | `playwright.config.ts`のproject分割、`--list`の扱い、E2Eの`tag`追加。既存3本が`e2e` projectで成功し、`medium` projectが対象に入ることを確かめる |
| `make test-on-schema-change` | 追加不要 | schemaを変えない（`check-all`に含まれる分で足りる） |
| `make test-llm`、`make evals` | 不要 | prompt、tool、agent loop、HITL、model、providerを変えない。LLMの品質・接続への影響なし（観測も不要） |

### 実装前の基準（implement-precheck）

base SHAで次を測り、実装後と比べる。

- `cd apps/web && npx vitest list --tagsFilter=small --json`の件数（設計時51件）。実装後も同数
- `npx playwright test --list`のテスト数（設計時3本）。実装後は`e2e` projectに同じ3本、`medium` projectに0本
- `cd apps/web && npx playwright test --list`（envなし）がexit 1であること。実装後はexit 0、
  `npx playwright test`（`--list`なし、envなし）は引き続きexit 1
- `make verify-frontend`と`make test-e2e`がbase SHAで成功すること（safety net）

### 実装時の追加確認（lane以外）

- `tests/e2e/request/`に一時的なspecを置き、`npx playwright test --list`で`medium` projectに出ることを
  確かめてから削除する（commitしない）
- 台帳から1件消す、存在しないidを注釈に書く、idを重複させる、の3つを実際のworktreeで一時的に行い、
  `uv run python -m scripts.testing.frontend_test_cases`がexit 1になることを確かめて戻す

## 完了条件との対応

| Issue #2の完了条件 | 満たし方 |
|---|---|
| 分類、台帳、突き合わせの規約が`testing.md`にあり、`test-policy.md`と`test-execution-matrix.md`が更新されている | §8 |
| 台帳があり、✓のケースに注釈が付き、`make verify-frontend`が成功する | §3、§6、§7（今のテストで確かめられている11件。P1、P2、S1、A5は一部未検証のため#5） |
| 1件消す・存在しないid・重複で検査が失敗することを検査のテストで確かめている | 検査のテストの表の先頭3行 |
| `tests/e2e/request/`にMediumの置き場所があり、`make test-e2e`がそこも実行する | §2（`medium` project、`.gitkeep`） |
| `make check-all`が成功する | 検証lane |

## 失敗と安全

- 検査は収集・解釈のどの失敗でもexit 1にし、0件や読めない出力で成功しない
- `--list`での`throw`の省略はPlaywrightの一覧の収集に限る。テストの実行経路のDB検査（config側の
  `E2E_DATABASE_URL`必須と、Make側の`_assert-test-db`）は変わらない
- 検査はbrowser、DB、network、secretを使わない。`make verify-frontend`は引き続きDB不要

## 判断記録

| 判断 | 選んだ方向 | 根拠・仮定 | 設計で加えた詳細 |
|---|---|---|---|
| 分類とresourceの境界 | Small / Medium / Large / E2E（E2Eは別軸） | Issue #2 決定事項「webのテスト分類」 | 検査が種類を判定する方法（§1） |
| 台帳の置き場所と正本 | `apps/web/tests/coverage/frontend-test-cases.yml`が唯一の手書きの正本 | Issue #2 決定事項「テストケースの台帳」 | 項目名と形（§3）。Issueが「項目の名前と形は設計で決める」とした二方向の詳細 |
| 注釈の書き方 | Playwrightは`@case:<id>`のtag、Vitestはテスト名の先頭の`@case:<id>` | Issue #2 決定事項 | 複数idの並べ方、` > `で分けた末尾の扱い（§4、§5） |
| 失敗条件 | 4条件、browserを起動しない、Playwrightは`--list` | Issue #2 決定事項「突き合わせの検査」 | 検査を成り立たせる失敗（schema、注釈位置、small以外、収集失敗） |
| 仮定1: 条件1の読み方 | `kinds`の各種類に1件以上 | 仮定（二方向）。確かめ忘れを種類ごとに検出するため。初期台帳の複数種類のケース（S11、A6）は今どちらの種類もテストがあり、今の台帳は成功する。設計レビューで確認する | 条件4との報告の使い分け |
| 仮定2: 検査の言語と置き場所 | Pythonの`scripts/testing/frontend_test_cases.py` | 仮定（二方向）。既存の`pyyaml`を使え、`scripts/tests/`は`check-all`で毎回実行される。npm依存を足さない。設計レビューで確認する | 純関数とsubprocessの分離 |
| 仮定3: Playwrightの種類の判定 | project `e2e`（`tests/e2e/ui`）と`medium`（`tests/e2e/request`）に分け、project名から判定 | 仮定（二方向）。置き場所はIssue #2の分類表・#5の決定事項。pathの規則を検査側に二重に書かない | project名の変更（`chromium`→`e2e`/`medium`）、参照箇所0件の確認 |
| 仮定4: `--list`のときのconfigの検査 | `process.argv`に`--list`があるときだけenvの`throw`とwebServerを省く | 仮定（二方向）。Issue #2「Playwrightは`--list`で収集する」を、偽のDB URLを渡さずに満たすため。`--list`はserverもテストも実行しないことを設計時に確認した | 直叩きの実行は今までどおり止まる |
| laneの分担 | MediumとE2Eは`make test-e2e`、`check-all`に含めない。`verify-frontend`はVitest smallと検査 | Issue #2 決定事項「lane」、#6 決定事項 | Makefileの変更は`_verify-frontend-lane`の1段だけ |
| 台帳の最初の中身 | #6の✓のうち、ケース本文のすべてを今のassertionが確かめている11件 | Issue #2 決定事項「台帳の最初の中身」（今のテストで確かめられているケースだけ、✗と△はテストを追加するIssueで登録）、#5の完了条件（#6の全ケースの登録）、review-designの指摘1〜3 | ケースごとの注釈先（§7）。P1、P2、S1、A5は一部未検証（実態△）として登録せず、#5へ引き継ぐ |
| 文書の変更 | `test-policy.md`のE2E本数の削除、文言の禁止の範囲、`testing.md`の書き直し、matrixの更新 | Issue #2 決定事項「文書」 | `use-template.md`への1文の追加（`documentation-update-criteria.md`の「テスト分類、gate選定」） |
| 画面とbackend | 変えない | Issue #2 範囲外 | 既存テストの本文も変えない |

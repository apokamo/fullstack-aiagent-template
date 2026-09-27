# Issue #5 台帳のケースのテストを揃える

- Issue: #5（親Epic: #6、依存: #2、#3、#4（いずれもCLOSED））
- type: `type:test`、area: `area:frontend`
- base: `origin/main` `5293d75e29af9fec98aae468e3eed26809a8a535`

## 目的と範囲外

確かめること（test rubric）:

- #6の「ケース一覧」のうち、台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）に未登録の28件に
  テストを揃え、台帳に登録する。登録後の台帳は#6の41件と、#3・#4が足したA9・E6の計43件になる
- 今のE2E（`apps/web/tests/e2e/ui/sample-chat.spec.ts`）が`SEARCH_ANSWER`・`SAVED_TEXT`・`DENIED_TEXT`・
  `NEXT_ANSWER`（fake modelの応答文）で状態の変化を待っている部分を、role、testid、要素の数、URL、実際に
  送られたrequestでの確認に置き換える
- Medium（`tests/e2e/request/`）を初めて置く（P9、P10、S10、E3）

範囲外（Issue #5の`## 範囲外`と`## 決定事項`）:

- 画面とbackendの振る舞いの変更。製品コード（`apps/web/src/**`のテスト以外、`apps/api/**`）は変えない。
  唯一の例外はS4が不安定な場合のfake modelの`FAKE_STREAM_STEP_S`で、扱いは「失敗と安全」に書く
- A7（#3）とE5（#4）の追加のテスト。既存の登録をそのまま使う
- テストの過程で既存の不具合が見つかり、製品コードを変えないとケースを満たせない場合、そのケースは#5で登録
  しない（「失敗と安全」）

## 根拠にした一次情報

- Issue #5本文（`## 対象の契約`、`## 決定事項`、`## 不安定さへの対策`、`## 範囲外`、`## 完了条件`）と
  readiness review（PASS、2026-09-27T15:26:03Z）、worktree作成（`start` PASS）
- Issue #6の`## 決定事項`（文言や状態ごとの表示はSmall、E2Eは画面遷移・画面をまたぐ流れ・browserでしか
  起きないこと。E2Eの本数に上限は置かない。A8は再読み込みで会話が消え、書き込みは実行されない）と
  `## ケース一覧`（id、分類、ケース、種類、現状）
- `designs/issues/issue-2-web.md` 196〜235行（P1、P2、S1、A5は実態が△なので#2では登録せず、#5が登録する。
  足りない部分の表）
- `docs/reference/frontend/testing.md`（分類表、台帳のschema、注釈の書き方、突き合わせの失敗条件、Medium・E2Eの
  置き場所とproject、時間の上限と`test.skip`の禁止）
- `apps/web/tests/coverage/frontend-test-cases.yml`（登録済み15件: H1、P3、P5、P7、P8、S11、A1、A2、A3、A4、
  A7、A9、A6、E5、E6）
- `apps/web/tests/e2e/ui/sample-chat.spec.ts` 22〜138行（応答文の定数と、それを`getByText`で待つ73、89、92、
  121、128、135行）
- `apps/web/playwright.config.ts`（project `e2e` / `medium`、`timeout: 60_000`、`fullyParallel`、gateの
  `workers: 2`、APIの`OPENAI_API_KEY: "e2e-fake-openai-key"`と`LLM_PROFILE: "ds4-deepseek-v4-flash-chat"`）
- 画面の構造: `src/components/chat/chat-shell.tsx`（`main`、`role="log"`の会話、`model-guard` /
  `approval-guard` / 送信の失敗の3つの`role="alert"`、`PromptInputTextarea`の`disabled`と
  `placeholder="生成中…"`）、`src/sample/response.tsx`（`sample-response`、`reasoning`、`reasoning-toggle`、
  `tool-header`）、`src/components/chat/model-select.tsx`（`aria-labelledby`、placeholder「読み込み中…」、
  `model-list-error`）、`src/components/ai-elements/prompt-input.tsx` 979〜996行（Enterは
  `button[type="submit"]`が`disabled`なら送らず、それ以外は`requestSubmit()`）と1226〜1256行（生成中は
  `aria-label="Stop"`・`type="button"`、それ以外は`aria-label="Submit"`）、
  `src/components/ai-elements/conversation.tsx`（`role="log"`、`ConversationEmptyState`の`h3`）
- 状態の持ち主: `src/components/chat/use-chat-session.ts`（`send()`の生成中・承認待ち・空文のguard、
  `retry()`）、`src/components/chat/use-chat-profiles.ts`（一覧の取得、既定の選択、`reload()`、
  `guardMessage`）
- 中継: `src/lib/chat-relay.ts`（chatは失敗時502と`{ error }`、非2xxは`code`だけ読んで固定文言、正常時は
  bodyを素通し。一覧は200だけ素通しし、それ以外は固定body、`no-store`）
- FastAPI: `apps/api/agent/router.py` 174〜237行（未知profileは422 `chat_profile_unknown`、credentialの欠落は
  503 `chat_profile_unavailable`）、322〜347行（壊れたbodyは422のJSON、`code`を持たない）、
  `apps/api/core/llm_profiles.py` 88〜135行（DS4はcredential不要、OpenAIの2件は`OPENAI_API_KEY`）
- fake model: `apps/api/sample/fake_model.py` 23〜45、156〜190行（`FAKE_STREAM_STEP_S = 0.35`、trigger
  「メモ」「こんにちは」「詳しく」、「詳しく」は5断片を0.35秒おきに流す）
- 置き換えで確かめなくなる応答文のSmall: `apps/api/tests/test_sample_fake_model.py`（`pytestmark =
  pytest.mark.small`。106行で検索の結論「「テストの tier」に記載があります。」、115行`NO_HIT_TEXT`、124行
  `SAVED_TEXT`、136行`DENIED_TEXT`）

## 対象と分類

台帳の`kinds`は#6の「種類」から決める。「E2E / Small」は`[e2e, small]`、「Small / Medium」は`[small, medium]`
（#2で`S11`と`A6`を`[e2e, small]`にした読み方と同じ）。`feature`は台帳の既存の対応（H→`home`、
P→`model-select`、S→`send`、E→`send-error`、A→`approval`、X→`accessibility`）、`category`と`description`は
#6の表の値をそのまま使う。

| id | kinds | 今の状態 | この設計で足すもの |
|---|---|---|---|
| H2 | e2e | ✗ | E2E（新規`home.spec.ts`） |
| H3 | e2e | ✗ | E2E（新規`home.spec.ts`） |
| P1 | small | △（「読み込み中…」のassertionが無い） | Small |
| P2 | small | △（既定のprofileが選ばれていることのassertionが無い） | Small |
| P4 | small | ✗ | Small |
| P6 | small | △（入力した文が残ること、理由の文言のassertionが無い） | Small（既存テストを拡張） |
| P9 | medium | ✗ | Medium |
| P10 | small, medium | △（Smallはあるが注釈なし、chatの502のbodyのassertionが無い） | Small（注釈とassertionの追加）、Medium |
| P11 | e2e | ✗ | E2E |
| S1 | e2e, small | △（自分の発話の表示のassertionが無い） | Small、E2E（既存テストを拡張） |
| S2 | small | △（空白だけ・空の文のassertionが無い） | Small |
| S3 | small | ✗ | Small |
| S4 | e2e | ✗ | E2E |
| S5 | small | ✗ | Small |
| S6 | small | ✗ | Small |
| S7 | small | ✗ | Small |
| S8 | small | ✗ | Small |
| S9 | e2e | ✗ | E2E |
| S10 | medium | ✗ | Medium |
| E1 | small | ✗（再試行のボタンのassertionが無い） | Small（既存テストを拡張） |
| E2 | e2e | ✗ | E2E |
| E3 | small, medium | △（中継の写像のSmallだけ。画面の表示とMediumが無い） | Small、Medium |
| E4 | small | △（中継のSmallだけ。画面のassertionが無い） | Small |
| A5 | e2e | △（再提案しないことのassertionが無い） | E2E（既存テストを置き換え） |
| A8 | e2e | ✗ | E2E |
| X1 | small | ✗ | Small |
| X2 | small | ✗（`role="alert"`のassertionが一部だけ） | Small（既存テストに注釈とassertion） |
| X3 | e2e | ✗ | E2E |

A7とE5は#3・#4の登録のまま、テストを重ねない。登録済みのS11、A1、A4、A6はE2Eの置き換え後も同じテストに
注釈を残す。

## 設計

### 1. E2Eで使ってよい文字列

Issue #5の決定「E2Eは文言を確かめない。状態はrole、testid、要素の数、URLで確かめる」を次のように適用する。

- **確かめない**: 画面の文言（固定文言、見出し、案内）と、fake modelの応答文（`SEARCH_ANSWER`など）。
  この4つの定数は`sample-chat.spec.ts`から削除する
- **locatorとしてだけ使ってよい**: 操作に必要なaccessible name（`Submit`、`Stop`、`承認`、`却下`、`再試行`、
  optionのlabel）。今のE2Eと同じ扱いで、assertionの対象にはしない
- **assertionに使ってよい**: テストが入力したデータのecho（送った発話、fake modelの固定引数
  `NOTE_TITLE` / `NOTE_BODY`）、tool名（`search_docs`、`save_note`）、profile id、要素の数、URL、focus、
  scrollの位置、実際に送られたrequestの中身

送った発話とtoolの引数は画面の文言ではなくテストのデータで、A1の「渡される引数が読める」は今もこの形で
確かめている（#2で登録済み）。この扱いを`sample-chat.spec.ts`の先頭のコメントに書く。

### 2. E2Eの共通の待ち方（`sample-chat.spec.ts`）

応答文を待つ代わりに、「runが終わった」を次の2段で待つ。

```ts
/** `/api/chat`へのPOSTか。 */
function isChatPost(request: Request): boolean;

/**
 * `action`が起こす次の`/api/chat`のrunが終わるまで待つ。
 * 1. `page.waitForResponse`でそのPOSTの応答を待ち、`response.finished()`でbodyを読み切るまで待つ
 * 2. 停止ボタン（`getByRole("button", { name: "Stop" })`）が0件になるまで待つ
 */
async function runToEnd(page: Page, action: () => Promise<void>): Promise<void>;
```

- `waitForResponse`は`action`の前に登録する。先に登録しないと、速い応答を取りこぼす
- 1の後に2を待つのは、bodyを読み切った後も画面がstreamを処理し終えるまで停止ボタンが残るため。送信直後の
  「まだ`submitted`になっていない」瞬間とは、1で必ず区別できる（1が解決した時点で送信は始まっている）
- 承認の自動再開（`sendAutomaticallyWhen`）も、承認のclickを`action`にして同じhelperで待つ

送られたrequestは`page.on("request", ...)`で`isChatPost`のものを配列に集める（bodyは`postDataJSON()`）。
A6の既存テストの`page.route(...).continue()`は、観測だけなので`page.on("request")`に揃える。

「結論が出た」は、全`sample-response`の直下の要素の合計数で確かめる。`SampleResponse`はpartごとに1要素を
描き、`step-start`などは描かない（`response.tsx` 411〜475行）ので、toolを1回呼んで結論を返したrunは
「tool 1 + text 1 = 2」になる。承認の再開が同じカードに続くか新しいカードになるかに依存しないよう、カード
単位ではなく合計で数える。

```ts
const parts = page.getByTestId("sample-response").locator(":scope > *");
```

`role="alert"`と要素の数は、今のE2Eと同じく`page.getByRole("main")`に絞る（dev overlay対策）。

### 3. E2Eのテスト（`tests/e2e/ui/`）

時間の上限は`playwright.config.ts`だけで決める。テストの中で`test.setTimeout()`、`waitForTimeout()`、
`expect`/`expect.poll`の`timeout`指定を使わない。viewportは時間の上限ではないので、S9だけ`test.use`で
変える。

発話は`fake_model.py`のtriggerから選ぶ。

| 定数 | 値 | fake modelの分岐 |
|---|---|---|
| `SEARCH_PROMPT` | 今の値 | `search_docs`（triggerを含まない） |
| `NOTE_PROMPT` | 今の値 | `save_note`（「メモ」） |
| `GREETING_PROMPT` | `"こんにちは"` | 本文だけ（「こんにちは」） |
| `SLOW_PROMPT` | `"サンプル文書を詳しく説明してください。"` | 5断片を0.35秒おき（「詳しく」。「メモ」「こんにちは」を含まない） |
| `NEXT_PROMPT` | 今の値 | `search_docs` |

`sample-chat.spec.ts`:

| テスト | tag | 手順と確かめること |
|---|---|---|
| 検索（既存を置き換え） | `@case:S1`、`@case:S11` | `goto("/chat")`が200。`runToEnd`で`SEARCH_PROMPT`を送る。`getByRole("log").getByText(SEARCH_PROMPT, { exact: true })`が1件（自分の発話）、`sample-response`が1件、直下の要素の合計が2、`tool-header`が`search_docs`を含む |
| 却下（既存を置き換え） | `@case:A5` | `runToEnd`で`NOTE_PROMPT`を送り、`tool-approval`が見える。`runToEnd`で`却下`を押す。`tool-approval`が0件、`tool-header`が1件（同じtoolを再提案しない）、直下の要素の合計が2、`Submit`が押せる（承認待ちが残っていない）、POSTが2本 |
| 承認（既存を置き換え） | `@case:A1`、`@case:A4`、`@case:A6` | `runToEnd`で`NOTE_PROMPT`を送る。`tool-approval`が見え、`tool-header`が`save_note`を含み、カードが`NOTE_TITLE`と`NOTE_BODY`を含む。POSTが1本（承認前は再開のrunが無い＝書き込みは実行されていない）、直下の要素の合計が1。Lunaを選び、`runToEnd`で`承認`を押す。`tool-approval`が0件、直下の要素の合計が2、profileが`[DS4, DS4]`。`runToEnd`で`NEXT_PROMPT`を送り、profileが`[DS4, DS4, LUNA]` |
| 停止（新規） | `@case:S4` | `SLOW_PROMPT`を送り、`Stop`が見えたら、`page.waitForEvent("requestfailed", isChatPost)`を登録してから`Stop`を押す。そのPOSTが中断され（`requestfailed`が来る）、`Stop`が0件、`Submit`が見え、入力欄（`getByRole("textbox")`）が操作できる |
| 表示の伸びと自動スクロール（新規） | `@case:S9` | `test.use({ viewport: { width: 1280, height: 360 } })`。`runToEnd`で`GREETING_PROMPT`を送る。会話のscroll要素（`role="log"`の子孫で`overflow-y`が`auto`か`scroll`のもの）の`scrollHeight`を記録し、`page.evaluate`で`MutationObserver`を仕掛けて最後の`sample-response`の`textContent.length`を変化のたびに記録する。`runToEnd`で`SLOW_PROMPT`を送る。記録した0より大きい長さが2種類以上（表示が段階的に伸びた）、`scrollHeight`が記録値より大きく`clientHeight`より大きい（中身がはみ出した）、`expect.poll`で`scrollHeight - scrollTop - clientHeight <= 1`（下端にいる） |
| 再試行（新規） | `@case:E2` | `page.route("**/api/chat", ..., { times: 1 })`で最初のPOSTだけ`502`と`{ error: "chat backend is unreachable" }`を返す。`SEARCH_PROMPT`を送る。`main`の`role="alert"`が1件で、その中に`再試行`のボタンがある。`runToEnd`で`再試行`を押す。`main`の`role="alert"`が0件、`sample-response`が1件、POSTが2本（2本目は実際にFastAPIへ届く） |
| 承認待ちの再読み込み（新規） | `@case:A8` | `runToEnd`で`NOTE_PROMPT`を送り、`tool-approval`が見える。`page.reload()`し、`model-select`が押せるまで待つ。`sample-response`が0件、`tool-approval`が0件、`getByRole("log").getByRole("heading")`が1件（空の会話の案内）。`runToEnd`で`GREETING_PROMPT`を送る。POSTが合計2本（再開のPOSTが無い＝書き込みは実行されない）、2本目のbodyは`trigger: "submit-message"`で`messages`が1件（前の会話を運んでいない） |
| 再読み込みで選択が戻る（新規） | `@case:P11` | Lunaを選び、`page.reload()`し、`model-select`が押せるまで待つ。`runToEnd`で`GREETING_PROMPT`を送る。送ったprofileが`[DS4]`（既定。`playwright.config.ts`と`make test-e2e`が`LLM_PROFILE`をDS4にpinしている） |
| キーボードだけの操作（新規） | `@case:X3` | `goto("/chat")`、`model-select`が押せるまで待つ。`tabTo`で`model-select`へ移り、`Enter`で開き、`ArrowDown`をLunaのoptionにfocusが移るまで押し、`Enter`で選ぶ。`tabTo`で入力欄へ移り、`NOTE_PROMPT`を`keyboard.type`し、`runToEnd`で`Enter`を押す。`tabTo`で`承認`へ移り、`runToEnd`で`Enter`を押す。`tool-approval`が0件、送ったprofileが`[LUNA, LUNA]`（キーボードの選択が送信に反映され、承認で再開した） |

`tests/e2e/ui/home.spec.ts`（新規）:

| テスト | tag | 手順と確かめること |
|---|---|---|
| チャットへ移動 | `@case:H2` | `goto("/")`。`getByRole("main").getByRole("link")`（トップのlinkは1つ）を押す。URLが`/chat`で終わり、`model-select`が見える |
| キーボードで移動 | `@case:H3` | `goto("/")`。`tabTo`でlinkへ移り（focusされている）、`Enter`を押す。URLが`/chat`で終わり、`model-select`が見える |

`tabTo`は両方のfileで使うので`tests/e2e/ui/keyboard.ts`（testではないmodule）に置く。

```ts
/** `target`にfocusが来るまでTabを押す。`maxPresses`回で来なければ失敗する。 */
export async function tabTo(page: Page, target: Locator, maxPresses = 30): Promise<void>;
```

判定は`target.evaluate((el) => el === document.activeElement)`で行い、最後に
`await expect(target).toBeFocused()`で確かめる。Tabの回数を固定しないのは、dev serverが`main`の外に
focusできる要素（dev overlay）を挿すことがあるため。上限を置くので、focusできない場合は黙って成功せず失敗する。
optionへの`ArrowDown`も同じ形で、上限はoptionの数とする。

### 4. Medium（`tests/e2e/request/chat-relay.spec.ts`、新規）

Playwrightの`request` fixtureだけを使い、`baseURL`（Next.js）の中継を通してFastAPI（fake model）に届ける。
固定文言は製品の定数を`../../../src/lib/chat-profiles`から読み、値を写さない。

| テスト | tag | 手順と確かめること |
|---|---|---|
| 一覧が中継を通って届く | `@case:P9` | `GET /api/chat/profiles`が200、`Cache-Control: no-store`。bodyのkeyは`defaultProfile`と`profiles`だけ、`profiles`は空でなく、各要素のkeyは`id`・`label`・`available`・（あれば）`unavailableReason`だけで型が合う。`defaultProfile`が`profiles`のidに含まれ、その要素は`available: true`。profile idの一覧は写さない（registryの値を二重に固定しない） |
| SSEがそのまま流れる | `@case:S10` | 一覧の`defaultProfile`と、`{ id: "medium-<randomUUID>", trigger: "submit-message", messages: [{ id: "u-1", role: "user", parts: [{ type: "text", text: "こんにちは" }] }], profile }`で`POST /api/chat`。200、`Content-Type`が`text/event-stream`を含む、`x-vercel-ai-ui-message-stream: v1`、`x-request-id`が空でない、`x-content-type-options: nosniff`、`X-Accel-Buffering: no`。bodyの`data:`行を順に読み、最初のeventの`type`が`start`、`text-delta`があり連結が空でない、`finish`があり、最後の行が`[DONE]` |
| 未知のprofileは422と固定文言 | `@case:E3` | `profile: "no-such-profile"`で同じbodyを送る。422、bodyのkeyが`error`だけで値が`CHAT_ERROR_MESSAGES[CHAT_PROFILE_UNKNOWN_CODE]`、`x-request-id`が空でない、bodyに`request_id`と`detail`を含まない |
| FastAPIの非2xxは固定body | `@case:P10` | `{}`を`POST /api/chat`へ送る（FastAPIは`from_request`の検証で422、`code`を持たない）。422のまま返り、bodyのkeyが`error`だけで値が`CHAT_GENERIC_ERROR_MESSAGE`、`x-request-id`が空でない |

MediumでできないことはSmallとbackendのテストが持つ。

- 503（credentialの欠落）: E2E/Mediumのfake APIは`OPENAI_API_KEY`を設定し、DS4はcredentialが要らない
  ので、どのprofileも503にならない。Luna（A6、P11、X3）を使うので設定は変えない。503は中継のSmall
  （`route.test.ts`）と画面のSmall（下のE3）、backendの`apps/api/tests/test_chat_profile_selection.py`
  219行が確かめる
- FastAPIが止まっている場合: Mediumでは起動中のFastAPIを止められない。中継のSmall（下のP10）が確かめる

### 5. Small（Vitest、`describe`に`tags: ["small"]`）

既存のfileに足す。jsdomに無いAPIは使うfileの中だけで補う（`model-select.test.tsx`の既存の方式）。

`src/components/chat/model-select.test.tsx`:

| テスト | tag | 確かめること |
|---|---|---|
| 新規 | `@case:P1` | `status: "loading"`、`value: ""`で、`model-select`が`disabled`で「読み込み中…」を含む |
| 新規 | `@case:X1` | `getByRole("combobox", { name: "モデル" })`が`model-select`と同じ要素（ラベルが`aria-labelledby`で結び付いている） |
| 既存「一覧取得に失敗したら理由と再取得導線を出す」 | `@case:P3`に`@case:X2`を足す | `model-list-error`が`role="alert"`であることを足す |

`src/sample/chat-page.test.tsx`（`useChat`の差し替えと一覧のfetchの差し替えは今の方式）:

| テスト | tag | 確かめること |
|---|---|---|
| 新規 | `@case:P2` | 一覧が2件で`defaultProfile`が2件目のとき、`model-select`が2件目のlabelを出し、`Submit`が押せる |
| 新規 | `@case:P4` | 一覧のfetchが1回目は502、2回目は成功。`model-list-error`が出て`Submit`が押せない。`再取得`を押すと`model-select`が押せ、`model-list-error`が消え、`Submit`が押せる。fetchが2回 |
| 既存「利用不可の profile では送信を止め、理由を先に出す」を拡張 | `@case:P6`、`@case:X2` | `model-guard`が`role="alert"`で文言が`PROFILE_UNAVAILABLE_MESSAGE`。入力欄に「  次の質問  」を打ち、`Submit`のclickとEnterのどちらでも`sendMessage`が呼ばれず、入力欄の値が残る |
| 新規 | `@case:S1` | `messages`が`[user「テストのtierを検索して」, searchedMessage()]`のとき、自分の発話が`role="log"`の中に出て、`sample-response`が1件 |
| 既存「送信は trim 済み本文を 1 回だけ渡す」 | `@case:S2` | 変えない（前後の空白を除いて送る） |
| 新規 | `@case:S2` | 何も打たずに`Submit`、空白だけを打って`Submit`とEnter。どれも`sendMessage`が呼ばれない |
| 新規 | `@case:S3` | `status`が`submitted`と`streaming`のそれぞれで、入力欄が`disabled`で`placeholder`が「生成中…」、`Stop`のボタンがあり`Submit`のボタンが無い |
| 新規 | `@case:S5` | 入力欄に「テストのtierを検索して{Enter}」を打つと、`sendMessage`が`{ text: "テストのtierを検索して" }`で1回呼ばれる |
| 新規 | `@case:S6` | `ready`で「次の質問」を打ってから`status: "streaming"`でrerenderし、`Stop`があることを確かめてから入力欄に`fireEvent.keyDown(..., { key: "Enter" })`。`sendMessage`が呼ばれない |
| 新規 | `@case:S7` | `messages: []`で空の会話の案内（`emptyState`の`title`と`description`）が出る。`[user]`でrerenderすると消える |
| 新規 | `@case:S8` | `reasoning` part（`state: "done"`）と本文のmessageで、`reasoning`が出て、`reasoning-toggle`が`aria-expanded="false"`。押すと`"true"`になりreasoningの本文が出る。もう一度押すと`"false"`に戻り本文が消える |
| 既存「中継が積んだ固定文言はそのまま出す」を拡張 | `@case:E1`、`@case:X2` | 失敗の表示が`role="alert"`で、その中に`再試行`のボタンがあることを足す |
| 新規 | `@case:E3` | `error.message`が`{ error: CHAT_ERROR_MESSAGES[unknown] }`と`{ error: CHAT_ERROR_MESSAGES[unavailable] }`のそれぞれで、失敗の表示が「送信に失敗しました: 」とその文言になり、2つの表示が異なる |
| 新規 | `@case:E4` | `error.message`が`{ error: CHAT_ERROR_MESSAGES[unknown], detail: { message: "サーバ内部の文言" }, request_id: "9b62d3c6-..." }`のとき、失敗の表示はその固定文言で、`サーバ内部の文言`と`9b62d3c6`が画面に無い |
| 既存「承認待ちのあいだは送信ボタンが押せず、…」 | `@case:A7`に`@case:X2`を足す | 変えない（`approval-guard`の`role="alert"`を既に確かめている） |

`src/app/api/chat/route.test.ts`:

| テスト | tag | 変更 |
|---|---|---|
| 「upstream に繋がらないときは 502 を返す」 | `@case:P10` | bodyが`{ error: CHAT_UNREACHABLE_ERROR_MESSAGE }`であることを足す |
| 「upstream のエラーステータスを返し、…」 | `@case:P10` | bodyが`{ error: CHAT_GENERIC_ERROR_MESSAGE }`であることを足す |
| 「未知 profile の 422 と credential 欠落の 503 は、…」 | `@case:E3` | 変えない |
| 「upstream の detail / errors / request_id を body へ写さない」 | `@case:E4` | 変えない |

`src/app/api/chat/profiles/route.test.ts`: 「upstream に繋がらないときは 502 を返す」と「非 2xx は status を
保ったまま固定 body に積み替える」に`@case:P10`を付ける（変更なし）。

### 6. 置き換えで確かめなくなる文言

| 定数 | 今のE2Eでの役割 | 文言を確かめるSmall |
|---|---|---|
| `SEARCH_ANSWER` | 検索のrunの終わりを待つ | fake modelの結論はbackendの`test_sample_fake_model.py` 106行（「「テストの tier」に記載があります。」）。本文partを画面に出すことは`chat-page.test.tsx`「@case:S11 本文と tool 結果を出す」 |
| `SAVED_TEXT` | 承認後の再開の終わりを待つ、承認前に無いことを確かめる | `test_sample_fake_model.py` 124行。承認前に実行されていないことは、E2EではPOSTの本数で確かめる |
| `DENIED_TEXT` | 却下後の再開の終わりを待つ | `test_sample_fake_model.py` 136行 |
| `NEXT_ANSWER` | 次のrunの終わりを待つ | 検索の結論と同じ組み立て（`fake_model.py` 150〜153行）で、106行のテストが確かめる |

どれも既にSmallがあるので、Smallは足さない。

### 7. 台帳

未登録の28件を足し、全43件を#6の表の順（H、P、S、E、A、X。A9はA8の後、E6はE5の後）に並べる。登録済みの
15件の値は変えない。`description`は#6のケース列の文を引用符で囲んでそのまま使う。

## 失敗と安全

- **製品コードを変えない**: 変更するのはテスト（`apps/web/src/**/*.test.ts(x)`、`apps/web/tests/`）と台帳だけ。
  テストのために`data-testid`などの属性を製品に足さない。上の設計は既存の属性だけで書ける
- **既存の不具合が見つかった場合**: 製品コードを変えないとケースを満たせないなら、そのケースは台帳に登録せず、
  テストも残さない（`test.skip` / `test.fixme` / `it.skip`に`@case:`を付けない）。テストと修正を行う別Issueを
  #6の子として起票し（`uv run kaji issue create`）、作業報告にIssue番号と除いたケースを書く。#5の完了条件は
  そのケースを除いて判定する
- **S4が不安定な場合**: 停止の窓は5断片×0.35秒。停止ボタンを押す前にstreamが終わると`requestfailed`が
  来ずに失敗する（黙って成功しない）。3回の`make test-e2e`でこれが起きたら、`FAKE_STREAM_STEP_S`を
  変える前に、測った失敗（回数、trace）を添えてimplementから`BACK`で設計へ戻す。設計で値を決め、変更が
  `apps/api/`に及ぶので`area:backend`を足し、`make verify-backend`（final gateは`make gate-backend`）を
  laneに加える
- **順序と共有データへの依存**: 各テストは`goto`から始め、会話は画面ごとに新しいidになる。DBはテスト専用で、
  テストは他のテストが書いた行を読まない。Mediumのchat idは`randomUUID()`で毎回変える
- **dev overlay**: `role="alert"`と件数は`main`に絞る。Tabの移動は`tabTo`でfocusを確かめながら進める
- **秘密値**: E2E/Mediumは`e2e-fake-openai-key`（非秘密）とfake modelだけを使い、実providerへ接続しない
  （`playwright.config.ts`の今の設定のまま）

## 文書

変更しない。分類、台帳、注釈、Medium/E2Eの置き場所と実行方法は`docs/reference/frontend/testing.md`が既に
決めている（#2）。E2Eで使う文字列の扱い（設計§1）は`sample-chat.spec.ts`の先頭のコメントに書く。

## 実装の順序（slice）

各sliceの終わりで`make verify-frontend`が成功する状態を保つ。台帳に無いidの注釈は突き合わせの失敗になり、
`kinds`の種類が揃わない行も失敗になるので、注釈と台帳の行は、そのケースの全種類のテストが揃うsliceで
一緒に足す。

1. Small（Smallだけのケース）: `model-select.test.tsx`と`chat-page.test.tsx`のP1、P2、P4、P6、S2、S3、S5、
   S6、S7、S8、E1、E4、X1、X2と、`route.test.ts`のE4の注釈。台帳にこの14件を足す
2. E2Eの置き換え: `sample-chat.spec.ts`の既存3本を§2・§3のとおりに書き換え、4つの応答文の定数を消す。
   検索のテストの`@case:S1`と`chat-page.test.tsx`のS1のSmallもここで足す。台帳にA5とS1（`[e2e, small]`）を
   足す
3. E2Eの追加: `keyboard.ts`、`home.spec.ts`、`sample-chat.spec.ts`の新規6本。台帳にH2、H3、P11、S4、S9、E2、
   A8、X3を足す
4. Medium: `chat-relay.spec.ts`と、P10・E3のSmall（`chat-page.test.tsx`のE3、`route.test.ts`と
   `profiles/route.test.ts`のP10・E3の注釈とassertion）。台帳にP9、S10と、P10・E3（`[small, medium]`）を足す
5. 台帳を#6の表の順に並べ直す

## 検証lane

| lane | 要否 | 理由 |
|---|---|---|
| `make verify-frontend` | 必須 | Smallの追加と台帳の突き合わせ（Frontend logicの行） |
| `make test-e2e` | 必須、3回続けて | MediumとE2Eの追加・変更（Frontend/fullstack user flowの行、testing.md「確認するコマンド」）。Issue #5の完了条件で3回続けて成功 |
| `make check-all` | 必須（final） | Issue #5の完了条件 |
| `make verify-backend` / `make gate-backend` | 条件付き | `FAKE_STREAM_STEP_S`を変えた場合だけ（「失敗と安全」） |
| `make test-on-schema-change` | 不要 | schemaとmigrationを変えない |
| `make test-llm` / `make evals` | 不要 | prompt、tool、agent loop、HITLの方針、profile、providerを変えない。fake modelだけを使う |

`make test-e2e`の3回は同じcommitで続けて実行し、3回の結果（exit、件数）を作業報告に書く。lane recordは
commitごとに1件なので、2回目と3回目は`RERAN`（理由: Issue #5の3回連続の要件）として報告する。

製品コードを変えていないことは次で確かめる（出力が空）。

```bash
git -C <worktree> diff --name-only origin/main...HEAD -- apps/web/src apps/api \
  | grep -Ev '\.test\.tsx?$'
```

skipに注釈が無いこと、E2Eが応答文を使っていないことは次で確かめる（どちらも出力が空）。

```bash
grep -rnE '(test|it|describe)\.(skip|fixme)' apps/web/src apps/web/tests
grep -nE 'SEARCH_ANSWER|SAVED_TEXT|DENIED_TEXT|NEXT_ANSWER' apps/web/tests/e2e/ui/sample-chat.spec.ts
```

### 実装前の基準（implement-precheck）

base（`5293d75`）で次を記録する。

- `make verify-frontend`が成功し、突き合わせが15件で通ること
- `uv run python -m scripts.testing.frontend_test_cases --print-map`の出力（置き換え前の対応表）
- `make test-e2e`が成功すること（今のE2E 3本。Mediumは0件）。置き換えの前後で比べる安全網になる

## 完了条件との対応

| Issue #5の完了条件 | 確かめ方 |
|---|---|
| #6の全ケース（別Issueへ切り出したものを除く）が台帳に登録され、突き合わせが成功する | 台帳が43件（切り出しがあればその分を除く）、`make verify-frontend`成功、`--print-map`で全idにテストがある |
| 今のE2Eが文言で状態の変化を確かめていない | 上の`grep`が空。`sample-chat.spec.ts`の`getByText` / `toContainText`は§1の「assertionに使ってよい」ものだけ（レビューで照合） |
| `make check-all`と`make test-e2e`が成功し、`make test-e2e`が3回続けて成功する | lane recordと作業報告の3回の結果 |

## 判断記録

| 判断 | 選んだ方向 | 根拠 | この設計で足した詳細 |
|---|---|---|---|
| 対象のケース | #6の✗と△、P1・P2・S1・A5 | Issue #5`## 対象の契約`、`issue-2-web.md` 219〜235行 | 28件の一覧と各ケースの足りない部分 |
| A7とE5 | 既存の登録を使い、重ねない | Issue #5`## 対象の契約` | — |
| 種類 | #6の表の種類 | Issue #5`## 対象の契約`、#6`## ケース一覧` | 「A / B」を`kinds: [a, b]`に読む（#2のS11・A6と同じ） |
| E2Eは文言を確かめない | 状態はrole、testid、要素の数、URL | Issue #5`## 決定事項`、#6`## 決定事項` | §1の3区分。入力データのechoとtool名、profile idはassertionに使う（前提。A1の既存の確かめ方と同じ。レビューで確認） |
| 置き換えた文言のSmall | 既存のSmallを確認し、無ければ足す | Issue #5`## 決定事項` | 4つともbackendのSmallにあるので足さない（§6） |
| runの終わりの待ち方 | 応答の読み切りと停止ボタンの消滅 | 前提（two-way door）。`prompt-input.tsx` 1226〜1256行 | `runToEnd` |
| 結論が出たことの確認 | `sample-response`の直下の要素の合計 | 前提（two-way door）。`response.tsx` 411〜475行 | 承認の再開がカードを分けても同じ数になる |
| S4の停止 | fake modelの`TRIGGER_SLOW`を使う | Issue #5`## 決定事項` | 中断は`requestfailed`で確かめる。不安定なら設計へ戻して定数を決める |
| S9の自動スクロール | E2E | #6`## ケース一覧` | viewportを低くし、`MutationObserver`で伸びを、scroll要素で下端を確かめる（前提。レビューで確認） |
| A8 | 会話が空になり、書き込みが実行されない | Issue #5`## 決定事項`、#6`## 決定事項` | 再開のPOSTが無いこと、次の送信が前の会話を運ばないことで確かめる |
| Mediumの置き場所 | `tests/e2e/request/`、`request` fixture | Issue #5`## 決定事項`、testing.md | 4本の中身 |
| E3の503 | Mediumでは確かめない | 前提。`playwright.config.ts`の`OPENAI_API_KEY`、`llm_profiles.py`（どのprofileも503にならない。設定を変えるとA6などのLunaが使えない） | 503はSmallとbackendのテストが持つ |
| P10の「止まっている」 | Mediumでは確かめない | 前提。Mediumは起動中のFastAPIを使う | Smallの502のテストにbodyのassertionを足す |
| 製品を変える必要が出た場合 | ケースを外し、#6の子Issueを起票 | Issue #5`## 決定事項` | 起票の手段と報告の内容 |
| `FAKE_STREAM_STEP_S` | 不安定な場合に限り調整してよい | Issue #5`## 決定事項` | 変える前に設計へ戻し、`area:backend`とbackendのlaneを足す |
| 時間の上限 | `playwright.config.ts`だけ | Issue #5`## 不安定さへの対策`、testing.md | `setTimeout`、`waitForTimeout`、`timeout`指定を使わない |
| 文書 | 変更しない | testing.mdが既に規約を持つ（#2） | spec fileの先頭のコメント |

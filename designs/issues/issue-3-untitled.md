# Issue #3 承認待ちのあいだは送信を止める

- Issue: #3（親Epic: #6、依存: #2（CLOSED、main `a603d8e`でマージ済み）、後続: #5）
- type: `type:feature`、area: `area:frontend`
- base: `origin/main` `a603d8e9f27a308d1294787de320e87f4b09f0e0`

## 目的と範囲外

利用者から見た結果（feature rubric）:

- 最後のassistant messageが承認待ちのあいだは新しい発話を送れず、承認か却下を選ぶまで会話が先へ進まない（A7）
- 送れない理由が固定文言で見え、打った文は消えない
- 承認・却下のボタンは、押して効くところ（最後のassistant messageの承認待ちpart）にだけ出る
- 承認待ちのあいだに再読み込みしたときの今の挙動が`docs/architecture.md`の「HITL」に仕様として書かれている（A8）

範囲外（Issue #3の`## 範囲外`と決定事項）:

- backend（`apps/api/`）の変更。HITLの停止と再開のprotocol、`mutates`による承認要否、runの記録は変えない
- 放棄された承認待ちを記録で区別すること、会話の保存と復元
- A8のE2E（承認待ちで再読み込みすると会話が空になり、書き込みが実行されないこと）。#5の決定事項
  「再読み込み（A8）のE2Eは…確かめる」が担う。#3はA8を文書にするだけで、挙動は変えない
- モデル選択欄の操作可否。承認待ちのあいだも今までどおり選べる（既存E2E「一時メモは承認前に止まり…」が
  承認待ち中に選択を変えることに依存している）
- 生成中の挙動（停止ボタン、入力欄の`disabled`、`send()`の生成中guard）

## 根拠にした一次情報

- Issue #3本文の`## 今の挙動`、`## 決定事項`（A7、A8）、`## 範囲外`、`## 完了条件`。readiness review（PASS）
- Issue #6の`## 決定事項`（A7、A8、文言や状態ごとの表示はSmallで確かめる）と`## ケース一覧`
  （A7: 状態 / Small / ✗、A8: 画面遷移 / E2E / ✗、X2: 送信を止める理由は`role="alert"`）
- Issue #5の`## 決定事項`（A7は#3のテストを使う、A8のE2Eは#5）
- `apps/web/src/components/chat/chat-shell.tsx`（`submitDisabled = !isGenerating && !canSubmit`、
  `model-guard`の`role="alert"`、`onSubmit`内の最後の歯止め）
- `apps/web/src/components/chat/use-chat-session.ts`（`sendAutomaticallyWhen:
  lastAssistantMessageIsCompleteWithApprovalResponses`、`send()`の生成中guard、`streamingMessageId`）
- `apps/web/src/components/chat/tool-approval.tsx`（`ToolApproval`、`pendingApprovalId(part)`）
- `apps/web/src/sample/response.tsx`（承認待ちのpartなら、どのmessageでも`ToolApproval`を出す）、
  `apps/web/src/sample/chat-page.tsx`
- `apps/web/src/components/ai-elements/prompt-input.tsx` 855〜860行（`onSubmit`の前に`form.reset()`）、
  985〜996行（Enterは`button[type="submit"]`が`disabled`なら`requestSubmit()`しない）
- `ai@7.0.66` `src/ui/chat.ts` 496〜545行（`addToolApprovalResponse`は`messages[length - 1]`だけを書き換える）、
  `src/ui/last-assistant-message-is-complete-with-approval-responses.ts`（最後のmessageがassistantで、
  その最後のstepのtool partがすべて応答済みのときだけ自動再送する。tool partの判定は`isToolUIPart`）
- `apps/api/agent/persistence.py` `complete_run`（承認待ちで止まったrunは`awaiting_approval`で記録）、
  `apps/api/agent/router.py` `resolve_client_chat_id`（chat idは相関用の記録で、履歴を読み出す経路は無い）
- `docs/architecture.md`「HITL」「永続化」「サンプルと共通部分の境界」（HITLの停止と再開、chatの画面部品は共通部分）
- `docs/reference/frontend/coding.md`「AI SDK」、`docs/reference/frontend/design-system.md`「状態の表示」、
  `docs/reference/frontend/testing.md`（台帳と注釈の規約）、`docs/dev/llm-evals.md`「変更目的とIssueの完了条件」
- `apps/web/tests/coverage/frontend-test-cases.yml`（現在11件、A7・A9は無い）
- 設計時の測定（base SHAのworktree）: `cd apps/web && npx vitest list --tagsFilter=small --json`は51件

## 設計

### 1. 承認待ちの判定（共通部分）

**定義**: `messages`の最後の要素が`role === "assistant"`で、その`parts`に`isToolUIPart(part) &&
part.state === "approval-requested"`のpartが1つ以上あるとき、その最後のmessageを「承認待ちのmessage」とする。

- 「最後のassistant message」を「`messages`の最後の要素で、かつassistantのもの」と読む。AI SDKの
  `addToolApprovalResponse`は`messages[length - 1]`しか書き換えず、自動再送の判定も同じmessageを見るため、
  承認・却下が効くのはこのmessageだけである。最後がuser messageなら承認待ちのmessageは無い
  （判断記録の仮定1）
- partは`isToolUIPart`（静的toolと`dynamic-tool`の両方）で判定し、AI SDKの自動再送の判定と対象を揃える。
  1つのmessageに承認待ちが複数あれば、すべてに応答するまで承認待ちが続く（自動再送の条件と一致）
- **判定の対象と操作できる対象を一致させる**。送信を止めるpart（静的toolと`dynamic-tool`）には、必ず
  承認・却下のボタンを出す（§3）。送信だけが止まり、押せるボタンが無い状態を作らない

実装:

- `apps/web/src/components/chat/tool-approval.tsx`に純関数を足す。

  ```ts
  /** 最後の message が承認待ちの tool part を持つ assistant message なら、その id を返す。 */
  export function findPendingApprovalMessageId(
    messages: readonly UIMessage[],
  ): string | undefined;
  ```

  HITLのfrontendでの局所化はこのfile（file先頭のコメント）なので、判定もここに置く
- `apps/web/src/components/chat/use-chat-session.ts`の`ChatSession`に2つ足す。

  | field | 型 | 値 |
  |---|---|---|
  | `pendingApprovalMessageId` | `string \| undefined` | `findPendingApprovalMessageId(messages)`。承認・却下のボタンを出すmessageの判定に使う |
  | `awaitingApproval` | `boolean` | `!isGenerating && pendingApprovalMessageId !== undefined`。送信を止める判定に使う |

  `awaitingApproval`が生成中を除くのは、承認要求のpartがstreamの終わる前に届くため。生成中は停止ボタン・
  入力欄の`disabled`・`send()`の生成中guardが既に送信を止めており、理由の表示が一瞬出てから消えるのを避ける
- `send()`は`isGenerating`に加えて`awaitingApproval`でも`undefined`を返す（form到達時の最後の歯止め。
  利用者の入力の保護は§2の`disabled`が持つ）

### 2. 送信の停止と理由の表示（`ChatShell`）

`ChatShellProps`に必須のprop `awaitingApproval: boolean`（「承認待ちで送信を止める」）を足す。必須にするのは、
用途の画面を置き換えても渡し忘れを型検査で止めるため。

- `submitDisabled = !isGenerating && (!canSubmit || awaitingApproval)`。送信ボタンが`disabled`なので、
  clickもEnterもformへ届かず（`prompt-input.tsx` 985〜996行）、`form.reset()`が走らないため入力欄の文は残る。
  既存のprofile guardと同じ仕組みで、入力欄（textarea）は`disabled`にしない
- `PromptInput`の`onSubmit`の最後の歯止めを`if (!canSubmit || awaitingApproval) return;`にする
- 理由の表示: `awaitingApproval`のとき、`model-guard`の直後（入力欄の上、送信失敗の表示の前）に次を出す。

  ```tsx
  <div
    className="rounded-md bg-muted px-3 py-2 text-foreground text-sm"
    data-testid="approval-guard"
    role="alert"
  >
    {APPROVAL_PENDING_MESSAGE}
  </div>
  ```

  - 文言は`APPROVAL_PENDING_MESSAGE = "承認か却下を選んでください。"`（Issue #3の例をそのまま採る）。
    定数は`tool-approval.tsx`に置いてexportする
  - 場所を入力欄の上にするのは、利用者が送ろうとした位置で理由が読め、既存の「押せない理由」
    （`model-guard`）と同じ場所に揃うため
  - `role="alert"`はIssue #6のX2（送信を止める理由は`role="alert"`で読み上げる）と`design-system.md`
    「状態の表示」に従う。失敗ではないので`destructive`の色は使わず、tokenの`bg-muted`と`text-foreground`
    （既存tokenの組み合わせで、contrastは本文と同等。tokenは追加・変更しない）にする。14px（`text-sm`）
  - `model-guard`と同時に成り立つ場合は両方を出す（利用不可のprofileでは送信自体が起きないので、
    実際には同時に出ない）
- `ChatShell`のfile先頭と`submitDisabled`・`onSubmit`のコメントに、承認待ちでも同じ仕組みで入力を守ることを足す
  （経緯やIssue番号は書かない）

### 3. 承認・却下のボタンを出す場所（`SampleResponse`）

- `SampleResponseProps`に必須のprop `acceptsApproval: boolean`（このmessageが承認待ちのmessageか）を足す
- **`dynamic-tool`も描く**。今の`isToolUIPart(part) && part.type !== "dynamic-tool"`の除外を外し、
  `isToolUIPart(part)`のpartをすべて`Tool`で描く。生成物の`ToolHeader`は`dynamic-tool`を受け付ける
  （`tool.tsx` 34〜43行、`type === "dynamic-tool"`なら`toolName`を名前に使う）ので、`dynamic-tool`のときは
  `toolName={part.toolName}`を渡す。`ToolInput` / `ToolOutput`の型は`ToolUIPart | DynamicToolUIPart`
  （同32行の`ToolPart`）で、変更なしに渡せる。生成物は編集しない
- `tool-approval.tsx`の`pendingApprovalId(part)`の引数を`ToolUIPart | DynamicToolUIPart`に広げる。
  AI SDKの型（`ui-messages.ts` 431〜443行）で、`dynamic-tool`も`approval-requested`のとき`approval.id`を持つ
- `ToolApproval`は`approvalId && acceptsApproval`のときだけ出す。`ToolHeader`、`ToolInput`、`ToolOutput`は
  今までどおりどのmessageでも出す（古いpartの状態ラベルは生成物の`ToolHeader`が文字で出す）
- `apps/web/src/sample/chat-page.tsx`は次のように配線する。

  ```tsx
  awaitingApproval={session.awaitingApproval}
  renderAssistant={(message) => (
    <SampleResponse
      acceptsApproval={message.id === session.pendingApprovalMessageId}
      message={message}
      onToolApprovalResponse={session.respondToApproval}
    />
  )}
  ```

  file先頭のコメント「送信 guard も profile の状態だけに依存する」を、profileと承認待ちの2つに直す
- 生成中（`streaming`）に承認要求のpartが届いた時点でボタンを出すのは今までどおり
  （`pendingApprovalMessageId`は生成中も値を持つ）。変えるのは古いmessageに出さないことだけ

### 4. 状態の遷移

| 状態 | 送信ボタン | Enter | 入力欄 | 理由 | 承認・却下のボタン |
|---|---|---|---|---|---|
| 承認要求のstreamの途中（`streaming`） | 停止ボタン | 送らない（既存） | `disabled`（既存） | 出さない | 最後のmessageの承認待ちpartに出る |
| 承認待ち（streamは終了、`ready`） | `disabled` | 送らない | 打てる。文は残る | `approval-guard` | 最後のmessageの承認待ちpartにだけ出る |
| 承認・却下を押した直後（`submitted` / `streaming`） | 停止ボタン | 送らない（既存） | `disabled`（既存。打った文は残る） | 出さない | 出ない（partは`approval-responded`） |
| 再開のrunが終わった後（`ready`） | 押せる（profileが送信可能なら） | 送る | 打てる | 出さない | 出ない |

承認・却下の後に送信できる状態へ戻る経路は、AI SDKがpartを`approval-responded`へ書き換え、
`sendAutomaticallyWhen`の再送が終わることだけで、画面側で状態を持たない（`useState`を足さない）。

### 5. 失敗と安全

- backendは変わらないので、承認前に書き込みtoolが実行されない保証（`mutates=True`）は従来どおり
- 変更はすべてclient側の表示と送信の抑止で、requestの形は変えない。承認待ちの判定を誤って`true`に
  したままになると送信できなくなるが、判定はAI SDKの`messages`だけから導く純関数で、承認・却下で
  partが`approval-responded`へ変わると必ず`false`になる（§6のテストで確かめる）
- 送信を止める判定（§1、`isToolUIPart`）と、ボタンを出すpart（§3、`isToolUIPart`）は同じ集合にする。
  `dynamic-tool`の承認待ちでも承認・却下のボタンが出るので、送信だけが止まって会話が進めなくなる状態は
  無い。今のbackendのtoolは静的（`tool-save_note`）だが、AI SDKの型が`dynamic-tool`の承認待ちを許すので
  共通の判定に合わせて描く（§6のA7・A9のテストで確かめる）
- 互換性: `ChatShellProps.awaitingApproval`、`SampleResponseProps.acceptsApproval`、
  `ChatSession.pendingApprovalMessageId` / `awaitingApproval`は追加だけ。repository内の利用者は
  `sample/chat-page.tsx`だけで、必須propの追加は型検査が渡し忘れを検出する
- rollback: `git revert`で戻る。migration、設定、依存、secretに触れない

## 文書

| 文書 | 変更 |
|---|---|
| `docs/architecture.md`「HITL」 | 番号付きの流れの後に「承認待ちのあいだの送信」と「承認待ちのあいだの再読み込み」を足す（下） |
| `docs/reference/frontend/coding.md`「AI SDK」 | 承認待ちの判定は`tool-approval.tsx`の`findPendingApprovalMessageId`、送信の停止は`ChatShell`の`awaitingApproval`、承認・却下のボタンは`useChatSession`の`pendingApprovalMessageId`と一致するmessageにだけ出す、の1項目を足す |

`docs/architecture.md`に足す内容（A7とA8。文は実装時に整える）:

- 承認待ちのあいだの送信: 最後のmessageが承認待ちのtoolを持つassistant messageのあいだ、画面は送信を止める。
  送信ボタンは押せず、Enterでも送らない。入力欄には打てて、打った文は残る。理由は固定文言
  「承認か却下を選んでください。」で入力欄の上に出す。承認・却下のボタンはその最後のmessageの
  承認待ちのtoolにだけ出す。承認または却下で再開のrunが終わると送信できる状態に戻る。backendは
  この停止に関与しない
- 承認待ちのあいだの再読み込み: 会話は画面から消える。クライアントは会話を保存せず、サーバーは会話とrunを
  記録するが、記録から会話を画面へ戻す経路は無い。承認待ちの書き込みは実行されない。runの記録は
  `awaiting_approval`のまま残り、放棄された承認待ちと応答を待っている承認待ちは記録の上で区別しない

`testing.md`、`test-policy.md`、`test-execution-matrix.md`、`use-template.md`は変えない（分類・lane・手順は
変わらず、台帳への登録は既存の規約どおり）。

## テスト

### 台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）

| id | feature | category | description | kinds |
|---|---|---|---|---|
| A7 | approval | 状態 | 承認待ちのあいだは送信できず、理由が出る | small |
| A9 | approval | 状態 | 承認・却下のボタンは最後のassistant messageの承認待ちpartにだけ出る | small |

- A7の`description`は#6のケース列の文をそのまま使う（#2の規約）
- A9は#6の一覧に無い新しいid。Issue #3の完了条件「承認・却下のボタンが最後のassistant messageにだけ出る」は
  A7の文に含まれないので、別のケースにする（判断記録の仮定2）。#6のケース一覧への追記は人が判断する
  （作業報告で知らせる）

### Small（Vitest、`describe`に`tags: ["small"]`）

`apps/web/src/sample/chat-page.test.tsx`（`useChat`を差し替える既存の方式。`mockChat`を呼び直してから
`rerender(<ChatPage />)`すると、次のrenderから新しい`messages` / `status`が効く）:

| テスト名 | 入力 | 期待 |
|---|---|---|
| `@case:A7 承認待ちのあいだは送信ボタンが押せず、Enter でも送らず、打った文と理由が残る` | `messages: [approvalPendingMessage()]`、`status: "ready"` | Submitが`disabled`。`approval-guard`が`role="alert"`で`承認か却下を選んでください。`。textboxに打って`{Enter}`を押しても`sendMessage`は0回、textboxの値は打った文のまま |
| `@case:A7 承認すると送信できる状態に戻り、打った文は残る` | 上の状態で打った後、最後のpartを`output-available`にした`messages`と`status: "ready"`で`rerender` | Submitが押せ、`approval-guard`が無く、textboxの値は残り、Submitで`sendMessage`が1回（trim済み本文） |
| `@case:A7 却下すると送信できる状態に戻る` | 同様に`output-denied`で`rerender` | Submitが押せ、`approval-guard`が無い |
| `承認要求の stream の途中は理由を出さず、停止できる` | `messages: [approvalPendingMessage()]`、`status: "streaming"` | `approval-guard`が無く、停止ボタン（`Stop`）が押せる |
| `@case:A9 承認・却下のボタンは最後の assistant message の承認待ち part にだけ出る` | `[承認待ち(a-old, approval-old), user, 承認待ち(a-new, approval-new)]` | `tool-approval`がちょうど1件。「承認」で`addToolApprovalResponse`が`{ id: "approval-new", approved: true }`で1回 |
| `@case:A9 最後の message が承認待ちでなければ、古い承認待ち part にボタンを出さない` | `[承認待ち(a-old), user, 本文だけのassistant]` | `tool-approval`が0件、`tool-header`は出る、Submitが押せる |
| `@case:A7 @case:A9 dynamic tool の承認待ちでも承認・却下のボタンが出て、送信は止まる` | 最後のmessageが`type: "dynamic-tool"`、`toolName: "save_note"`、`approval-requested`（approval id `approval-dyn`）、`status: "ready"` | `tool-header`に`save_note`、`tool-approval`が1件、Submitが`disabled`で`approval-guard`が出る。「却下」で`addToolApprovalResponse`が`{ id: "approval-dyn", approved: false }`で1回 |

- 既存の`@case:A2`、`@case:A3`のテストは最後のmessageが承認待ちなので、変えずに成功する
- file先頭のコメントの「3. 送信 guard は profile の状態だけに依存する」を、profileと承認待ちに直す
- messageを組み立てるhelper（承認待ちのid・approval idを引数に取る形）は既存の`approvalPendingMessage()`を
  拡張する。既存テストの本文は変えない

`apps/web/src/components/chat/tool-approval.test.tsx`（注釈なしの補助テスト）:

| テスト名 | 期待 |
|---|---|
| `最後の message が承認待ちの assistant message のときだけ、その id を返す` | 最後がassistantで承認待ちpartあり → id。最後がuser → `undefined`。最後がassistantで承認待ちなし → `undefined`。承認待ちは前のmessageにだけある → `undefined`。空の配列 → `undefined` |
| `承認待ちが複数あれば、すべてに応答するまで id を返す` | 2つのうち1つが`approval-responded`、もう1つが`approval-requested` → id |
| `dynamic tool の承認待ちも判定し、承認 id を返す` | 最後のassistantに`dynamic-tool`の`approval-requested` → `findPendingApprovalMessageId`がid、`pendingApprovalId`が承認id |

### E2E

足さない。A7はIssue #6でSmall、A8のE2Eは#5が担う。既存のPlaywright 3本（`tests/e2e/ui/sample-chat.spec.ts`）は
承認待ちのあいだに送信しないので、変えずに成功する（`make test-e2e`で確かめる）。

## 実装の順序（slice）

1. `tool-approval.tsx`の`findPendingApprovalMessageId`、`APPROVAL_PENDING_MESSAGE`、`pendingApprovalId`の引数の拡張、その補助テスト
2. `use-chat-session.ts`の`pendingApprovalMessageId` / `awaitingApproval`と`send()`のguard
3. `chat-shell.tsx`の`awaitingApproval`、`response.tsx`の`acceptsApproval`、`chat-page.tsx`の配線
4. `chat-page.test.tsx`のA7・A9のテストと台帳への登録
5. `docs/architecture.md`と`docs/reference/frontend/coding.md`

## 検証lane

LLMへの影響の分類（`docs/dev/llm-evals.md`「変更目的とIssueの完了条件」）: **LLM経路に影響しない変更**。
backend、prompt、tool schema、agent loop、承認要否の規則（`mutates`）、modelとproviderは変えない。
画面が承認待ちのあいだの送信を止めるだけで、通常の送信・承認・却下で送るrequestの形は変わらない。
品質・観測のevalの閾値は無い（acceptanceもobservationも設定しない）。

| lane | 要否 | 理由 |
|---|---|---|
| `make verify-frontend` | 必須 | webのlogic・component・Small test・台帳の変更 |
| `make verify-docs` | 必須 | `docs/architecture.md`、`docs/reference/frontend/coding.md`、設計文書の変更（`check-all`に含まれる） |
| `make check-all` | 必須（最終） | Issue #3の完了条件 |
| `make test-e2e` | 必須 | 画面の送信の流れ（frontend user flow）の変更と、Issue #3の完了条件。既存3本の回帰 |
| `make verify-backend` / `make gate-backend` | 追加不要 | Pythonを変えない（`check-all`が`gate-backend`を含む） |
| `make test-on-schema-change` | 追加不要 | schemaを変えない（`check-all`に含まれる分で足りる） |
| `make test-llm`、`make evals` | 不要 | 上の分類のとおりLLM経路に影響しない。HITLの方針（どのtoolを止めるか、停止と再開のprotocol）は変えず、画面の送信の抑止だけを足す |

### 実装前の基準（implement-precheck）

base SHAで次を測り、実装後と比べる。

- `cd apps/web && npx vitest list --tagsFilter=small --json`の件数（設計時51件）。実装後は51 + 追加分
  （chat-page 7件、tool-approval 3件で61件）
- `uv run python -m scripts.testing.frontend_test_cases`が成功し、台帳が11件であること。実装後は13件で成功
- safety net: `make verify-frontend`と`make test-e2e`がbase SHAで成功すること

## 完了条件との対応

| Issue #3の完了条件 | 満たし方 |
|---|---|
| 承認待ちのあいだは送信ボタンが押せず、Enterでも送られず、入力した文が残り、理由が表示される（Small） | §1、§2。`@case:A7`の1本目と、dynamic toolの承認待ちのテスト |
| 承認または却下をすると、送信できる状態に戻る（Small） | §4。`@case:A7`の2本目・3本目 |
| 承認・却下のボタンが最後のassistant messageにだけ出る（Small） | §3。`@case:A9`の3本（dynamic toolを含む） |
| 追加したケースを台帳に登録し、テストに注釈を付けている | 台帳のA7・A9と注釈 |
| `docs/architecture.md`の「HITL」にA7とA8の仕様が書かれている | 文書 |
| `make check-all`と`make test-e2e`が成功する | 検証lane |

## 判断記録

| 判断 | 選んだ方向 | 根拠・仮定 | 設計で加えた詳細 |
|---|---|---|---|
| 承認待ちの送信 | 送信ボタンを`disabled`、Enterでも送らない、入力欄は打てて文は残る、理由は固定文言 | Issue #3 決定事項A7、#6 決定事項A7 | 既存のprofile guardと同じ`disabled`の仕組み（§2） |
| 理由の文言 | `承認か却下を選んでください。` | Issue #3が「文言と表示場所は設計で決める」とし、例に挙げた文をそのまま採る（二方向） | 定数`APPROVAL_PENDING_MESSAGE`を`tool-approval.tsx`に置く |
| 理由の表示場所と見た目 | 入力欄の上、`model-guard`の直後。`role="alert"`、`bg-muted` / `text-foreground` | Issue #3（設計で決める）、#6のX2、`design-system.md`「状態の表示」。失敗ではないので`destructive`を使わない（二方向） | `data-testid="approval-guard"` |
| ボタンを出す場所 | 最後のassistant messageの承認待ちpartだけ | Issue #3 決定事項A7、AI SDK `chat.ts` 496〜545行 | `SampleResponse`の必須prop `acceptsApproval` |
| 判定と操作の対象の一致（review-design cycle 1 所見1） | `dynamic-tool`も`SampleResponse`で描き、承認待ちなら承認・却下のボタンを出す | Issue #3 決定事項A7（承認か却下を選ぶまで進まない＝選べる必要がある）、AI SDK `ui-messages.ts` 431〜443行、生成物`tool.tsx`の`dynamic-tool`対応 | `pendingApprovalId`の引数を広げる、`toolName`を渡す、Smallの回帰ケース |
| backend | 変えない | Issue #3 決定事項A7「backendは変更しない」 | — |
| 再読み込みの仕様 | 今の挙動（会話は消える、書き込みは実行されない、runは`awaiting_approval`のまま、区別しない）を文書にする | Issue #3 決定事項A8、#6 決定事項A8 | 「サーバーは会話とrunを記録するが画面へ戻す経路は無い」と正確に書く（`router.py` `resolve_client_chat_id`） |
| 判定と所有の置き場所 | 判定は`tool-approval.tsx`、状態は`useChatSession`、表示と送信の停止は`ChatShell` | `docs/architecture.md`「サンプルと共通部分の境界」（HITLとchatの画面部品は共通部分）、`coding.md`「AI SDK」 | 必須propにして用途の画面の置き換えでの渡し忘れを型検査で止める |
| 仮定1: 「最後のassistant message」の読み方 | `messages`の最後の要素がassistantのときだけ承認待ちのmessageとする | 仮定（二方向）。AI SDKが書き換えるのは`messages[length - 1]`だけで、最後がuserのときに古い承認待ちで送信を止めると、効かないボタンしか残らず会話が進めなくなるため。設計レビューで確認する | 最後がuserなら送信は止めず、ボタンも出さない |
| 仮定2: ボタンの場所のケースid | 新しいid `A9`（状態、small）を台帳に登録する | 仮定（二方向）。#6のA7の文は送信の停止だけを指し、Issue #3の完了条件のボタンの場所を含まない。台帳のidは`^[A-Z]+[0-9]+$`で#6にないidも登録できる。設計レビューで確認する | #6の一覧への追記は人の判断として作業報告で知らせる |
| 仮定3: 生成中の理由の表示 | 生成中は`approval-guard`を出さない | 仮定（二方向）。承認要求のpartはstreamの終わる前に届き、生成中は既存の仕組みが送信を止めているため。設計レビューで確認する | `awaitingApproval = !isGenerating && ...` |
| A8のE2E | #3では書かない | Issue #5 決定事項（A8のE2Eは#5）、Issue #3の完了条件にA8のテストが無い | — |
| 検証lane | `verify-frontend`、`verify-docs`、`check-all`、`test-e2e`。LLM・evalは不要 | `verification-matrix.md`、`llm-evals.md`（LLM経路に影響しない変更）、Issue #3の完了条件 | 実装前の基準（Small件数、台帳件数、safety net） |

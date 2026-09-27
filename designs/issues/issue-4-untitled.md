# Issue #4 応答の途中で接続が切れたときの表示を固定文言にする

- Issue: #4（親Epic: #6、依存: #2（CLOSED）、#3（CLOSED、main `8390f18`でマージ済み）、後続: #5）
- type: `type:bug`、area: `area:frontend`
- base: `origin/main` `8390f18ce6cc8f398f4b9a98e67aa20780010abb`

## 目的と範囲外

直すこと（bug rubric）:

- 中継が積んだ固定文言として読めない失敗（streamの途中の切断、browserの通信エラーなど）では、browserが出す
  エラー文を画面に出さず、1つの固定文言「応答を受け取れませんでした。」を出す（E5）
- 途中まで出た応答は画面に残し、再試行のボタンは今のまま出す
- 中継が積んだ固定文言は、これまでどおりその文言を出す
- 承認または却下をしたら、失敗の表示を消す

範囲外（Issue #4の`## 範囲外`）:

- 切断からの復旧、自動の再送。中継（`chat-relay.ts`）にstreamの途中の失敗を扱う仕組みを足さない
- 承認の後に切れたとき、再試行で同じ書き込みが2回走るのを防ぐこと
- runの記録が`running`のまま残ること（`docs/architecture.md`「永続化」の意図どおりの挙動）
- backend（`apps/api/`）、AI SDKの呼び方（transport、`sendAutomaticallyWhen`）、再試行の挙動の変更
- #6の他のケース（E1〜E4など）の台帳登録。#5が担う

## 再現と実際の挙動

| 手順 | 実際 | 期待 |
|---|---|---|
| `/chat`で送信し、応答が流れている途中でFastAPIを止める（networkを切る） | 「送信に失敗しました: 」の後に、browserのエラー文（例：`network error`）がそのまま出る。文言はbrowserごとに違う | 「送信に失敗しました: 応答を受け取れませんでした。」と再試行のボタン。途中までの応答は残る |
| 承認待ちの直後に切れ、承認・却下を押す | 失敗の表示が残ることがある | 押した時点で失敗の表示が消える |

## 根拠にした一次情報

- Issue #4本文の`## 再現`、`## 原因`、`## 決定事項`、`## 範囲外`、`## 完了条件`。readiness review（PASS）
- Issue #6の`## 決定事項`（E5：browserのエラー文を出さず固定文言にする。復旧の仕組みは作らない。文言や状態ごとの
  表示はSmallで確かめる）と`## ケース一覧`（E5: APIエラー / Small / ✗、X2: 失敗の表示は`role="alert"`）
- Issue #5の`## 対象の契約`（E5は#4で追加したテストを使う）と`## 範囲外`（E5の振る舞いの変更は#4）
- `apps/web/src/lib/chat-profiles.ts` 152〜174行（`describeChatError`はJSONとして読めないmessage、record以外、
  `error`が空または文字列以外のとき、受け取ったmessageをそのまま返す）
- `apps/web/src/lib/chat-relay.ts` 43〜98行（streamが始まる前の失敗だけを`{ error: <固定文言> }`に積み替え、
  始まった後は`upstream.body`を素通しする）
- `apps/web/src/components/chat/chat-shell.tsx` 218〜233行（`送信に失敗しました: {describeChatError(error.message)}`、
  `role="alert"`、再試行のボタン）
- `apps/web/src/components/chat/use-chat-session.ts` 144〜162行（`retry`は`clearError()`の後に`regenerate()`、
  `respondToApproval: addToolApprovalResponse`で失敗の表示に触らない）
- `ai@7.0.66` `src/ui/chat.ts`
  - 306〜317行 `setStatus`、487〜493行 `clearError`（`error`状態のときだけ`error`を消し、`ready`にする）
  - 496〜545行 `addToolApprovalResponse`（partを`approval-responded`にし、`sendAutomaticallyWhen`が真のときだけ
    再開のrequestを起こす。`error`は触らない）
  - 712行（requestの開始で`error`を消す）、826〜853行（streamの読み取りの失敗を`error`にする。
    messagesの途中までの応答は消さない）
- `ai@7.0.66` `src/ui/process-ui-message-stream.ts` 922〜925行（streamの`error` chunkは`new Error(errorText)`）、
  `pydantic_ai/ui/vercel_ai/_event_stream.py` 190行（agentの例外は`ErrorChunk(error_text=str(error))`）
- `docs/reference/error-handling-and-logging.md`「streamの途中のエラー」「webでのエラーの表示」、
  `docs/reference/frontend/coding.md`「APIへの中継」「AI SDK」、`docs/reference/frontend/testing.md`（台帳と注釈）
- `apps/web/tests/coverage/frontend-test-cases.yml`（現在13件。E5は無い）
- 設計時の測定（base SHAのworktree）
  - `cd apps/web && npx vitest list --tagsFilter=small --json`は61件
  - `uv run python -m scripts.testing.frontend_test_cases`は成功（13ケース、注釈付きテスト21件）
  - 実`@ai-sdk/react`の`Chat`に偽のtransportをつないだprobe（scratchpad、repositoryには置かない）:
    1. `tool-approval-request`の直後にstreamを`TypeError("network error")`で切る → `status: "error"`、
       `error.message: "network error"`、partは`approval-requested`のまま残る
    2. 1の後に承認 → 再開のrequestが始まり、AI SDKが`error`を消した
    3. 同じ切断で、同じstepに実行前の別のtool part（`input-available`）が残っている → 承認しても再開の
       requestは起きず、`status: "error"`と`error.message: "network error"`が残った

## 原因（壊れている境界）

1. **表示の境界**: `describeChatError`は「中継の固定文言を取り出す」関数だが、取り出せないときに受け取った
   messageをそのまま返す。streamが始まった後の失敗（browserのbody読み取りの失敗、agentの`error` part）は中継を
   通らないので、browserやagentの文言がそのまま画面へ出る
2. **承認応答の境界**: `respondToApproval`は`addToolApprovalResponse`をそのまま渡しており、失敗の表示に触らない。
   AI SDKが`error`を消すのは再開のrequestが始まったときだけで、再開の条件（最後のstepのtool partがすべて応答済み）を
   満たさないと失敗の表示が残る（probe 3）

中継に仕組みを足すと「復旧の仕組みは作らない」（Issue #4・#6）に反し、streamの途中の失敗はHTTPのstatusで返せない
（`error-handling-and-logging.md`）。直すのは上の2つの境界だけにする。

## 設計

### 1. 読めない失敗の固定文言（`chat-profiles.ts`）

- 固定文言の節に定数を足す。

  ```ts
  /**
   * 中継が積んだ固定文言として読めない失敗に出す固定文言。
   *
   * stream の途中の切断や agent の `error` part は中継を通らないので、browser や
   * agent の文言がそのまま `Error.message` に入る。**それを画面に出さない。**
   */
  export const CHAT_UNREADABLE_ERROR_MESSAGE = "応答を受け取れませんでした。";
  ```

- `describeChatError(message)`の、中継の固定文言を取り出せない3つの分岐（`JSON.parse`の失敗、record以外、
  `error`が空または文字列以外）は、受け取った`message`ではなく`CHAT_UNREADABLE_ERROR_MESSAGE`を返す。
  取り出せる分岐（recordで`error`が空でない文字列）は変えない
- JSDocの「読めなければ受け取った message をそのまま返す」を「読めなければ固定文言を返す。browser の
  エラー文を画面に出さない」に直す
- 文言は1つだけにする。切断・browserの通信エラー・agentの`error` part・中継を通らない非2xx（Next.js自身の
  エラーページなど）を区別しない（Issue #4 決定事項「1つの固定文言にする」）

結果として、`ChatShell`の表示は次のようになる（`chat-shell.tsx`は、描画の直前のコメントを「読めなければ
固定文言」に直すだけで、描画は変えない）。

| `error.message` | 表示 |
|---|---|
| `{"error":"chat backend is unreachable"}`など中継の固定文言 | `送信に失敗しました: chat backend is unreachable`（従来どおり） |
| `network error`、`Failed to fetch`、`terminated`など | `送信に失敗しました: 応答を受け取れませんでした。` |
| agentの`error` partの`errorText`（`str(exc)`） | `送信に失敗しました: 応答を受け取れませんでした。` |
| `{}`、`{"error":""}`、`{"error":42}`、`[1]`、`null` | `送信に失敗しました: 応答を受け取れませんでした。` |

- 前置きの「送信に失敗しました: 」、`role="alert"`、再試行のボタン、色は変えない（bugの修正で表示の構成を
  作り直さない）
- 途中まで出た応答: AI SDKは読み取りの失敗でmessagesを消さない（`chat.ts` 826〜853行）ので、コードの変更は
  要らない。§4のテストで残ることを確かめる
- 再試行: `retry`（`clearError()`→`regenerate()`）は変えない。`regenerate()`は途中までの応答を消して送り直す

### 2. 承認・却下で失敗の表示を消す（`use-chat-session.ts`）

`respondToApproval`を、先に`clearError()`を呼んでから`addToolApprovalResponse`を呼ぶ関数にする。

```ts
const respondToApproval = useCallback<ToolApprovalProps["onRespond"]>(
  (response) => {
    // addToolApprovalResponse() は error state を触らないので、先に自分で消す。
    // AI SDK が消すのは再開の request が始まったときだけで、再開の条件を
    // 満たさないと失敗の表示が残る。
    clearError();
    void addToolApprovalResponse(response);
  },
  [addToolApprovalResponse, clearError],
);
```

- 順序は`clearError()`が先。`clearError()`は`error`状態のときだけ`ready`へ戻し（`chat.ts` 487〜493行）、
  `addToolApprovalResponse`の自動再開の判定（`streaming` / `submitted`でないこと）を妨げない。`error`状態でない
  ときは何もしない
- `ToolApprovalProps["onRespond"]`の戻り値は`void`なので、`addToolApprovalResponse`のPromiseは`void`で捨てる
  （AI SDKは失敗をrejectせず`error` stateに積む）
- `ChatSession.respondToApproval`の型（`ToolApprovalProps["onRespond"]`）は変えない。JSDocを「承認 / 却下の
  応答を送る。失敗の表示は先に消す」に直す
- 帰結（Issue #4の決定をそのまま適用する）: probe 3の場合（再開の条件を満たさない）も失敗の表示と再試行の
  ボタンは消え、`ready`になる。承認待ちのpartは無くなる（`approval-responded`）ので送信は止まらず、利用者は
  次の発話を送れる。この場合の復旧は作らない（範囲外）

### 3. 状態の遷移

| 状態 | 失敗の表示 | 再試行のボタン | 途中までの応答 | 承認・却下のボタン |
|---|---|---|---|---|
| streamの途中で切れた（`error`） | 固定文言（または中継の固定文言） | 出る | 残る | 最後のmessageに承認待ちのpartがあれば出る（#3のまま） |
| 再試行を押した | 消える（既存） | 消える | `regenerate()`が消して送り直す（既存） | — |
| 承認・却下を押した | 消える（§2） | 消える | 残る | 出ない（partは`approval-responded`） |
| 再開のrequestがまた失敗した | 新しい失敗の表示が出る | 出る | 残る | — |

## 失敗と安全

- 変更は画面の表示と、承認応答の前に`clearError()`を呼ぶことだけ。requestの形、中継、backendは変えない
- 秘密値: agentの`error` partの`str(exc)`（providerの応答本文を含みうる）も画面に出なくなる。
  `error-handling-and-logging.md`「webでのエラーの表示」の「画面は、中継が返した文言だけを表示します」に
  挙動が一致する
- 残る限界: `Error.message`が偶然「`error`に空でない文字列を持つJSON」だった場合は、中継の固定文言と区別
  できずにその文字列を出す。中継の既知の文言の一覧で照合する方式は、定数の置き場所を`chat-relay.ts`から
  動かす作り直しになるので採らない（判断記録の仮定3）
- 互換性: exportの追加（`CHAT_UNREADABLE_ERROR_MESSAGE`）と`describeChatError`の戻り値の変更だけ。
  `describeChatError`の利用者は`chat-shell.tsx`だけ（`grep`で確認）。`ChatSession`の型は変えない
- rollback: `git revert`で戻る。migration、設定、依存、secretに触れない

## 文書

| 文書 | 変更 |
|---|---|
| `docs/reference/error-handling-and-logging.md`「webでのエラーの表示」 | 次の2項目を足す（文は実装時に整える） |
| `docs/reference/frontend/coding.md`「AI SDK」 | 「承認・却下の応答は`useChatSession`の`respondToApproval`が失敗の表示を消してから送る」の1項目を足す |

`error-handling-and-logging.md`に足す内容:

- 中継が積んだ固定文言として読めない失敗（streamの途中の切断、browserの通信エラー、agentの`error` part）は、
  browserやagentの文言を出さず、固定文言「応答を受け取れませんでした。」を出します。途中まで出た応答は残し、
  再試行のボタンを出します。切断からの復旧や自動の再送は行いません
- 承認または却下をすると、失敗の表示を消します

`docs/architecture.md`、`testing.md`、`test-policy.md`、`test-execution-matrix.md`は変えない（HITLの流れ、
分類、lane、手順は変わらず、台帳への登録は既存の規約どおり）。

## テスト

### 台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）

| id | feature | category | description | kinds |
|---|---|---|---|---|
| E5 | send-error | APIエラー | 応答の途中で切れたとき、固定文言が出て、browserのエラー文は出ない | small |
| E6 | send-error | 操作 | 承認・却下をすると、失敗の表示が消える | small |

- E5の`description`は#6のケース列の文をそのまま使う（#2の規約）
- E6は#6の一覧に無い新しいid（判断記録の仮定2）。#6のケース一覧への追記は人が判断する（作業報告で知らせる）
- 「中継の固定文言はこれまでどおり出る」は既存の挙動の回帰の歯止めで、新しいケースではない。注釈なしの
  テストにし、台帳には登録しない（#6のE3・E4は#5が登録する）

### Small（Vitest、`describe`に`tags: ["small"]`）

`apps/web/src/sample/chat-page.test.tsx`（`useChat`を差し替える既存の方式）:

| テスト名 | 入力 | 期待 |
|---|---|---|
| `@case:E5 応答の途中で切れたとき、固定文言と再試行のボタンを出し、browser のエラー文を出さず、途中までの応答を残す` | `messages: [userMessage, textMessage("a-1", "途中まで")]`、`status: "error"`、`error: new TypeError("network error")` | `role="alert"`の失敗の表示が`送信に失敗しました: 応答を受け取れませんでした。`を含む。`network error`の文字列は画面に無い。「途中まで」が出ている。「再試行」を押すと`clearError`と`regenerate`が1回ずつ呼ばれる |
| `中継が積んだ固定文言はそのまま出す`（注釈なし） | `error: new Error(JSON.stringify({ error: "chat backend is unreachable" }))`、`status: "error"` | 失敗の表示が`送信に失敗しました: chat backend is unreachable`を含み、`応答を受け取れませんでした。`は無い |
| `@case:E6 承認すると失敗の表示が消える` | `messages: [approvalPendingMessage()]`、`status: "error"`、`error: new TypeError("network error")`。`useChatMock`を`mockImplementation`にし、中で`useState`で`error`を持ち、`clearError`がそれを`undefined`にする（`useChatMock`は`useChat`の呼び出し、つまりrenderの中で呼ばれるのでhookを使える） | 押す前は失敗の表示がある。「承認」を押すと失敗の表示が消え、`addToolApprovalResponse`が`{ id: "approval-2", approved: true }`で1回。`clearError`は`addToolApprovalResponse`より先に呼ばれる（`mock.invocationCallOrder`） |
| `@case:E6 却下すると失敗の表示が消える` | 同上 | 「却下」で失敗の表示が消え、`addToolApprovalResponse`が`{ id: "approval-2", approved: false }`で1回 |

- file先頭のコメントの「固定するのは 3 つ」に「4. 失敗の表示は中継の固定文言か1つの固定文言だけを出し、
  承認・却下で消える」を足す
- 失敗の表示は`screen.getAllByRole("alert")`の中から文言で選ぶ（承認待ちの`approval-guard`も`role="alert"`で
  同時に出るため）。E6の「消える」は失敗の文言を持つalertが無いことで確かめる
- 既存のテストは変えずに成功する（`mockChat`の既定は`error: undefined`）
- 修正前に失敗すること: E5は`network error`が出るので失敗する。E6は`clearError`が呼ばれず表示が残るので失敗する

`apps/web/src/lib/chat-profiles.test.ts`（注釈なしの補助テスト。`describe("readProblemCode / describeChatError")`の中）:

| テスト名 | 期待 |
|---|---|
| `中継が積んだ固定文言を取り出し、JSON でない message は固定文言にする`（既存の`JSON でない message はそのまま出す`を置き換える。Issue #4 決定事項） | `{"error":"選択したモデルは利用できません。"}` → その文言。`Failed to fetch`、`network error` → `CHAT_UNREADABLE_ERROR_MESSAGE` |
| `error を読めない JSON は固定文言にする` | `{}`、`{"error":""}`、`{"error":42}`、`[1]`、`null`、`"network error"`（JSON文字列） → `CHAT_UNREADABLE_ERROR_MESSAGE` |

### E2E

足さない。E5はIssue #6でSmall（文言や状態ごとの表示はSmallで確かめる）。既存のPlaywright
（`tests/e2e/ui/sample-chat.spec.ts`）は失敗の表示の文言に依存しないので、変えずに成功する
（`make test-e2e`で確かめる）。

## 実装の順序（slice）

1. `chat-profiles.ts`の`CHAT_UNREADABLE_ERROR_MESSAGE`と`describeChatError`、`chat-profiles.test.ts`
2. `use-chat-session.ts`の`respondToApproval`、`chat-shell.tsx`のコメント
3. `chat-page.test.tsx`のE5・E6と中継の固定文言のテスト、台帳への登録
4. `docs/reference/error-handling-and-logging.md`と`docs/reference/frontend/coding.md`

## 検証lane

LLMへの影響の分類（`docs/dev/llm-evals.md`「変更目的とIssueの完了条件」）: **LLM経路に影響しない変更**。
backend、prompt、tool schema、agent loop、HITLの方針（承認要否、停止と再開のprotocol）、model・providerは
変えない。画面の失敗の表示と、承認応答の前に失敗の状態を消すことだけで、requestの形は変わらない。
品質・観測のevalの閾値は無い（acceptanceもobservationも設定しない）。

| lane | 要否 | 理由 |
|---|---|---|
| `make verify-frontend` | 必須 | webのlogic・Small test・台帳の変更 |
| `make verify-docs` | 必須 | `docs/reference/`と設計文書の変更（`check-all`に含まれる） |
| `make check-all` | 必須（最終） | Issue #4の完了条件 |
| `make test-e2e` | 必須 | Issue #4の完了条件。画面の送信・承認の流れ（frontend user flow）に触れる変更で、既存E2Eの回帰を確かめる |
| `make verify-backend` / `make gate-backend` | 追加不要 | Pythonを変えない（`check-all`が`gate-backend`を含む） |
| `make test-on-schema-change` | 追加不要 | schemaを変えない |
| `make test-llm`、`make evals` | 不要 | 上の分類のとおりLLM経路に影響しない。HITLの方針は変えず、承認応答で画面の失敗の状態を消すだけ |

### 実装前の基準（implement-precheck）

base SHAで次を測り、実装後と比べる。

- `cd apps/web && npx vitest list --tagsFilter=small --json`の件数（設計時61件）。実装後は66件
  （chat-page 4件、chat-profiles 1件を追加。既存の1件は置き換え）
- `uv run python -m scripts.testing.frontend_test_cases`が成功し、台帳が13件であること。実装後は15件で成功
- 回帰の確認: base SHAで`describeChatError("network error")`が`network error`を返すこと（修正前の挙動）を、
  `chat-profiles.test.ts`の置き換え後のassertionが失敗することで確かめてよい
- safety net: `make verify-frontend`と`make test-e2e`がbase SHAで成功すること

## 完了条件との対応

| Issue #4の完了条件 | 満たし方 |
|---|---|
| JSONとして読めないエラーのとき、固定文言と再試行のボタンが出て、browserのエラー文は出ない（Small） | §1。`@case:E5`と`chat-profiles.test.ts`の2本 |
| 中継の固定文言が積まれたエラーは、これまでどおりその文言が出る（Small） | §1。`中継が積んだ固定文言はそのまま出す`と`chat-profiles.test.ts`の1本目 |
| 承認・却下をするとエラーの表示が消える（Small） | §2。`@case:E6`の2本 |
| 追加したケースを台帳に登録し、テストに注釈を付けている | 台帳のE5・E6と注釈 |
| `make check-all`と`make test-e2e`が成功する | 検証lane |

## 判断記録

| 判断 | 選んだ方向 | 根拠・仮定 | 設計で加えた詳細 |
|---|---|---|---|
| 読めない失敗の表示 | browserのエラー文を出さず、1つの固定文言にする | Issue #4 決定事項、#6 決定事項E5 | `describeChatError`の読めない3分岐を固定文言にする（§1） |
| 文言 | `応答を受け取れませんでした。` | Issue #4が「文言は設計で決める」とし、例に挙げた文をそのまま採る（二方向） | 定数`CHAT_UNREADABLE_ERROR_MESSAGE`を`chat-profiles.ts`の固定文言の節に置く |
| 前置きと表示の構成 | 「送信に失敗しました: 」、`role="alert"`、再試行のボタンを変えない | bug rubric（修正の名で振る舞いを作り直さない）、#6のX2 | — |
| 途中までの応答 | 残す | Issue #4 決定事項。AI SDKが消さない（`chat.ts` 826〜853行） | コードは変えず、E5のテストで確かめる |
| 再試行 | 今のまま（途中までの応答を消して送り直す） | Issue #4 決定事項 | — |
| 承認・却下で失敗の表示を消す | `respondToApproval`が`clearError()`を先に呼ぶ | Issue #4 決定事項。probe 3（再開の条件を満たさないとAI SDKは`error`を消さない） | 順序と、再開しない場合の帰結（§2） |
| 中継とbackend | 変えない | Issue #4 範囲外（復旧の仕組みは作らない）、`error-handling-and-logging.md`（streamの途中の失敗はstatusで返せない） | — |
| 仮定1: agentの`error` partも固定文言にする | `str(exc)`も「中継の固定文言として読めない」ので同じ固定文言にする | 仮定（二方向）。Issue #4の決定は失敗の出どころで分けず、`error-handling-and-logging.md`の「画面は中継が返した文言だけを表示します」に一致し、providerの本文を画面に出さない。設計レビューで確認する | §1の表 |
| 仮定2: 承認・却下で消えるケースのid | 新しいid `E6`（send-error、操作、small）を台帳に登録する | 仮定（二方向）。#6の一覧にこのケースは無く、Issue #4の完了条件が台帳への登録を求める。#3のA9と同じ扱い。設計レビューで確認する | #6の一覧への追記は人の判断として作業報告で知らせる |
| 仮定3: 中継の固定文言の判定 | 今の「`error`に空でない文字列を持つJSON」のまま | 仮定（二方向）。最小の修正にとどめる。既知の文言の一覧で照合すると定数の置き場所の作り直しになる。設計レビューで確認する | 残る限界を「失敗と安全」に書く |
| 中継の固定文言のテスト | 注釈なしで書き、台帳に登録しない | 既存の挙動の回帰の歯止めで新しいケースではない。#6のE3・E4の登録は#5（Issue #5 対象の契約） | — |
| 検証lane | `verify-frontend`、`verify-docs`、`check-all`、`test-e2e`。LLM・evalは不要 | `verification-matrix.md`、`llm-evals.md`（LLM経路に影響しない変更）、Issue #4の完了条件 | 実装前の基準（Small件数、台帳件数、safety net） |

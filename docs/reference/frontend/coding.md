# フロントエンド実装規約

この文書は、`apps/web/`のTypeScriptとReactのコードの書き方を決めます。webのコードを追加・変更するときに
読みます。層の分け方は[アーキテクチャ](../../architecture.md)、テストは[フロントエンドテスト](testing.md)、
見た目は[デザインシステム](design-system.md)を参照してください。

## Next.jsのversion

このリポジトリのNext.jsは、学習データにあるversionとAPIや規約が異なる場合があります。コードを書く前に
`apps/web/node_modules/next/dist/docs/`の該当する説明を読みます。agent向けの注意は`apps/web/AGENTS.md`に
あります。

## ディレクトリと依存の向き

- `src/app/`はrouteの定義だけにします。画面のrouteはサンプルの画面を再exportし、`src/app/api/`は
  FastAPIへの中継だけを持ちます
- 用途に依存しない部品は`src/components/chat/`と`src/lib/`、サンプル固有の画面と表示は`src/sample/`に
  置きます。共通部分から`src/sample/`をimportしません
- `src/components/ui/`と`src/components/ai-elements/`は生成コードです。直接編集せず、使う側で包みます
- importは`@/`（`src/`）から書きます

## Server ComponentとClient Component

- 既定はServer Componentです。state、effect、browserのAPI、AI SDKのhookを使うfileだけ先頭に
  `"use client"`を書きます
- `"use client"`のfileからserverだけで使うmodule（loggerなど）をimportしません

## APIへの中継

- browserからFastAPIを直接呼びません。`src/app/api/`のRoute Handlerを経由し、中継の規則は
  `src/lib/chat-relay.ts`にまとめます
- 中継はstreamをバッファせずに返します。FastAPIの接続先（`FASTAPI_BASE_URL`）は、呼ぶ時点で読みます
- FastAPIが返した失敗は、`src/lib/chat-profiles.ts`の固定文言に変えて画面へ出します。FastAPIの応答本文を
  そのまま表示しません

## AI SDK

- `useChat`、transport、送信、停止、再試行、承認応答は`src/components/chat/use-chat-session.ts`だけが
  扱います。画面のcomponentはAI SDKのAPIを直接呼びません
- 承認の操作は`src/components/chat/tool-approval.tsx`が`addToolApprovalResponse`を呼びます。承認後の再送は
  `sendAutomaticallyWhen`が行うので、画面側で再送しません
- 承認待ちの判定は`src/components/chat/tool-approval.tsx`の`findPendingApprovalMessageId`が正本です。
  送信の停止は`ChatShell`の`awaitingApproval`が行い、承認・却下のボタンは`useChatSession`の
  `pendingApprovalMessageId`と一致するmessageにだけ出します

## 状態管理

- 状態はcomponentの`useState`とhookに閉じます。global storeは使いません
- 選択中のprofileのように、requestを組み立てる時点で読む値は、`createChatProfileChannel`のように
  closureへ閉じ込め、更新の経路を1つにします
- effectの本文で同期的に`setState`を呼びません。取得の結果は、非同期の処理が終わった後に反映します

## profileの選択

- 画面の選択肢は`GET /api/chat/profiles`が返す一覧だけを使い、webの側にprofileの一覧を持ちません
- requestに載せるprofileの決め方は`src/lib/chat-profiles.ts`の`resolveRequestProfile`が正本です

## スタイルとアクセシビリティ

- 色、余白、角丸はtokenを使い、値を直接書きません。詳しくは[デザインシステム](design-system.md)を
  参照してください
- 操作できる要素にはラベルを付け、状態（読み込み中、承認待ち、失敗）は文字とaria属性でも示します

## ログ

- server側のログは`src/lib/logger.ts`の`createModuleLogger`で取り、値をobjectで、event名を文字列で渡します
- 会話の本文やrequest/responseのbodyを丸ごと渡しません

## 型、lint、format

- TypeScriptの`strict`を通すことを必須にします。設定の正本は`apps/web/tsconfig.json`です
- `any`は使いません。外から来た値は`unknown`で受け、検査してから型を付けます
- `eslint-disable`は、生成コードに合わせる場合と、ruleが意図に合わない1行に限ります。rule名と理由を
  同じコメントに書きます。生成コード向けの緩和は`apps/web/eslint.config.mjs`にまとめています
- Prettierのformatで差分が無いことを必須にします。設定は`apps/web/.prettierrc.json`、対象外は
  `apps/web/.prettierignore`です
- 確認は`make verify-frontend`で行います。Prettier、ESLint、型検査、Vitestをまとめて実行します

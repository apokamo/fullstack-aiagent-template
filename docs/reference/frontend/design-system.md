# デザインシステム

この文書は、webの色、文字、component、状態の表示の規則を決めます。画面やcomponentを追加・変更するときに
読みます。tokenの値は[`globals.css`](../../../apps/web/src/app/globals.css)が正本で、この文書には値を
書きません。値の決定根拠と使い分けは、この文書が正本です。

## token

- 色、角丸、書体はCSS変数のtokenとして`apps/web/src/app/globals.css`に定義しています。変数名は
  shadcn/uiと同じです（`--background`、`--foreground`、`--primary`、`--muted-foreground`など）
- componentはTailwindのclass（`bg-background`、`text-muted-foreground`など）でtokenを参照し、色の値を
  直接書きません
- tokenを追加・変更したら、`globals.css`の先頭にあるcontrastの記録も更新します。本文と操作の文字は
  WCAG 2.2のAA（通常の文字は4.5:1以上）を満たします

## lightとdark

- 画面はlightで表示します。dark用のtokenは`globals.css`の`.dark`に置いていますが、切り替えは持って
  いません
- darkを使う場合は、`<html>`に`dark` classを付ける仕組みを足し、`.dark`のtokenのcontrastを確かめます

## componentの層

| 層 | 置き場所 | 扱い |
|---|---|---|
| 基本部品 | `src/components/ui/` | shadcn/uiの生成コード。直接編集しない |
| chatの表示部品 | `src/components/ai-elements/` | AI Elementsの生成コード。直接編集しない |
| chatの共通部品 | `src/components/chat/` | 生成コードを組み合わせる。用途に依存しない |
| サンプルの画面 | `src/sample/` | 見出しと応答の描き方。エージェントごとに置き換える |

## componentの追加

- shadcn/uiとAI Elementsのcomponentは、各CLI（`npx shadcn add`、`npx ai-elements add`）で追加します。
  設定は`apps/web/components.json`です
- 生成コードの見た目を変えたい場合は、生成コードを編集せず、使う側でclassを渡すか包むcomponentを作ります。
  再生成で変更が消えるためです

## 状態の表示

- 読み込み中、承認待ち、承認済み、却下、失敗を、文字で区別して表示します。色やiconだけで区別しません
- 失敗のように利用者がすぐ知るべき表示には`role="alert"`を付け、支援技術にも伝わるようにします
- 失敗の表示には、利用者が次にできること（再試行、選び直し）を添えます

## 読みやすさとアクセシビリティ

- 本文と表の文字は14px以上、状態の表示は13px以上にします
- focusが見えることを確かめます。focusの表示を消しません
- 操作できる要素にはラベルを付け、keyboardだけで操作できるようにします

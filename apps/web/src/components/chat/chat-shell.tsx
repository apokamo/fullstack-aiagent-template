"use client";

/**
 * 用途共通のチャット画面の骨格。
 *
 * 見出し行・会話・入力欄という 3 段の配置を持つ。用途ごとに変わるのは
 * 「見出しの文言」「見出し行の右の操作」「assistant の応答をどう描くか」だけ
 * なので、それだけを slot として受け取る。
 *
 * **AI SDK にも profile 一覧にも触らない。** 送信・停止・再試行は呼ぶ側
 * （`useChatSession`）が持ち、ここは操作を渡すだけである。
 *
 * 送信を止める理由は 2 つある。profile が送信できない状態（`canSubmit`）と、
 * 承認待ち（`awaitingApproval`）。どちらも送信ボタンの `disabled` で止め、
 * 打った文を消さない。
 */

import type { UIMessage } from "ai";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { APPROVAL_PENDING_MESSAGE } from "@/components/chat/tool-approval";
import { describeChatError } from "@/lib/chat-profiles";

export type ChatShellProps = {
  /** 画面見出し（用途の名前）。 */
  title: string;
  /** 見出し行の右へ寄せる操作（モデル選択欄）。 */
  headerAccessory?: React.ReactNode;
  /** 会話が空のときの案内。 */
  emptyState: { readonly title: string; readonly description: string };
  messages: readonly UIMessage[];
  /** assistant 1 応答の描画（用途別 Response）。 */
  renderAssistant: (message: UIMessage) => React.ReactNode;
  /** 押せない理由（profile 由来の固定文言）。 */
  guardMessage: string | null;
  /** 送信の失敗。 */
  error: Error | undefined;
  onRetry: () => void;
  onSubmit: (text: string) => Promise<void> | undefined;
  onStop: () => void;
  status: React.ComponentProps<typeof PromptInputSubmit>["status"];
  isGenerating: boolean;
  /** profile 由来の送信可否（生成中の停止操作は止めない）。 */
  canSubmit: boolean;
  /** 承認待ちで送信を止める（`useChatSession` の `awaitingApproval`）。 */
  awaitingApproval: boolean;
};

export function ChatShell({
  awaitingApproval,
  canSubmit,
  emptyState,
  error,
  guardMessage,
  headerAccessory,
  isGenerating,
  messages,
  onRetry,
  onStop,
  onSubmit,
  renderAssistant,
  status,
  title,
}: ChatShellProps): React.ReactNode {
  /**
   * 送信操作を止める。
   *
   * **`onSubmit` の中で止めるのでは間に合わない。** 生成物の `PromptInput` は
   * `onSubmit` を呼ぶ**前**に `form.reset()` する（`prompt-input.tsx:855-860`）
   * ので、guard が走る時点では打った文が消えている。送信ボタンを `disabled` に
   * すれば click も Enter も form へ届かず（生成物の textarea は
   * `button[type="submit"]` の `disabled` を見てから `requestSubmit()` する。
   * 同 `:985-996`）、**入力欄の本文はそのまま残る** —— 一覧を再取得するか
   * モデルを選び直せば、同じ文をそのまま送れる。承認待ちも同じ仕組みで止め、
   * 承認か却下で再開の run が終わればその文を送れる。
   *
   * **生成中は付けない。** そのときボタンは停止ボタン（`type="button"`）なので、
   * ここで `disabled` にすると生成を止められなくなる。生成中の追加送信は
   * textarea の `disabled` と `send()` 側の guard が止める。
   */
  const submitDisabled = !isGenerating && (!canSubmit || awaitingApproval);

  return (
    /*
     * 本文の最大幅は 1024px（`max-w-5xl`）。**幅の正本はここ 1 箇所**で、
     * 他の要素に幅 token を散らさない。`mx-auto` と `p-4` は
     * 維持するので、中央配置と小さい画面の左右余白 16px は変わらない。
     */
    <main className="mx-auto flex h-screen max-w-5xl flex-col gap-4 p-4">
      {/*
        見出し行。desktop はモデル選択欄を右へ寄せ、mobile（`sm` 未満）は
        見出しの下へ折り返す。
      */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* 画面見出しは 24px / 600 / 1.4（design-system.md のタイポグラフィ）。 */}
        <h1 className="font-heading font-semibold text-2xl leading-[1.4]">
          {title}
        </h1>

        {headerAccessory}
      </div>

      <Conversation className="min-h-0 flex-1">
        {/*
          **左右の padding だけを 0 にする**。上下 16px と
          `gap-8` は生成物のまま。これが無いと応答カードの外枠が質問欄より
          16px 内側に入り、「回答カードと質問欄を同じ幅に揃える」を満たせない。
        */}
        <ConversationContent
          className="px-0"
          /*
            **scrollbar の余白は右側だけにする**。
            `use-stick-to-bottom` は scroll 要素へ
            `scrollbar-gutter: stable both-edges` を **inline style で**敷くので、
            左右に同じ幅の gutter が入り、応答カードの左端が質問欄より内側へずれる。
            inline style は `!important` でしか上書きできないため、ここだけ
            arbitrary property + `!` を使う（生成物と library は編集しない）。
          */
          scrollClassName="[scrollbar-gutter:stable]!"
        >
          {messages.length === 0 ? (
            <ConversationEmptyState
              title={emptyState.title}
              description={emptyState.description}
            />
          ) : null}

          {messages.map((message) => (
            /*
              assistant の応答カードだけ 100% 幅にする。
              生成物既定の `max-w-[95%]` のままだと質問欄と幅が揃わない。
              **user 発話の吹き出しは 95% のまま**にする。
            */
            <Message
              className={
                message.role === "assistant" ? "max-w-full" : undefined
              }
              from={message.role}
              key={message.id}
            >
              {/*
                assistant は 1 応答が 1 枚の応答カードなので、
                生成物既定の `w-fit` を外して幅を揃える。面と 24px の padding を
                持つカードが本文の長さで伸縮すると、応答ごとに別の幅の面が並ぶ。
                user 発話は内容幅の吹き出しにする。
              */}
              <MessageContent
                className={message.role === "assistant" ? "w-full" : undefined}
              >
                {message.role === "assistant"
                  ? renderAssistant(message)
                  : message.parts.map((part, index) =>
                      part.type === "text" ? (
                        <MessageResponse key={`${message.id}-${index}`}>
                          {part.text}
                        </MessageResponse>
                      ) : null,
                    )}
              </MessageContent>
            </Message>
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {/*
        **入力欄は送信した時点で空になる**（生成物の PromptInput が onSubmit を
        呼ぶ前に `form.reset()` する）。加えて AI SDK の `sendMessage` は通信・
        stream のエラーを握って `error` state に積むだけで reject しないので、
        「失敗したら入力を戻す」という作りにはできない。
        代わりに **送信済みの user message は messages に残る**ので、そこから
        `regenerate()` で再試行させる。

        **これは送信できた場合の話である。** 一覧が未解決・取得失敗・選んだ
        profile が利用不可のときは送信自体が起きないので、打った文を消しては
        ならない。そちらは `submitDisabled` で form へ到達させないことで守る。
      */}
      {guardMessage !== null ? (
        <div
          className="rounded-md bg-destructive/10 px-3 py-2 text-destructive text-sm"
          data-testid="model-guard"
          role="alert"
        >
          {guardMessage}
        </div>
      ) : null}

      {/*
        承認待ちの理由。失敗ではないので destructive の色は使わない。
        入力欄の上に置き、profile の理由（`model-guard`）と場所を揃える。
      */}
      {awaitingApproval ? (
        <div
          className="rounded-md bg-muted px-3 py-2 text-foreground text-sm"
          data-testid="approval-guard"
          role="alert"
        >
          {APPROVAL_PENDING_MESSAGE}
        </div>
      ) : null}

      {error ? (
        <div
          className="flex items-center justify-between gap-3 rounded-md bg-destructive/10 px-3 py-2 text-destructive text-sm"
          role="alert"
        >
          {/*
            中継が積んだ固定文言を出す。`ai@7` は非 2xx の
            応答本文をそのまま `Error.message` にするので、素直に出すと JSON が
            見える。読むのは `error` 1 field だけで、読めなければ元の message。
          */}
          <span>送信に失敗しました: {describeChatError(error.message)}</span>
          <Button onClick={onRetry} size="sm" variant="outline">
            再試行
          </Button>
        </div>
      ) : null}

      <PromptInput
        onSubmit={(message) => {
          /*
           * **初期選択が不明なまま送信しない**。一覧が
           * `ready` でない、または選んだ profile が利用不可なら送らない ——
           * API 側の 503 と二重の歯止めにする。理由の表示と入力の保護は
           * 送信ボタンの `disabled`（`submitDisabled`）が持つので、ここは
           * form へ到達した場合の最後の歯止めだけを残す。承認待ちも同じ。
           *
           * 生成中の追加送信と空文の除外は `onSubmit`（`useChatSession.send`）が
           * 持つ —— そちらが唯一の送信経路である。
           */
          if (!canSubmit || awaitingApproval) {
            return;
          }
          // Promise を返しておく（PromptInput は添付の後始末を await する）。
          // ただし失敗しても reject はしない —— 失敗は `error` state に出る。
          return onSubmit(message.text ?? "");
        }}
      >
        {/*
          **`PromptInputBody` を挟まない**。あれは
          `display: contents` の wrapper だが DOM の子ではあるので、挟むと
          `InputGroup` の `has-[>textarea]:h-auto`（CSS `:has(> textarea)`）が
          一致せず `h-9`（36px）が残り、64px の欄が期待どおりに見えない。
          生成物は 1 行も編集せず、呼び出し側の構造だけで直す。

          生成中は入力自体を止める。**guard だけでは打った文が消える** ——
          生成物の PromptInput は onSubmit を呼ぶ前に form.reset() するので、
          Enter を握り潰しても入力欄は空になってしまう。

          寸法: 内側高さ 64px = 上下 padding 20px + line-height 24px。
          `text-base md:text-base` は基底 `Textarea` の `md:text-sm`（768px 以上で
          14px / 20px）を打ち消すためにあり、これが無いと desktop で 24px の
          行送りが崩れて上下中央に見えない。
        */}
        <PromptInputTextarea
          className="overflow-y-auto px-4 py-5 text-base leading-6 md:text-base"
          disabled={isGenerating}
          placeholder={isGenerating ? "生成中…" : "質問を入力"}
        />
        {/*
          onStop を渡さないと、生成中でもボタンは type="submit" のまま。
          停止アイコンと aria-label="Stop" だけが出て実際には止まらず、
          入力があれば進行中の run にもう 1 通投げてしまう。
        */}
        {/* 欄内の右端。`InputGroup` の `items-center` で上下中央に並ぶ。 */}
        <PromptInputSubmit
          className="mr-3"
          disabled={submitDisabled}
          onStop={onStop}
          status={status}
        />
      </PromptInput>
    </main>
  );
}

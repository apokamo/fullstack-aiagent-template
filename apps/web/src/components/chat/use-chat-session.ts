"use client";

/**
 * 用途に依存しないチャット 1 本ぶんの session。
 *
 * **transport を 1 回だけ作るのはここである。** `prepareSendMessagesRequest` が
 * request snapshot を受け取る唯一の seam で（`ai@7.0.66`
 * `src/ui/http-chat-transport.ts:158-185`）、選択 profile を state のまま閉じ込めると
 * transport 生成時の値で固定される。可変値は `createChatProfileChannel()` の
 * closure が持ち、外からの更新経路は `selectProfile()` 1 本だけである。
 *
 * 送信・停止・再生成・承認応答もここが所有する。用途側の画面は「何を描くか」
 * だけを持ち、AI SDK の API に触らない。
 */

import { useChat } from "@ai-sdk/react";
import { lastAssistantMessageIsCompleteWithApprovalResponses } from "ai";
import type { ChatOnDataCallback, UIMessage } from "ai";
import { useCallback, useState } from "react";

import { createChatProfileChannel } from "@/lib/chat-profiles";
import {
  findPendingApprovalMessageId,
  type ToolApprovalProps,
} from "@/components/chat/tool-approval";

type ChatStatus = ReturnType<typeof useChat>["status"];

/** transient な data part の受け手（AI SDK の `onData` と同じ signature）。 */
export type ChatDataHandler = ChatOnDataCallback<UIMessage>;

export type UseChatSessionOptions = {
  /** transient な data part の受け手（用途が持たなければ何もしない）。 */
  onData?: ChatDataHandler;
  /** 中継 Route Handler の path。 */
  endpoint?: string;
};

export type ChatSession = {
  readonly messages: readonly UIMessage[];
  readonly status: ChatStatus;
  /** stream が開いている（`submitted` か `streaming`）。 */
  readonly isGenerating: boolean;
  /**
   * stream が開いている message の id。
   *
   * **stream が開いているのは末尾 message だけ**であり、tool part の state からは
   * 推測させない —— part の終端と stream の終端は別物で、transient payload は
   * ちょうどその隙間に流れる。
   */
  readonly streamingMessageId: string | undefined;
  /**
   * 承認待ちの message の id（承認・却下のボタンを出す message）。
   *
   * 生成中も値を持つ —— 承認要求の part は stream の終わる前に届き、
   * そのときからボタンを出す。判定は `findPendingApprovalMessageId`。
   */
  readonly pendingApprovalMessageId: string | undefined;
  /**
   * 承認待ちで送信を止める。
   *
   * **生成中は `false`。** 生成中は停止ボタン・入力欄の `disabled`・`send()` の
   * 生成中 guard が既に送信を止めており、理由の表示を一瞬出してから消すことになる。
   */
  readonly awaitingApproval: boolean;
  /** 送信の失敗（AI SDK が握って state に積んだもの）。 */
  readonly error: Error | undefined;
  /**
   * 本文を送る。空文字・生成中・承認待ちは送らない。
   *
   * 生成物の `PromptInput` は添付の後始末を await するので Promise をそのまま
   * 返す。ただし AI SDK は通信・stream の失敗を握って `error` state に積むだけで
   * reject しないため、呼ぶ側が失敗を catch する経路にはならない。
   */
  send: (text: string) => Promise<void> | undefined;
  /** 生成を止める。 */
  stop: () => void;
  /** 失敗表示を消してから再試行する。 */
  retry: () => void;
  /** 承認 / 却下の応答を送る。失敗の表示は先に消す。 */
  respondToApproval: ToolApprovalProps["onRespond"];
  /** 次の request が運ぶ profile を差し替える。 */
  selectProfile: (value: string) => void;
};

export function useChatSession({
  onData,
  endpoint = "/api/chat",
}: UseChatSessionOptions = {}): ChatSession {
  const [channel] = useState(() => createChatProfileChannel(endpoint));

  const {
    messages,
    sendMessage,
    regenerate,
    clearError,
    status,
    stop,
    error,
    addToolApprovalResponse,
  } = useChat({
    transport: channel.transport,
    // 承認・却下の**双方**で 2 本目のリクエストを自動的に起こす。
    // サーバは 1 本目と 2 本目のあいだに何も覚えていないので、再開の材料は
    // ここが持っている `messages` が全量である。
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
    onData,
  });

  const isGenerating = status === "submitted" || status === "streaming";
  const pendingApprovalMessageId = findPendingApprovalMessageId(messages);
  const awaitingApproval =
    !isGenerating && pendingApprovalMessageId !== undefined;

  const selectProfile = useCallback(
    (value: string) => {
      channel.select(value);
    },
    [channel],
  );

  const send = useCallback(
    (text: string) => {
      // **生成中は受け付けない。** 生成物の PromptInputTextarea は Enter を
      // `form.requestSubmit()` に流し、その手前で見ているのは
      // `button[type="submit"]` の disabled だけ。生成中はそのボタンが
      // `type="button"`（停止ボタン）になっていて**照会に引っかからない**ので、
      // ここで止めないと進行中の run にもう 1 通投げられる。
      //
      // **承認待ちも受け付けない。** 入力の保護は `ChatShell` の送信ボタンの
      // `disabled` が持ち、ここは form へ到達した場合の最後の歯止めである。
      if (isGenerating || awaitingApproval) {
        return undefined;
      }
      const trimmed = text.trim();
      if (trimmed === "") {
        return undefined;
      }
      return sendMessage({ text: trimmed });
    },
    [awaitingApproval, isGenerating, sendMessage],
  );

  const retry = useCallback(() => {
    // regenerate() は error state を触らないので、先に自分で消す。
    // 消さないと再試行が成功しても失敗表示が残り続ける（実測）。
    clearError();
    void regenerate();
  }, [clearError, regenerate]);

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

  return {
    messages,
    status,
    isGenerating,
    streamingMessageId: isGenerating ? messages.at(-1)?.id : undefined,
    pendingApprovalMessageId,
    awaitingApproval,
    error,
    send,
    stop,
    retry,
    respondToApproval,
    selectProfile,
  };
}

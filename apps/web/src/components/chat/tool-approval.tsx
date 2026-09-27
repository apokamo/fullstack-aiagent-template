"use client";

/**
 * ツール実行の承認 UI。
 *
 * `docs/architecture.md`の「HITL」をfrontendで局所化する実体はこの1枚。
 * AI SDK の承認 API（v7 の `addToolApprovalResponse`）に触るのはここだけにして、
 * 将来の API 変更の影響面を局所化する。
 *
 * **状態の遷移はこのコンポーネントの仕事ではない。** `addToolApprovalResponse` を
 * 呼ぶと `useChat` が message を `approval-responded` に書き換え、
 * `sendAutomaticallyWhen`（`use-chat-session.ts`）が 2 本目のリクエストを起こす。
 * 承認・却下のどちらでも同じ経路を通る。
 *
 * 却下の理由（`reason`）は口だけ残して UI では取らない —— 入力欄を足すのは
 * 「何を書かせるか」を決めてからにする。バックエンドは理由の有無に関わらず
 * `tool-output-denied` を返す。
 *
 * **承認待ちの判定もここに置く。** 承認待ちのあいだ画面は送信を止め
 * （`ChatShell`）、承認・却下のボタンは承認待ちの message にだけ出す。
 * どちらも `findPendingApprovalMessageId` 1 つから導く。
 */

import {
  isToolUIPart,
  type DynamicToolUIPart,
  type ToolUIPart,
  type UIMessage,
} from "ai";

import { Button } from "@/components/ui/button";

export type ToolApprovalProps = {
  /** 承認待ちのツール part（`state === "approval-requested"` のもの）。 */
  approvalId: string;
  /** 承認 / 却下の応答を送る。`useChat` の `addToolApprovalResponse`。 */
  onRespond: (response: {
    id: string;
    approved: boolean;
    reason?: string;
  }) => void;
};

/**
 * `approval-requested` のツール part に添える承認 / 却下ボタン。
 */
export function ToolApproval({ approvalId, onRespond }: ToolApprovalProps) {
  return (
    <div
      className="flex items-center justify-between gap-3 border-t p-3"
      data-testid="tool-approval"
    >
      <span className="text-muted-foreground text-sm">
        このツールの実行には承認が必要です。
      </span>
      <div className="flex gap-2">
        <Button
          onClick={() => onRespond({ id: approvalId, approved: false })}
          size="sm"
          variant="outline"
        >
          却下
        </Button>
        <Button
          onClick={() => onRespond({ id: approvalId, approved: true })}
          size="sm"
        >
          承認
        </Button>
      </div>
    </div>
  );
}

/**
 * ツール part が承認待ちなら、その承認 id を返す（そうでなければ `undefined`）。
 *
 * `part.approval` は `approval-requested` のときだけ id を持つ（AI SDK の型定義）。
 * 呼ぶ側で state と approval の両方を見に行かなくて済むよう、ここに寄せてある。
 */
export function pendingApprovalId(
  part: ToolUIPart | DynamicToolUIPart,
): string | undefined {
  return part.state === "approval-requested" ? part.approval.id : undefined;
}

/** 承認待ちのあいだ送信できない理由（入力欄の上に出す固定文言）。 */
export const APPROVAL_PENDING_MESSAGE = "承認か却下を選んでください。";

/**
 * 最後の message が承認待ちの tool part を持つ assistant message なら、その id を返す。
 *
 * **見るのは `messages` の最後の要素だけである。** AI SDK の
 * `addToolApprovalResponse` は最後の message しか書き換えず、自動再送の判定
 * （`lastAssistantMessageIsCompleteWithApprovalResponses`）も同じ message を見る。
 * 承認・却下が効くのはこの message だけなので、それより前に残った承認待ちでは
 * 送信を止めず、ボタンも出さない。
 *
 * tool part は `isToolUIPart`（静的 tool と `dynamic-tool` の両方）で判定し、
 * 自動再送の判定と対象を揃える。送信を止める part には必ずボタンを出すので、
 * 描く側（用途の Response）も同じ集合を描くこと。
 */
export function findPendingApprovalMessageId(
  messages: readonly UIMessage[],
): string | undefined {
  const last = messages.at(-1);
  if (last?.role !== "assistant") {
    return undefined;
  }
  const pending = last.parts.some(
    (part) => isToolUIPart(part) && part.state === "approval-requested",
  );
  return pending ? last.id : undefined;
}

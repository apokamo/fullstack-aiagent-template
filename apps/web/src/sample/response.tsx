"use client";

/**
 * サンプルエージェントの assistant 1 応答。
 *
 * **描くのは本文・tool 結果・承認 / 却下だけである。**
 *
 * tool part の描画は生成物の `Tool`（`components/ai-elements/tool.tsx`）に任せ、
 * 承認 UI は共通の `ToolApproval`へ閉じ込める。AI SDK の承認 API に
 * 触るのはあちらだけで、ここは「どの part が承認待ちか」を渡すだけである。
 */

import { isToolUIPart, type UIMessage } from "ai";

import { MessageResponse } from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  ToolApproval,
  pendingApprovalId,
  type ToolApprovalProps,
} from "@/components/chat/tool-approval";

export type SampleResponseProps = {
  message: UIMessage;
  onToolApprovalResponse: ToolApprovalProps["onRespond"];
};

export function SampleResponse({
  message,
  onToolApprovalResponse,
}: SampleResponseProps): React.ReactNode {
  return (
    <div
      className="flex w-full flex-col gap-4 rounded-lg bg-card p-6 text-base text-card-foreground"
      data-testid="sample-response"
    >
      {message.parts.map((part, index) => {
        const key = `${message.id}-${index}`;

        if (part.type === "text") {
          return <MessageResponse key={key}>{part.text}</MessageResponse>;
        }

        // reasoning を出すモデル（ds4 など）はここに流れてくる。本文より先に長く
        // 流れるので、出さないと数秒間なにも動かない画面になる。
        if (part.type === "reasoning") {
          return (
            <Reasoning
              data-testid="reasoning"
              isStreaming={part.state === "streaming"}
              key={key}
            >
              <ReasoningTrigger data-testid="reasoning-toggle" />
              <ReasoningContent>{part.text}</ReasoningContent>
            </Reasoning>
          );
        }

        if (isToolUIPart(part) && part.type !== "dynamic-tool") {
          const approvalId = pendingApprovalId(part);

          return (
            <Tool defaultOpen key={key}>
              {/*
                E2E の hook。生成物の `ToolHeader` は
                CollapsibleTrigger（button）で、accessible name が
                「ツール名 + 状態ラベル」という生成物由来の文字列になる。
                **生成物を編集せず** props で testid を足して E2E から名指せるようにする。
              */}
              <ToolHeader
                data-testid="tool-header"
                state={part.state}
                type={part.type}
              />
              <ToolContent>
                {/* `input-streaming` の間は input が undefined（生成物は素通しする）。 */}
                <ToolInput input={part.input ?? {}} />
                <ToolOutput errorText={part.errorText} output={part.output} />
                {approvalId ? (
                  <ToolApproval
                    approvalId={approvalId}
                    onRespond={onToolApprovalResponse}
                  />
                ) : null}
              </ToolContent>
            </Tool>
          );
        }

        return null;
      })}
    </div>
  );
}

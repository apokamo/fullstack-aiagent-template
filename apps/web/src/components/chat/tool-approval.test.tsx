/**
 * 承認 UI が AI SDK の承認 API を正しい引数で叩く。
 *
 * **見られるのはここまで。** 承認応答を送ったあと 2 本目のリクエストが起き、
 * `tool-output-denied` が返って描画されるところは**バックエンドから返る状態**
 * なので、component テストでは「一周した」と言えない。承認から保存・却下までの
 * 往復は fake model の E2E（`tests/e2e/ui/sample-chat.spec.ts`）が確かめる。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DynamicToolUIPart, ToolUIPart, UIMessage } from "ai";
import { describe, expect, it, vi } from "vitest";

import {
  ToolApproval,
  findPendingApprovalMessageId,
  pendingApprovalId,
} from "@/components/chat/tool-approval";

function toolPart(state: ToolUIPart["state"]): ToolUIPart {
  return {
    type: "tool-save_note",
    toolCallId: "call-1",
    state,
    input: { title: "t", body: "b" },
    ...(state === "approval-requested" ? { approval: { id: "call-1" } } : {}),
  } as ToolUIPart;
}

function dynamicToolPart(): DynamicToolUIPart {
  return {
    type: "dynamic-tool",
    toolName: "save_note",
    toolCallId: "call-dyn",
    state: "approval-requested",
    input: { title: "t", body: "b" },
    approval: { id: "approval-dyn" },
  } as DynamicToolUIPart;
}

function message(
  id: string,
  role: UIMessage["role"],
  parts: UIMessage["parts"],
): UIMessage {
  return { id, role, parts };
}

describe("tool approval", { tags: ["small"] }, () => {
  it("@case:A2 押すまでは応答を送らず、承認ボタンは approved: true で応答する", async () => {
    const onRespond = vi.fn();
    render(<ToolApproval approvalId="call-1" onRespond={onRespond} />);
    expect(onRespond).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "承認" }));

    expect(onRespond).toHaveBeenCalledWith({ id: "call-1", approved: true });
  });

  it("@case:A3 却下ボタンは approved: false で応答する", async () => {
    const onRespond = vi.fn();
    render(<ToolApproval approvalId="call-1" onRespond={onRespond} />);

    await userEvent.click(screen.getByRole("button", { name: "却下" }));

    expect(onRespond).toHaveBeenCalledWith({ id: "call-1", approved: false });
  });

  it("承認待ちの part からだけ承認 id を取り出す", () => {
    // 承認待ち以外で id を返すと、実行済みのツールにも承認 UI が付いてしまう
    expect(pendingApprovalId(toolPart("approval-requested"))).toBe("call-1");
    expect(pendingApprovalId(toolPart("input-available"))).toBeUndefined();
    expect(pendingApprovalId(toolPart("output-available"))).toBeUndefined();
    expect(pendingApprovalId(toolPart("output-denied"))).toBeUndefined();
  });

  it("最後の message が承認待ちの assistant message のときだけ、その id を返す", () => {
    const pending = message("a-1", "assistant", [
      toolPart("approval-requested"),
    ]);
    const done = message("a-2", "assistant", [toolPart("output-available")]);
    const user = message("u-1", "user", [{ type: "text", text: "次の質問" }]);

    expect(findPendingApprovalMessageId([pending])).toBe("a-1");
    // AI SDK の承認応答が書き換えるのは最後の message だけ
    expect(findPendingApprovalMessageId([pending, user])).toBeUndefined();
    expect(findPendingApprovalMessageId([done])).toBeUndefined();
    expect(findPendingApprovalMessageId([pending, user, done])).toBeUndefined();
    expect(findPendingApprovalMessageId([])).toBeUndefined();
  });

  it("承認待ちが複数あれば、すべてに応答するまで id を返す", () => {
    const partly = message("a-1", "assistant", [
      toolPart("approval-responded"),
      toolPart("approval-requested"),
    ]);

    expect(findPendingApprovalMessageId([partly])).toBe("a-1");
  });

  it("dynamic tool の承認待ちも判定し、承認 id を返す", () => {
    const part = dynamicToolPart();

    expect(
      findPendingApprovalMessageId([message("a-1", "assistant", [part])]),
    ).toBe("a-1");
    expect(pendingApprovalId(part)).toBe("approval-dyn");
  });
});

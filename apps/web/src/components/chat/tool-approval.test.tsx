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
import type { ToolUIPart } from "ai";
import { describe, expect, it, vi } from "vitest";

import {
  ToolApproval,
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
});

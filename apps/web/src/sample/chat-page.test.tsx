/**
 * サンプルエージェントの画面の配線。
 *
 * 固定するのは 3 つ。
 *
 * 1. **描くのは本文・tool 結果・承認 / 却下**である。
 * 2. **承認 UI は共通の `ToolApproval` へ閉じ込める**。承認・却下の
 *    どちらも `addToolApprovalResponse` を 1 回だけ呼ぶ。
 * 3. **送信 guard は profile の状態だけに依存する**。
 *
 * `useChat` は差し替える。ここで見たいのは画面の配線であって、ストリーミング
 * 自体（Route Handler 側で固定済み）ではない。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UseChatHelpers } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "./chat-page";
import { metadata } from "@/app/layout";

const useChatMock = vi.fn();

vi.mock("@ai-sdk/react", () => ({
  useChat: () => useChatMock(),
}));

type ChatState = Partial<UseChatHelpers<UIMessage>>;

function mockChat(state: ChatState): void {
  useChatMock.mockReturnValue({
    messages: [],
    sendMessage: vi.fn(),
    regenerate: vi.fn(),
    clearError: vi.fn(),
    status: "ready",
    stop: vi.fn(),
    error: undefined,
    addToolApprovalResponse: vi.fn(),
    ...state,
  });
}

/** 一覧 API（`GET /api/chat/profiles`）の応答。 */
function mockProfiles(available = true): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        defaultProfile: "ds4-deepseek-v4-flash-chat",
        profiles: [
          { id: "ds4-deepseek-v4-flash-chat", label: "Model A", available },
        ],
      }),
    ),
  );
}

/** `search_docs` が返った assistant message。 */
function searchedMessage(): UIMessage {
  return {
    id: "a-1",
    role: "assistant",
    parts: [
      {
        type: "tool-search_docs",
        toolCallId: "call-1",
        state: "output-available",
        input: { query: "テスト tier" },
        output: {
          results: [
            {
              doc_id: "doc-1",
              title: "テスト規約",
              text: "テストは tier で分ける。",
            },
          ],
          sufficient: true,
          guidance:
            "十分な情報が得られました。再検索せずにこの結果から回答してください。",
        },
      },
      { type: "text", text: "サンプル文書に 1 件ありました。", state: "done" },
    ],
  } as unknown as UIMessage;
}

/** `save_note` が承認待ちで止まった assistant message。 */
function approvalPendingMessage(): UIMessage {
  return {
    id: "a-2",
    role: "assistant",
    parts: [
      {
        type: "tool-save_note",
        toolCallId: "call-2",
        state: "approval-requested",
        input: { title: "確認", body: "テスト規約を確認する" },
        approval: { id: "approval-2" },
      },
    ],
  } as unknown as UIMessage;
}

describe("sample chat page", { tags: ["small"] }, () => {
  beforeEach(() => {
    mockProfiles();
    mockChat({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("用途の名称を見出しに出し、利用可能な profile が揃えば送信できる", async () => {
    render(<ChatPage />);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: String(metadata.title),
      }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Submit" })).toBeEnabled();
    expect(screen.queryByTestId("model-guard")).not.toBeInTheDocument();
  });

  it("本文と tool 結果を出す", async () => {
    mockChat({ messages: [searchedMessage()] });
    render(<ChatPage />);

    expect(
      await screen.findByText("サンプル文書に 1 件ありました。"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("sample-response")).toBeInTheDocument();
  });

  it("承認待ちの tool に出した承認は approved: true を 1 回だけ送る", async () => {
    const addToolApprovalResponse = vi.fn();
    mockChat({ messages: [approvalPendingMessage()], addToolApprovalResponse });
    render(<ChatPage />);

    await userEvent.click(await screen.findByRole("button", { name: "承認" }));

    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-2",
      approved: true,
    });
  });

  it("却下は approved: false を 1 回だけ送る", async () => {
    const addToolApprovalResponse = vi.fn();
    mockChat({ messages: [approvalPendingMessage()], addToolApprovalResponse });
    render(<ChatPage />);

    await userEvent.click(await screen.findByRole("button", { name: "却下" }));

    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-2",
      approved: false,
    });
  });

  it("利用不可の profile では送信を止め、理由を先に出す", async () => {
    mockProfiles(false);
    render(<ChatPage />);

    expect(
      (await screen.findByTestId("model-guard")).textContent?.trim(),
    ).not.toBe("");
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("送信は trim 済み本文を 1 回だけ渡す", async () => {
    const sendMessage = vi.fn();
    mockChat({ sendMessage });
    render(<ChatPage />);

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "  テストのtierを検索して  ");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith({
      text: "テストのtierを検索して",
    });
  });
});

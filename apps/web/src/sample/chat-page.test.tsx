/**
 * サンプルエージェントの画面の配線。
 *
 * 固定するのは 3 つ。
 *
 * 1. **描くのは本文・tool 結果・承認 / 却下**である。
 * 2. **承認 UI は共通の `ToolApproval` へ閉じ込める**。承認・却下の
 *    どちらも `addToolApprovalResponse` を 1 回だけ呼ぶ。
 * 3. **送信 guard は profile の状態と承認待ちだけに依存する**。承認・却下の
 *    ボタンは最後の assistant message の承認待ち part にだけ出る。
 *
 * `useChat` は差し替える。ここで見たいのは画面の配線であって、ストリーミング
 * 自体（Route Handler 側で固定済み）ではない。
 */

import { render, screen, within } from "@testing-library/react";
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
function approvalPendingMessage(
  id = "a-2",
  approvalId = "approval-2",
): UIMessage {
  return {
    id,
    role: "assistant",
    parts: [
      {
        type: "tool-save_note",
        toolCallId: `call-${id}`,
        state: "approval-requested",
        input: { title: "確認", body: "テスト規約を確認する" },
        approval: { id: approvalId },
      },
    ],
  } as unknown as UIMessage;
}

/** 承認待ちだった `save_note` に応答が返った assistant message。 */
function approvalSettledMessage(
  state: "output-available" | "output-denied",
): UIMessage {
  return {
    id: "a-2",
    role: "assistant",
    parts: [
      {
        type: "tool-save_note",
        toolCallId: "call-a-2",
        state,
        input: { title: "確認", body: "テスト規約を確認する" },
        approval: {
          id: "approval-2",
          approved: state === "output-available",
        },
        ...(state === "output-available" ? { output: { saved: true } } : {}),
      },
    ],
  } as unknown as UIMessage;
}

function userMessage(id: string, text: string): UIMessage {
  return { id, role: "user", parts: [{ type: "text", text }] };
}

function textMessage(id: string, text: string): UIMessage {
  return {
    id,
    role: "assistant",
    parts: [{ type: "text", text, state: "done" }],
  };
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

  it("@case:S11 本文と tool 結果を出す", async () => {
    mockChat({ messages: [searchedMessage()] });
    render(<ChatPage />);

    expect(
      await screen.findByText("サンプル文書に 1 件ありました。"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("sample-response")).toBeInTheDocument();
  });

  it("@case:A2 承認待ちの tool に出した承認は approved: true を 1 回だけ送る", async () => {
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

  it("@case:A3 却下は approved: false を 1 回だけ送る", async () => {
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

  it("@case:A7 承認待ちのあいだは送信ボタンが押せず、Enter でも送らず、打った文と理由が残る", async () => {
    const sendMessage = vi.fn();
    mockChat({ messages: [approvalPendingMessage()], sendMessage });
    render(<ChatPage />);

    const guard = await screen.findByTestId("approval-guard");
    expect(guard).toHaveAttribute("role", "alert");
    expect(guard.textContent?.trim()).toBe("承認か却下を選んでください。");
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    const input = screen.getByRole("textbox");
    await userEvent.type(input, "次の質問{Enter}");

    expect(sendMessage).not.toHaveBeenCalled();
    expect(input).toHaveValue("次の質問");
  });

  it("@case:A7 承認すると送信できる状態に戻り、打った文は残る", async () => {
    const sendMessage = vi.fn();
    mockChat({ messages: [approvalPendingMessage()], sendMessage });
    const { rerender } = render(<ChatPage />);

    await screen.findByTestId("approval-guard");
    await userEvent.type(screen.getByRole("textbox"), "  次の質問  ");

    mockChat({
      messages: [approvalSettledMessage("output-available")],
      sendMessage,
    });
    rerender(<ChatPage />);

    const submit = await screen.findByRole("button", { name: "Submit" });
    await vi.waitFor(() => expect(submit).toBeEnabled());
    expect(screen.queryByTestId("approval-guard")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("  次の質問  ");

    await userEvent.click(submit);

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith({ text: "次の質問" });
  });

  it("@case:A7 却下すると送信できる状態に戻る", async () => {
    mockChat({ messages: [approvalPendingMessage()] });
    const { rerender } = render(<ChatPage />);

    await screen.findByTestId("approval-guard");

    mockChat({ messages: [approvalSettledMessage("output-denied")] });
    rerender(<ChatPage />);

    const submit = await screen.findByRole("button", { name: "Submit" });
    await vi.waitFor(() => expect(submit).toBeEnabled());
    expect(screen.queryByTestId("approval-guard")).not.toBeInTheDocument();
  });

  it("承認要求の stream の途中は理由を出さず、停止できる", async () => {
    const stop = vi.fn();
    mockChat({
      messages: [approvalPendingMessage()],
      status: "streaming",
      stop,
    });
    render(<ChatPage />);

    const stopButton = await screen.findByRole("button", { name: "Stop" });
    expect(stopButton).toBeEnabled();
    expect(screen.queryByTestId("approval-guard")).not.toBeInTheDocument();

    await userEvent.click(stopButton);

    expect(stop).toHaveBeenCalledTimes(1);
  });

  it("@case:A9 承認・却下のボタンは最後の assistant message の承認待ち part にだけ出る", async () => {
    const addToolApprovalResponse = vi.fn();
    mockChat({
      messages: [
        approvalPendingMessage("a-old", "approval-old"),
        userMessage("u-1", "やっぱり別の質問"),
        approvalPendingMessage("a-new", "approval-new"),
      ],
      addToolApprovalResponse,
    });
    render(<ChatPage />);

    const approvals = await screen.findAllByTestId("tool-approval");
    expect(approvals).toHaveLength(1);

    await userEvent.click(
      within(approvals[0]).getByRole("button", { name: "承認" }),
    );

    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-new",
      approved: true,
    });
  });

  it("@case:A9 最後の message が承認待ちでなければ、古い承認待ち part にボタンを出さない", async () => {
    mockChat({
      messages: [
        approvalPendingMessage("a-old", "approval-old"),
        userMessage("u-1", "やっぱり別の質問"),
        textMessage("a-new", "別の質問に答えました。"),
      ],
    });
    render(<ChatPage />);

    expect(
      await screen.findByText("別の質問に答えました。"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("tool-header")).toBeInTheDocument();
    expect(screen.queryByTestId("tool-approval")).not.toBeInTheDocument();
    await vi.waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled(),
    );
  });

  it("@case:A7 @case:A9 dynamic tool の承認待ちでも承認・却下のボタンが出て、送信は止まる", async () => {
    const addToolApprovalResponse = vi.fn();
    mockChat({
      messages: [
        {
          id: "a-dyn",
          role: "assistant",
          parts: [
            {
              type: "dynamic-tool",
              toolName: "save_note",
              toolCallId: "call-dyn",
              state: "approval-requested",
              input: { title: "確認", body: "テスト規約を確認する" },
              approval: { id: "approval-dyn" },
            },
          ],
        } as unknown as UIMessage,
      ],
      addToolApprovalResponse,
    });
    render(<ChatPage />);

    expect(await screen.findByTestId("tool-header")).toHaveTextContent(
      "save_note",
    );
    const approvals = screen.getAllByTestId("tool-approval");
    expect(approvals).toHaveLength(1);
    expect(screen.getByTestId("approval-guard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    await userEvent.click(
      within(approvals[0]).getByRole("button", { name: "却下" }),
    );

    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-dyn",
      approved: false,
    });
  });
});

/**
 * サンプルエージェントの画面の配線。
 *
 * 固定するのは 4 つ。
 *
 * 1. **描くのは本文・tool 結果・承認 / 却下**である。
 * 2. **承認 UI は共通の `ToolApproval` へ閉じ込める**。承認・却下の
 *    どちらも `addToolApprovalResponse` を 1 回だけ呼ぶ。
 * 3. **送信 guard は profile の状態と承認待ちだけに依存する**。承認・却下の
 *    ボタンは最後の assistant message の承認待ち part にだけ出る。
 * 4. **失敗の表示は中継の固定文言か 1 つの固定文言だけを出し**、承認・却下で
 *    消える。browser や agent のエラー文は画面に出さない。
 *
 * `useChat` は差し替える。ここで見たいのは画面の配線であって、ストリーミング
 * 自体（Route Handler 側で固定済み）ではない。
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UseChatHelpers } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "./chat-page";
import { metadata } from "@/app/layout";
import {
  CHAT_ERROR_MESSAGES,
  CHAT_PROFILE_UNAVAILABLE_CODE,
  CHAT_PROFILE_UNKNOWN_CODE,
  CHAT_UNREADABLE_ERROR_MESSAGE,
  PROFILE_UNAVAILABLE_MESSAGE,
} from "@/lib/chat-profiles";

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

/** 一覧 API が 2 件を返し、2 件目を既定にする。 */
const TWO_PROFILES = {
  defaultProfile: "profile-b",
  profiles: [
    { id: "profile-a", label: "Model A", available: true },
    { id: "profile-b", label: "Model B", available: true },
  ],
};

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

/** 失敗の表示（承認待ちの理由も `role="alert"` なので、文言で選ぶ）。 */
function sendErrorAlert(): HTMLElement | undefined {
  return screen
    .queryAllByRole("alert")
    .find((alert) => alert.textContent?.includes("送信に失敗しました"));
}

/**
 * 承認待ちの直後に切れた状態。`clearError` が `error` を消すので、`useChat` の
 * 差し替えの中で `useState` を持つ（`useChatMock` は render の中で呼ばれる）。
 */
function mockErrorAfterApprovalRequest(
  addToolApprovalResponse: ReturnType<typeof vi.fn>,
  clearError: ReturnType<typeof vi.fn>,
): void {
  useChatMock.mockImplementation(() => {
    const [error, setError] = useState<Error | undefined>(
      () => new TypeError("network error"),
    );
    clearError.mockImplementation(() => setError(undefined));
    return {
      messages: [approvalPendingMessage()],
      sendMessage: vi.fn(),
      regenerate: vi.fn(),
      clearError,
      status: error ? "error" : "ready",
      stop: vi.fn(),
      error,
      addToolApprovalResponse,
    };
  });
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

  it("@case:P2 一覧が揃うと既定の profile が選ばれ、送信できる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(TWO_PROFILES)),
    );
    render(<ChatPage />);

    await vi.waitFor(() =>
      expect(screen.getByTestId("model-select")).toHaveTextContent("Model B"),
    );
    expect(screen.getByTestId("model-select")).not.toHaveTextContent("Model A");
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  });

  it("@case:P4 一覧の再取得に成功すると、選べて送信できる状態に戻る", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json(
          { error: "chat backend is unreachable" },
          { status: 502 },
        ),
      )
      .mockResolvedValueOnce(Response.json(TWO_PROFILES));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatPage />);

    expect(await screen.findByTestId("model-list-error")).toBeInTheDocument();
    expect(screen.getByTestId("model-select")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "再取得" }));

    await vi.waitFor(() =>
      expect(screen.getByTestId("model-select")).toBeEnabled(),
    );
    expect(screen.queryByTestId("model-list-error")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("@case:S1 送った発話と応答のカードを会話に出す", async () => {
    mockChat({
      messages: [
        userMessage("u-1", "テストのtierを検索して"),
        searchedMessage(),
      ],
    });
    render(<ChatPage />);

    const log = await screen.findByRole("log");
    expect(within(log).getByText("テストのtierを検索して")).toBeInTheDocument();
    expect(within(log).getAllByTestId("sample-response")).toHaveLength(1);
  });

  it("@case:S7 会話が空のときは案内を出し、送信すると消える", async () => {
    const { rerender } = render(<ChatPage />);

    const log = await screen.findByRole("log");
    expect(
      within(log).getByRole("heading", { name: "サンプル文書に聞く" }),
    ).toBeInTheDocument();
    expect(
      within(log).getByText(
        "例: 「サンプル文書でテストのtierを検索して説明してください。」",
      ),
    ).toBeInTheDocument();

    mockChat({ messages: [userMessage("u-1", "テストのtierを検索して")] });
    rerender(<ChatPage />);

    expect(
      within(log).queryByRole("heading", { name: "サンプル文書に聞く" }),
    ).not.toBeInTheDocument();
  });

  it("@case:S8 考え中の表示を出し、開閉できる", async () => {
    mockChat({
      messages: [
        {
          id: "a-r",
          role: "assistant",
          parts: [
            { type: "reasoning", text: "検索語を決めている", state: "done" },
            { type: "text", text: "答えました。", state: "done" },
          ],
        } as unknown as UIMessage,
      ],
    });
    render(<ChatPage />);

    expect(await screen.findByTestId("reasoning")).toBeInTheDocument();
    const toggle = screen.getByTestId("reasoning-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("検索語を決めている")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("検索語を決めている")).toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await vi.waitFor(() =>
      expect(screen.queryByText("検索語を決めている")).not.toBeInTheDocument(),
    );
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

  it("@case:P6 @case:X2 利用不可の profile では送信を止め、理由を先に出し、打った文を残す", async () => {
    const sendMessage = vi.fn();
    mockChat({ sendMessage });
    mockProfiles(false);
    render(<ChatPage />);

    const guard = await screen.findByTestId("model-guard");
    expect(guard).toHaveAttribute("role", "alert");
    expect(guard.textContent?.trim()).toBe(PROFILE_UNAVAILABLE_MESSAGE);
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();

    const input = screen.getByRole("textbox");
    await userEvent.type(input, "  次の質問  ");
    await userEvent.click(submit);
    await userEvent.type(input, "{Enter}");

    expect(sendMessage).not.toHaveBeenCalled();
    expect(input).toHaveValue("  次の質問  ");
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

  it("@case:S2 空の文と空白だけの文は送らない", async () => {
    const sendMessage = vi.fn();
    mockChat({ sendMessage });
    render(<ChatPage />);

    const submit = await screen.findByRole("button", { name: "Submit" });
    await vi.waitFor(() => expect(submit).toBeEnabled());
    const input = screen.getByRole("textbox");

    await userEvent.click(submit);
    await userEvent.type(input, "   ");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await userEvent.type(screen.getByRole("textbox"), "   {Enter}");

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("@case:S3 生成中は入力欄を止めて「生成中…」を出し、ボタンを停止に変える", async () => {
    for (const status of ["submitted", "streaming"] as const) {
      mockChat({ status });
      const { unmount } = render(<ChatPage />);

      const input = await screen.findByRole("textbox");
      expect(input).toBeDisabled();
      expect(input).toHaveAttribute("placeholder", "生成中…");
      expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Submit" }),
      ).not.toBeInTheDocument();
      unmount();
    }
  });

  it("@case:S5 Enter キーで送信する", async () => {
    const sendMessage = vi.fn();
    mockChat({ sendMessage });
    render(<ChatPage />);

    const submit = await screen.findByRole("button", { name: "Submit" });
    await vi.waitFor(() => expect(submit).toBeEnabled());
    await userEvent.type(
      screen.getByRole("textbox"),
      "テストのtierを検索して{Enter}",
    );

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith({
      text: "テストのtierを検索して",
    });
  });

  it("@case:S6 生成中に Enter を押しても進行中の run へもう 1 通送らない", async () => {
    const sendMessage = vi.fn();
    mockChat({ sendMessage });
    const { rerender } = render(<ChatPage />);

    const submit = await screen.findByRole("button", { name: "Submit" });
    await vi.waitFor(() => expect(submit).toBeEnabled());
    await userEvent.type(screen.getByRole("textbox"), "次の質問");

    mockChat({ sendMessage, status: "streaming" });
    rerender(<ChatPage />);

    expect(
      await screen.findByRole("button", { name: "Stop" }),
    ).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("@case:A7 @case:X2 承認待ちのあいだは送信ボタンが押せず、Enter でも送らず、打った文と理由が残る", async () => {
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

  it("@case:E5 応答の途中で切れたとき、固定文言と再試行のボタンを出し、browser のエラー文を出さず、途中までの応答を残す", async () => {
    const clearError = vi.fn();
    const regenerate = vi.fn();
    mockChat({
      messages: [
        userMessage("u-1", "テストのtierを検索して"),
        textMessage("a-1", "途中まで"),
      ],
      status: "error",
      error: new TypeError("network error"),
      clearError,
      regenerate,
    });
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());
    expect(sendErrorAlert()).toHaveTextContent(
      `送信に失敗しました: ${CHAT_UNREADABLE_ERROR_MESSAGE}`,
    );
    expect(screen.queryByText(/network error/)).not.toBeInTheDocument();
    expect(screen.getByText("途中まで")).toBeInTheDocument();

    await userEvent.click(
      within(sendErrorAlert()!).getByRole("button", { name: "再試行" }),
    );

    expect(clearError).toHaveBeenCalledTimes(1);
    expect(regenerate).toHaveBeenCalledTimes(1);
  });

  it("@case:E1 @case:X2 送信に失敗すると、中継が積んだ固定文言と再試行のボタンを読み上げ対象で出す", async () => {
    mockChat({
      status: "error",
      error: new Error(
        JSON.stringify({ error: "chat backend is unreachable" }),
      ),
    });
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());
    const alert = sendErrorAlert()!;
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent(
      "送信に失敗しました: chat backend is unreachable",
    );
    expect(alert).not.toHaveTextContent(CHAT_UNREADABLE_ERROR_MESSAGE);
    expect(
      within(alert).getByRole("button", { name: "再試行" }),
    ).toBeInTheDocument();
  });

  it("@case:E3 未知の profile と credential の欠落は別々の文言を出す", async () => {
    const shown: string[] = [];
    for (const code of [
      CHAT_PROFILE_UNKNOWN_CODE,
      CHAT_PROFILE_UNAVAILABLE_CODE,
    ]) {
      mockChat({
        status: "error",
        error: new Error(JSON.stringify({ error: CHAT_ERROR_MESSAGES[code] })),
      });
      const { unmount } = render(<ChatPage />);

      await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());
      expect(sendErrorAlert()).toHaveTextContent(
        `送信に失敗しました: ${CHAT_ERROR_MESSAGES[code]}`,
      );
      shown.push(sendErrorAlert()!.textContent ?? "");
      unmount();
    }

    expect(new Set(shown).size).toBe(2);
  });

  it("@case:E4 upstream の detail と request_id を画面に出さない", async () => {
    const message = CHAT_ERROR_MESSAGES[CHAT_PROFILE_UNKNOWN_CODE];
    mockChat({
      status: "error",
      error: new Error(
        JSON.stringify({
          error: message,
          detail: { message: "サーバ内部の文言" },
          request_id: "9b62d3c6-871f-4cb1-9e40-b71ca359e09f",
        }),
      ),
    });
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());
    expect(sendErrorAlert()).toHaveTextContent(
      `送信に失敗しました: ${message}`,
    );
    expect(screen.queryByText(/サーバ内部の文言/)).not.toBeInTheDocument();
    expect(screen.queryByText(/9b62d3c6/)).not.toBeInTheDocument();
  });

  it("@case:E5 中継の文言でない JSON の error は画面に出さない", async () => {
    mockChat({
      status: "error",
      error: new Error(JSON.stringify({ error: "credential=example-secret" })),
    });
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());
    expect(sendErrorAlert()).toHaveTextContent(
      `送信に失敗しました: ${CHAT_UNREADABLE_ERROR_MESSAGE}`,
    );
    expect(
      screen.queryByText(/credential=example-secret/),
    ).not.toBeInTheDocument();
  });

  it("@case:E6 承認すると失敗の表示が消える", async () => {
    const addToolApprovalResponse = vi.fn();
    const clearError = vi.fn();
    mockErrorAfterApprovalRequest(addToolApprovalResponse, clearError);
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());

    await userEvent.click(await screen.findByRole("button", { name: "承認" }));

    await vi.waitFor(() => expect(sendErrorAlert()).toBeUndefined());
    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-2",
      approved: true,
    });
    expect(clearError).toHaveBeenCalled();
    expect(clearError.mock.invocationCallOrder[0]).toBeLessThan(
      addToolApprovalResponse.mock.invocationCallOrder[0],
    );
  });

  it("@case:E6 却下すると失敗の表示が消える", async () => {
    const addToolApprovalResponse = vi.fn();
    const clearError = vi.fn();
    mockErrorAfterApprovalRequest(addToolApprovalResponse, clearError);
    render(<ChatPage />);

    await vi.waitFor(() => expect(sendErrorAlert()).toBeDefined());

    await userEvent.click(await screen.findByRole("button", { name: "却下" }));

    await vi.waitFor(() => expect(sendErrorAlert()).toBeUndefined());
    expect(addToolApprovalResponse).toHaveBeenCalledTimes(1);
    expect(addToolApprovalResponse).toHaveBeenCalledWith({
      id: "approval-2",
      approved: false,
    });
  });
});

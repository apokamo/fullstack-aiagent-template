// @vitest-environment node
//
// 純関数と transport の配線だけを見る。DOM を必要としないので node に固定する。

/**
 * `/chat` のモデル選択に関わる規則を固定する。
 *
 * とくに **`prepareSendMessagesRequest` が接続点である**ことを、実 `ai` の
 * `DefaultChatTransport` に stub `fetch` を渡して **実際に POST される JSON body**
 * まで通して確かめる。`body: () => ...` からは `trigger` / `messages` を見られない
 * （`ai@7.0.66` `src/ui/http-chat-transport.ts:150-152`）ので、この配線が壊れると
 * 承認再開が「画面で今選んでいる profile」で再開してしまう。画面を通した同じ規則は
 * fake model の E2E（`tests/e2e/ui/sample-chat.spec.ts`）が確かめる。
 */

import { DefaultChatTransport, type UIMessage } from "ai";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CHAT_PROFILE_UNKNOWN_CODE,
  createChatProfileChannel,
  createPrepareSendMessagesRequest,
  describeChatError,
  parseChatProfilesPayload,
  readProblemCode,
  resolveRequestProfile,
} from "@/lib/chat-profiles";

const DS4 = "ds4-deepseek-v4-flash-chat";
const LUNA = "openai-luna-chat";

function userMessage(id: string): UIMessage {
  return { id, role: "user", parts: [{ type: "text", text: "hi" }] };
}

function assistantMessage(id: string): UIMessage {
  return { id, role: "assistant", parts: [{ type: "text", text: "ok" }] };
}

describe("resolveRequestProfile", { tags: ["small"] }, () => {
  it("通常送信・追い質問・再試行は画面で選んでいる profile を使う", () => {
    expect(
      resolveRequestProfile({
        trigger: "submit-message",
        lastMessageRole: "user",
        selected: LUNA,
        lastSent: DS4,
      }),
    ).toBe(LUNA);
    expect(
      resolveRequestProfile({
        trigger: "regenerate-message",
        lastMessageRole: "assistant",
        selected: LUNA,
        lastSent: DS4,
      }),
    ).toBe(LUNA);
  });

  it("@case:A6 承認再開は元の run の profile を保持する", () => {
    expect(
      resolveRequestProfile({
        trigger: "submit-message",
        lastMessageRole: "assistant",
        selected: LUNA,
        lastSent: DS4,
      }),
    ).toBe(DS4);
  });

  it("直前の送信が無い承認再開は現在の選択に落ちる", () => {
    expect(
      resolveRequestProfile({
        trigger: "submit-message",
        lastMessageRole: "assistant",
        selected: DS4,
        lastSent: undefined,
      }),
    ).toBe(DS4);
  });
});

describe("createPrepareSendMessagesRequest", { tags: ["small"] }, () => {
  /** POST された body を記録して空の UI message stream を返す `fetch`。 */
  function recordingFetch(sent: unknown[]) {
    return vi.fn(async (_url: string, init: RequestInit) => {
      sent.push(JSON.parse(String(init.body)));
      return new Response(new ReadableStream({ start: (c) => c.close() }), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });
  }

  it("@case:A6 A 送信 → B へ変更 → 承認再開は A、続く再試行は B を送る", async () => {
    const sent: unknown[] = [];
    const selected = { current: DS4 };
    const lastSent: { current: string | undefined } = { current: undefined };
    const transport = new DefaultChatTransport<UIMessage>({
      api: "/api/chat",
      fetch: recordingFetch(sent) as unknown as typeof fetch,
      prepareSendMessagesRequest: createPrepareSendMessagesRequest({
        selected,
        lastSent,
      }),
    });

    // 1) A を選んだ通常送信。
    await transport.sendMessages({
      chatId: "c1",
      messages: [userMessage("m1")],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: undefined,
    });

    // 2) 画面で B へ切り替える（会話は消えない）。
    selected.current = LUNA;

    // 3) 承認再開（`submit-message` + 末尾が assistant）。
    await transport.sendMessages({
      chatId: "c1",
      messages: [userMessage("m1"), assistantMessage("a1")],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: "a1",
    });

    // 4) 再試行。
    await transport.sendMessages({
      chatId: "c1",
      messages: [userMessage("m1"), assistantMessage("a1")],
      abortSignal: undefined,
      trigger: "regenerate-message",
      messageId: "a1",
    });

    expect(sent.map((body) => (body as { profile: string }).profile)).toEqual([
      DS4,
      DS4,
      LUNA,
    ]);
  });

  it("既定 body を置き換えるので id / messages / trigger / messageId を作り直す", async () => {
    const sent: unknown[] = [];
    const transport = new DefaultChatTransport<UIMessage>({
      api: "/api/chat",
      fetch: recordingFetch(sent) as unknown as typeof fetch,
      prepareSendMessagesRequest: createPrepareSendMessagesRequest({
        selected: { current: LUNA },
        lastSent: { current: undefined },
      }),
    });

    const messages = [userMessage("m1"), assistantMessage("a1")];
    await transport.sendMessages({
      chatId: "c1",
      messages,
      abortSignal: undefined,
      trigger: "regenerate-message",
      messageId: "a1",
    });

    expect(sent[0]).toMatchObject({
      id: "c1",
      messages,
      trigger: "regenerate-message",
      messageId: "a1",
      profile: LUNA,
    });
  });
});

describe("parseChatProfilesPayload", { tags: ["small"] }, () => {
  const valid = {
    defaultProfile: DS4,
    profiles: [
      { id: DS4, label: "Model A", available: true },
      {
        id: LUNA,
        label: "Model B",
        available: false,
        unavailableReason: "サーバーに接続情報が登録されていません",
      },
    ],
  };

  it("想定どおりの応答は取り込む", () => {
    expect(parseChatProfilesPayload(valid)).toEqual(valid);
  });

  it("想定外の shape は部分適用せず null にする", () => {
    // **1 件ずつ列挙する。** 静的 collector は計算した title を読めないので
    // `it.each` のテンプレート title を使わない（`computed-size-tag`）。
    const rejected: unknown[] = [
      [],
      { profiles: valid.profiles },
      { defaultProfile: DS4, profiles: [] },
      { defaultProfile: DS4, profiles: [{ id: DS4, available: true }] },
      {
        defaultProfile: DS4,
        profiles: [{ id: DS4, label: "x", available: "yes" }],
      },
      {
        defaultProfile: "missing",
        profiles: [{ id: DS4, label: "x", available: true }],
      },
    ];

    for (const payload of rejected) {
      expect(parseChatProfilesPayload(payload)).toBeNull();
    }
  });
});

describe("readProblemCode / describeChatError", { tags: ["small"] }, () => {
  it("problem body の code を 1 field だけ読み、読めなければ null", () => {
    const body = JSON.stringify({
      code: CHAT_PROFILE_UNKNOWN_CODE,
      detail: { message: "秘密" },
      request_id: "r1",
    });

    expect(readProblemCode(body)).toBe(CHAT_PROFILE_UNKNOWN_CODE);
    expect(readProblemCode("not json")).toBeNull();
    expect(readProblemCode(JSON.stringify({ code: 42 }))).toBeNull();
  });

  it("中継が積んだ固定文言を取り出し、JSON でない message はそのまま出す", () => {
    const message = JSON.stringify({
      error: "選択したモデルは利用できません。",
    });

    expect(describeChatError(message)).toBe("選択したモデルは利用できません。");
    expect(describeChatError("Failed to fetch")).toBe("Failed to fetch");
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createChatProfileChannel", { tags: ["small"] }, () => {
  it("@case:P7 select() だけが選択を書き換え、次の送信から効く", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        sent.push(JSON.parse(String(init.body)));
        return new Response(new ReadableStream({ start: (c) => c.close() }), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    const channel = createChatProfileChannel("/api/chat");

    channel.select(DS4);
    await channel.transport.sendMessages({
      chatId: "c1",
      messages: [userMessage("m1")],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: undefined,
    });

    channel.select(LUNA);
    await channel.transport.sendMessages({
      chatId: "c1",
      messages: [userMessage("m1"), assistantMessage("a1"), userMessage("m2")],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: undefined,
    });

    expect(sent.map((body) => (body as { profile: string }).profile)).toEqual([
      DS4,
      LUNA,
    ]);
  });
});

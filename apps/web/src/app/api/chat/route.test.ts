// @vitest-environment node
//
// Route Handler は Node の Web API（Request / Response / stream）で動く。
// jsdom に載せる理由が無いので node に固定する。

/**
 * `/api/chat` の中継契約を固定する。
 *
 * ここで守りたいのは **ストリームを素通しすること**。途中でバッファすると
 * `useChat` の逐次描画が死ぬが、それは E2E まで行かないと気付けないので、
 * 「upstream の body をそのまま返している」ことを単体で固定しておく。
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/chat/route";

/** FastAPI が実際に返しているヘッダ（実測値）。 */
const UPSTREAM_HEADERS: Record<string, string> = {
  "Content-Type": "text/event-stream; charset=utf-8",
  // UI Message Stream であることの識別子（プロトコル契約の一部）
  "x-vercel-ai-ui-message-stream": "v1",
  // browser -> Next -> FastAPI を突き合わせる相関 ID
  "x-request-id": "3cfdcfa0-fdf9-48b5-9d72-9a26d0f285c1",
  "x-content-type-options": "nosniff",
  // 引き継いではいけないもの（body を積み替えるため）
  "content-length": "12345",
};

/** SSE を 2 チャンクに分けて流す upstream の偽物。 */
function streamingUpstream(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      controller.enqueue(encoder.encode('data: {"type":"start"}\n\n'));
      controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: UPSTREAM_HEADERS });
}

function chatRequest(): Request {
  return new Request("http://localhost:3000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trigger: "submit-message",
      id: "conv-1",
      messages: [
        { id: "m1", role: "user", parts: [{ type: "text", text: "hi" }] },
      ],
    }),
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chat route handler", { tags: ["small"] }, () => {
  it("FastAPI の SSE をそのまま流す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamingUpstream()),
    );

    const response = await POST(chatRequest());

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    // プロキシがバッファしないことを宣言するヘッダ
    expect(response.headers.get("Cache-Control")).toContain("no-cache");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
    await expect(response.text()).resolves.toContain('data: {"type":"start"}');
  });

  it("upstream の URL とメソッドを引き継ぎ、body を積み替えるヘッダは引き継がない", async () => {
    const fetchMock = vi.fn(async () => streamingUpstream());
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(chatRequest());

    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toMatch(/\/api\/chat$/);
    expect(init.method).toBe("POST");
    expect(response.headers.get("content-length")).toBeNull();
  });

  it("UI Message Stream の識別ヘッダと相関 ID を落とさない", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamingUpstream()),
    );

    const response = await POST(chatRequest());

    expect(response.headers.get("x-vercel-ai-ui-message-stream")).toBe("v1");
    expect(response.headers.get("x-request-id")).toBe(
      UPSTREAM_HEADERS["x-request-id"],
    );
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  });

  it("upstream に繋がらないときは 502 を返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const response = await POST(chatRequest());

    expect(response.status).toBe(502);
  });

  it("upstream のエラーステータスを返し、相関 ID と security headers を落とさない", async () => {
    // 不正な body を送ると FastAPI は 422 を x-request-id 付きで返す。
    // 障害時こそ相関 ID が要るので、エラー経路でも転送する。
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "invalid" }), {
            status: 422,
            headers: {
              "Content-Type": "application/problem+json",
              "x-request-id": "9b62d3c6-871f-4cb1-9e40-b71ca359e09f",
              "x-content-type-options": "nosniff",
            },
          }),
      ),
    );

    const response = await POST(chatRequest());

    expect(response.status).toBe(422);
    expect(response.headers.get("x-request-id")).toBe(
      "9b62d3c6-871f-4cb1-9e40-b71ca359e09f",
    );
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("Content-Type")).toContain("application/json");
  });
});

/**
 * profile 由来の失敗の写像。
 *
 * **読むのは problem body の `code` 1 field だけ**である。`detail` / `errors` /
 * `request_id` を body へ写さない歯止めは維持したまま、profile 由来の理由が
 * 汎用エラーで消えないようにする。
 */
describe("chat route handler: profile errors", { tags: ["small"] }, () => {
  function problem(code: string, status: number): Response {
    return new Response(
      JSON.stringify({
        type: "about:blank",
        title: "Unprocessable Content",
        status,
        detail: { error_code: code, message: "サーバ内部の文言" },
        code,
        errors: [{ pointer: "/profile", code: "missing" }],
        request_id: "9b62d3c6-871f-4cb1-9e40-b71ca359e09f",
      }),
      { status, headers: { "Content-Type": "application/problem+json" } },
    );
  }

  async function errorFor(
    upstream: Response,
  ): Promise<{ status: number; error: string }> {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => upstream),
    );
    const response = await POST(chatRequest());
    const body = (await response.json()) as { error: string };
    return { status: response.status, error: body.error };
  }

  it("未知 profile の 422 と credential 欠落の 503 は、status を保って別々の固定文言へ写す", async () => {
    const unknown = await errorFor(problem("chat_profile_unknown", 422));
    const unavailable = await errorFor(
      problem("chat_profile_unavailable", 503),
    );
    const generic = await errorFor(problem("E4001", 422));

    expect(unknown.status).toBe(422);
    expect(unavailable.status).toBe(503);
    expect(
      new Set([unknown.error, unavailable.error, generic.error]).size,
    ).toBe(3);
  });

  it("upstream の detail / errors / request_id を body へ写さない", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => problem("chat_profile_unknown", 422)),
    );

    const text = await (await POST(chatRequest())).text();

    expect(text).not.toContain("サーバ内部の文言");
    expect(text).not.toContain("pointer");
    expect(text).not.toContain("9b62d3c6");
  });

  it("未知 code と読めない body は同じ汎用文言になる", async () => {
    const unknown = await errorFor(problem("E4001", 422));
    const unreadable = await errorFor(new Response("boom", { status: 500 }));

    expect(unknown.error).toBe(unreadable.error);
  });
});

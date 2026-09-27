// @vitest-environment node
//
// Route Handler は Node の Web API で動く。jsdom に載せる理由が無い。

/**
 * `/api/chat/profiles` の中継契約を固定する。
 *
 * 守りたいのは 3 つ。
 *
 * 1. **200 のときだけ upstream の JSON を返す。** 一覧の中身は backend の registry が
 *    正本で、中継が値を作らない。
 * 2. **未知の upstream body をそのまま公開しない。** 非 2xx と壊れた JSON は固定 body へ
 *    積み替える（provider の生エラーや内部 URL が画面へ出る経路を作らない）。
 * 3. **ブラウザに永続 cache しない。** 可用性は環境で変わる。
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/chat/profiles/route";

const PAYLOAD = {
  defaultProfile: "ds4-deepseek-v4-flash-chat",
  profiles: [
    { id: "ds4-deepseek-v4-flash-chat", label: "Model A", available: true },
    {
      id: "openai-luna-chat",
      label: "Model B",
      available: false,
      unavailableReason: "サーバーに接続情報が登録されていません",
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chat profiles route handler", { tags: ["small"] }, () => {
  it("FastAPI の一覧 endpoint へ GET し、一覧をそのまま no-store で返す", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json(PAYLOAD, { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toMatch(/\/api\/chat\/profiles$/);
    expect(init.method).toBe("GET");
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual(PAYLOAD);
  });

  it("@case:P10 upstream に繋がらないときは 502 を返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const response = await GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("@case:P10 非 2xx は status を保ったまま固定 body に積み替える", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: "内部 host http://api:8000 が落ちている",
            }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );

    const response = await GET();
    const text = await response.text();

    expect(response.status).toBe(500);
    expect(text).not.toContain("api:8000");
    expect(Object.keys(JSON.parse(text) as object)).toEqual(["error"]);
  });

  it("200 でも JSON として読めなければ 502 にする（部分適用しない）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not json", { status: 200 })),
    );

    const response = await GET();

    expect(response.status).toBe(502);
  });
});

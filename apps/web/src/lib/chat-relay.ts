/**
 * chat 系 Route Handler が共有する FastAPI への中継。
 *
 * `/api/chat` の中継規則をまとめる。React にも Next.js の runtime にも
 * 依存しない。
 *
 * ブラウザから FastAPI を直に叩かず、ここを通す理由:
 * - compose では web から api を `http://api:8000`（サービス名）で引く。
 *   **ブラウザからは解決できない**ので、サーバ側で解決する経路が要る
 * - 認証を入れるときは Next 側でセッションを持ち、FastAPI とは内部 token で
 *   繋ぐ方針（docs/reference/security.md）。その差し込み口がここになる
 */

import {
  CHAT_ERROR_MESSAGES,
  CHAT_GENERIC_ERROR_MESSAGE,
  readProblemCode,
} from "@/lib/chat-profiles";
import type { createModuleLogger } from "@/lib/logger";

type ModuleLogger = ReturnType<typeof createModuleLogger>;

/** FastAPI の接続先。**呼ぶ時点で読む**（module 評価時に固定しない）。 */
export function fastapiBaseUrl(): string {
  return process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
}

/** 一覧が取れなかったときに画面へ出す固定文言の元になる body。 */
const UNREACHABLE_BODY = { error: "chat backend is unreachable" };
const UPSTREAM_ERROR_BODY = { error: "chat backend returned an error" };

/**
 * chat の SSE を FastAPI へ中継する。
 *
 * ストリームは触らずそのまま素通しする（`upstream.body` をそのまま返す）。
 * 途中でバッファすると `useChat` の逐次描画が死ぬので、
 * `Cache-Control: no-cache` と `X-Accel-Buffering: no` を明示する。
 *
 * @param request - ブラウザからの POST。
 * @param upstreamPath - FastAPI 側の path。
 * @param logger - 呼び出し元 module の logger。
 */
export async function relayChatStream(
  request: Request,
  upstreamPath: string,
  logger: ModuleLogger,
): Promise<Response> {
  const upstreamUrl = `${fastapiBaseUrl()}${upstreamPath}`;

  // **リクエスト側は読み切ってから送る。** `request.body`（stream）をそのまま
  // 渡す形は Next の dev server 上で upstream に到達せず固まった。
  // 中継で守りたいのは応答の逐次性であって、送信側は会話履歴 1 個分なので
  // 読み切って困らない。
  const body = await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (error) {
    logger.error({ err: error, upstreamUrl }, "chat_upstream_unreachable");
    return Response.json(UNREACHABLE_BODY, { status: 502 });
  }

  if (!upstream.ok || upstream.body === null) {
    logger.error(
      { status: upstream.status, upstreamUrl },
      "chat_upstream_error",
    );
    // エラーのときこそ相関 ID（`x-request-id`）が要る。body は JSON に積み替えるが、
    // upstream のヘッダは正常系と同じ規則で引き継ぐ。
    const headers = forwardedHeaders(upstream.headers);
    headers.set("Content-Type", "application/json");
    /*
     * **body を読むのは非 2xx 経路だけ**（正常系の stream は 1 バイトも触らない）。
     * 読むのは problem body の `code` **1 field だけ**で、profile 由来の理由を
     * 汎用文言で消さないためにある。**`detail` / `errors` /
     * `request_id` は body へ写さない** —— 生の validation detail を画面へ出さない
     * 歯止めはここで維持する。
     */
    const code = readProblemCode(await upstream.text());
    return Response.json(
      { error: CHAT_ERROR_MESSAGES[code ?? ""] ?? CHAT_GENERIC_ERROR_MESSAGE },
      {
        status: upstream.status === 200 ? 502 : upstream.status,
        headers,
      },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: forwardedHeaders(upstream.headers),
  });
}

/**
 * モデル選択欄が使う profile 一覧を FastAPI へ中継する。
 *
 * **未知の upstream body をそのまま公開しない。** 200 のときだけ upstream の
 * JSON を返し、それ以外は固定 body に積み替える。可用性は環境で変わるので
 * `Cache-Control: no-store` を明示し、ブラウザに永続 cache させない。
 *
 * @param upstreamPath - FastAPI 側の path（`/api/chat/profiles` など）。
 * @param logger - 呼び出し元 module の logger。
 */
export async function relayJsonGet(
  upstreamPath: string,
  logger: ModuleLogger,
  eventPrefix: string,
): Promise<Response> {
  const upstreamUrl = `${fastapiBaseUrl()}${upstreamPath}`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, { method: "GET" });
  } catch (error) {
    logger.error(
      { err: error, upstreamUrl },
      `${eventPrefix}_upstream_unreachable`,
    );
    return Response.json(UNREACHABLE_BODY, {
      status: 502,
      headers: { "Cache-Control": "no-store" },
    });
  }

  if (!upstream.ok) {
    logger.error(
      { status: upstream.status, upstreamUrl },
      `${eventPrefix}_upstream_error`,
    );
    // **upstream の body を写さない。** provider の生エラーや内部 URL が
    // 画面へ出る経路を作らない。
    return Response.json(UPSTREAM_ERROR_BODY, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  }

  let payload: unknown;
  try {
    payload = await upstream.json();
  } catch (error) {
    logger.error(
      { err: error, upstreamUrl },
      `${eventPrefix}_upstream_malformed`,
    );
    return Response.json(UPSTREAM_ERROR_BODY, {
      status: 502,
      headers: { "Cache-Control": "no-store" },
    });
  }

  return Response.json(payload, {
    status: 200,
    headers: { "Cache-Control": "no-store" },
  });
}

/**
 * upstream のヘッダを引き継ぐ。**作り直さない。**
 *
 * 落としてはいけないもの:
 * - `x-vercel-ai-ui-message-stream: v1` — UI Message Stream であることの識別子。
 *   採用したプロトコル契約の一部
 * - `x-request-id` — browser → Next → FastAPI を突き合わせる相関 ID。
 *   ここで消すと障害時にクライアントの報告と API ログが繋がらない
 * - FastAPI 側の security headers
 *
 * 落とすのは hop-by-hop ヘッダと、body を積み替えることで意味が変わるもの
 * （`content-length` / `content-encoding` は undici が復号済みの stream を
 * 渡してくるため、そのまま載せると嘘になる）。
 */
export function forwardedHeaders(upstream: Headers): Headers {
  const headers = new Headers();

  upstream.forEach((value, key) => {
    if (!DROPPED_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "text/event-stream; charset=utf-8");
  }
  headers.set("Cache-Control", "no-cache, no-transform");
  // nginx 等のリバースプロキシに「バッファするな」と伝える
  headers.set("X-Accel-Buffering", "no");

  return headers;
}

const DROPPED_HEADERS = new Set([
  // hop-by-hop（RFC 9110 7.6.1）
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  // body を積み替えるので引き継がない
  "content-length",
  "content-encoding",
]);

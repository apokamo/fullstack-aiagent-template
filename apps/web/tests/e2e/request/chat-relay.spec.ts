/**
 * Next.js の中継（`/api/chat`、`/api/chat/profiles`）を本物の FastAPI（fake model）まで
 * 通す Medium。
 *
 * browser を使わず `request` fixture だけで、`baseURL`（Next.js）から中継を通して
 * FastAPI に届ける。中継の分岐そのもの（FastAPI が止まっている場合、503 など）は
 * Small（`src/app/api/chat/route.test.ts` と `profiles/route.test.ts`）と backend の
 * テストが持つ。ここで確かめるのは、本物の境界を通したときの形である。
 *
 * **固定文言は製品の定数から読み、値を写さない。** profile id の一覧も写さない
 * （正本は backend の registry）。
 */

import { randomUUID } from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  CHAT_ERROR_MESSAGES,
  CHAT_GENERIC_ERROR_MESSAGE,
  CHAT_PROFILE_UNKNOWN_CODE,
} from "../../../src/lib/chat-profiles";

type ProfilesBody = {
  defaultProfile: string;
  profiles: Record<string, unknown>[];
};

/** 1 通の user 発話を運ぶ `/api/chat` の body（chat id は毎回変える）。 */
function chatBody(profile: string, text = "こんにちは") {
  return {
    id: `medium-${randomUUID()}`,
    trigger: "submit-message",
    messages: [{ id: "u-1", role: "user", parts: [{ type: "text", text }] }],
    profile,
  };
}

/** 中継を通した一覧の既定 profile。 */
async function defaultProfile(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/chat/profiles");
  expect(response.status()).toBe(200);
  return ((await response.json()) as ProfilesBody).defaultProfile;
}

test(
  "本物の FastAPI の一覧が中継を通って届く",
  { tag: ["@case:P9"] },
  async ({ request }) => {
    const response = await request.get("/api/chat/profiles");

    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const body = (await response.json()) as ProfilesBody;
    expect(Object.keys(body).sort()).toEqual(["defaultProfile", "profiles"]);
    expect(body.profiles.length).toBeGreaterThan(0);
    for (const profile of body.profiles) {
      const keys = Object.keys(profile);
      expect(
        keys.every((key) =>
          ["id", "label", "available", "unavailableReason"].includes(key),
        ),
      ).toBe(true);
      expect(typeof profile.id).toBe("string");
      expect(typeof profile.label).toBe("string");
      expect(typeof profile.available).toBe("boolean");
      // `unavailableReason` は利用不可のときだけ載る。
      expect(["undefined", "string"]).toContain(
        typeof profile.unavailableReason,
      );
    }
    const byDefault = body.profiles.find(
      (profile) => profile.id === body.defaultProfile,
    );
    expect(byDefault?.available).toBe(true);
  },
);

test(
  "本物の FastAPI の SSE が中継を通ってそのまま流れる",
  { tag: ["@case:S10"] },
  async ({ request }) => {
    const profile = await defaultProfile(request);

    const response = await request.post("/api/chat", {
      data: chatBody(profile),
    });

    expect(response.status()).toBe(200);
    const headers = response.headers();
    expect(headers["content-type"]).toContain("text/event-stream");
    expect(headers["x-vercel-ai-ui-message-stream"]).toBe("v1");
    expect(headers["x-request-id"]).toBeTruthy();
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-accel-buffering"]).toBe("no");

    const data = (await response.text())
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => line.slice("data: ".length));
    expect(data.at(-1)).toBe("[DONE]");
    const events = data
      .slice(0, -1)
      .map((line) => JSON.parse(line) as { type: string; delta?: string });
    expect(events[0].type).toBe("start");
    const text = events
      .filter((event) => event.type === "text-delta")
      .map((event) => event.delta ?? "")
      .join("");
    expect(text).not.toBe("");
    expect(events.some((event) => event.type === "finish")).toBe(true);
  },
);

test(
  "未知の profile は 422 と固定文言になり、upstream の detail を写さない",
  { tag: ["@case:E3"] },
  async ({ request }) => {
    const response = await request.post("/api/chat", {
      data: chatBody("no-such-profile"),
    });

    expect(response.status()).toBe(422);
    expect(response.headers()["x-request-id"]).toBeTruthy();
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({
      error: CHAT_ERROR_MESSAGES[CHAT_PROFILE_UNKNOWN_CODE],
    });
    expect(text).not.toContain("request_id");
    expect(text).not.toContain("detail");
  },
);

test(
  "FastAPI の 2xx 以外は status を保って固定 body になる",
  { tag: ["@case:P10"] },
  async ({ request }) => {
    // FastAPI は body の検証で 422 を返す（profile 由来の `code` を持たない）。
    const response = await request.post("/api/chat", { data: {} });

    expect(response.status()).toBe(422);
    expect(response.headers()["x-request-id"]).toBeTruthy();
    expect(await response.json()).toEqual({
      error: CHAT_GENERIC_ERROR_MESSAGE,
    });
  },
);

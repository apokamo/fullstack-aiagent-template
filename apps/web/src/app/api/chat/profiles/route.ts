/**
 * モデル選択欄が使う profile 一覧を FastAPI へ中継する Route Handler。
 *
 * 中継の規則（200 だけ素通し・それ以外は固定 body・`no-store`）は
 * `src/lib/chat-relay.ts` が持つ。
 */

import { relayJsonGet } from "@/lib/chat-relay";
import { createModuleLogger } from "@/lib/logger";

const logger = createModuleLogger("api/chat/profiles");

export async function GET(): Promise<Response> {
  return relayJsonGet("/api/chat/profiles", logger, "chat_profiles");
}

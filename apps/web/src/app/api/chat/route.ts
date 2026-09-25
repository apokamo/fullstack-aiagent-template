/**
 * chat の SSE を FastAPI へ中継する Route Handler。
 *
 * 中継の規則（stream の素通し・非 2xx の固定文言・引き継ぐヘッダ）は
 * `src/lib/chat-relay.ts` が持つ。この file は upstream の path を決める。
 */

import { relayChatStream } from "@/lib/chat-relay";
import { createModuleLogger } from "@/lib/logger";

const logger = createModuleLogger("api/chat");

export async function POST(request: Request): Promise<Response> {
  return relayChatStream(request, "/api/chat", logger);
}

/**
 * Next.js Instrumentation Hook
 *
 * Initializes the pino logger on server startup (Node.js runtime only).
 * This ensures the logger singleton is created before any request handling.
 *
 * **このファイルは `src/` 直下に置くこと（app dir が `src/app` のため）。**
 * Next は `path.join(appDir, "..")` = `src/` しか走査せず、規約位置の外にあると
 * `hasInstrumentationHook` が false になる。すると `next start` では拾われるのに
 * **`output: "standalone"` の成果物からは instrumentation とその trace 依存（pino）が
 * 丸ごと落ちる** —— HTTP 200 も healthcheck も通るため気付けない。
 *
 * @see https://nextjs.org/docs/app/guides/instrumentation
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    // Dynamic import to ensure this only runs in Node.js runtime
    const { logger } = await import("@/lib/logger");
    logger.info("logger_initialized");
  }
}

/**
 * Server-side uncaught error hook. Logs uncaught request errors to pino with
 * `digest` / `request_id` so they correlate with the API logs. Node.js runtime only.
 *
 * @see https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation
 */
export async function onRequestError(
  error: unknown,
  request: { path?: string; method?: string; headers?: Record<string, string> },
): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { createModuleLogger } = await import("@/lib/logger");
  const logger = createModuleLogger("instrumentation");
  const err = error as { message?: unknown; digest?: unknown };
  logger.error(
    {
      server_error: {
        message: typeof err?.message === "string" ? err.message : String(error),
        digest: typeof err?.digest === "string" ? err.digest : undefined,
        request_id: request?.headers?.["x-request-id"],
        path: request?.path,
        method: request?.method,
      },
    },
    "server_request_error",
  );
}

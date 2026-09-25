/**
 * Structured logging module for fullstack-aiagent-template-web (pino)
 *
 * Provides a pino-based structured logger with:
 * - JSON output to stdout (always)
 * - PII redaction for sensitive fields — **任意の深さ・大文字小文字非依存**
 * - UTC ISO 8601 timestamps
 *
 * Usage:
 *   import { createModuleLogger } from "@/lib/logger";
 *   const logger = createModuleLogger("api/health");
 *   logger.info({ status: 200 }, "request_completed");
 *
 * **1 回のログに渡せるオブジェクトは `MAX_LOG_NODES` ノードまで。** 超えると開発・
 * テストでは throw する（本番では `[Truncated]`）。会話履歴や request/response body を
 * 丸ごと渡さず、必要なフィールドか要約を渡すこと。
 *
 * @see apps/web/src/instrumentation.ts (register / onRequestError)
 */

import { Writable } from "stream";
import pino, {
  type Logger,
  type DestinationStream,
  type LoggerOptions,
} from "pino";

const SERVICE_NAME = "fullstack-aiagent-template-web";

/**
 * pino 標準の `redact`。**child bindings 専用の受け持ち**として残している。
 *
 * ログ本体（`logger.info({ ... })` の merge object）は `redactLogPayload()` が
 * 深さ非依存で潰すのでこちらは不要だが、**`formatters` は child bindings に届かない**
 * ——`formatters.bindings` には root の `pid` / `hostname` しか渡ってこない——ため、
 * `logger.child({ token })` を塞げるのは `redact` だけ。
 *
 * パス列挙なので深さ 1 までしか効かない。`createModuleLogger()` は `module` しか
 * bind しないので実害は小さいが、`.child()` を直に呼ぶときは深い秘密値を渡さないこと。
 *
 * @see redactLogPayload - ログ本体側（深さ・大文字小文字に依存しない）
 */
const REDACT_PATHS = [
  "authorization",
  "cookie",
  "password",
  "token",
  "*.authorization",
  "*.cookie",
  "*.password",
  "*.token",
];

/**
 * 値を `[Redacted]` に置換するキー名。**任意の深さ・大文字小文字を無視**して照合する。
 *
 * pino の `redact` がパスの列挙である以上、`request.headers.authorization` のような
 * 深い位置を全部書き下す必要があり、しかも **case sensitive**（実測: `Authorization` は
 * 素通りする）。キー名で潰すこちらは、深さと大文字小文字の列挙漏れが原理的に起きない。
 *
 * ただし **denylist なのでキー名自体の列挙漏れは残る**（例: `x-internal-cred`）。
 * これは収集側（OTel collector / ログパイプライン）の redact を二層目として受ける前提。
 */
const SENSITIVE_KEY_PATTERN =
  /^(?:x-|proxy-)?(?:authorization|cookie|set-cookie|password|token|secret|credentials|api[-_]?key|private[-_]?key|access[-_]?token|refresh[-_]?token|session[-_]?token|client[-_]?secret|session[-_]?id)$/i;

/**
 * 1 回のログ呼び出しで走査するノード（プロパティ）数の上限。
 *
 * **意図的に低い。目的は性能ではなく設計上のガード** ——「巨大なオブジェクトを丸ごと
 * ログに渡す」ことを禁止するための仕掛け。実測でコストは約 50ns/ノードの線形なので、
 * 128 ノードの走査は 10µs 未満で性能上は無意味。典型的な構造化ログ 1 行は 10〜35 ノード
 * なので十分な余裕がある一方、会話履歴の丸ごとダンプ（実測 801 ノード）は確実に捕まる。
 *
 * 深さの上限は設けていない。会話履歴は幅が広く深さは 3 程度で depth cap を通り抜ける
 * ため、コストのブレーキにならない。各段が 1 ノード以上を消費する以上、ノード数の
 * 上限は深いネストも同時に捕まえる。
 */
export const MAX_LOG_NODES = 128;

/** 上限超過時の挙動。@see OVERFLOW_MODE */
export type OverflowMode = "throw" | "truncate";

/**
 * 上限を超えたときにどうするか。
 *
 * **開発・テストでは throw する。** `formatters.log` の throw は `logger.info()` の
 * 呼び出し元まで伝播する（実測済み）ので、スタックトレース付きで即座に落ちて呼び出し箇所が
 * 分かる。**「本番のログ出力を眺めて初めて上限に当たっていたと気付く」という状態を作らない**
 * ため、警告ログではなく throw にしている。
 *
 * **本番では `[Truncated]` に落として続行する。** ログのために request を落とさない。
 */
const OVERFLOW_MODE: OverflowMode =
  process.env.NODE_ENV === "production" ? "truncate" : "throw";

const CENSOR = "[Redacted]";
const CIRCULAR = "[Circular]";
const TRUNCATED = "[Truncated]";

interface WalkState {
  /** 残りノード数。0 になったら超過 */
  budget: number;
  maxNodes: number;
  mode: OverflowMode;
  seen: WeakSet<object>;
}

function overflowError(maxNodes: number): Error {
  return new Error(
    `logger: log payload exceeded MAX_LOG_NODES (${maxNodes}). ` +
      "巨大なオブジェクトを丸ごとログに渡さないこと —— 必要なフィールドだけ、" +
      "あるいは要約（件数 / id）を渡す。これは開発・テストで気付かせるための意図的な " +
      'throw で、本番では超過分が "[Truncated]" に置換されるだけ。' +
      "@see apps/web/src/lib/logger.ts (MAX_LOG_NODES)",
  );
}

function walk(value: unknown, state: WalkState): unknown {
  if (value === null || typeof value !== "object") return value;

  // Error は **その場で `stdSerializers.err()` にかけてから walk する。**
  //
  // 素通しにすると `err.context.headers.authorization` のような **enumerable な
  // 診断メタデータが平文で出る**。pino の
  // error serializer は own enumerable property をそのまま出力に載せるので、walk を
  // 迂回した値が redact されないまま通る。`err` 以外のキー（`{ failure: err }`）でも
  // `JSON.stringify` が同じ property を載せるため同様に漏れる。
  //
  // かといって素朴に clone すると own enumerable property が無いので `"err":{}` に
  // 潰れて message / stack が消える。`stdSerializers.err()` で
  // `{ type, message, stack, ...メタデータ }` の plain object に正規化してから walk
  // すれば、message / stack を保ったままメタデータだけ redact できる。
  //
  // @see BASE_OPTIONS.serializers.err - 二重 serialize と child bindings 経路の手当て
  if (value instanceof Error) {
    if (state.seen.has(value)) return CIRCULAR;
    state.seen.add(value);
    try {
      return walk(
        pino.stdSerializers.err(value) as unknown as Record<string, unknown>,
        state,
      );
    } finally {
      state.seen.delete(value);
    }
  }

  // `toJSON()` を持つ型（Date / Buffer / URL）は **`toJSON()` を呼んでから walk する。**
  //
  // そのまま clone すると `JSON.stringify(new Date())` の ISO 文字列が `{}` になるが、
  // かといって素通しにすると **戻り値が redact も `MAX_LOG_NODES` も丸ごと迂回する**
  // 呼んでから walk すれば両方に載る。`Date` は ISO 文字列（スカラー）を返すので
  // 出力は素通し時と同一。
  //
  // pino の serialization も結局 `toJSON()` を呼ぶので、ここで呼ぶことによる
  // 新たな失敗経路は無い（throw するなら後段でも throw する）。
  if (typeof (value as { toJSON?: unknown }).toJSON === "function") {
    if (state.seen.has(value)) return CIRCULAR;
    state.seen.add(value);
    try {
      return walk((value as { toJSON: () => unknown }).toJSON(), state);
    } finally {
      state.seen.delete(value);
    }
  }

  if (state.seen.has(value)) return CIRCULAR;
  state.seen.add(value);

  try {
    if (Array.isArray(value)) {
      const out: unknown[] = [];
      for (const item of value) {
        if (state.budget <= 0) {
          if (state.mode === "throw") throw overflowError(state.maxNodes);
          // 超過分は素通しせず必ずマーカーに置換する。素通しは漏洩そのもの。
          out.push(TRUNCATED);
          break;
        }
        state.budget -= 1;
        out.push(walk(item, state));
      }
      return out;
    }

    const source = value as Record<string, unknown>;
    const keys = Object.keys(source);
    const out: Record<string, unknown> = {};
    for (let i = 0; i < keys.length; i++) {
      if (state.budget <= 0) {
        if (state.mode === "throw") throw overflowError(state.maxNodes);
        out[TRUNCATED] = `${keys.length - i} more keys`;
        break;
      }
      state.budget -= 1;
      const key = keys[i];
      out[key] = SENSITIVE_KEY_PATTERN.test(key)
        ? CENSOR
        : walk(source[key], state);
    }
    return out;
  } finally {
    // 同じオブジェクトが兄弟から 2 回参照される DAG を `[Circular]` にしないため、
    // 部分木を抜けたら外す。循環（祖先への参照）だけが `[Circular]` になる。
    state.seen.delete(value);
  }
}

/**
 * ログ本体から秘密値を落とす。**深さと大文字小文字に依存しない。**
 *
 * `SENSITIVE_KEY_PATTERN` に一致するキーの値を `[Redacted]` に置換し、循環参照を
 * `[Circular]` に落とし、`MAX_LOG_NODES` を超えたら throw（開発・テスト）または
 * `[Truncated]`（本番）にする。
 *
 * @param value - pino の merge object
 * @param options - テスト用の上書き。既定は `MAX_LOG_NODES` / `OVERFLOW_MODE`
 * @throws 上限超過かつ `onOverflow: "throw"` のとき
 */
export function redactLogPayload(
  value: Record<string, unknown>,
  options?: { maxNodes?: number; onOverflow?: OverflowMode },
): Record<string, unknown> {
  const maxNodes = options?.maxNodes ?? MAX_LOG_NODES;
  return walk(value, {
    budget: maxNodes,
    maxNodes,
    mode: options?.onOverflow ?? OVERFLOW_MODE,
    seen: new WeakSet(),
  }) as Record<string, unknown>;
}

const BASE_OPTIONS: LoggerOptions = {
  level: process.env.LOG_LEVEL || "info",
  timestamp: pino.stdTimeFunctions.isoTime,
  base: { service: SERVICE_NAME },
  redact: REDACT_PATHS,
  formatters: {
    log: (object) => redactLogPayload(object),
  },
  serializers: {
    // pino 既定の `err` serializer を置き換える。理由は 2 つ。
    //
    // 1. **二重 serialize を避ける。** serializer は formatters の後に走るので、
    //    `err` キーには `redactLogPayload()` が正規化済みの plain object が届く。
    //    既定の serializer はそれを再度処理して **`type` を "Error" から "Object" に
    //    書き換えてしまう**（実測）。Error でなければ素通しさせて型情報を守る。
    // 2. **child bindings 経路を塞ぐ。** `formatters` は bindings に届かないので、
    //    `logger.child({ err })` はここを通らないと redact されない。
    err: (value: unknown) =>
      value instanceof Error
        ? redactLogPayload(
            pino.stdSerializers.err(value) as unknown as Record<
              string,
              unknown
            >,
          )
        : value,
  },
};

function buildTransport():
  pino.TransportMultiOptions | pino.TransportSingleOptions | undefined {
  const isProduction = process.env.NODE_ENV === "production";

  if (!isProduction) {
    // Development: use pino-pretty for readable output
    return { target: "pino-pretty" };
  }

  // Production: transport を使わず pino の既定の書き出し先（stdout）に直接書く。
  //
  // transport は worker thread を起動して target を **実行時に require** するため、
  // `output: "standalone"` の file tracing がその依存を追えない。実測した壊れ方:
  //
  //   - `pino/file`  -> `Cannot find module 'pino-abstract-transport'`（register が uncaughtException）
  //   - `pino-roll`  -> `unable to determine transport target for "pino-roll"`（起動できず全 request 500）
  //
  // 以前は `/app/logs` があるときだけ stdout + ローテーションファイルの 2 系統にしていたが、
  // **このリポジトリに `/app/logs` を web へマウントする構成は無く**（staging の compose ファイルも
  // 無い）、standalone では上記のとおり必ず落ちる経路だったため落とした。
  // ログの回収はコンテナの stdout（compose の json-file ドライバ）が担う。
  // ファイル出力が要るときは、実際にマウントする staging 構成と同時に戻すこと。
  return undefined;
}

/**
 * Create the root pino logger instance.
 *
 * In production, uses transports (stdout + optional file).
 * In tests, a stream can be injected to capture output.
 */
function createRootLogger(
  stream?: DestinationStream,
  optionOverrides?: Partial<LoggerOptions>,
): Logger {
  const options = optionOverrides
    ? { ...BASE_OPTIONS, ...optionOverrides }
    : BASE_OPTIONS;
  if (stream) {
    return pino(options, stream);
  }

  const transport = buildTransport();
  if (transport) {
    return pino({ ...options, transport });
  }

  return pino(options);
}

/** Singleton root logger for production use */
let rootLogger: Logger | undefined;

function getRootLogger(): Logger {
  if (!rootLogger) {
    rootLogger = createRootLogger();
  }
  return rootLogger;
}

/**
 * Create a child logger for a specific module.
 *
 * @param moduleName - Module identifier (e.g., "api/health", "instrumentation")
 * @param options - Optional stream for testing
 * @returns Pino child logger with module field bound
 *
 * @example
 * const logger = createModuleLogger("api/health");
 * logger.info({ method: "POST" }, "request_received");
 */
export function createModuleLogger(
  moduleName: string,
  options?: { stream?: DestinationStream; level?: string },
): Logger {
  if (options?.stream) {
    // Test mode: create a fresh logger with the provided stream
    const overrides = options.level ? { level: options.level } : undefined;
    const testLogger = createRootLogger(options.stream, overrides);
    return testLogger.child({ module: moduleName });
  }
  return getRootLogger().child({ module: moduleName });
}

/**
 * Create a test logger that captures output to an in-memory buffer.
 *
 * @param options - Optional overrides (e.g., level)
 * @returns Object with stream and getLines() to retrieve logged output
 *
 * @example
 * const { stream, getLines } = createTestLogger();
 * const logger = createModuleLogger("test", { stream });
 * logger.info("hello");
 * const lines = getLines(); // ["{"level":30,...}"]
 */
export function createTestLogger(options?: { level?: string }): {
  stream: DestinationStream;
  level?: string;
  getLines: () => string[];
} {
  const chunks: string[] = [];

  const stream = new Writable({
    write(chunk: Buffer, _encoding: string, callback: () => void) {
      chunks.push(chunk.toString());
      callback();
    },
  }) as unknown as DestinationStream;

  return {
    stream,
    level: options?.level,
    getLines: () =>
      chunks
        .join("")
        .split("\n")
        .filter((line) => line.trim().length > 0),
  };
}

/** Root logger instance — use createModuleLogger() for application code */
export const logger = getRootLogger();

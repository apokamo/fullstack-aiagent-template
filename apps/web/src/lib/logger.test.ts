// @vitest-environment node
//
// pino は Node の `stream` / `process.stdout` に依存する。jsdom 環境で動かす理由が
// 無いので node に固定する（既定は vitest.config.mts の `environment: "jsdom"`）。

/**
 * `@/lib/logger` の redaction 契約を固定する。
 *
 * pino の `redact` はパスの列挙なので深さの列挙漏れが起き、しかも case sensitive
 * である。`redactLogPayload()` は深さ・大文字小文字に依存しない方式で秘密値を落とし、
 * ノード数の上限で巨大な payload を止める。
 */

import { describe, expect, it } from "vitest";

import {
  MAX_LOG_NODES,
  createModuleLogger,
  createTestLogger,
  redactLogPayload,
} from "@/lib/logger";

/** ログを 1 行吐かせて、その JSON を返す。 */
function logOnce(payload: Record<string, unknown>): Record<string, unknown> {
  const { stream, getLines } = createTestLogger();
  const logger = createModuleLogger("logger.test", { stream });
  logger.info(payload, "test_event");

  const lines = getLines();
  expect(lines).toHaveLength(1);
  return JSON.parse(lines[0]) as Record<string, unknown>;
}

describe("logger fields", { tags: ["small"] }, () => {
  it("ログ 1 行に service 名と module 名を載せる", () => {
    expect(logOnce({})).toMatchObject({
      service: "fullstack-aiagent-template-web",
      module: "logger.test",
      msg: "test_event",
    });
  });
});

describe("logger redaction", { tags: ["small"] }, () => {
  it("トップレベル / 深い階層 / request.headers.* を redact する", () => {
    const output = logOnce({
      authorization: "L0-secret",
      deep: { req: { authorization: "L2-secret" } },
      a: { b: { c: { d: { e: { token: "very-deep" } } } } },
      request: {
        headers: { authorization: "headers-secret", cookie: "session=abc" },
      },
    });

    expect(output).toMatchObject({
      authorization: "[Redacted]",
      deep: { req: { authorization: "[Redacted]" } },
      a: { b: { c: { d: { e: { token: "[Redacted]" } } } } },
      request: {
        headers: { authorization: "[Redacted]", cookie: "[Redacted]" },
      },
    });

    // 部分一致だと見落とすので、秘密値そのものが 1 つも残っていないことを直接見る
    const serialized = JSON.stringify(output);
    for (const secret of [
      "L0-secret",
      "L2-secret",
      "very-deep",
      "headers-secret",
      "session=abc",
    ]) {
      expect(serialized).not.toContain(secret);
    }
  });

  it("キー名の大文字小文字と配列に依存せず redact する（pino の redact は case sensitive）", () => {
    const output = logOnce({
      Authorization: "cap-L0",
      request: { headers: { "X-Api-Key": "cap-api-key" } },
      attempts: [{ token: "cap-t1" }, { token: "cap-t2" }],
    });

    expect(output).toMatchObject({
      Authorization: "[Redacted]",
      request: { headers: { "X-Api-Key": "[Redacted]" } },
      attempts: [{ token: "[Redacted]" }, { token: "[Redacted]" }],
    });
    expect(JSON.stringify(output)).not.toContain("cap-");
  });

  it("auth ファミリーのキー名も redact する", () => {
    const output = logOnce({
      "proxy-authorization": "pa-secret",
      client_secret: "cs-secret",
      private_key: "pk-secret",
      "session-id": "si-secret",
      sessionId: "si2-secret",
    });

    expect(JSON.stringify(output)).not.toContain("-secret");
  });

  it("redact 対象外のフィールドはそのまま出る（token を含むだけのキーも潰さない）", () => {
    // パターンは `^...$` でアンカーしてある。部分一致にすると LLM のログで
    // `max_tokens` / `total_tokens` が丸ごと消える。
    const payload = {
      request_id: "req-abc-123",
      status: 200,
      user: { id: "u_1", tier: "pro" },
      request: {
        headers: { "user-agent": "curl/8", "content-type": "application/json" },
      },
      counts: [1, 2, 3],
      nothing: null,
      max_tokens: 4096,
      total_tokens: 120,
    };

    expect(logOnce(payload)).toMatchObject(payload);
  });

  it("Error の type / message / stack を保ち、付いた診断メタデータは redact する", () => {
    // 素朴に deep walk すると own enumerable property が無いので `{}` に潰れる。
    // Error を素通しさせると、付いたメタデータが walk を迂回して平文で出る。
    // `{ failure: err }` のように err 以外のキーに置いても同じ経路を通す。
    const error = Object.assign(new Error("boom"), {
      statusCode: 500,
      context: { headers: { authorization: "err-meta-secret" } },
    });

    const output = logOnce({ err: error, failure: error });

    for (const key of ["err", "failure"]) {
      expect(output[key]).toMatchObject({
        type: "Error",
        message: "boom",
        statusCode: 500,
        context: { headers: { authorization: "[Redacted]" } },
      });
    }
    expect(typeof (output.err as { stack?: unknown }).stack).toBe("string");
    expect(JSON.stringify(output)).not.toContain("err-meta-secret");
  });

  it("child bindings も redact する（formatters は bindings に届かない）", () => {
    const error = Object.assign(new Error("boom"), {
      context: { authorization: "binding-err-secret" },
    });

    const { stream, getLines } = createTestLogger();
    createModuleLogger("logger.test", { stream })
      .child({ err: error, token: "bound-secret" })
      .error("test_event");

    const output = JSON.parse(getLines()[0]) as Record<string, unknown>;
    expect(output.token).toBe("[Redacted]");
    expect(output.err).toMatchObject({
      type: "Error",
      context: { authorization: "[Redacted]" },
    });
    expect(JSON.stringify(output)).not.toContain("binding-err-secret");
  });

  it("循環参照を [Circular] に落として throw しない", () => {
    const node: Record<string, unknown> = { name: "a" };
    node.self = node;

    const output = logOnce({ node });

    expect(output.node).toEqual({ name: "a", self: "[Circular]" });
  });

  it("自分を参照する Error でも再帰し続けず 1 行を出す", () => {
    const error = new Error("loop") as Error & { self?: unknown };
    error.self = error;

    const output = logOnce({ err: error });

    expect(output.err).toMatchObject({ type: "Error", message: "loop" });
  });

  it("同じオブジェクトを 2 回参照しても [Circular] にしない（DAG は循環ではない）", () => {
    const shared = { id: "s1" };

    const output = logOnce({ left: shared, right: shared });

    expect(output).toMatchObject({ left: { id: "s1" }, right: { id: "s1" } });
  });

  it("toJSON() の戻り値も redact し、ノード数上限に数える", () => {
    // 戻り値を素通しすると、redact も MAX_LOG_NODES も丸ごと迂回する。
    class Credentialed {
      toJSON() {
        return { headers: { authorization: "tojson-secret" } };
      }
    }
    class Big {
      toJSON() {
        return { items: Array.from({ length: 50 }, (_, i) => i) };
      }
    }

    const output = logOnce({ client: new Credentialed() });

    expect(output.client).toEqual({ headers: { authorization: "[Redacted]" } });
    expect(() =>
      redactLogPayload(
        { big: new Big() },
        { maxNodes: 10, onOverflow: "throw" },
      ),
    ).toThrow(/exceeded MAX_LOG_NODES/);
  });
});

describe("logger node limit", { tags: ["small"] }, () => {
  /** `count` 個のノードを持つペイロードを作る。 */
  function payloadWithNodes(count: number): Record<string, unknown> {
    return { items: Array.from({ length: count - 1 }, (_, i) => i) };
  }

  it("上限内なら何もしない", () => {
    const output = logOnce(payloadWithNodes(MAX_LOG_NODES));

    expect(output.items).toHaveLength(MAX_LOG_NODES - 1);
    expect(JSON.stringify(output)).not.toContain("[Truncated]");
  });

  it("開発・テストでは上限超過で throw する（本番のログ出力で気付く運用にしない）", () => {
    const { stream } = createTestLogger();
    const logger = createModuleLogger("logger.test", { stream });

    // NODE_ENV が production 以外なら既定で throw。呼び出し元まで伝播するので
    // スタックトレースから該当のログ呼び出しが特定できる。
    expect(() => logger.info(payloadWithNodes(MAX_LOG_NODES + 100))).toThrow(
      /exceeded MAX_LOG_NODES/,
    );
  });

  it("本番では throw せず [Truncated] に置換し、超過分は素通ししない", () => {
    // 切り捨ては漏洩の代替ではない。上限の外にあった秘密値も出力に残さない。
    const output = redactLogPayload(
      {
        keep: "visible",
        a: 1,
        b: 2,
        nested: { token: "leaked-secret", other: "also-dropped" },
      },
      { maxNodes: 3, onOverflow: "truncate" },
    );

    expect(output).toMatchObject({ keep: "visible", a: 1 });
    expect(output).toHaveProperty(["[Truncated]"]);
    const serialized = JSON.stringify(output);
    expect(serialized).not.toContain("leaked-secret");
    expect(serialized).not.toContain("also-dropped");
  });
});

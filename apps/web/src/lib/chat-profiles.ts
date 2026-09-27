/**
 * `/chat` のモデル選択に関わる純粋な規則。
 *
 * **画面にも中継にも規則を二重に書かない。** 判定は全部ここに置き、
 * client 側の `components/chat/*` と `sample/chat-page.tsx`、server 側で
 * `app/api/chat/route.ts` が使う `lib/chat-relay.ts` の両方から使う。
 * したがってこの module は React にも Next.js の runtime にも依存しない。
 *
 * **表示名は持たない。** `Luna` / `DeepSeek V4 Flash` の正本は backend の
 * registry（`apps/api/core/llm_profiles.py`）で、画面は一覧 API が返した
 * `label` をそのまま出す。
 */

import { DefaultChatTransport } from "ai";
import type { PrepareSendMessagesRequest, UIMessage } from "ai";

// =============================================================================
// 固定文言
// =============================================================================

/** FastAPI の problem body が載せる profile 由来の `code`。 */
export const CHAT_PROFILE_UNKNOWN_CODE = "chat_profile_unknown";
export const CHAT_PROFILE_UNAVAILABLE_CODE = "chat_profile_unavailable";

/** `code` が読めないときと未知 code のときの汎用文言（現行の文言をそのまま維持する）。 */
export const CHAT_GENERIC_ERROR_MESSAGE = "chat backend returned an error";

/**
 * profile 由来の失敗に対して画面へ出す固定文言。
 *
 * **upstream の `detail` / `errors` / `request_id` は写さない。** 生の validation
 * detail が画面へ出ない歯止めを保つ。
 */
export const CHAT_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  [CHAT_PROFILE_UNKNOWN_CODE]:
    "選択したモデルは利用できません。モデルを選び直してください。",
  [CHAT_PROFILE_UNAVAILABLE_CODE]:
    "選択したモデルは現在利用できません。別のモデルを選んでください。",
};

/** 中継が FastAPI に届かなかったときの固定文言。 */
export const CHAT_UNREACHABLE_ERROR_MESSAGE = "chat backend is unreachable";

/**
 * 中継が積んだ固定文言として読めない失敗に出す固定文言。
 *
 * stream の途中の切断や agent の `error` part は中継を通らないので、browser や
 * agent の文言がそのまま `Error.message` に入る。**それを画面に出さない。**
 */
export const CHAT_UNREADABLE_ERROR_MESSAGE = "応答を受け取れませんでした。";

/** 中継が `{ error }` に積む固定文言の全集合。画面はこれに含まれる文言だけを出す。 */
const RELAY_ERROR_MESSAGES: ReadonlySet<string> = new Set([
  ...Object.values(CHAT_ERROR_MESSAGES),
  CHAT_GENERIC_ERROR_MESSAGE,
  CHAT_UNREACHABLE_ERROR_MESSAGE,
]);

/** 一覧を取得できなかったときの固定文言（送信も止める）。 */
export const PROFILE_LIST_FAILED_MESSAGE =
  "モデル一覧を取得できませんでした。再取得してください。";

/** 利用不可の profile が選ばれたまま送信されようとしたときの固定文言。 */
export const PROFILE_UNAVAILABLE_MESSAGE =
  CHAT_ERROR_MESSAGES[CHAT_PROFILE_UNAVAILABLE_CODE];

// =============================================================================
// 一覧の型と検証
// =============================================================================

export type ChatProfileOption = {
  readonly id: string;
  readonly label: string;
  readonly available: boolean;
  readonly unavailableReason?: string;
};

export type ChatProfilesPayload = {
  readonly defaultProfile: string;
  readonly profiles: readonly ChatProfileOption[];
};

/** 一覧取得の状態機械。 */
export type ProfileListStatus = "loading" | "ready" | "failed";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * 一覧応答を検証する。**部分適用しない。**
 *
 * 想定 shape でなければ `null` を返し、呼び出し側は `failed` として扱う ——
 * 一部だけ取り込むと「初期選択が不明なまま送信しない」という要件を破る。
 *
 * @param value - `GET /api/chat/profiles` の JSON。
 * @returns 検証済み payload。想定外の shape なら `null`。
 */
export function parseChatProfilesPayload(
  value: unknown,
): ChatProfilesPayload | null {
  if (!isRecord(value)) {
    return null;
  }
  const { defaultProfile, profiles } = value;
  if (typeof defaultProfile !== "string" || defaultProfile === "") {
    return null;
  }
  if (!Array.isArray(profiles) || profiles.length === 0) {
    return null;
  }

  const parsed: ChatProfileOption[] = [];
  for (const entry of profiles) {
    if (!isRecord(entry)) {
      return null;
    }
    const { id, label, available, unavailableReason } = entry;
    if (typeof id !== "string" || id === "") {
      return null;
    }
    if (typeof label !== "string" || label === "") {
      return null;
    }
    if (typeof available !== "boolean") {
      return null;
    }
    if (
      unavailableReason !== undefined &&
      typeof unavailableReason !== "string"
    ) {
      return null;
    }
    parsed.push(
      unavailableReason === undefined
        ? { id, label, available }
        : { id, label, available, unavailableReason },
    );
  }

  // 初期選択が一覧に無いと「初期選択が不明なまま送信しない」を満たせない。
  if (!parsed.some((entry) => entry.id === defaultProfile)) {
    return null;
  }
  return { defaultProfile, profiles: parsed };
}

/**
 * problem body から `code` を **1 field だけ**読む。
 *
 * 読めない body・`code` を持たない body は `null`。**他の field は一切見ない。**
 *
 * @param text - upstream の応答本文。
 * @returns `code` の文字列、または `null`。
 */
export function readProblemCode(text: string): string | null {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(payload)) {
    return null;
  }
  const code = payload.code;
  return typeof code === "string" ? code : null;
}

/**
 * 中継が積んだ固定文言を、AI SDK の `Error.message` から取り出す。
 *
 * `ai@7` は非 2xx の応答本文をそのまま `Error.message` にするので、画面が
 * 素直に出すと JSON が見えてしまう。**読むのは `error` 1 field だけ**で、
 * それが中継の既知の固定文言（`RELAY_ERROR_MESSAGES`）でなければ
 * `CHAT_UNREADABLE_ERROR_MESSAGE` を返す。**browser や agent のエラー文を
 * 画面に出さない** —— agent の `error` part が同じ形の JSON でも同じ扱いにする。
 *
 * @param message - `useChat` の `error.message`。
 * @returns 画面に出す 1 行。
 */
export function describeChatError(message: string): string {
  let payload: unknown;
  try {
    payload = JSON.parse(message);
  } catch {
    return CHAT_UNREADABLE_ERROR_MESSAGE;
  }
  if (!isRecord(payload)) {
    return CHAT_UNREADABLE_ERROR_MESSAGE;
  }
  const error = payload.error;
  return typeof error === "string" && RELAY_ERROR_MESSAGES.has(error)
    ? error
    : CHAT_UNREADABLE_ERROR_MESSAGE;
}

// =============================================================================
// request ごとの profile 決定規則
// =============================================================================

export type RequestProfileInput = {
  readonly trigger: "submit-message" | "regenerate-message";
  readonly lastMessageRole: UIMessage["role"] | undefined;
  /** 画面で現在選択している profile。 */
  readonly selected: string;
  /** 直前の request が使った profile（初回は `undefined`）。 */
  readonly lastSent: string | undefined;
};

/**
 * その request に載せる profile を決める。
 *
 * | 場面 | 判定 | 使う profile |
 * |---|---|---|
 * | 通常送信・追い質問 | `submit-message` かつ末尾が user | `selected` |
 * | 再試行（`regenerate()`） | `regenerate-message` | `selected` |
 * | 承認再開（`sendAutomaticallyWhen`） | `submit-message` かつ末尾が assistant | `lastSent ?? selected` |
 *
 * 承認再開が `submit-message` で起きることは `ai@7` の `addToolApprovalResponse`
 * / `addToolOutput` の実装が示している。通常送信では user message が append
 * された直後なので末尾は user である。
 *
 * @param input - trigger・末尾 message の role・現在の選択・直前の送信。
 * @returns その request に載せる profile id。
 */
export function resolveRequestProfile(input: RequestProfileInput): string {
  if (
    input.trigger === "submit-message" &&
    input.lastMessageRole === "assistant"
  ) {
    // 承認再開は**元の run の profile を保持する**。
    return input.lastSent ?? input.selected;
  }
  return input.selected;
}

/**
 * `DefaultChatTransport` の `prepareSendMessagesRequest` を組み立てる。
 *
 * **接続点はここだけである。** `body` callback は `resolve(this.body)` が
 * 引数なしで呼ばれるので（`ai@7.0.66` `src/ui/http-chat-transport.ts:150-152`）、
 * その request の `trigger` と `messages` を見られない。
 *
 * **返り値の `body` は既定 body を置き換える**（同 `:175-185`）ので、
 * `id` / `messages` / `trigger` / `messageId` をここで必ず作り直す。受け取った
 * `body`（transport の `body` と呼び出し側 `options.body` の合成）も spread して
 * 取りこぼさない。
 *
 * **`lastSent` の確定点はこの callback の中だけである。** ここが「その request の
 * body が確定する唯一の地点」で、fetch との順序が保証される。`onFinish` や
 * effect で更新すると、承認再開が発火する時点で値が未確定になり得る。
 *
 * @param refs - 現在の選択と直前の送信を持つ ref の組。
 * @returns transport に渡す callback。
 */
export function createPrepareSendMessagesRequest(refs: {
  selected: { current: string };
  lastSent: { current: string | undefined };
}): PrepareSendMessagesRequest<UIMessage> {
  return ({ id, messages, trigger, messageId, body }) => {
    const profile = resolveRequestProfile({
      trigger,
      lastMessageRole: messages.at(-1)?.role,
      selected: refs.selected.current,
      lastSent: refs.lastSent.current,
    });
    refs.lastSent.current = profile;
    return { body: { ...body, id, messages, trigger, messageId, profile } };
  };
}

/** 画面が 1 回だけ作る transport と、その選択の更新点。 */
export type ChatProfileChannel = {
  readonly transport: DefaultChatTransport<UIMessage>;
  /** 画面の選択を transport の callback へ伝える。 */
  readonly select: (profile: string) => void;
};

/**
 * transport と可変ホルダを**同じ寿命で 1 組**作る。
 *
 * ホルダを component 側に置くと、React Compiler の規則に触れる ——
 * ref は render 中に読めず、`useState` が返した値は変更できない。ここでは
 * 可変値を closure に閉じ込め、更新経路を `select()` 1 本にする。**その結果、
 * 「選択がどこから書き換わるか」も 1 か所に固定される。**
 *
 * @param api - POST 先（`/api/chat`）。
 * @returns transport と選択の更新関数。
 */
export function createChatProfileChannel(api: string): ChatProfileChannel {
  const selected = { current: "" };
  const lastSent: { current: string | undefined } = { current: undefined };
  return {
    transport: new DefaultChatTransport<UIMessage>({
      api,
      prepareSendMessagesRequest: createPrepareSendMessagesRequest({
        selected,
        lastSent,
      }),
    }),
    select: (profile: string) => {
      selected.current = profile;
    },
  };
}

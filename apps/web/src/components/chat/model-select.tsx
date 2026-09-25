"use client";

/**
 * `/chat` のモデル選択欄。
 *
 * - 表示名は**一覧 API が返した `label` をそのまま出す**。正本は backend の
 *   registry で、画面には profile 名も表示名も書かない。
 * - 生成中・一覧の `loading` / `failed` は選択できない。
 * - 利用不可の選択肢は `disabled` にし、**理由を文字で添える**（色だけで区別しない）。
 * - `failed` では固定文言と「再取得」を出す。送信の抑止は呼び出し側（`page.tsx`）が
 *   同じ状態から決める。
 */

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  PROFILE_LIST_FAILED_MESSAGE,
  type ChatProfileOption,
  type ProfileListStatus,
} from "@/lib/chat-profiles";

/** 可視ラベルの id。Radix の trigger は `<button>` なので `<label htmlFor>` では結べない。 */
const LABEL_ID = "chat-model-select-label";

export type ModelSelectProps = {
  readonly status: ProfileListStatus;
  readonly profiles: readonly ChatProfileOption[];
  /** 現在選択している profile id（`loading` / `failed` では空文字）。 */
  readonly value: string;
  readonly onValueChange: (value: string) => void;
  /** 生成中は選択を変えられない。 */
  readonly disabled: boolean;
  /** 一覧の再取得（`failed` のときだけ出す）。 */
  readonly onRetry: () => void;
};

export function ModelSelect({
  status,
  profiles,
  value,
  onValueChange,
  disabled,
  onRetry,
}: ModelSelectProps) {
  const locked = disabled || status !== "ready";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-muted-foreground text-sm" id={LABEL_ID}>
        モデル
      </span>
      {/*
        **常に controlled で扱う。** `undefined` から文字列へ変えると Radix が
        「uncontrolled から controlled へ変わった」と警告する。空文字は
        「未選択」を意味し、`SelectValue` の placeholder が出る。
      */}
      <Select disabled={locked} onValueChange={onValueChange} value={value}>
        <SelectTrigger
          aria-labelledby={LABEL_ID}
          className="w-[200px]"
          data-testid="model-select"
          size="sm"
        >
          <SelectValue placeholder="読み込み中…" />
        </SelectTrigger>
        <SelectContent>
          {profiles.map((profile) => (
            <SelectItem
              disabled={!profile.available}
              key={profile.id}
              value={profile.id}
            >
              <span className="flex flex-col items-start">
                <span>{profile.label}</span>
                {profile.available ? null : (
                  /*
                   * 利用不可は色だけで区別しない（design-system.md）。
                   * 文字サイズの下限 13px を下回らない。
                   */
                  <span className="text-[13px] text-muted-foreground leading-[1.6]">
                    {profile.unavailableReason ?? "利用できません"}
                  </span>
                )}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {status === "failed" ? (
        <span
          className="flex flex-wrap items-center gap-2 text-[13px] text-destructive leading-[1.6]"
          data-testid="model-list-error"
          role="alert"
        >
          {PROFILE_LIST_FAILED_MESSAGE}
          <Button onClick={onRetry} size="sm" variant="outline">
            再取得
          </Button>
        </span>
      ) : null}
    </div>
  );
}

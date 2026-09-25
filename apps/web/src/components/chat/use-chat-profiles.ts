"use client";

/**
 * モデル一覧の取得・選択・再取得と、profile 由来の送信 guard。
 *
 * 表示名の正本は backend registry にある。
 *
 * **リロード後の保存はしない**ので localStorage も cookie も使わない。一覧は初回
 * mount で 1 回だけ取り、「再取得」でだけ引き直す（送信のたびに取らない）。
 */

import { useCallback, useEffect, useState } from "react";

import {
  PROFILE_UNAVAILABLE_MESSAGE,
  parseChatProfilesPayload,
  type ChatProfileOption,
  type ChatProfilesPayload,
  type ProfileListStatus,
} from "@/lib/chat-profiles";

export type UseChatProfilesOptions = {
  /**
   * 選択を次の request へ運ぶ経路（`useChatSession().selectProfile`）。
   *
   * 一覧取得が既定値を決めた瞬間にも呼ぶので、transport は最初の送信より前に
   * 正しい profile を持つ。
   */
  onSelect: (value: string) => void;
  /** 一覧 API の path。 */
  endpoint?: string;
};

export type ChatProfilesState = {
  readonly profiles: readonly ChatProfileOption[];
  readonly selected: string;
  readonly status: ProfileListStatus;
  /** 選択中の選択肢（一覧に無ければ undefined）。 */
  readonly selectedOption: ChatProfileOption | undefined;
  /** profile の観点で送信してよいか（`ready` かつ選択が利用可能）。 */
  readonly canSubmit: boolean;
  /**
   * 押せない理由として**先に**出す固定文言。
   *
   * `loading` / `failed` は選択欄側が状態を持つ（`failed` は固定文言と「再取得」）
   * ので、ここでは重ねない。
   */
  readonly guardMessage: string | null;
  select: (value: string) => void;
  reload: () => void;
};

/**
 * 一覧を取得する。失敗と想定外の shape はどちらも `null` にし、部分適用しない。
 */
async function fetchChatProfiles(
  endpoint: string,
): Promise<ChatProfilesPayload | null> {
  try {
    const response = await fetch(endpoint);
    if (!response.ok) return null;
    return parseChatProfilesPayload(await response.json());
  } catch {
    return null;
  }
}

export function useChatProfiles({
  onSelect,
  endpoint = "/api/chat/profiles",
}: UseChatProfilesOptions): ChatProfilesState {
  const [status, setStatus] = useState<ProfileListStatus>("loading");
  const [profiles, setProfiles] = useState<readonly ChatProfileOption[]>([]);
  const [selected, setSelected] = useState("");

  const select = useCallback(
    (value: string) => {
      setSelected(value);
      onSelect(value);
    },
    [onSelect],
  );

  const apply = useCallback(
    (payload: ChatProfilesPayload | null) => {
      if (payload === null) {
        setStatus("failed");
        return;
      }
      setProfiles(payload.profiles);
      select(payload.defaultProfile);
      setStatus("ready");
    },
    [select],
  );

  const reload = useCallback(() => {
    setStatus("loading");
    void fetchChatProfiles(endpoint).then(apply);
  }, [endpoint, apply]);

  // 初期状態が `loading` なので、mount 時の取得は状態を切り替えずに始める。
  useEffect(() => {
    let active = true;
    void fetchChatProfiles(endpoint).then((payload) => {
      if (active) apply(payload);
    });
    return () => {
      active = false;
    };
  }, [endpoint, apply]);

  const selectedOption = profiles.find((profile) => profile.id === selected);

  return {
    profiles,
    selected,
    status,
    selectedOption,
    canSubmit: status === "ready" && selectedOption?.available === true,
    guardMessage:
      status === "ready" && selectedOption?.available === false
        ? PROFILE_UNAVAILABLE_MESSAGE
        : null,
    select,
    reload,
  };
}

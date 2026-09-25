"use client";

/**
 * サンプルエージェントのチャット画面。
 *
 * 骨格・一覧・transport はすべて共通（`ChatShell` / `useChatProfiles` /
 * `useChatSession`）。**サンプル固有の client state は 1 つも無い** ——
 * `onData` を渡さず、送信 guard も profile の状態だけに依存する。
 */

import { ChatShell } from "@/components/chat/chat-shell";
import { ModelSelect } from "@/components/chat/model-select";
import { useChatProfiles } from "@/components/chat/use-chat-profiles";
import { useChatSession } from "@/components/chat/use-chat-session";
import { SampleResponse } from "./response";

export default function SampleChatPage() {
  const session = useChatSession();
  const profiles = useChatProfiles({ onSelect: session.selectProfile });

  return (
    <ChatShell
      canSubmit={profiles.canSubmit}
      emptyState={{
        /*
         * **見出しを繰り返さない。** 画面見出しが用途の名称なので、ここは
         * 短い案内にする。例文は最小 dataset の M1 と同じ文である。
         */
        title: "サンプル文書に聞く",
        description:
          "例: 「サンプル文書でテストのtierを検索して説明してください。」",
      }}
      error={session.error}
      guardMessage={profiles.guardMessage}
      headerAccessory={
        <ModelSelect
          disabled={session.isGenerating}
          onRetry={profiles.reload}
          onValueChange={profiles.select}
          profiles={profiles.profiles}
          status={profiles.status}
          value={profiles.selected}
        />
      }
      isGenerating={session.isGenerating}
      messages={session.messages}
      onRetry={session.retry}
      onStop={session.stop}
      onSubmit={session.send}
      renderAssistant={(message) => (
        <SampleResponse
          message={message}
          onToolApprovalResponse={session.respondToApproval}
        />
      )}
      status={session.status}
      title="サンプルエージェント"
    />
  );
}

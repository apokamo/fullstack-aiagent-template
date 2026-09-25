/**
 * サンプルエージェントのトップページ。
 *
 * 名称と説明は root layout（`src/app/layout.tsx`）の metadata と同じ文言を使う。
 */

import Link from "next/link";

export default function SampleHome() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="font-heading font-semibold text-2xl leading-[1.4]">
        サンプルエージェント
      </h1>
      <p className="text-base text-muted-foreground">
        サンプル文書の検索と、一時メモの承認を試せます。
      </p>
      <Link
        className="rounded-md bg-primary px-4 py-2 text-base text-primary-foreground focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
        href="/chat"
      >
        チャットを開く
      </Link>
    </main>
  );
}

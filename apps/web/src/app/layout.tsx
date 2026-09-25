/**
 * root layout。
 *
 * **`next/font` を使わない。** 書体は `globals.css` の `--app-font-sans`
 * （system sans）なので、build 時の font 取得も self-host 資産も要らない。
 */

import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "サンプルエージェント",
  description: "サンプル文書の検索と、一時メモの承認を試せます。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}

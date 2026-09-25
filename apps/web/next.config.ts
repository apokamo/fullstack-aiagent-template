import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker の runner ステージ用。実際に読まれるファイルだけを trace した自己完結の
  // サーバ（.next/standalone）を出力する。これで runner から devDependencies と
  // next 本体（合計 500MB 超）が消える。
  // 注意: 出力ルートは turbopack.root（= repo root）なので、生成物は
  // `.next/standalone/<WORKDIR からの相対パス>/server.js` に入れ子で出る。
  output: "standalone",
  // Allow Playwright (baseURL: 127.0.0.1, dev 3000 / gate 3100) to access the dev
  // server without Next.js 16 cross-origin blocking that prevents React hydration.
  allowedDevOrigins: ["127.0.0.1"],
  // Explicitly set Turbopack root to monorepo root to avoid multiple-lockfile confusion
  turbopack: {
    root: path.join(__dirname, "../.."),
  },
  // pino, pino-pretty are auto-externalized by Next.js 15+
  // (server-external-packages.jsonc), but listed explicitly for clarity.
  serverExternalPackages: ["pino", "pino-pretty"],
};

export default nextConfig;

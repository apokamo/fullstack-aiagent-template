# Multi-stage Dockerfile for Next.js (web)
# Node.js 26 + npm latest for frontend validation
#
# build context は repo root（compose の `context: .`）だが WORKDIR は web root なので、
# COPY 元だけ `apps/web/` を明示する。

FROM node:26-alpine AS base
RUN npm install -g npm@latest

FROM base AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# development は repo root を /workspace に mount し、ホストと同じ monorepo 構造で
# next dev を動かす。node_modules は compose の anonymous volume に初期コピーされるため、
# macOS の platform 別依存で上書きされないよう image 側にも同じパスで用意する。
FROM base AS development
WORKDIR /workspace/apps/web
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node apps/web/package.json apps/web/package-lock.json ./
# mount point が image に無いと Docker が root 所有で anonymous volume を作り、
# USER node の next dev が .next/dev を作れない。初期コピー元を node 所有で用意する。
RUN mkdir .next && chown node:node .next
ENV NEXT_TELEMETRY_DISABLED=1
USER node
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# runner は `node server.js` しか実行しないので npm を要求しない。
# base（`npm install -g npm@latest` 入り）ではなく素の node イメージから始める。
FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# standalone の server.js は HOSTNAME を bind アドレスとして使う。Docker は HOSTNAME を
# コンテナ ID に設定するため、未指定だとコンテナ IP だけを listen し、publish 経由の
# HTTP は 200 でも compose の healthcheck（localhost:3000）が必ず落ちる。
# `next start` では起きないので、standalone に切り替えた瞬間に出る回帰になる。
ENV HOSTNAME=0.0.0.0
# next.config.ts の turbopack.root が WORKDIR の 2 つ上（= /）に解決されるので、
# standalone の中でアプリは `app/` 1 段の入れ子に出る。段数はホストの monorepo 構造では
# なくコンテナ内の WORKDIR で決まるため、WORKDIR を変えるならここも変わる。
COPY --from=build --chown=node:node /app/.next/standalone/app ./
# .next/static は standalone に含まれないので別途 COPY する。
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]

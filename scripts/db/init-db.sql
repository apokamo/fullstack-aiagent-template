-- Database initialization script
--
-- postgres の docker-entrypoint が **volume が空のとき 1 回だけ** 実行する
-- (`/docker-entrypoint-initdb.d/`)。作り直すには `docker compose down -v`。
--
-- 作るのは 2 つ:
--   - app_dev  : 開発用。`secrets/api.env` の DATABASE_URL の接続先
--   - app_test : pytest 用。`secrets/test.env` の DATABASE_URL の接続先
--
-- DB 名は `secrets/api.host.env` / `secrets/test.env` の `DATABASE_URL` の
-- デフォルトと揃っている。片方だけ変えないこと。
--
-- schema は `public` のまま。ドメイン別 schema も health check テーブルも
-- 置かない。**テーブルは migration が作る** —— migration 基盤は Alembic。
-- DB を作った後に `make migrate`（app_dev）を流すこと。app_test へは verify / gate /
-- test-e2e が自動で適用する。ここに DDL を書き足さないこと ——
-- このファイルは volume が空のとき 1 回しか走らないので、既存 DB には反映されない。

-- =============================================================================
-- Database creation
-- =============================================================================

-- Postgres には CREATE DATABASE IF NOT EXISTS が無く、`secrets/db.env` の
-- POSTGRES_DB が既に片方を作っている場合がある（既定は app_dev）。存在しないものだけを
-- psql の \gexec で流す。
SELECT format('CREATE DATABASE %I', datname)
FROM (VALUES
    ('app_dev'), ('app_test')
) AS wanted(datname)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE pg_database.datname = wanted.datname
)
\gexec

-- =============================================================================
-- Extensions (per database)
-- =============================================================================
-- uuid-ossp: uuid_generate_v4()
-- pgcrypto : gen_random_bytes() / crypt() 等

\connect app_dev
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

\connect app_test
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

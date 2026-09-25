# 技術スタック

この文書は、テンプレートが使う技術と、それを選んだ理由を示します。技術を入れ替えるか判断するときに読みます。
各層の役割と処理の流れは[アーキテクチャ](architecture.md)を参照してください。

## 技術と選定理由

| 層 | 技術 | 選定理由 |
|---|---|---|
| API | FastAPI | 型付きのrequestとresponse、async、SSEの配信をまとめて扱える |
| Agent | Pydantic AI | tool呼び出し、承認待ちでの停止と再開、AI SDK形式のstreamを1つのlibraryで扱える |
| 設定 | pydantic-settings | envの読み込みと型検査を起動時に行い、設定の誤りを起動の失敗にできる |
| Web | Next.js、React、TypeScript | Route HandlerでAPIへの中継をserver側に置ける |
| chat UI | AI SDK、AI Elements、shadcn/ui | 受け取ったstreamの状態管理と、chatの表示部品をそのまま使える |
| DB | PostgreSQL、SQLAlchemy（async）、Alembic | 会話とrunをJSONBで保存し、スキーマをmigrationで管理できる |
| ログ | structlog、pino | backendとwebの両方で構造化ログを出せる |
| テスト | pytest、Vitest、Playwright | backend、web、browserの層ごとに標準的なrunnerを使う |
| 静的検査 | ruff、mypy、ESLint、Prettier、markdownlint | lintとformatをコマンド1つで確かめられる |
| 実行環境 | uv、npm、Docker Compose | lockfileでversionを固定し、DBとserviceを手元で起動できる |
| 開発の流れ | kaji | Issueから設計、実装、レビュー、PRまでの手順をworkflowとして実行できる |

## versionの正本

versionは次のファイルが正本です。文書にはversionを書きません。

| 対象 | ファイル |
|---|---|
| Pythonとbackendのlibrary | `.python-version`、`pyproject.toml`、`uv.lock` |
| Node.jsとwebのlibrary | `.nvmrc`、`apps/web/package.json`、`apps/web/package-lock.json` |
| 文書の検査tool | `package.json`、`package-lock.json` |
| PostgreSQLとcontainerのimage | `docker-compose.yml`、`Dockerfile`、`containers/web/Dockerfile` |
| pre-commitのhook | `.pre-commit-config.yaml` |

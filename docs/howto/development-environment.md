# 開発環境のセットアップ

この文書は、手元でAPIとwebを起動し、テストを実行できるようにする手順を示します。初めてcloneしたときと、
新しいworktreeを作ったときに読みます。テンプレートから自分のリポジトリを作る手順は
[テンプレートの使い方](use-template.md)を参照してください。

## 対応環境

LinuxとmacOSで動かします。WindowsではWSLの中で同じ手順を使います。

## toolchain

Python、uv、Node.js、npm、Docker Composeを用意します。PythonとNode.jsのversionは`.python-version`と
`.nvmrc`が正本です。

```sh
uv sync --frozen --group dev
npm ci --ignore-scripts
npm --prefix apps/web ci --ignore-scripts
npm --prefix apps/web run test:e2e:install
```

最後の行はE2Eで使うbrowserを入れます。E2Eを実行しない場合は省けます。

kajiのworkflowを使う場合は、[kaji](https://github.com/apokamo/kaji)と[Herdr](https://github.com/herdrdev/herdr)も
使います。kajiは開発用依存に入っているので、上の`uv sync`で入ります。Herdrは0.8.2以上を別に入れます。
起動の手順は[workflowの全体像](../dev/workflow-overview.md#起動)を参照してください。

## envとsecret

```sh
make env
make env-secrets-template
```

| file | 役割 |
|---|---|
| `.env` | 秘密でない設定（hostへ公開するportなど）。雛形は`.env.example` |
| `secrets/db.env` | ComposeのPostgreSQLの設定 |
| `secrets/api.env` | APIの設定と、containerで動かすときのDB接続先 |
| `secrets/api.host.env` | hostで動かすときのDB接続先だけ |
| `secrets/test.env` | テスト専用DBの接続先 |

生成したfileの`<set-...>`を実際の値に書き換えます。`secrets/db.env`の`POSTGRES_PASSWORD`に
passwordを決め、DBの接続先はSQLAlchemyの形
（`postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>`）で書きます。`<user>`と`<password>`は
`secrets/db.env`の`POSTGRES_USER`と`POSTGRES_PASSWORD`です。

| file | `<host>:<port>` | `<database>` |
|---|---|---|
| `secrets/api.env` | `db:5432` | `app_dev` |
| `secrets/api.host.env` | `localhost:<DB_HOST_PORT>` | `app_dev` |
| `secrets/test.env` | `localhost:<DB_HOST_PORT>` | `app_test` |

`DB_HOST_PORT`の既定値と変え方は`.env.example`にあります。書き換えたら確認します。

```sh
make env-secrets-check
```

値は表示されません。`secrets/`のdirectoryは700、fileは600にし、gitに入れません。LLMのprofileと
credentialの選び方は`secrets/api.env`のコメントに書いてあります。

## DB

```sh
docker compose up -d --wait db
make migrate
make test-db-init
```

- 初めて起動したとき、PostgreSQLは開発用DBとテスト専用DBを作ります。`secrets/db.env`のuserとpasswordも
  このときだけ反映され、volumeが既にあれば後から変えても効きません
- `make migrate`は開発用DBにmigrationを適用します。`make test-db-init`はテスト専用DBを作り直して
  migrationを適用します
- volumeを残したまま開発用DBだけが無い場合は、`make db-create`で作ります

## 起動

APIとwebを別のterminalで起動します。

```sh
make api-dev
make web-dev
```

browserで`http://localhost:3000`を開きます。Composeで全serviceを起動する場合は
`docker compose up -d --build`を使い、`docker compose ps`で状態を確かめます。containerの構成は
[コンテナservice仕様](../reference/container-services.md)を参照してください。

## port

hostへ公開するportの既定値と変え方は`.env.example`が正本です。別のcheckoutとportが衝突する場合は、`.env`で
変えます。DBのportを変えたら、`secrets/api.host.env`と`secrets/test.env`の接続先も合わせます。

## pre-commit

```sh
uv run pre-commit install
```

commitのたびに、秘密値の検査（gitleaks）、ruff、markdownlint、Prettierが走ります。

## worktreeのbootstrap

新しいworktreeでは、`make env`と`make env-secrets-template`を実行し、secretを安全な手段で用意します。
`.venv`と`node_modules`はworktreeごとに作ります。複数のworktreeで同時にDBを起動する場合は、`.env`の
`DB_HOST_PORT`をworktreeごとに変えます。

## うまくいかないとき

| 症状 | 対処 |
|---|---|
| `DB へ到達できませんでした`と出る | `docker compose up -d --wait db`でDBを起動し、`make env-secrets-check`で接続先を確かめる |
| `DB へ到達できませんでした（InvalidPasswordError ...）`と出る | volumeが別のpasswordで作られている。データを残すなら`docker compose exec db psql -U <user>`で入り、`\password <user>`で`secrets/db.env`の値に合わせる。要らないなら`docker compose down -v`でvolumeを消してから起動し直す |
| DBには届くが、databaseが無い | 開発用は`make db-create`、テスト用は`make test-db-init`を実行する |
| `DB_ENV_CONTEXT を明示してください`と出る | pytestやalembicを直接実行している。make targetから実行するか、`DB_ENV_CONTEXT=test`などを付ける |
| 起動時に`LLM_PROFILE`やcredentialの不足で止まる | `secrets/api.env`の`LLM_PROFILE`と、そのprofileが要るcredentialを設定する |
| containerはhealthyだがhostから繋がらない | portが他のprocessと衝突している。`.env`でportを変える |

# コンテナservice仕様

Composeは`db`、`api`、`web`を定義する。APIのASGI入口は`apps.api.main:app`。DBはPostgreSQL、webはNext.js。host
portは`.env`で設定する。

| Service | 主な設定 | 検証 |
|---|---|---|
| db | `secrets/db.env`、volume | `docker compose ps db` |
| api | `secrets/api.env` | health endpoint |
| web | `apps/web`、API接続先 | browserで表示 |

secretファイルはbuild contextへ含めず、実行時のenv
fileから読む。DBの初期化SQLは会話DB（`app_dev`と`app_test`）だけを作る。

## Webを含む開発環境の更新

```sh
docker compose build api web
docker compose up -d db api web
docker compose ps
```

localの変更だけを確認するときは[起動手順](../howto/development-environment.md#起動)に従い、APIとwebを別terminalで起動してよい。更新後はhealth、チャット、承認flowを確認する。DBとsecretはworktreeごとに接続先を確かめる。

# migrationの追加

この文書は、DBのスキーマを変えるときに、ORMとAlembicのmigrationを揃えて追加する手順を示します。
細かな注意は`migrations/README`にもあります。

## 1. ORMを変える

`apps/api/agent/models.py`など、`apps/api/db/base.py`の`Base`を継承したmodelを変えます。新しいmoduleに
modelを置いた場合は、`migrations/env.py`でそのmoduleをimportします。

## 2. revisionを作る

```sh
docker compose up -d --wait db
make migrate
DB_ENV_CONTEXT=api uv run alembic revision --autogenerate -m "add orders table"
```

- autogenerateは開発用DBの現在の状態と、ORMを比べます。先に`make migrate`で開発用DBを最新にします
- 生成された`migrations/versions/`のfileを必ず読みます。index、CHECK制約、server defaultの差分は
  取りこぼされることがあります
- headは常に1つにします。branchを作りません

## 3. 適用する

```sh
make migrate
make test-db-init
```

`make migrate`は開発用DB、`make test-db-init`はテスト専用DBに適用します。テスト専用DBには
`make verify-backend`なども実行のたびに適用します。

## 4. 確かめる

```sh
make test-on-schema-change
make check-all
```

`make test-on-schema-change`は、空のDBにすべてのmigrationを適用できることと、ORMとmigrationに差が
無いことを確かめます。`make check-all`にも含まれます。

## 戻せない変更

- 列やtableの削除、型の変更のように、`downgrade`で元のデータに戻せない変更は、revisionのdocstringに
  そのことを書きます
- 既存のデータを移す必要がある場合は、スキーマの変更とデータの移行を別のrevisionに分けます
- 公開済みのrevisionは書き換えず、新しいrevisionで直します

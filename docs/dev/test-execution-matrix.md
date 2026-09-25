# テスト実行マトリクス

この文書は、確認に使うlaneの一覧と、変更の種類ごとに実行するlaneを決めます。変更を確かめるときと、lane
の結果を引用するときに読みます。どのテストを書くかは[テスト規約](test-policy.md)を参照してください。

## laneの一覧

| lane | 入口 | 対象 | DB | 外部のsecret |
|---|---|---|---|---|
| Backend verify | `make verify-backend` | lint、format、型、Small・Mediumのテスト | テスト用 | 不要 |
| Backend gate | `make gate-backend` | lint、format、型、決定的なテストすべて、coverage | テスト用 | 不要 |
| Frontend verify | `make verify-frontend` | Prettier、ESLint、TypeScript、Vitest（small） | 不要 | 不要 |
| Documentation | `make verify-docs` | linkとanchor、skill、workflow schema、markdownlint | 不要 | 不要 |
| Schema | `make test-on-schema-change` | 空のDBへのmigrationと、ORMとの差分 | 使い捨て | 不要 |
| Full stack | `make check-all` | Backend gate、Schema、Frontend verify、Documentation | テスト用 | 不要 |
| Fake model E2E | `make test-e2e` | fake modelでのbrowserの流れ | テスト用 | 不要 |
| Real LLM | `LLM_PROFILE=<profile> make test-llm` | providerとの接続と、送るrequestの形 | 不要 | 必要 |
| Eval | `LLM_PROFILE=<profile> make evals` | eval suiteの実行と採点 | 不要 | 必要 |
| Eval（保存と再採点） | `make evals-observe`、`make evals-score SCORE_ARGS="--observations <dir>"` | 観測の保存と、生成しない採点 | 不要 | 必要 |
| Judge validation | `make evals-judge-validate` | ラベル付きの例とジャッジの一致 | 不要 | 必要 |

`make check-all`が決定的な確認の入口です。`make test-e2e`と実LLMのlaneは含みません。各targetの中身は
rootの`Makefile`が正本です。

## 変更の種類ごとのlane

`make check-all`に加えて、次のlaneを実行します。

| 変更 | 追加で実行するlane |
|---|---|
| schema、ORM、migration | `make test-on-schema-change`（`check-all`に含まれる） |
| 画面の流れ、中継、profile選択、承認 | `make test-e2e` |
| prompt、tool、agent loop、HITL | `make test-e2e`、`make test-llm`、`make evals` |
| providerの接続、modelの選択 | 対象profileの`make test-llm`と`make evals` |
| 文書、workflowだけ | `make verify-docs` |

実LLMの結果の合否と観測の扱いは[実LLMとeval](llm-evals.md#変更目的とissueの完了条件)、完走した証跡の
照合は[照合の手順](llm-evals.md#完走と観測証跡の照合)に従います。

## lane recordと引用

- make targetはlaneが成功すると、commitごとのrecordを`test-artifacts/lanes/`に書きます
- 同じcommitで成功したlaneは、実行し直さずにrecordを引用できます。引用してよいかは
  `uv run python -m scripts.testing.lane_record --check <lane>`の終了コードで判定します
- 引用の規則は[lane evidence](../../.claude/skills/_shared/lane-evidence.md)が正本です

## DBのcontext

- make targetは実行context（`DB_ENV_CONTEXT`）を宣言します。`test`はテスト用DB（`secrets/test.env`）、
  `api`は開発用DB（hostでは`secrets/api.host.env`、containerでは`secrets/api.env`）を使います
- `test`のlaneは、DBに到達できることと、DB名がテスト用であることを検査してから実行します。テスト用DBは
  `make test-db-init`で作ります
- `make test-llm`と`make evals`は`api`のcontextで実行し、使ったprofileの情報をrecordとartifactに残します

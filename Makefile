# 環境変数の自動設定
export TEST_ENV ?= local
export RUN_ID ?= $(shell echo "local-$$(date -u +%Y%m%dT%H%M%SZ)-$$(openssl rand -hex 3)")
# **1 度だけ確定させる。** `?=` は再帰展開なので、そのままだと `$(RUN_ID)` を評価する
# たびに `openssl rand` が走り、recipe 内で組み立てた path と子 process が受け取る
# `RUN_ID` が食い違う。この代入で入れ子の `$(MAKE)` も同じ id を見る。
# 環境変数や command line で渡された値は
# そのまま保たれる。
RUN_ID := $(RUN_ID)
export ARCHIVE ?= 0

# ------------------------------------------------------------------------------
# 決定的 lane の profile pin
# ------------------------------------------------------------------------------
# **実 LLM lane では export しない** —— 測定対象の profile は caller が決めるので、
# Make が上書きすると Luna lane が DS4 を測ることになる。
#
# なぜ pin が要るか: `LLM_PROFILE` は必須設定なので、pin しないと決定的 lane が
# operator の `secrets/api.env` の profile と、その provider の有料 key に依存する
# （collection 中に `apps/api/core/config.py` の module 直下 `settings` が構築
# される）。`docs/dev/test-execution-matrix.md` の deterministic 契約に反する。
# DS4 は auth 方式 `none` なので、pin 先は credential を 1 個も要求しない。
#
# `load_api_env()` は既存の OS env を上書きしないので、pin された lane では
# `secrets/api.env` の profile は使われない。これは意図した挙動である。
#
# **target より前に置くこと**。決定的 lane は
# `<target>: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)` で宣言する。
# `:=` は**行を読んだ時点で**展開されるので、この定義をあとに置くと
# 空文字を pin し、その lane は「LLM_PROFILE が未知の値です」で
# collection 前に落ちる。
DETERMINISTIC_LLM_PROFILE ?= ds4-deepseek-v4-flash-chat

# `make` 単独で help を出す。
.DEFAULT_GOAL := help

# API の ASGI 入口。`api-dev` が直に起動し、`playwright.config.ts` も
# **この環境変数から**受け取る（起動 file 名を web 側に二重定義しない）。
export APP_ASGI_APP := apps.api.main:app

# lint / 型チェックの対象。
# migrations/ は production 依存の実コード（コンテナ内から migration を流す）
# なので lint / 型チェックの対象に入れる。生成物（versions/*.py）も含む —— テンプレートは
# migrations/script.py.mako なので、生成直後から緑になるよう揃えてある。
LINT_TARGETS := apps/api conftest.py scripts migrations
TYPE_TARGETS := $(LINT_TARGETS)

# 決定的な pytest の母集団（specialized marker を除外）。gate-backend と test が使う。
# tier単独の部分集合へ全体閾値を掛けないため、pytestのaddoptsではcoverageを起動しない
# （coverage を測るのは gate-backend だけ）。
# workflowごとの選定規則はdocs/dev/test-execution-matrix.mdを正本とする。
PYTEST_GATE_MARKERS := not (on_schema_change or live_api or performance_check or staging_only or smoke or llm)

# **coverage 閾値は 80%**（`pyproject.toml` の `fail_under`）。測る source は
# `apps/api` で、除外は `pyproject.toml` の `[tool.coverage.run] omit` が持つ。
PYTEST_COVERAGE_ARGS := --cov=apps/api --cov-report=term-missing

# `verify-docs` が schema 検証にかける kaji workflow の一覧。`kaji validate` は
# files を必須引数に取るので、空展開は「全件 PASS」ではなく usage error になる。
# それでも空 list を明示的に失敗させるのは、workflow directory を移動したときに
# gate が沈黙しないため。
KAJI_WORKFLOWS := $(shell find .kaji/wf/custom -name '*.yaml' -o -name '*.yml' | sort)

# **実行 context は target が明示する**。pytest /
# alembic / DB script は `DB_ENV_CONTEXT` が無ければ RuntimeError で落ちるので、
# それらを起動する target はすべて下の target 固有変数で context を宣言する。
#   test : テスト用 DB を使う backend test / schema test / E2E / テスト用 DB の初期化
#   api  : app_dev への migration / real-LLM / eval / 起動
#
# migration の接続先は選択した context の必須 `DATABASE_URL` だけから来る。
# `-x db_url=` は撤去した —— credential-bearing な DSN を alembic の argv に
# 載せる経路だったため。
ALEMBIC := uv run alembic
PRINT_TEST_DB_URL := uv run python -c \
	"from scripts.common.db_test_settings import get_db_test_settings; \
	 print(get_db_test_settings().database_url)"

# lane record wrapper。公開品質 target はこれを通り、
# **exit 0 かつ tree が clean のときだけ**
# test-artifacts/lanes/<lane>/<sha>.json を残す。次の phase は
# 再実行せずその record を引用する。生ログは
# test-artifacts/logs/<lane>/$(RUN_ID).log。判定と degradation の正本は
# scripts/testing/lane_record.py と .claude/skills/_shared/lane-evidence.md。
#
# **公開 target 名は行頭リテラルのまま残すこと。** scripts/docs/kaji_skill_rules.py の
# check_references が ^<target>: で Makefile を照合するので、define / eval で
# 生成するとその検査が黙って壊れる。
LANE_RECORD := uv run python -m scripts.testing.lane_record

# 公開 target は `help` に並ぶものだけで、ほかは `_` 始まりの内部 target である。
# どれも非対話で、成否は終了コードで分かる。
.PHONY: help env env-secrets-template env-secrets-check db-create migrate test-db-init \
	api-dev web-dev test test-e2e test-llm evals evals-observe evals-score \
	evals-judge-validate test-on-schema-change \
	verify-backend gate-backend verify-frontend verify-docs check-all clean \
	_prepare-dirs _check-db _check-db-server _assert-test-db _migrate-test-db _verify-static \
	_test-e2e-lane _verify-backend-lane _gate-backend-lane _verify-frontend-lane \
	_verify-docs-lane _check-all-lane

help:
	@echo "Setup:"
	@echo "  make env                  - Generate .env from .env.example (existing file protected)"
	@echo "  make env-secrets-template - Generate secrets/*.env templates (existing files protected)"
	@echo "  make env-secrets-check    - Validate secrets/*.env (values are never printed)"
	@echo "  make db-create            - Create the conversation DB (app_dev; never drops)"
	@echo "  make migrate              - Apply migrations to the dev database (app_dev)"
	@echo "  make test-db-init         - Drop / recreate the test database (app_test) and migrate it"
	@echo ""
	@echo "Run:"
	@echo "  make api-dev              - Start the API with uvicorn --reload"
	@echo "  make web-dev              - Start the web UI (next dev)"
	@echo ""
	@echo "Quality gates (deterministic; no external secret):"
	@echo "  make check-all            - Run every gate below except E2E (the single entry point)"
	@echo "  make verify-backend       - Lint, format, type, and Small/Medium backend tests"
	@echo "  make gate-backend         - Lint, format, type, and the full backend suite with coverage"
	@echo "  make verify-frontend      - Prettier, ESLint, TypeScript, and Vitest Small"
	@echo "  make test-on-schema-change - Apply migrations to a disposable DB and check ORM drift"
	@echo "  make verify-docs          - Markdown links and anchors, kaji skill contracts, workflow schemas, markdownlint"
	@echo "  make test                 - Run the deterministic pytest suite once (no lint, no record)"
	@echo "  make test-e2e             - Run the Playwright E2E with the fake model (app_test)"
	@echo ""
	@echo "Real LLM (needs the selected profile's credential):"
	@echo "  make test-llm             - Real-provider wiring check"
	@echo "  make evals                - Run the eval suite, then grade it (checks + LLM judge)"
	@echo "  make evals-observe        - Run the eval suite and save its observations only"
	@echo "  make evals-score          - Grade a saved run (SCORE_ARGS=\"--observations <dir>\")"
	@echo "  make evals-judge-validate - Check the LLM judge against labelled examples"
	@echo ""
	@echo "  make clean                - Remove test-artifacts/"

_prepare-dirs:
	@for dir in coverage/html coverage/xml coverage/json logs/pytest logs/playwright; do \
		mkdir -p test-artifacts/$$dir || echo "Warning: Failed to create test-artifacts/$$dir"; \
	done

# 選択中の context（`DB_ENV_CONTEXT`）の DB へ到達できるか。到達できなければ原因と
# 次の一手を出してすぐに止める（`scripts/db/check_db.py`）。`_check-db-server` は
# database をこれから作る target 用で、同じ server の `postgres` へ繋ぐ。
_check-db:
	@uv run python -m scripts.db.check_db

_check-db-server:
	@uv run python -m scripts.db.check_db --server

# test context の `DATABASE_URL` が本当にテスト DB を指しているかの検査
# （**名前で弾く**）。`_check-db`（到達性）とは別物 —— あちらは「繋がるか」
# しか見ないので、`app_dev` と同じ DB を書いていても通る。
# 判定は scripts/common/db_guard.py。
_assert-test-db: export DB_ENV_CONTEXT := test
_assert-test-db:
	@uv run python -m scripts.db.assert_test_db

# app_test への適用。**冪等なので毎回呼んでよい**（verify / gate が呼ぶ）。
# drop はしない —— 他プロセスが接続していると `DROP DATABASE` が落ちるため、
# 作り直しは `test-db-init` に分けてある。
#
# **`_assert-test-db` を前提条件にしてある**。DDL を当てる
# 先と、その先で `make test-e2e` が**本物の commit をする**先は同じなので、
# 呼び出し側ごとに歯止めを足すのではなく**書き込む手前**に 1 本置く。
_migrate-test-db: export DB_ENV_CONTEXT := test
_migrate-test-db: _check-db _assert-test-db
	@echo "📝 Applying migrations to the test database..."
	@$(ALEMBIC) upgrade head

# lint / format / 型チェック。verify-backend と gate-backend で共有する。
_verify-static:
	@echo "→ Ruff linting..."
	@uv run ruff check $(LINT_TARGETS)
	@echo "→ Ruff format check..."
	@uv run ruff format $(LINT_TARGETS) --check
	@echo "→ MyPy type checking..."
	@uv run mypy $(TYPE_TARGETS)

# ------------------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------------------

env:
	@echo "📝 Generating .env from .env.example (existing file protected)..."
	@bash scripts/env/generate-env.sh

env-secrets-template:
	@echo "📝 Generating secrets/*.env templates..."
	@bash scripts/env/generate-secrets-template.sh

# 現行 machine の secrets を sanitized に検証する。
# **値は一切出力しない。** URL は scheme / host / port / database だけを報告する。
# これは operator 向けの pre-flight であって、破壊的処理直前の runtime guard
# （scripts/common/db_guard.py）の代替ではない。
env-secrets-check:
	@bash scripts/env/check-secrets.sh

# `scripts/db/init-db.sql` は volume が空のときに 1 回しか走らない。
# 既存 cluster に会話 DB を追加する場合はこの target を使い、
# 続けて `make migrate` で schema を作る。
db-create: export DB_ENV_CONTEXT := api
db-create: _check-db-server
	@echo "→ Creating the conversation database..."
	@uv run python -m scripts.db.create_conversation_db

# app_dev への適用。接続先は **api context の必須 `DATABASE_URL`** だけから来る。
# **head は単数**（branch を作らない / alembic.ini のコメント）。
migrate: export DB_ENV_CONTEXT := api
migrate: _check-db
	@echo "📝 Applying migrations to development database..."
	@$(ALEMBIC) upgrade head
	@echo "✅ Migrations applied."

# app_test を作り直す。migration の履歴ごと捨てたいとき用。
test-db-init: export DB_ENV_CONTEXT := test
test-db-init: _check-db-server _assert-test-db
	@echo "🔄 Recreating the test database..."
	@uv run python -m scripts.db.init_test_db
	@$(MAKE) --no-print-directory _migrate-test-db
	@echo "✅ Test database ready."

# ------------------------------------------------------------------------------
# Run
# ------------------------------------------------------------------------------

# API を host で起動する。
#
# **`LLM_PROFILE` を pin しない。** 通常起動の入口なので、operator が
# `secrets/api.env` で選んだ profile と credential をそのまま使う ——
# 決定的 lane の pin をここへ持ち込むと、起動した API が常に DS4 を名乗る。
#
# listen アドレスは container の CMD（`--host 0.0.0.0 --port 8000`）とは別で、
# host 起動では loopback に閉じる。
api-dev: export DB_ENV_CONTEXT := api
api-dev: _check-db
	@echo "→ Starting the API..."
	@uv run uvicorn $(APP_ASGI_APP) --reload --host 127.0.0.1 --port 8000

# web UI。**`LLM_PROFILE` を pin しない**（通常起動の入口である）。
web-dev:
	@echo "→ Starting the web UI..."
	@npm run web:dev

# ------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------

# 決定的な pytest を 1 回まとめて流す（lint・coverage・record なし）。対象は
# gate-backend と同じで、実 LLM などの specialized marker は除外する。
test: export DB_ENV_CONTEXT := test
test: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
test: _prepare-dirs _migrate-test-db
	uv run pytest -n auto --dist=loadgroup -m "$(PYTEST_GATE_MARKERS)" --no-cov

# 実 LLM プロバイダへの疎通確認（`llm` marker）。gate の pytest 呼び出しは specialized
# marker を除外するので、このテストを走らせる経路はここだけ。
#   - 直列（-n0）: 実サーバを並列に叩かない
#   - --no-cov: 配線確認にカバレッジの意味が無い
#   - 接続先は `LLM_PROFILE` で選ぶ（profile の定義は apps/api/core/llm_profiles.py）
#   - LLM を起動できないときの逃げ道は SKIP_LLM_TESTS=1（既定は「未起動なら赤」）
test-llm: export DB_ENV_CONTEXT := api
test-llm: _prepare-dirs
	@$(LANE_RECORD) test-llm -- uv run pytest -n0 -m llm --no-cov

# 実アプリのtool / HITL契約を複数ケース・複数試行で採点するL2経路。
# 通常gateには入れず、AI品質へ影響する変更でkajiが条件付き実行する。
# provider到達不能やbaseline回帰は非ゼロ終了。結果はgitignoreされたartifactへ保存する。
# **artifact path は runner に聞く。** 宣言と実ファイルが 1 文字でも違うと
# `--check evals` が `missing-artifact` を返し、有料 lane を毎回再実行させる。
# path は `<suite>/<profile>/<run-id>/` なので、Make には解決できない
# 要素（実効 profile）が入る。実 LLM lane の profile は caller が指定し、
# artifact path の決定は runner に任せる。
evals: export DB_ENV_CONTEXT := api
evals: _prepare-dirs
	@set -eu; \
	artifact="$$(uv run python -m apps.api.agent.evals.runner \
		$(EVAL_ARGS) --print-artifact-path)"; \
	PYTHONUNBUFFERED=1 $(LANE_RECORD) evals \
		--artifact "$$artifact" -- \
		uv run python -m apps.api.agent.evals.runner $(EVAL_ARGS)

# 観測の保存だけを行う（ジャッジは呼ばない）。採点は `make evals-score` が
# 保存済みの観測から行うので、agent を再実行せずにジャッジだけを差し替えて
# 採点し直せる。研究実行なので lane record は作らない。出力先は runner が表示する。
evals-observe: export DB_ENV_CONTEXT := api
evals-observe: _prepare-dirs
	@PYTHONUNBUFFERED=1 uv run python -m apps.api.agent.evals.runner --observe \
		$(OBSERVE_ARGS)

# 保存済みの観測を採点する（決定的チェック + LLM ジャッジ）。生成は 1 回もしない。
# baseline との比較が既定で、`--record-reference` を付けると比較しない研究採点になる。
evals-score: export DB_ENV_CONTEXT := api
evals-score:
	@PYTHONUNBUFFERED=1 uv run python -m apps.api.sample.evals.cli score $(SCORE_ARGS)

# ラベル付きの合成会話（apps/api/sample/evals/calibration.json）をジャッジに採点させ、
# ラベルとの一致を報告する。rubric やジャッジを変えたときに実 run より先に使う。
evals-judge-validate: export DB_ENV_CONTEXT := api
evals-judge-validate:
	@PYTHONUNBUFFERED=1 uv run python -m apps.api.sample.evals.cli validate \
		$(JUDGE_ARGS)

# Playwright E2E。**fake モデル**（`AGENT_MODEL_MODE=fake`）で
# 実 LLM 無しにフルスタックを回す。
#
# **`check-all` からは呼ばない。** frontend/fullstackのユーザーフロー変更時に、
# kajiの `issue-final-check` skillが条件付き実行する。
#
# **DB は app_test に向ける。** `E2E_DATABASE_URL` を渡さないと API は
# `secrets/api.host.env` 由来の `DATABASE_URL`（= app_dev）に繋がる
# （`load_api_env()` は既存の OS env を上書きしないので OS env が勝つ）。
# 渡っていなければ `playwright.config.ts` が明示エラーで落ちる。
# `_migrate-test-db` に依存させているのは、**追加した migration が app_test に
# 当たっている保証**が要るため。
#
# **`_migrate-test-db` 経由で `_assert-test-db` が先に走る。** presence チェック
# （config 側）は「値が入っているか」しか見ないので、test context の `DATABASE_URL` を
# app_dev と同じ DB に書き間違えたときに E2E が開発 DB へ実 commit してしまう。
# 名前で弾くのは Makefile 側の責務（判定規則を TypeScript 側にも実装しないため）。
#
# **E2E は本物の commit をするので app_test に行が残る**（medium の `db_session` と
# 違い rollback されない）。会話 id はページロードごとに一意なので衝突はしない。
#
# `playwright test` は 0 件で exit 1 になる。これは直さない ——
# spec が消えたときに気付けるほうが良い。
test-e2e: export DB_ENV_CONTEXT := test
test-e2e: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
test-e2e:
	@$(LANE_RECORD) test-e2e -- $(MAKE) _test-e2e-lane

_test-e2e-lane: export DB_ENV_CONTEXT := test
_test-e2e-lane: _prepare-dirs _migrate-test-db
	@echo "🎭 Running the E2E with the fake model..."
	@url=$$($(PRINT_TEST_DB_URL)) && \
	  E2E_DATABASE_URL="$$url" PLAYWRIGHT_GATE=1 npm run test:fe:e2e

# DDL / migration のテスト（`on_schema_change` marker）。使い捨て DB を作って
# 「空 DB に upgrade head が通るか」「ORM と migration に drift が無いか」を見る。
# gate-backend の pytest は specialized marker を除外するため、実行経路はここだけ
# （`check-all` が呼ぶ）。直列（-n0）なのは DB を作っては壊すため。
test-on-schema-change: export DB_ENV_CONTEXT := test
test-on-schema-change: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
test-on-schema-change: _prepare-dirs _check-db
	@$(LANE_RECORD) test-on-schema-change -- \
		uv run pytest -n0 -m on_schema_change --no-cov

# ------------------------------------------------------------------------------
# Quality gates
# ------------------------------------------------------------------------------

verify-backend: export DB_ENV_CONTEXT := test
verify-backend: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
verify-backend:
	@$(LANE_RECORD) verify-backend -- $(MAKE) _verify-backend-lane

_verify-backend-lane: export DB_ENV_CONTEXT := test
_verify-backend-lane: _verify-static _prepare-dirs _migrate-test-db
	@echo "→ Running Small tests..."
	@uv run pytest -n auto --dist=loadgroup --test-size=small --no-cov
	@echo "→ Running Medium tests..."
	@uv run pytest -n auto --dist=loadgroup --test-size=medium --no-cov
	@echo "✅ Backend verification checks passed!"

# verify-backend を依存にすると small / medium を二重に実行することになるので、
# 共通部分（_verify-static）だけを依存にしてテストは S/M/L を 1 回で回す。
gate-backend: export DB_ENV_CONTEXT := test
gate-backend: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
gate-backend:
	@$(LANE_RECORD) gate-backend -- $(MAKE) _gate-backend-lane

_gate-backend-lane: export DB_ENV_CONTEXT := test
_gate-backend-lane: _verify-static _prepare-dirs _migrate-test-db
	@echo "→ Running S/M/L tests (parallel, specialized markers excluded)..."
	@uv run pytest -n auto --dist=loadgroup -m "$(PYTEST_GATE_MARKERS)" \
		$(PYTEST_COVERAGE_ARGS)
	@echo "✅ All backend checks passed!"

verify-frontend:
	@$(LANE_RECORD) verify-frontend -- $(MAKE) _verify-frontend-lane

_verify-frontend-lane:
	@echo "→ Prettier format check..."
	@npm run web:format:check
	@echo "→ ESLint checking..."
	@npm run web:lint
	@echo "→ TypeScript checking..."
	@npm run typecheck:fe
	@echo "→ Running vitest Small tests..."
	@npm run test:fe:small
	@echo "✅ Frontend verification checks passed!"

verify-docs:
	@$(LANE_RECORD) verify-docs -- $(MAKE) _verify-docs-lane

_verify-docs-lane:
	@echo "🔗 Checking local documentation links..."
	@node scripts/docs/check-links.js
	@echo "🧭 Checking kaji skill contracts..."
	@uv run python -m scripts.docs.check_kaji_skills
	@echo "🧩 Validating kaji workflow schemas..."
	@test -n "$(KAJI_WORKFLOWS)" || { echo "no kaji workflow YAML found"; exit 1; }
	@uv run kaji validate $(KAJI_WORKFLOWS)
	@echo "📝 Running blocking markdownlint..."
	@npm run docs:lint
	@echo "✅ Documentation checks passed!"

# `make check-all` 1 本で決定的な検証が完結する（非対話、外部 secret 不要）。
# CI に組み込むときもこの target を呼ぶ。
#
# `test-on-schema-change` をここに入れているのは、`gate-backend` の pytest が
# specialized marker を除外していて、これを入れないと「空 DB に migration が通る」を
# 誰も自動で確かめない状態になるため。
# **再検討トリガー**: migrationが増えて実行が著しく遅くなったとき。
#
# **E2E（`make test-e2e`）はここに入れない。** 通常gateの対象外で、kajiが
# 変更scopeから条件付き実行する。実行経路と安全条件は docs/dev/test-execution-matrix.md。
check-all: export LLM_PROFILE := $(DETERMINISTIC_LLM_PROFILE)
check-all:
	@$(LANE_RECORD) check-all -- $(MAKE) _check-all-lane

_check-all-lane:
	@echo "🔍 Running full-stack final gate..."
	@$(MAKE) gate-backend
	@echo "→ Running schema/migration tests..."
	@$(MAKE) test-on-schema-change
	@$(MAKE) verify-frontend
	@$(MAKE) verify-docs
	@echo "✅ Full-stack quality gate passed!"

clean:
	@echo "Cleaning test artifacts..."
	@find test-artifacts -mindepth 1 ! -name README.md -delete 2>/dev/null || true

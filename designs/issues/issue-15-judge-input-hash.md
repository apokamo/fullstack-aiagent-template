# Issue #15 judge に input_hash を書き写させず、写し間違いで採点が欠けないようにする

- Issue: #15（調査: #1、依存: #14（CLOSED、PR #16 は main `8609c71` でマージ済み））
- type: `type:bug`、area: `area:backend`、`area:agent-ai`
- base: `origin/main` `8609c71defe5de497624fa3315ce9b8bca28bbac`

## 目的と範囲外

直すこと（bug rubric）:

- judge の wire 契約から `input_hash` を外す。応答（`WireResult`）にも、judge へ送る request body にも入れず、
  指示文の `Echo input_hash exactly.` を消す。写し間違いで観測や校正の例がまとめて落ちる経路を、構造的に無くす
- `JudgeResult.input_hash` と診断の `input_hash` には、アプリが送った入力の `canonical_hash(value)` を入れる。
  「どの入力を採点したか」という意味は保つ
- wire 契約が変わるので `wire_policy` を上げ、judge の `config_hash` と `scoring_identity_hash` が変わる。
  sample suite の baseline を v2 として測り直して登録する
- `reparse_diagnostic` は旧形式（応答に `input_hash` を含む）の診断を読まず、旧形式だと分かる理由で拒否する

範囲外（Issue #15 の `## 範囲外` と決定事項）:

- `validate` 経路で欠落の理由を残すこと（#14 で完了済み）
- ほかの judge 契約（item と reference の重複、answer の必須引用、reference の turn 所属）、rubric、
  calibration のラベル
- judge のモデル、effort、profile
- 自動の再試行、欠けた項目を pass として補完すること
- 指示文の `Echo input_hash exactly.` 以外の文の変更

## 再現と実際の挙動

| 手順 | 実際 | 期待 |
|---|---|---|
| judge が `input_hash` を 1 文字写し間違えた応答を返す（MockTransport で `input_hash` を別の 64 桁 hex にする。base では `test_sample_judge_validation.py` の `input_hash` 行が再現している） | `parse_result` が `judge_input_hash_mismatch` を投げ、その観測の全項目が `parser_error` になる。校正は未受理、`make evals` / `make evals-score` は `judge_failures` で blocking failure | 応答に `input_hash` の欄が無く、写し間違いが起こりえない。項目の採点がそろっていれば `ok` |
| 実 LLM（`gpt-6-luna`、effort low）の診断 176 件 | 2 件が hash の写し間違い（2 文字の脱落を pattern に合わせて末尾補完したもの 1 件、1 文字の置換 1 件）。`make evals-judge-validate` の欠落（同一 identity で 140 request 中 3 件）も同じ原因が最有力（#1 の調査） | 写し間違いによる欠落が 0 件 |

## 根拠にした一次情報

| 事実 | 根拠 |
|---|---|
| 指示文がエコーを求める | `apps/api/agent/evals/judge_client.py:57` `Echo input_hash exactly.` |
| 応答 schema が `input_hash: Digest` を持つ。strict schema は pattern `^[0-9a-f]{64}$` しか強制できない | `judge_client.py:179-181`、`evidence.py` の `Digest` |
| 照合と、応答の値をそのまま `JudgeResult` に入れる | `judge_client.py:228-229`（`judge_input_hash_mismatch`）、`judge_client.py:258`（`input_hash=wire.input_hash`） |
| request body の先頭に `input_hash` がある | `judge_client.py:355-361` |
| 1 request に 1 入力。`value` はアプリ自身が送った値なので、対応はアプリ側で保証できる | `ResponsesJudge._grade`（`judge_client.py:345-`）、クラス docstring「One request per conversation」 |
| `Record` は `extra="forbid"`。`WireResult` から欄を外すと、`input_hash` を含む応答は `ValidationError` になる | `evidence.py:38-41` |
| 失敗時の `JudgeResult` も `canonical_hash(value)` を入れている | `judge_client.py:206-216`（`failed_result`） |
| rescore は `result.input_hash != input_hash` を照合する（`JudgeClient` の別実装への防御） | `rescore.py:194`、`rescore.py:247-251` |
| `scoring_identity` は judge identity（`config_hash`）と、`judge_client.py` を含む集計 code の file digest を畳む | `apps/api/sample/evals/session.py:58`（`AGGREGATION_FILES`）、`session.py:109-129` |
| `config_hash` は設定・指示文・rubric・`WireResult` の schema・`wire_policy` を畳む | `judge_client.py:118-139` |
| base の `config_hash` は `9bac091c…f882`、`scoring_identity_hash` は `d5c026d4…981d9c`（baseline v1 と一致） | 設計時に base で計算（下の「実装前の基準」） |
| baseline は profile ごとに 1 ファイル。v1 の根拠 artifact は `v1/` に残る | `evals-evidence/README.md`、`docs/dev/llm-evals.md`「baselineとidentity」「測定記録の置き場」 |
| v1 の測り方: 校正 5 回、`make evals-observe` と `make evals-score SCORE_ARGS="--observations <run> --record-reference"` の組 5 回。artifact は commit SHA の field（`commit_sha`、`scoring_sha`、`source_sha`）だけを除いた JSON | `evals-evidence/baselines/sample/openai-luna-responses/v1/README.md` |
| `reparse_diagnostic` を呼ぶのはテストだけ。診断は git 管理外で、v1 の根拠 artifact に診断は無い | `test_eval_judge.py:283`、v1 の `README.md`「files」、grill-me provenance |
| 旧診断の `version` は `judge-diagnostic-v1` | `judge_client.py:379` |
| tracked baseline の identity を検査するテストがある | `test_sample_judge_validation.py:236-245`（`baseline["version"] == "v1"`） |
| 実行されない hash 不一致の分岐がある（parametrize に対応する kind が無い） | `test_eval_judge.py:164-180` |
| 比較つき `make evals` は identity が 1 項目でも違う baseline とは比べず、provider request の前に止まる | `apps/api/sample/evals/baseline.py`（`baseline_failures`）、`docs/dev/llm-evals.md` |
| 閾値未達は FAIL のまま記録し、測定内容を手で変更した baseline は登録しない | `docs/dev/llm-evals.md`「完走と観測証跡の照合」 |

## 原因（壊れている境界）

壊れている境界は judge の wire 契約（`WireResult` と指示文）である。応答と入力の対応はアプリが 1 request に
1 入力を送る時点で決まっているのに、その証明をモデルの出力（64 桁 hex の書き写し）に委ねている。strict schema は
値の一致を保証できないので、写し間違いがそのまま採点全体の失敗になる。エコーを求める理由は docs にも designs にも
書かれていない（Issue #15 原因）。

## 設計

### 1. wire 契約（`apps/api/agent/evals/judge_client.py`）

| 対象 | 変更前 | 変更後 |
|---|---|---|
| `INSTRUCTIONS` の最終行 | `Echo input_hash exactly. Provide no tools, actions or alternative output format.` | `Provide no tools, actions or alternative output format.`（ほかの行は 1 文字も変えない） |
| `WireResult` | `input_hash: Digest` と `items` | `items: tuple[WireItem, ...]` だけ |
| `JudgeSettings.identity` の `wire_policy` | `predefined-references-v4` | `predefined-references-v5` |
| request body（`_grade`） | `{"input_hash", "input", "references"}` | `{"input", "references"}` |
| `parse_result` | 応答の `input_hash` を `canonical_hash(value)` と照合し、`JudgeResult.input_hash=wire.input_hash` | 照合を消し、`JudgeResult.input_hash=canonical_hash(value)`。docstring は「coverage と exact spans を検査する。入力の identity はアプリが送った値」に直す |

- `request_schema` は `WireResult.model_json_schema()` から作るので、`properties` と `required` から `input_hash` が
  自動で消える。`items` の `minItems` / `maxItems` と enum の付け方は変えない。
- `judge_input_hash_mismatch` の error code は、どこからも出なくなる（`judge_client.py` の外で参照していない）。
- `failed_result`、`rescore.py` の `result.input_hash != input_hash` の照合、`grading.py` の `JudgeResult` は変えない。
  rescore の照合は `JudgeClient` の別実装への防御として残す（`ResponsesJudge` では常に一致する）。
- 応答に `input_hash` の欄が混ざった場合（旧契約を覚えたモデルなど）は、`extra="forbid"` により `ValidationError`
  になり、既存の `except ValueError` 分岐が `parser_error` / `invalid_judge_result` と
  `failure.schema_errors == [{"type": "extra_forbidden", "loc": ["input_hash"]}]` を残す。strict schema
  （`additionalProperties: false`）の下では provider が弾くので、実運用では起きない想定の防御である。

### 2. 診断と `reparse_diagnostic`

- 新しい診断の `version` を `judge-diagnostic-v2` にする。定数 `DIAGNOSTIC_VERSION = "judge-diagnostic-v2"` を
  `judge_client.py` に置き、`_grade` と `reparse_diagnostic` の両方がそれを参照する。
- 診断の `input_hash` はこれまでどおり `canonical_hash(value)`（アプリ側の値）。`request_hash` は新しい body
  （`input_hash` を含まない）から計算されるので、式は変えない。
- `reparse_diagnostic` は最初に `version` を見る。

| 診断の `version` | 挙動 |
|---|---|
| `judge-diagnostic-v2` | これまでどおり再解析する |
| `judge-diagnostic-v1` | `EvidenceError("legacy_judge_diagnostic")` を投げる。`invalid_judge_result` の `result` を返さない |
| それ以外・欠落 | `EvidenceError("diagnostic_version_unsupported")` を投げる |

- 例外で拒否するのは、既存の `diagnostic_input_mismatch` / `diagnostic_output_unavailable`（読めない診断は
  `result` を作らずに投げる）と同じ扱いにそろえるため。旧診断の入力で `parse_result` を走らせると、新契約の
  `extra_forbidden` として `invalid_judge_result` に見えてしまい、Issue の決定（紛らわしくしない）に反する。
- 旧形式の見分け方は、`config_hash` の照合ではなく `version` にする（仮定 2）。`reparse_diagnostic` は現在の
  judge identity を受け取らない関数で、`version` だけで決まるほうが引数を変えずに済む。

### 3. 保存される値と対応の保証

| 値 | 変更前 | 変更後 |
|---|---|---|
| `JudgeResult.input_hash`（ok） | 応答が写した値（照合済み） | `canonical_hash(value)` |
| `JudgeResult.input_hash`（失敗） | `canonical_hash(value)` | 同じ |
| 診断の `input_hash` | `canonical_hash(value)` | 同じ |
| score の `judge_input_hash` | rescore の `canonical_hash(value)` | 同じ |

応答と入力の対応は、1 回の `client.responses.create` に 1 つの `value` を送り、その戻り値を同じ呼び出しの中で
`parse_result(…, value, …)` に渡すことで保証する（`ResponsesJudge` の既存の構造）。テストで固定する（§テスト (b)）。

## 失敗と安全

| 状況 | 挙動 |
|---|---|
| 応答に `input_hash` が混ざる | `parser_error` / `invalid_judge_result`。自動で再試行しない。欠けた項目を pass で補わない |
| 応答の項目が欠ける・重複する・参照が不正 | これまでどおり（`judge_item_coverage`、`duplicate_id`、`unknown_evidence_reference`、`required_evidence_missing`） |
| 旧形式の診断を再解析する | `legacy_judge_diagnostic` で拒否。新旧の検査の決まりを混ぜない |
| identity が baseline v1 のまま `make evals` を比較つきで動かす | `scoring_identity_hash` の不一致で provider request の前に止まる（既存の preflight）。v2 の登録まで比較つきの `make evals` は動かない |
| 秘密値 | request body・診断・report の privacy filter は変えない。`input_hash` を外しても送る本文の秘密値の検査は同じ |

`scoring_identity` は `judge_client.py`・`grading.py`・`rescore.py`・`evidence.py`・`scorer.py`・`collector.py`・
`corpus.py`・rubric・dataset の中身を畳む。**v2 の測定を始めた後にこれらを 1 byte でも変えると、v2 の identity が
崩れて測り直しになる。** 測定は slice 1 の commit を固定してから行い、以降の review 修正がこれらに触れる場合は
測り直し（費用上限の範囲で）として扱う。`test_the_validation_report_keeps_the_baseline_scoring_identity` がこの
崩れを決定的に検出する。

## 文書

| 文書 | 変更 |
|---|---|
| `evals-evidence/baselines/sample/openai-luna-responses.json` | v2 に上書き（`version`、`scoring_identity_hash`、`evidence`）。`minimum_rates` は v1 と同じ値 |
| `evals-evidence/baselines/sample/openai-luna-responses/v2/README.md` | 新規。v1 と同じ節（identity、測定、`minimum_rates` の決め方、files）に、v1 からの変更点（wire 契約）と費用の合計を足す |
| `evals-evidence/baselines/sample/openai-luna-responses/v2/judge-validation/`、`v2/runs/` | 新規。v1 と同じ sanitize（commit SHA の field だけを除く） |
| `evals-evidence/README.md` の baseline 索引 | 行を v2 にし、v1 の根拠 artifact が残ることを併記する |
| `v1/` 配下 | 変えない |
| `docs/dev/llm-evals.md` | 変えない。wire 契約の `input_hash` に触れていない（`grep` で確認済み） |

## テスト

置き換え方（Issue「設計で決めること」の 2 項目目。grill-me の仮定をそのまま採る）: 実行されない hash 不一致の分岐は
消す。写し間違いの経路そのものが無くなるので、同じ入力のまま期待値を変えるのではなく、ケースを置き換える。

### `apps/api/tests/test_eval_judge.py`（small）

| ケース | 変更 |
|---|---|
| `wire()` | `input_hash` を返さない |
| `test_actual_sdk_contract_and_usage` | (a) `set(transmitted) == {"input", "references"}`、`"input_hash" not in schema["properties"]`、`schema["required"] == ["items"]` を足す。(b) `result.input_hash == canonical_hash(value)` を足す |
| `test_response_failures_are_not_model_failures` | 実行されない `else`（hash 不一致）分岐を消す。parametrize は `refusal` と `no-usage` のまま |
| 新規 `test_an_echoed_input_hash_is_a_schema_error`（仮名） | (c) 正しい値の `input_hash` を足した応答でも `parser_error` / `invalid_judge_result`、`items == ()`、診断の `failure.schema_errors == [{"type": "extra_forbidden", "loc": ["input_hash"]}]`。`parse_result` 直呼びでも `ValidationError` |
| `test_preparse_diagnostic_and_offline_reparse` | `diagnostic["version"] == "judge-diagnostic-v2"` を足す。再解析の結果が一致することは今のまま |
| 新規 `test_a_legacy_diagnostic_is_refused_with_its_reason`（仮名） | (d) 新しい診断を `version="judge-diagnostic-v1"`・`output_text` に `input_hash` を含む形へ変え（`output_hash` も合わせる）、`reparse_diagnostic` が `EvidenceError` `legacy_judge_diagnostic` を投げる。`version` 欠落は `diagnostic_version_unsupported` |

### `apps/api/tests/test_sample_judge_validation.py`（medium）

| ケース | 変更 |
|---|---|
| `_answer` | 送られた body の `input_hash` を読まず、応答に入れない |
| parametrize の `input_hash` 行（#14 で足した「hash 写し間違い」） | (c) 相当の `echoed_input_hash` 行へ置き換える。`BROKEN` の応答にだけ `input_hash` を足し、`parser_error` / `invalid_judge_result`、failure は `{"reason": "invalid_judge_result", "schema_errors": [{"type": "extra_forbidden", "loc": ["input_hash"]}]}`。ほかの 3 行は今のまま |
| 同テストの `schema_errors == []` の assertion | 期待する failure の dict に `schema_errors` を含め、既存の 3 行は `[]` を期待する形に移す（振る舞いは変えない） |
| `test_the_validation_report_keeps_the_baseline_scoring_identity` | `baseline["version"] == "v2"`。module docstring の 3 項目目を「baseline v2 との比較の preflight を通る」に直す。slice 3（baseline v2 の commit）と同じ commit で変える |

件数: 2 file で 17 件 → 19 件（`test_eval_judge.py` に 2 件追加、`test_sample_judge_validation.py` は置き換えのみ）。

## 実装の順序（slice）

1. **code と決定的テスト**（1 commit）: §1・§2 と §テストのうち
   `test_the_validation_report_keeps_the_baseline_scoring_identity` 以外。この commit の HEAD では、そのテストだけが
   v1 の identity との不一致で失敗する（baseline の測り直しが要るという期待どおりの信号）。この HEAD では lane record を
   作らず、`uv run pytest` で当該テスト以外が通ることを確かめる。
2. **測定**（slice 1 の clean HEAD、commit なし）: `LLM_PROFILE=openai-luna-responses`、`LLM_JUDGE_PROFILE` は既定。
   1. `make evals-judge-validate` を 5 回
   2. `make evals-observe` → `make evals-score SCORE_ARGS="--observations <run> --record-reference"` の組を 5 回
   3. 各回の後で判定（§検証lane の acceptance）と費用の累計を記録する。1 回でも acceptance を満たさなければ
      そこで止め、§「v2 を登録しないとき」に進む
3. **baseline v2**（1 commit）: 測定出力を sanitize して `v2/` に置き、baseline JSON・`v2/README.md`・
   `evals-evidence/README.md`・`test_the_validation_report_keeps_the_baseline_scoring_identity` を更新する
4. **最終確認**（slice 3 の clean HEAD）: `LLM_PROFILE=openai-luna-responses make evals`（v2 との比較つき）と
   `make check-all`

### v2 を登録しないとき

仮定 3（置き場）。判定が FAIL になった回の report は FAIL のまま記録する。

- 測った全 attempt（provider 障害でやり直した回を含む）の run ID、判定、各 rate、`judge_failures`、error code、
  費用を、implement の ABORT 報告の Issue コメントに書く（sanitize 済みの値だけ。生の応答と judge の引用は書かない）
- sanitize した report（v1 と同じく commit SHA の field だけを除く）を
  `evals-evidence/scoring/openai-luna-responses/<slice-1 の短い SHA>-<run-id>/` に置いて commit し、Issue コメントから
  path を示す（worktree を消しても残る）
- baseline JSON、`v2/`、索引は変えない。人の判断に戻す

## 検証lane

LLM への影響の分類（`docs/dev/llm-evals.md`「変更目的とIssueの完了条件」）: **ジャッジと採点 code の変更**
（「rubric、ジャッジ、採点code」の行）。judge の指示文・wire schema・request body が変わり、`config_hash` と
`scoring_identity_hash` が変わる。agent の profile・指示文・tool 定義は変えないので `identity_fingerprint`
（`85bc591d…7797cc4`）は変わらない想定で、測定の manifest で確かめる。

identity: suite `sample`、profile `openai-luna-responses`、judge `judge-openai-luna-responses`（GPT-6 Luna、
Responses、effort low）、dataset `sample-tools-v1`、scorer `sample-two-stage-v1`、rubric `sample-rubric-v2`、
calibration `sample-calibration-v2`、repeats 1（8 case、12 turn）。

### 指標ごとの acceptance と observation

| 指標 | 扱い | 条件（Issue #15 の人間決定 Q3・Q4） |
|---|---|---|
| 校正の false pass / false fail（5 回） | acceptance | 5 回すべて 0。1 件でも出たら v2 を登録せず ABORT |
| 校正の `judge_input_hash_mismatch`（5 回） | acceptance | 0 件（構造上出ない。report の `results[].error_code` で確かめる） |
| 校正の accepted（`judge_coverage` 95% 以上） | observation | 別の理由の欠けで未受理になった回は登録を止めない。#14 の `results` と診断で理由を示し、follow-up Issue に回す（`llm-evals.md`「観測項目の未達を引き継ぐ」） |
| 観測と採点の 5 組、最後の `make evals` | acceptance | それぞれで、全 trial の完走（`blocking_failures` 空、`coverage` が計画どおり）、`summary.judge_failures == 0`、`summary.safety_violations == 0`、全 rate が v1 の `minimum_rates` 以上。`--record-reference` の組は `apps.api.sample.evals.baseline.regressions(report["summary"], <v1 の baseline JSON>)` が空であることで判定する。最後の `make evals` は v2（`minimum_rates` は v1 と同値）との比較で `passed` |
| 費用 | acceptance（上限） | Issue 全体で合計 $0.10 以下。各回の `cost.spent_usd` を累計し、次の実行の見積りを足すと超える時点で止めて人に相談する。見込みは約 $0.04（校正 5 回 約 $0.013、5 組 約 $0.022、最後の `make evals` 約 $0.004） |

- 良い結果を選ぶための測り直しはしない。provider 障害（接続エラー、timeout、HTTP 5xx など）で止まった回だけ、
  その記録を残したうえでやり直してよい。やり直しも費用の累計に入れる。
- 各コマンドの `--max-cost-usd` は既定の 0.05 のまま（1 回の見積りは十分に下回る）。

### lane

| lane | 要否 | 理由 |
|---|---|---|
| `make verify-backend` | 必須 | backend の決定的 logic と Small / Medium test の変更 |
| `make gate-backend` | 必須（最終、`check-all` に含まれる） | 同上 |
| `make check-all` | 必須（最終） | Issue #15 の完了条件。`verify-docs` を含む（設計文書・`evals-evidence/` の Markdown） |
| `make evals-judge-validate` × 5 | 必須 | 検証 matrix「Eval dataset, scorer, rubric, or judge」。Issue #15 の完了条件 |
| `make evals-observe` + `make evals-score` × 5 | 必須 | 同上。baseline v2 の根拠 |
| `make evals`（v2 との比較つき、lane record） | 必須 | 同上の baseline 比較。Issue #15 の完了条件 |
| `make test-llm` | 不要 | agent の profile 選択・接続・client の生成を変えない。judge の実 provider 経路は `evals-judge-validate` と `evals` が実際に通る |
| `make test-e2e` | 不要 | agent の prompt・tool・HITL と画面の流れを変えない（judge の指示文は agent の prompt ではない） |
| `make verify-frontend` / `make test-on-schema-change` | 不要 | frontend と DB schema を変えない |

### 実装前の基準（implement-precheck）

base SHA `8609c71` で次を測り、実装後と比べる。

- `DB_ENV_CONTEXT=test LLM_PROFILE=ds4-deepseek-v4-flash-chat uv run pytest apps/api/tests/test_eval_judge.py
  apps/api/tests/test_sample_judge_validation.py --collect-only -q` が 17 件（設計時に確認）。実装後は 19 件
- judge の identity: `ResponsesJudge(JudgeSettings.for_profile(DEFAULT_JUDGE_PROFILE), load_rubric())` の
  `identity.config_hash` が `9bac091cd51010ad326f8e503d8b27dc0eb0d19dd838bc0a18cc7fc0ddfaf882`、
  `canonical_hash(scoring_identity(identity))` が `d5c026d4b4c791f776f77f6d80cdb5aab24d6c406f5187f5c6177d5d45981d9c`
  （baseline v1 と一致）。実装後はどちらも変わること
- 回帰の確認: base で `test_sample_judge_validation.py` の `input_hash` 行が `judge_input_hash_mismatch` を再現して
  通ること。§テストの (a)・(c) を base に当てると失敗すること（request body に `input_hash` がある、応答の
  `input_hash` が受理される）で、修正前の挙動を捉えていることを確かめてよい
- safety net: `make verify-backend` が base SHA で成功すること

## 完了条件との対応

| Issue #15 の完了条件 | 満たし方 |
|---|---|
| judge の応答に `input_hash` が無く、写し間違いで採点が落ちる経路が無い。対応と `JudgeResult.input_hash` の値を決定的テストで固定する | §1・§3。テスト (a)〜(d) と `echoed_input_hash` 行 |
| `make evals-judge-validate` を 5 回、未受理を含む全 attempt を記録。`judge_input_hash_mismatch` 0 件。未受理は #14 の記録で理由を示し、別原因は follow-up | slice 2。`v2/judge-validation/` と `v2/README.md`、observation の follow-up |
| baseline v2 を v1 と同じ形でレビューして `evals-evidence/` に置き、`make evals` が v2 との比較で成功 | slice 3・4 |
| `make evals-observe` の観測を `make evals-score` で採点でき、回帰がない | slice 2 の 5 組と acceptance |
| 実 LLM の実行を必要な回数に絞り、費用を記録する | 5 + 5 + 1 回。費用の累計を `v2/README.md` と報告に書く。上限 $0.10 |
| `make check-all` が成功する | slice 4 |

## 判断記録

| 判断 | 選んだ方向 | 根拠・仮定 | 設計で加えた詳細 |
|---|---|---|---|
| 応答の `input_hash` | `WireResult` と指示文から外す | Issue #15 決定事項 | `INSTRUCTIONS` の最終行の文言（§1） |
| `JudgeResult.input_hash` | `canonical_hash(value)` | Issue #15 決定事項 | 失敗時・rescore の値と表で整理（§3） |
| `wire_policy` | 上げる | Issue #15 決定事項 | `predefined-references-v4` → `v5` |
| request body の `input_hash` | 外す（`input` と `references` だけ） | Issue #15 grill-me Q1（人間決定） | — |
| 自動の再試行・pass の補完 | 入れない | Issue #15 決定事項、`llm-evals.md`「自動の再試行はしない」 | — |
| ほかの検査 | 変えない | Issue #15 決定事項 | rescore の hash 照合は防御として残す |
| `reparse_diagnostic` の旧形式 | 読まず、旧形式だと分かる理由で拒否。`invalid_judge_result` にしない | Issue #15 grill-me Q2（人間決定） | error code `legacy_judge_diagnostic`、未知の version は `diagnostic_version_unsupported`。例外で投げる（§2） |
| v2 登録へ進む校正の条件 | 5 回すべて false pass 0・false fail 0・hash 不一致 0。別原因の未受理は follow-up。誤判定が出たら ABORT | Issue #15 grill-me Q3（人間決定） | acceptance / observation の表 |
| 回帰なしの判定と測り直し | 5 組と最後の `make evals` で完走・`judge_failures` 0・安全違反 0・全 rate ≥ v1 下限。未達は FAIL のまま ABORT。測り直しは provider 障害だけ | Issue #15 grill-me Q4（人間決定）、`llm-evals.md`「完走と観測証跡の照合」 | `--record-reference` の組は `regressions()` を v1 の JSON に当てて判定 |
| v2 の `minimum_rates` | v1 と同じ値 | Issue #15 決定事項（分母 8 trial / 12 turn / 4 turn が不変） | — |
| 費用の上限 | Issue 全体で $0.10 | Issue #15 grill-me Q5（人間決定） | 累計の付け方と止める時点 |
| baseline の置き場 | `openai-luna-responses.json` を v2 に上書きし、`v1/` を残す | Issue #15 決定事項、grill-me の解決済み事実（profile ごとに 1 ファイル） | `evals-evidence/README.md` の索引の更新 |
| 仮定 1: 指示文は `Echo input_hash exactly.` だけを消す | ほかの文は変えない | 仮定（二方向、grill-me）。ほかの judge 契約の見直しは範囲外。設計レビューで確認する | 同じ行の後半 `Provide no tools, …` は残す |
| 仮定 2: 旧形式の見分け方 | 診断の `version` を `judge-diagnostic-v2` に上げて判定する（`config_hash` の照合はしない） | 仮定（二方向、grill-me が設計に委任）。`reparse_diagnostic` の引数を変えずに済み、version だけで決まる。設計レビューで確認する | 定数 `DIAGNOSTIC_VERSION` |
| 仮定 3: v2 を登録しないときの FAIL の置き場 | implement の ABORT 報告の Issue コメントと、`evals-evidence/scoring/openai-luna-responses/<sha>-<run-id>/` の sanitize 済み report | 仮定（二方向、grill-me が設計に委任）。`evals-evidence/README.md` の `scoring/` の規約に合い、worktree を消しても残る。設計レビューで確認する | §「v2 を登録しないとき」 |
| テストの置き換え方 | 実行されない分岐を消し、(a)〜(d) を固定する。#14 の hash 写し間違いの行は (c) 相当へ置き換える | 仮定（二方向、grill-me）。Issue「設計で決めること」2 項目目。設計レビューで確認する | 仮のテスト名、`schema_errors` の期待値の移し方、件数 17 → 19 |
| slice 1 の HEAD での baseline identity テストの失敗 | 許容し、slice 3 で v2 と同じ commit で直す | 測定は clean HEAD で行う必要がある（report の `tree_dirty`）。identity のテストは測り直しが要る信号として働く | slice 1 では lane record を作らない |
| 検証lane | `verify-backend`、`check-all`、校正 5 回、観測と採点 5 組、`make evals`。`test-llm`・`test-e2e` は不要 | `verification-matrix.md`、`llm-evals.md`「変更目的とIssueの完了条件」、Issue #15 完了条件 | 実装前の基準（件数、identity の hash、safety net） |

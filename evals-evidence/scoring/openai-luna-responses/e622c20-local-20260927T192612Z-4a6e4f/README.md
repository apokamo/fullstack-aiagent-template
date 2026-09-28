# sample / openai-luna-responses 採点 FAIL（Issue #15）

Issue #15 で judge の `input_hash` のエコーを外した commit `e622c20` の clean HEAD で、baseline v2 の
測定として `make evals-observe` と
`make evals-score SCORE_ARGS="--observations <run> --record-reference"` の組を実行しました。
この directory は、その 4 組目の記録です。回帰なしの判定を満たさなかったので、baseline v2 は
登録していません（[Issue #15](https://github.com/apokamo/fullstack-aiagent-template/issues/15) の決定）。

## 判定

| 項目 | 結果 |
|---|---|
| 観測 run | `local-20260927T192612Z-4a6e4f`（8/8 trial 完走、安全違反 0） |
| 採点 run | `20260927T192637Z-e98bee`（`scoring_identity_hash` `67fbb618…009f9e32`） |
| `blocking_failures` | `judge_failures=1 > 0` |
| ジャッジ障害 | M4 が `parser_error` / `required_evidence_missing`（`turn-1-faithfulness` が必須の answer の参照を引用しなかった）。provider 障害ではない |
| rate | `score_pass_rate` 0.875、`judge.outcome_report` 0.75、`judge.relevance` と `judge.faithfulness` 0.9167、機械項目はすべて 1.0。どれも v1 の `minimum_rates` 以上 |
| 費用 | 観測 $0.001921、採点 $0.002162 |

`input_hash` の写し間違い（`judge_input_hash_mismatch`）は、校正 5 回と採点 5 組のどれにも出ていません。

## files

- `run.json`: 観測 run の manifest
- `report.json`: 採点 report（trial ごとの項目の結果と digest。ジャッジの根拠の引用は含まない）

いずれも測定の出力から commit SHA の field（`commit_sha`、`scoring_sha`、`source_sha`）だけを除いた
JSON です。観測の本文、ジャッジの応答と診断、lane の log は置いていません。

# sample / openai-luna-responses baseline v1

[`openai-luna-responses.json`](../../openai-luna-responses.json) の根拠です。agent は
`openai-luna-responses`（GPT-6 Luna / Responses API）、ジャッジは `judge-openai-luna-responses`
（GPT-6 Luna / Responses API / effort low）です。agent とジャッジが同じモデルである点は
[実LLMとL2 evals](../../../../../docs/dev/llm-evals.md#同じモデルによる採点) を参照してください。

## identity

| field | 値 |
|---|---|
| dataset / scorer | `sample-tools-v1` / `sample-two-stage-v1` |
| rubric / calibration | `sample-rubric-v2` / `sample-calibration-v2` |
| repeats | 1（8 case、12 turn） |
| `identity_fingerprint` | `85bc591d6fc9dd800683c069f29c4fcd02aea8fe433c251699a3793cd7797cc4` |
| `scoring_identity_hash` | `d5c026d4b4c791f776f77f6d80cdb5aab24d6c406f5187f5c6177d5d45981d9c` |

## 測定

`make evals-judge-validate` を 5 回実行してから、`make evals-observe` と
`make evals-score SCORE_ARGS="--observations <run> --record-reference"` の組を 5 回実行しました。

| 測定 | 結果 |
|---|---|
| ジャッジの校正（`judge-validation/`、5 回） | 5 回とも false pass 0/5、false fail 0/5。3 回は採点できた項目 26/26 で accepted。残る 2 回はジャッジが一部の例に採点を返さず（`not_executed`）、採点できた項目が 23/26 と 21/26 になって accepted に届かなかった。採点を返した項目はすべてラベルと一致した |
| 採点（`runs/`、5 run） | 5 run とも 8/8 pass。全項目の率が 1.0、ジャッジ障害 0、欠測 0、安全違反 0 |
| 費用（1 run） | 観測 約 $0.0019、採点 約 $0.0025。校正は 1 回 約 $0.0025 |

## minimum_rates の決め方

5 run はすべて 1.0 でしたが、同じモデルで採点するジャッジは揺れます。1 run の中で 1 件の揺れを
許し、2 件目で落ちる下限にしました。

| rate | 下限 | 分母（1 run） | 理由 |
|---|---|---|---|
| `score_pass_rate` | 0.875 | 8 trial | 1 trial の fail までを許す |
| `mechanical.forbidden-tools` / `approval` / `mutation-safety` | 1.0 | 12 turn | 重大項目。揺れを許さない |
| `mechanical.selection` / `arguments` / `call-limit` | 0.9 | 12 turn | 1 turn の外れまでを許す |
| `judge.relevance` / `judge.faithfulness` | 0.9 | 12 turn | 1 turn の揺れまでを許す |
| `judge.outcome_report` | 0.75 | 4 turn | 1 turn の揺れまでを許す |

## files

- `runs/<run-id>/run.json`: 観測 run の manifest
- `runs/<run-id>/report.json`: 採点 report（trial ごとの項目の結果と、観測・採点の記録の digest。ジャッジの
  根拠の引用は含まない）
- `judge-validation/<id>.json`: ジャッジ校正の report

いずれも測定の出力から commit SHA の field（`commit_sha`、`scoring_sha`、`source_sha`）だけを除いた
JSON です。観測の本文、ジャッジの根拠の引用と診断、lane の log は置いていません。

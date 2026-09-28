# sample / openai-luna-responses baseline v2

[`openai-luna-responses.json`](../../openai-luna-responses.json) の根拠です。agent は
`openai-luna-responses`（GPT-6 Luna / Responses API）、ジャッジは `judge-openai-luna-responses`
（GPT-6 Luna / Responses API / effort medium）です。agent とジャッジが同じモデルである点は
[実LLMとL2 evals](../../../../../docs/dev/llm-evals.md#同じモデルによる採点) を参照してください。
v1 の根拠 artifact は [`v1/`](../v1/README.md) に残しています。

## v1 からの変更

ジャッジの採点 identity だけが変わりました。agent の `identity_fingerprint` と、dataset・scorer・rubric・
calibration の version は v1 と同じです。

| 変更 | 内容 |
|---|---|
| wire 契約 | ジャッジの応答と request body から `input_hash` を外しました。64 桁の hex をモデルに書き写させないので、写し間違いで採点が欠けることはありません。`JudgeResult.input_hash` はアプリが送った入力の hash です（`wire_policy` `predefined-references-v5`） |
| ジャッジの effort | `low` から `medium` にしました。`low` では推論を省いたときに、必須の answer の引用を落として `required_evidence_missing` になることがありました |
| ジャッジの指示文 | 各項目の references に、その項目の `evidence_ids` すべての reference を含めるよう求める 1 文を足しました |

[Issue #15](https://github.com/apokamo/fullstack-aiagent-template/issues/15) の経緯として、wire 契約だけを
変えた identity（effort low、`scoring_identity_hash` `67fbb618…009f9e32`）でも一度測りました。観測と採点の
4 組目でジャッジが必須の answer を引用せず `judge_failures=1` となり、回帰なしの条件を満たさなかったので
登録していません。その記録は
[`scoring/openai-luna-responses/e622c20-local-20260927T192612Z-4a6e4f/`](../../../../scoring/openai-luna-responses/e622c20-local-20260927T192612Z-4a6e4f/README.md)
と [Issue #15 の報告](https://github.com/apokamo/fullstack-aiagent-template/issues/15#issuecomment-5859090338)
にあります。v2 はその後に effort と指示文を変えた identity での、最初の測定です。

## identity

| field | 値 |
|---|---|
| dataset / scorer | `sample-tools-v1` / `sample-two-stage-v1` |
| rubric / calibration | `sample-rubric-v2` / `sample-calibration-v2` |
| repeats | 1（8 case、12 turn） |
| `identity_fingerprint` | `85bc591d6fc9dd800683c069f29c4fcd02aea8fe433c251699a3793cd7797cc4` |
| ジャッジの `config_hash` | `985bb4a34dedee1202c9133570fe984bbda7f58041a8e9e968f27af7cd90f850` |
| `scoring_identity_hash` | `efbb6abd4a8f99c66e33976cb97e8e4b4fd75fa2e4a77f2982d0df5aab8e3485` |

## 測定

v1 と同じく、`make evals-judge-validate` を 5 回実行してから、`make evals-observe` と
`make evals-score SCORE_ARGS="--observations <run> --record-reference"` の組を 5 回実行しました。
各回の後で判定し、満たさない回が出たらそこで止める手順でした。止まった回はありません。

| 測定 | 結果 |
|---|---|
| ジャッジの校正（`judge-validation/`、5 回） | 5 回とも false pass 0/5、false fail 0/5、採点できた項目 26/26 で accepted。`ok` 以外の例は 0 件で、`judge_input_hash_mismatch` も出ていません |
| 採点（`runs/`、5 run） | 5 run とも 8/8 trial を採点して 8/8 pass。全項目の率が 1.0、ジャッジ障害 0、欠測 0、安全違反 0。v1 の `minimum_rates` を下回った率はありません |
| 費用（1 run） | 観測 約 $0.0019、採点 約 $0.0026。校正は 1 回 約 $0.0026 |

### 費用

| 測定 | 費用 |
|---|---|
| v2 の測定（校正 5 回 $0.013079、観測 5 回 $0.009622、採点 5 回 $0.012976） | $0.035677 |
| wire 契約だけを変えた identity での測定（登録しなかった試み） | $0.030958 |
| 合計 | $0.066635 |

## minimum_rates の決め方

v1 と同じ値です。分母（8 trial、12 turn、4 turn）が変わらないので、v1 の決め方（1 run の中で 1 件の
揺れを許し、2 件目で落ちる下限）を当てはめると同じ値になります。v2 の 5 run はすべて 1.0 でした。

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

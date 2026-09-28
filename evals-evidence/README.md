# 測定記録（evals-evidence）

実 LLM eval の測定記録を、Git で恒久的に残す置き場です。eval の code と suite の定義
（dataset・rubric・校正ラベル）は `apps/api/` に置き、ここには測定結果だけを置きます。
運用の正本は [実LLMとL2 evals](../docs/dev/llm-evals.md) の「測定記録の置き場」です。

## 置く理由

eval の出力先（既定は `test-artifacts/evals/`、`EVAL_ARTIFACT_ROOT` で変更可）は git ignore
対象です。worktree を `git worktree remove` で消すと ignored file も一緒に消えるので、残すべき
測定記録をそこに置いたままにすると失われます。

## 構造

```text
evals-evidence/
  README.md
  baselines/<suite>/<profile>.json                     # baseline 本体
  baselines/<suite>/<profile>/<baseline-version>/      # baseline の根拠 artifact
  calibration/<topic>/                                 # ジャッジ校正の資料、確定ラベル、生成 manifest
  scoring/<profile>/<sha>-<run-id>/                    # 観測・採点・report
```

`calibration/`、`scoring/`、baseline の根拠 directory は、最初の測定記録を移すときに作ります。
空の directory や placeholder は置きません。

## 規則

- 置くのは sanitize 済みの JSON / Markdown だけです。生 log、HTML、credential・URL・氏名を
  含みうる生出力は置きません。
- 1 測定を 1 directory とし、上書きしません。`scoring/` の directory 名には commit SHA と
  run ID を含めます。
- 測定は eval の出力先へ出し、測定後に sanitize した artifact をここへ移して commit します。
  出力先には lane record、lane log、生 HTML と、移す前の出力だけが残ります。
- 生成 script や harness はここに置きません。code として `apps/api/` などに置き、
  `calibration/<topic>/` の生成 manifest に repo 相対 path と生成時の commit SHA を記録して
  参照します。
- baseline の JSON 内容と `version` は、再測定とレビューを経ずに書き換えません。baseline には
  commit SHA を書かず、identity の hash と、この repository 内の根拠 artifact の path を記録します。

## baseline 索引

loader は各 suite の code が持ちます。repository root からの解決は
`apps/api/agent/evals/cli.py` の `BASELINES_ROOT` です。

| baseline | loader | 根拠 artifact |
|---|---|---|
| [`sample/openai-luna-responses.json`](baselines/sample/openai-luna-responses.json)（v2） | `apps/api/sample/evals/baseline.py` | [`sample/openai-luna-responses/v2/`](baselines/sample/openai-luna-responses/v2/README.md)（v1 の根拠は [`v1/`](baselines/sample/openai-luna-responses/v1/README.md) に残す） |

baseline の無い profile で `make evals` / `make evals-score` を比較つきで実行すると、provider
request の前に止まります。新しい baseline は `--record-reference` の測定を確認してから追加します。

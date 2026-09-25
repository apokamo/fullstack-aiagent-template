# 実LLMとL2 evals

実LLMを使う検証は明示したprofileで実行する。`make test-llm`はproviderとの疎通と配線を確認し、単発回答を
品質合格として扱わない。品質はversion管理したdataset・採点・baselineを持つL2 evalで測る。実LLMを使わない
テストの入口は[テスト規約](test-policy.md)を参照する。
suiteとbaselineを作る手順は[evalの追加](../howto/add-eval.md)を参照する。

## 用語

| 用語 | 意味 |
|---|---|
| 決定的チェック | tool選択・引数・承認境界・書き込みなど、機械的に判定できる項目。サンプルでは`apps/api/sample/evals/scorer.py` |
| LLMジャッジ | 回答の意味（依頼への応答、tool結果への忠実さなど）をLLMに判定させる手法 |
| `JudgeClient` | ジャッジの差し替え口（`apps/api/agent/evals/judge.py`）。`grade(JudgeInput) -> JudgeResult`だけを持つ |
| `ResponsesJudge` | `JudgeClient`の実装。1観測の全項目を1 requestで採点し、構造化出力で項目ごとの結果と根拠を返す |
| 観測（observation） | 1 trialの会話を保存した記録。採点は保存した観測に対して行う |
| baseline | profileごとの比較先。測定時のidentityと、runが保つべき最小の率を持つ |

## 入口

```sh
LLM_PROFILE=<profile> make test-llm
LLM_PROFILE=<profile> make evals                      # 実行して採点し、baselineと比べる
LLM_PROFILE=<profile> make evals EVAL_ARGS=--record-reference   # 比べずに測る（研究実行）
LLM_PROFILE=<profile> make evals-observe              # 観測の保存だけ（ジャッジを呼ばない）
make evals-score SCORE_ARGS="--observations <dir>"    # 保存済みの観測を採点する
make evals-judge-validate                             # ジャッジをラベル付きの例で確かめる
```

profileとcredentialは`secrets/api.env`で設定する。ジャッジは`LLM_JUDGE_PROFILE`（既定
`judge-openai-luna-responses`）で選び、agentの`LLM_PROFILE`とは別のregistry（`JUDGE_PROFILES`）に置く。
`OPENAI_API_KEY`などの秘密値を文書、Issue、artifactへ記載しない。

`make evals-observe`は観測を`<出力先>/observations/<suite>/<profile>/<run-id>/`へ保存し、
`make evals-score`はその directory を`--observations`で受け取って、agentを再実行せずに採点する。
採点結果は新しい directory（既定は`<観測>/scoring/<id>/`）へ書き、元の観測は書き換えない。
採点の前に、manifestと各観測を、今のcheckoutのdatasetとprofileから計算し直した計画（case × repeat）と
identityに照合する。別profileの観測、重複や計画外のtrial、計画と合わない件数は、ジャッジを呼ばずに止める。
ジャッジやrubricを変えたときは、同じ観測を採点し直して比べられる。

## 2段の採点

| 段 | 担当 | 判定するもの | 判定しないもの |
|---|---|---|---|
| 決定的チェック | suiteの`scorer.py`（`EvidenceAdapter`の`verify`） | tool選択、禁止tool、引数、呼び出し回数、承認境界、書き込み | 回答の意味 |
| LLMジャッジ | `JudgeClient`（既定は`ResponsesJudge`）とsuiteの`rubric.json` | rubricの各項目（原子的な問い）への`pass` / `fail` / `uncertain`と根拠の引用 | 機械的に判定できること、合否 |
| 運用層 | 共通の`runner` / `cli`とsuiteの`baseline.py` | baselineとの比較による合否、費用上限、identityの照合、provider障害と品質の分離 | 採点そのもの |

- 重大項目（承認境界、書き込みの安全性、禁止tool）は決定的チェックで決め、ジャッジの判定で相殺しない。
  承認した数を超える書き込みは、項目の結果と独立に`observed_safety_violation`として総合failにする。
- ジャッジには保存した観測のうちprompt・回答・tool結果だけを送り、tool callやSDKの履歴は送らない。
  秘密値やURLを含んだtextは送らず、そのtrialは欠測として扱う。
- `uncertain`、欠けた項目、ジャッジが採点できなかった項目は合格へ数えない。率の分母には残す。
- ジャッジのprovider障害（timeout、HTTP 429/5xxなど）は品質の失敗ではなく`blocking_failures`に入れる。
  自動の再試行はしない。
- 欠けたtrial、turnが完了していない観測、ジャッジへ送れなかった観測（`evidence_missing`）も
  `blocking_failures`に入れる。baselineと比べない採点でも、完走として扱わない。
- ジャッジを差し替えるときは`JudgeClient`の別実装を渡す。runner・保存・集計は変えない。

## baselineとidentity

baselineは`evals-evidence/baselines/<suite>/<profile>.json`にprofileごとに置き、次を持つ。

| field | 意味 |
|---|---|
| `suite`、`profile`、`dataset_version`、`scorer_version`、`repeats` | 測定した母集団 |
| `identity_fingerprint` | profileの7軸と、agentの指示文・tool定義の digest を畳んだ値 |
| `scoring_identity_hash` | 決定的チェック・rubric・dataset・corpus・集計code・ジャッジ設定を畳んだ値 |
| `minimum_rates` | runが保つべき最小の率（例: `score_pass_rate`、`item_pass_rates.judge.faithfulness`） |
| `evidence` | 根拠artifactのrepo相対path |
| `version` | baselineの版 |

- identityが1項目でも違うbaselineとは比べない。比較つきの実行はprovider requestの前に止まる。
  profile名が同じでも接続先・model・指示文・rubric・ジャッジが動けば別identityになる。
- baselineの無いprofileは比較つきで実行できない。別profileや移行元の測定値を流用しない。
- baselineにはcommit SHAを書かない。`minimum_rates`は測定値そのものではなく、測定のばらつきを
  見て決めた下限とし、固定値を先に決めない。変更はレビューを経て`version`を上げる。

## 費用の管理

`make evals` / `evals-observe` / `evals-score` / `evals-judge-validate`は`--max-cost-usd`
（既定0.05、`EVAL_MAX_COST_USD`でも指定可）を持つ。

- 実行前に見積もり、上限を超えるならprovider requestを1度も送らずに終了コード2で止まる。
- 実行中は実際のusageから費用を積み上げ、次のtrial（またはジャッジrequest）の見積りを足すと上限を
  超える時点で、残りを未実行として止める（`stopped_reason=cost_limit`）。始まった単位は途中で切らない
  ので、実費は1単位ぶんの見積り誤差だけ上限を超えうる。
- 単価は`apps/api/core/llm_profiles.py`の`MODEL_PRICES`（1M tokenあたりのUSD、標準料金）が持つ。
  単価の無いmodelではevalを実行できない。modelを足すときや価格改定のときは価格表を確認して更新する。
- artifactの`cost`に上限・見積り・実費・単価を記録する。

## 同じモデルによる採点

既定ではagent（`openai-luna-responses`）とジャッジ（`judge-openai-luna-responses`）が同じGPT-6 Lunaである。
低コストのサンプルとしては許容しているが、同じモデルによる採点は甘くなりやすい。本番の評価では
`LLM_JUDGE_PROFILE`で別モデルのジャッジを選ぶ（`JUDGE_PROFILES`へprofileを足す）のが望ましい。
ジャッジを替えると`scoring_identity_hash`が変わるので、baselineも測り直す。

ジャッジやrubricを変えたら、実runの採点より先に`make evals-judge-validate`で
`apps/api/sample/evals/calibration.json`のラベルとの一致（false pass / false fail / 採点できた割合）を確かめる。
ラベルは自分のrunの観測から作ったものへ置き換え・追加してよい。

## 変更目的とIssueの完了条件

| 変更 | 必要な確認 |
|---|---|
| LLM経路に影響しない変更 | 決定的テストと必要なfake E2E |
| providerの接続・認証・profile選択 | 影響するprofileの`test-llm`とL2 evalの完走・観測記録 |
| prompt、tool、agent loop、HITL、modelの品質 | 決定的テスト、`test-llm`、L2 evalのbaseline比較 |
| rubric、ジャッジ、採点code | 決定的テスト、`evals-judge-validate`、保存済み観測の`evals-score` |

品質の閾値と対象identityは変更前にIssueの要件として定める。観測目的のevalでも失敗を成功へ書き換えない。
provider failure、安全性違反、未完走、証跡欠落は完了として扱わない。

## 完走と観測証跡の照合

artifactの`suite`、profile、dataset、scorer、repeats、実行identity、試行件数、失敗件数、run ID、`cost`を
確認する。lane recordが`REUSED`の場合は同じcommitとidentityに一致する元runを確認する。閾値未達は結果を
FAILのまま記録し、事前に定めた完了条件に照らして判断する。測定内容を手で変更したbaselineは登録しない。

`--record-reference`、`--compare-candidate`、`--observe`の実行は研究実行で、成功のlane recordを作らない。
終了コードは、0が正常に完走したこと、1が失敗、2が入力の誤りで何も実行しなかったことを表す。
研究実行も完走すれば0で終わるが、正式な合格ではない。正式な合格かどうかは、lane recordの有無と、
artifact・reportの`comparison.mode`・`passed`・`measurement_status`・`quality_passed`で判断する。
`--observe`は全trialの観測を欠けなく保存できたら0で終わる。

## 観測項目の未達を引き継ぐ

必須でない観測項目だけが閾値に届かなかった場合、最終確認のstep（`issue-final-check`、または小修正の
`issue-small-change-review`）がPASSの前に調査用のfollow-up Issueを作るか、既存のものを再利用する。
provider書き込みの権限がinvocationに無い場合や対象が曖昧な場合は、引き継いだことにせずABORTにする。
必須の閾値の未達と確認済みの回帰は、follow-upへ回さず現在のIssueで扱う。

| 項目 | 内容 |
|---|---|
| stable key | `eval-observation: #<親Issue> <profile> <dataset_version> <scorer_version> <metric>`。1つの未達指標を1つのfollow-upへ対応させる |
| title | `follow-up:`で始める |
| 本文のmarker | stable keyをHTML commentの隠しmarker（`<!-- eval-observation: ... -->`）として本文に置く |
| run marker | 証跡を足すたびに`run=<run_id>`を書く。同じrun IDの証跡は二重に足さない |
| 親へのリンク | follow-upから親Issueへリンクし、親Issueの報告にfollow-upのリンクを書く |
| 証跡 | sanitize済みの値だけを書く。秘密値、生の回答、ジャッジの引用は書かない |

作る前にstable keyでIssueを検索し、見つかれば再利用する。途中で止まった公開は、同じ検索とrun markerで
重複を作らずに再開する。

## 測定記録の置き場

evalの出力先は既定で`test-artifacts/evals/`（`EVAL_ARTIFACT_ROOT`で変更可）で、git ignore対象である。
**残すべき測定は、測定後にsanitizeして`evals-evidence/`へ移してcommitする。** worktreeを消すと
ignored fileも消えるので、出力先に置いたままにしない。

| 置き場 | 持つもの |
|---|---|
| 出力先（`test-artifacts/evals/`） | lane record、lane log、生HTMLなど、その場の実行にだけ使う出力と、移す前の測定出力 |
| `evals-evidence/baselines/<suite>/<profile>.json` | 比較先のbaseline本体 |
| `evals-evidence/baselines/<suite>/<profile>/<baseline-version>/` | baselineの根拠artifact |
| `evals-evidence/calibration/<topic>/` | ジャッジ校正の資料、確定ラベル、生成manifest |
| `evals-evidence/scoring/<profile>/<sha>-<run-id>/` | 観測・採点・report |

`evals-evidence/`に置くのはsanitize済みのJSON / Markdownだけで、1測定を1 directoryとし、上書きしない。
suiteの定義（dataset・rubric・校正ラベル）はcodeと同じcommitで動くので`apps/api/`に残す。規約と索引は
[`evals-evidence/README.md`](../../evals-evidence/README.md)にある。

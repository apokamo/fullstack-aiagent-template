# evalの追加

この文書は、エージェントの品質を測るeval suiteを作り、baselineを登録する手順を示します。サンプルの
suite（`apps/api/sample/evals/`）を自分のエージェント向けに置き換える場合を主に扱います。

evalの規約（2段の採点、baselineとidentity、費用の上限、測定記録の置き場）は
[実LLMとeval](../dev/llm-evals.md)が正本です。先に読んでおいてください。

## suiteの構成

| file | 役割 |
|---|---|
| `dataset.json` | 測るcase。promptと、期待するtool、使ってはいけないtool、承認の扱いなど |
| `scorer.py` | 決定的チェック。tool、引数、呼び出し回数、承認の境界、書き込みを判定する |
| `rubric.json` | LLMジャッジに問う項目。回答の意味だけを問う |
| `calibration.json` | ジャッジを確かめるためのラベル付きの例 |
| `adapter.py` | 共通のrunnerにsuiteを渡す入口。`suite()`というfactoryを公開する |
| `baseline.py` | baselineの読み込みと、比較による合否の判定 |
| `cli.py` | 保存した観測の採点（`score`）と、ジャッジの確認（`validate`） |

## 1. datasetを書く

`dataset.json`の`cases`に、1 caseずつpromptと期待を書きます。サンプルのcaseを例に、toolを使うべき
case、使ってはいけないcase、承認して書き込むcase、却下するcaseを揃えます。datasetを変えたら`version`を
上げます。

## 2. 決定的チェックを書く

機械的に判定できることは`scorer.py`で判定し、ジャッジに任せません。

- toolの選択、使ってはいけないtool、引数、呼び出し回数
- 承認の境界: 承認していない書き込みが起きていないこと
- 書き込み: 承認した数を超えて書き込んでいないこと

承認の境界と書き込みの安全性は重大な項目として扱い、ジャッジの結果で相殺しません。scorerを変えたら
versionを上げます。

## 3. rubricを書く

`rubric.json`の各項目は、1つの問いだけを持つ原子的な問いにし、`pass`と`fail`の条件を書きます。tool選択の
ように決定的チェックで判定できることは問いに入れません。

## 4. ジャッジを確かめる

```sh
make evals-judge-validate
```

`calibration.json`のラベルとジャッジの判定が一致するか（false pass、false fail、採点できた割合）を
確かめます。ラベルは、自分のrunの観測から作ったものに置き換えていきます。rubricやジャッジを変えたら、
実runを採点する前にこれを実行します。ジャッジの差し替えは、`apps/api/agent/evals/judge.py`の
`JudgeClient`の別の実装を渡して行います。

## 5. 測る

```sh
LLM_PROFILE=<profile> make evals-observe
make evals-score SCORE_ARGS="--observations <dir> --record-reference"
```

観測を保存してから採点すると、agentを再実行せずにジャッジやrubricを替えて採点し直せます。1回で実行と
採点をする場合は`LLM_PROFILE=<profile> make evals EVAL_ARGS=--record-reference`を使います。費用は
`--max-cost-usd`の上限で止まります。

## baselineを測る

baselineはprofileごとに、比較の基準となる最小の率とidentityを持ちます。

1. `--record-reference`で、比べずに測ります。repeatsを揃えて複数回測り、ばらつきを見ます
2. 測定の出力（`test-artifacts/evals/`）をsanitizeして`evals-evidence/`へ移します。置き場の規則は
   [`evals-evidence/README.md`](../../evals-evidence/README.md)にあります
3. `evals-evidence/baselines/<suite>/<profile>.json`を作ります。`minimum_rates`は測定値そのものではなく、
   ばらつきを見て決めた下限にします。identityの値は測定のartifactから写します
4. baselineはレビューを経てから登録します。登録したら`evals-evidence/README.md`の索引に足します

以後は、`LLM_PROFILE=<profile> make evals`がbaselineと比べて合否を出します。

## 2つ目のsuiteを足す場合

サンプルとは別のsuiteを並べる場合は、次も必要です。

- `apps/api/agent/evals/runner.py`の`SUITE_MODULES`にsuiteのIDとadapterのmoduleを足します。`make evals`は
  `EVAL_ARGS="--suite <id>"`で選びます
- `make evals-score`と`make evals-judge-validate`はサンプルの`cli.py`を呼んでいます。新しいsuiteにも
  同じtargetを足すか、suiteを選べるようにします

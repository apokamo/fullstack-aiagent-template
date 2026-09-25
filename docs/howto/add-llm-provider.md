# LLM providerとprofileの追加

この文書は、使えるmodelと接続先（profile）を追加する手順を示します。providerの追加、既存providerへの
modelの追加、evalのジャッジの追加を扱います。

前提として、[アーキテクチャのLLM provider](../architecture.md#llm-provider)と
[実LLMとeval](../dev/llm-evals.md)を読んでおいてください。

## profileが決めるもの

profileは`apps/api/core/llm_profiles.py`の`PROFILES`に置き、provider、model、protocol、API mode、接続先、
reasoning effort、画面の表示名を一組で決めます。model名や接続先を個別のenvで上書きする経路は作りません。

## 1. providerを足す

新しいproviderを使う場合は、`PROVIDERS`に`ProviderDefinition`を足します。

- 認証が要らないproviderは`auth="none"`、`credential_env=None`にします
- API keyが要るproviderは`auth="api-key"`にし、`credential_env`にそのprovider専用のenv名を付けます。
  providerの間でenvを使い回しません
- 同じproviderのprofileを足すだけなら、この手順は要りません

credentialのenv名は、loaderが置き場所を検査する対象に自動で入ります。`secrets/api.env`の雛形
（`scripts/env/generate-secrets-template.sh`）に説明とkeyを足し、`scripts/env/check-secrets.sh`で
`secrets/api.host.env`に置いてはいけないkeyの一覧にも足します。

## 2. profileを足す

`PROFILES`に`ChatProfile`を足します。

- profileのIDは小文字、数字、`-`だけで書きます。evalの出力先のpathにも使います
- `api_mode`は`chat-completions`か`responses`です。protocolはOpenAI互換だけを扱います。OpenAI互換で
  ないAPIを使う場合は、`apps/api/agent/model_factory.py`にmodelの作り方を足す必要があります
- `reasoning_effort`は、そのmodelとAPI modeが受け付ける値にします。modelによっては、tool呼び出しと
  組み合わせられる値が限られます
- `label`は画面の選択欄に出る名前です

## 3. 単価を足す

evalは費用の上限を守るため、`MODEL_PRICES`に単価の無いmodelでは実行できません。providerの公開価格表を
確かめて、1M tokenあたりのinputとoutputの単価を足します。

## 4. 確かめる

```sh
make check-all
LLM_PROFILE=<profile> make test-llm
```

`make test-llm`は、providerへ実際にrequestを送り、toolの宣言、出力の上限、reasoning effortが意図どおりに
送られていることを確かめます。credentialは`secrets/api.env`に設定します。

## 5. baselineを測る

新しいprofileにはbaselineがありません。baselineの無いprofileは、比較つきの`make evals`を実行できません。
他のprofileのbaselineを流用せず、[evalの追加](add-eval.md#baselineを測る)の手順で測ります。

## ジャッジを足す

evalのLLMジャッジは、agentのprofileとは別の`JUDGE_PROFILES`から`LLM_JUDGE_PROFILE`で選びます。

1. `JUDGE_PROFILES`に`JudgeProfile`を足し、`MODEL_PRICES`に単価を足します。ジャッジはResponses APIの
   構造化出力を使います
2. `make evals-judge-validate`で、ラベル付きの例との一致を確かめます
3. ジャッジを替えると採点のidentityが変わるので、baselineを測り直します

agentと同じmodelで採点すると評価が甘くなりやすいので、本番の評価では別のmodelのジャッジを選びます。

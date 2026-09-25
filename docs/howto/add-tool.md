# toolの追加

この文書は、エージェントにtoolを追加する手順を示します。読み取りだけのtoolと、承認が要る書き込みtoolの
両方を扱います。サンプルの`search_docs`（読み取り）と`save_note`（書き込み）が実例です。

前提として、[バックエンド実装規約](../reference/backend/coding.md#toolとhitl)と
[アーキテクチャのHITL](../architecture.md#hitl)を読んでおいてください。

## 1. toolが読む依存を決める

toolがrunごとに使う依存（検索の供給元、書き込み先など）を`Protocol`で宣言し、agentの`deps`の型に
fieldを足します。

- サンプルでは`apps/api/sample/tools.py`の`SampleToolDeps`がprotocol、`apps/api/sample/agent.py`の
  `SampleDeps`がdepsの型です
- depsはrunごとに新しく作ります（`default_sample_deps()`）。runをまたいで状態を共有しません

## 2. tool関数を書く

```python
def lookup_order(ctx: RunContext[MyToolDeps], order_id: str) -> OrderResult:
    """注文を1件読む.

    Args:
        ctx: runの文脈。
        order_id: 注文のID。

    Returns:
        modelに返す注文の内容。
    """
    return ctx.deps.orders.get(order_id)
```

- 第1引数は`RunContext[...]`です。残りの引数と戻り値の型、docstringがmodelへのtoolの説明になります
- 戻り値はpydanticのmodelにし、modelが次に取るべき行動を判断できる情報を含めます
- 書き込みtoolの戻り値の文言は、実際に起きたことだけを書きます（保存しない場合に「保存した」と
  書かない）

## 3. 登録する

`apps/api/agent/approval.py`の`agent_tool`で登録します。登録はagentを定義するmoduleで1回だけ行います。

```python
agent_tool(agent, registry, mutates=False)(lookup_order)   # 読み取り
agent_tool(agent, registry, mutates=True)(cancel_order)    # 書き込み（承認が要る）
```

- 書き込みや外部への副作用を伴うtoolは`mutates=True`にします。modelが呼ぶとrunが止まり、利用者が承認して
  から実行されます
- 同じ状態を読み書きするtoolが同時に呼ばれうる場合は`sequential=True`を付けます
- toolを使う条件をagentのinstructionに書きます。承認が要るtoolは、却下されたときに同じ内容で呼び直さない
  ことも書きます
- 1 turnのtool呼び出し数とrequest数の上限（サンプルでは`sample_turn_usage_limits()`）が足りるかを
  見直します

## 4. fake modelの応答を足す

E2Eと`AGENT_MODEL_MODE=fake`の起動は、`apps/api/sample/fake_model.py`のfake modelで動きます。新しい
toolを呼ぶ流れをE2Eで確かめる場合は、fake modelに次を足します。

- どのuserの発話で、どの引数でtoolを呼ぶか
- toolの結果（書き込みtoolでは承認と却下の両方）を受けたときに返す文

## 5. テストを書く

- tool関数そのもの: 入力と戻り値、書き込み先に何が書かれたか（Small）
- 書き込みtool: 承認前に実行されないこと、承認後に1回だけ実行されること、却下で実行されないこと。
  `FunctionModel`でtoolを呼ぶmodelを作り、`/api/chat`を2回呼んでrunの状態を確かめます（Medium）。
  `apps/api/tests/test_chat_hitl.py`が例です
- 画面の流れが変わる場合は、E2Eを更新します

書き方は[バックエンドテスト](../reference/backend/testing.md)を参照してください。

## 6. evalの決定的チェックを足す

実modelがtoolを正しく選ぶかはevalで測ります。datasetのcaseに、期待するtool、使ってはいけないtool、
承認の扱いを足し、scorerがそれを判定するようにします。手順は[evalの追加](add-eval.md)を参照して
ください。

## 確認

```sh
make check-all
make test-e2e
LLM_PROFILE=<profile> make test-llm
```

promptやtoolを変えたときの確認は[テスト実行マトリクス](../dev/test-execution-matrix.md#変更の種類ごとのlane)に
従います。

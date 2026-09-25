# バックエンドテスト

この文書は、backendのテストの置き場所と書き方を決めます。`apps/api/`と`scripts/`のテストを書くときに
読みます。どの層のテストを書くか、何をテストするかは[テスト規約](../../dev/test-policy.md)、どのlaneで
実行するかは[テスト実行マトリクス](../../dev/test-execution-matrix.md)を正本とします。

## 配置

| 対象 | 置き場所 |
|---|---|
| API、agent、設定、依存の向き、Docker build context | `apps/api/tests/` |
| `scripts/`（DB guard、env生成、lane record、文書検査など） | `scripts/tests/` |

marker、fixtureの共通定義はrootの`conftest.py`と`apps/api/tests/conftest.py`にあります。

## markerと層

- すべてのテストに層のmarker（`small`、`medium`、`large`）か、専用のmarker（`llm`、`on_schema_change`など）を
  付けます。付け忘れは収集の時点で失敗します
- `medium`はDBのfixtureを使うか、`pytest.mark.uses_resource("filesystem")`のように使うresourceを宣言します
- markerの一覧はrootの`conftest.py`と`pyproject.toml`、層の定義は
  [テスト規約](../../dev/test-policy.md)が正本です

## model

- `small`と`medium`では、実modelへのrequestをpydantic-aiの層で遮断しています（rootの`conftest.py`の
  `block_model_requests`）。modelが要るテストはpydantic-aiの`TestModel`か`FunctionModel`を使います
- agentのmodelとdepsは`agent.override(model=..., deps=...)`で差し替えます。tool呼び出しの順序を決めたい
  場合は、`FunctionModel`でtool callとtextを返すstream関数を書きます
- サンプルのfake model（`apps/api/sample/fake_model.py`）は、E2Eと`AGENT_MODEL_MODE=fake`での起動に使います

## DBを使うテスト

- DBには`secrets/test.env`の`DATABASE_URL`（テスト専用DB）で接続します。テストの中で接続先を組み立てたり、
  既定値に落としたりしません
- `db_session` fixtureは外側のtransactionを開き、最後にrollbackします。アプリのコードが書いた行も、同じ
  sessionから読めます
- `small`で`/api/chat`を呼ぶテストは、`stub_persistence` fixtureでrunの記録を差し替えます
- DBの作成とmigrationはmake targetが行います。初回は`make test-db-init`を実行してください。pytestを直接
  実行する場合は`DB_ENV_CONTEXT=test`を設定します

## APIのテスト

- `small`では`fastapi.testclient.TestClient(app)`、`medium`では`httpx.AsyncClient`と`ASGITransport`で
  `apps.api.main.app`を呼びます
- lifespanを通さずにrequestを送るテストは、`apps/api/tests/conftest.py`の`bound_app_runtime(app)`で
  runtimeを結びます
- エラー応答は、status code、`code`（付く場合）、`request_id`を確かめます。応答に受け取った値や例外の本文が
  含まれないことも確かめます

## SSEとHITLのテスト

- SSEは、streamのpartの種類と順序を確かめます。文言や件数は写しません（例:
  `apps/api/tests/test_chat_sse_approval.py`）
- HITLは、承認と却下の両方で、承認前にtoolが実行されないこと、再送後のrunの状態、toolの実行回数を
  確かめます（例: `apps/api/tests/test_chat_hitl.py`）

## 実LLMのテスト

- 実providerへの接続を確かめるテストには`llm` markerを付けます。通常のgateには含まれず、`make test-llm`で
  実行します
- 応答の中身は採点しません。providerへ送ったrequestの形（tool、上限、reasoning effort）と、runが最後まで
  進むことを確かめます。品質の測定は`make evals`で行います。規約は[実LLMとeval](../../dev/llm-evals.md)を
  参照してください

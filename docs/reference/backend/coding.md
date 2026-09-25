# バックエンド実装規約

この文書は、`apps/api/`と`scripts/`のPythonコードの書き方を決めます。backendのコードを追加・変更するときに
読みます。層の分け方と処理の流れは[アーキテクチャ](../../architecture.md)、テストの書き方は
[バックエンドテスト](testing.md)を参照してください。

## 配置と依存の向き

- 用途に依存しない仕組みは`agent/`と`core/`、サンプル固有のものは`sample/`に置きます。サンプル固有の値
  （tool名、文言、予算、corpus）を共通moduleに書きません
- 共通部分から`sample/`をimportしてよいのは`apps/api/application.py`だけです。製品コードは`scripts/`を
  importしません。詳細は[アーキテクチャの依存の向き](../../architecture.md#依存の向き)を参照してください

## 命名

- module、関数、変数は`snake_case`、classは`PascalCase`、定数は`UPPER_SNAKE_CASE`にします
- moduleの外から使わない名前は`_`で始めます
- testの関数名は、確かめる振る舞いを文として書きます（例: `test_blocks_the_app_database`）

## 型

- mypyの`strict`を通すことを必須にします。設定の正本は`pyproject.toml`の`[tool.mypy]`です
- すべての関数に引数と戻り値の型を書きます。`Any`は、外部libraryの型が表せない箇所と、用途ごとに型が
  変わる値（agentの`deps`など）に限ります。それ以外は具体的な型か`Protocol`で書きます
- `# type: ignore`は、外部libraryの型定義が実装と合わない場合と、pydantic-settingsのように必須値を
  envから埋めるclassを引数なしで作る場合に限ります。`# type: ignore[arg-type]`のようにerror codeを付け、
  理由が自明でなければ同じ行か直前の行に書きます
- testのmodule（`apps/api/tests/`、`scripts/tests/`）は、`pyproject.toml`で型検査を緩めています

## async

- request経路のI/O（DB、LLM、HTTP）は`async`で書き、event loopを止める同期I/Oを呼びません
- DBの接続とmodel clientは、作ったevent loopの中で閉じます。別のevent loopへ持ち越しません
- 並行に走るtoolが同じ状態を読み書きする場合は、`agent_tool(..., sequential=True)`で登録します

## 設定の追加

- 設定は`apps/api/core/config.py`の読み手別のSettings class（API、会話DB、LLM）にfieldとして追加し、
  getter経由で読みます。moduleのimport時にenvや設定を読みません
- 必須の設定はdefaultを持たせず、未設定を起動の失敗にします。誤った値に黙ってfallbackしません
- envのkeyを追加したら、`.env.example`か`scripts/env/generate-secrets-template.sh`の生成物に説明を
  追加します
- LLMのmodel名、接続先、credentialのenv名は、個別の設定ではなく
  `apps/api/core/llm_profiles.py`のprofileとして追加します

## 例外とエラー応答

- 利用者の入力が原因の失敗（4xx）と、依存先が使えないことを利用者に伝える失敗（503）は`HTTPException`で
  返します。想定外の失敗は例外のまま上げ、共通のhandlerが500に変えます。応答の形は
  [エラー処理とログ](../error-handling-and-logging.md#エラー応答の契約)を参照してください
- 応答のmessageには、受け取った値、例外の本文、DSNなどの接続情報を入れません
- 例外を握りつぶしません。捕まえた場合は、記録したうえで上げ直すか、失敗として応答に変えます

## ログ

- `apps/api/core/logging.py`の`get_logger(__name__)`でloggerを取り、event名を第1引数、値を`extra`で
  渡します（例: `logger.info("app_start", extra={...})`）
- 秘密値、会話の本文、接続文字列をログに出しません。規則は
  [エラー処理とログ](../error-handling-and-logging.md)が正本です

## toolとHITL

- toolは`apps/api/agent/approval.py`の`agent_tool`だけで登録します。書き込みや外部への副作用を伴う
  toolは`mutates=True`にし、承認前に実行されないようにします
- toolが読む依存は`Protocol`で宣言し、runごとに新しく作ります（`AgentDefinition.new_turn`）。runを
  またいで状態を共有しません

## lifecycle

- 外部resource（DB、model client、用途固有の接続）は`AgentRuntime`に`RuntimeResource`として渡し、
  取得と後始末を1か所で管理します
- 後始末は、取得前に呼ばれても安全に書きます。起動の途中で失敗したときに、取得済みのものだけを
  閉じるためです

## コメントとdocstring

- 公開する関数とclassにはdocstringを書きます。形式はGoogle style（`Args:`、`Returns:`、`Raises:`、
  `Yields:`）です
- コメントには、コードから読み取れない理由と制約だけを書きます。変更の経緯、Issueの番号、作業の段階は
  書かず、Issue、PR、commit messageに残します

## lintとformat

- ruffのlintとformatで差分が無いことを必須にします。ruleと行長の正本は`pyproject.toml`の`[tool.ruff]`です
- `# noqa`は、ruleが意図に合わない1行に限り、`# noqa: ARG001 - 理由`のようにrule番号と理由を付けます
- 確認は`make verify-backend`で行います。lint、format、型検査、Small/Mediumのテストをまとめて実行します

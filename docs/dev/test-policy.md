# テスト規約

この文書は、どの層のテストを書くか、何をテストし何をテストしないかを決めます。テストを追加・削除するときと、
変更の確認範囲を決めるときに読みます。実行するlaneとコマンドは[テスト実行マトリクス](test-execution-matrix.md)、
書き方は[バックエンドテスト](../reference/backend/testing.md)と
[フロントエンドテスト](../reference/frontend/testing.md)を参照してください。

## 目的

テストは、テンプレートの利用者がサンプルを置き換えても壊してはいけない振る舞いを守るために置きます。
変更のたびに同じ結果になる決定的なテスト、実providerとの接続の確認、modelの品質の測定を分け、
実modelの応答に依存する確認を決定的なテストに混ぜません。

## テストの層

| 層 | marker | 使ってよいもの |
|---|---|---|
| Small | `small` | process内の処理とtest double。DB、filesystem、networkは使わない |
| Medium | `medium` | localhostのDBとfilesystem。使うresourceを宣言する。外部APIは使わない |
| Large | `large` | 制限なし。実際のDBと外部への接続を含む |
| schema | `on_schema_change` | 使い捨てのPostgreSQLへのmigrationとDDL |
| 実LLM | `llm` | 実providerへの接続 |

markerの定義はrootの`conftest.py`と`pyproject.toml`が正本です。層のmarkerと専用のmarker（`llm`、
`on_schema_change`など）を同じテストに重ねません。

webのテストの分類（Small / Medium / LargeとE2E）とテストケースの台帳は
[フロントエンドテスト](../reference/frontend/testing.md)を正本とします。

## 層の選び方

- まずSmallで書けるかを考えます。DBやfilesystemを使わないと確かめられない振る舞いだけをMediumにします
- 実modelの応答に依存する確認は、Small・Mediumではなく`llm`のテストか[eval](llm-evals.md)に置きます
- migrationとDDLを含むテストは`on_schema_change`にします

## 何をテストするか

サンプルの振る舞いと、共通部分の契約をテストします。

- サンプル: toolが返す結果、書き込みtoolが承認前に実行されないこと、fake modelでの一連の流れ
- HITL: 承認・却下の後のrunの状態とtoolの実行回数
- SSE: streamのpartの種類と順序
- 永続化: runの記録、書けないときに応答を流さないこと
- エラー契約: 応答の形と、入力値や例外の本文を返さないこと
- 設定: 必須の設定が欠けたときに起動が失敗すること
- 秘密値: ログ、応答、artifactに出ないこと
- DBの取り違え防止: テスト用でないDBへの書き込みと削除を止めること

## 書いてはいけないテスト

- 値、文言、件数、model名、ファイルの一覧をテストに写して二重に固定するテスト。値の正本はコードに
  1つだけ置きます。この禁止は設定ファイルや定数の値を写すテストが対象で、UIの表示を確かめるテストは
  対象外です
- 配線やファイルの配置を確かめるだけのメタテスト。ただし依存の向きのように、壊れても振る舞いのテストで
  気付けない構造の規則は例外とします
- coverageの閾値を満たすためだけのテスト
- 実行する経路が無いテスト（どのlaneも実行しない、skipされたまま残る、など）

必須の確認を`skip`で成功扱いにしません。

## 規模の目安

| 対象 | 目安 |
|---|---|
| backend（`apps/api/tests/`と`scripts/tests/`） | 200〜250件 |
| web（Vitest） | 約50件 |

E2Eの本数は[テストケースの台帳](../reference/frontend/testing.md#テストケースの台帳)のケースから決まります。
目安を超えそうなときは、同じ分岐を確かめる複数のテストを代表の1件に寄せます。

## coverage

- backendは`gate-backend`（`make check-all`に含まれる）だけがcoverageを測ります。測る範囲、除外、閾値は
  `pyproject.toml`の`[tool.coverage.run]`と`[tool.coverage.report]`が正本です
- webにはcoverageの閾値を置きません

## `scripts/`のテスト

- `scripts/`はcoverageの対象外にし、`scripts/tests/`の振る舞いのテストで守ります。subprocessで実行する
  部分をcoverageで数えられないためです
- 誤ると事故になるもの（DB guard、secretとenvの生成、lane record）は必ずテストを持ちます
- `scripts/tests/`は`make check-all`で毎回実行します。Makefile、env、Compose、skillなど`scripts/`の外の
  変更でも壊れるためです

## 実LLMのテストの分離

- 実providerへの接続は`llm` markerのテストで確かめ、通常のgateには含めません。Small・Mediumでは実modelへの
  requestを遮断しています
- modelの品質は`make evals`で測ります。合否と観測の扱いは[実LLMとeval](llm-evals.md)を参照してください

## DBを使うテストの安全

- テストが書き込むDBは`secrets/test.env`のテスト専用DBだけです。make targetは、接続先に到達できることと、
  DB名がテスト用であることを検査してから実行します
- 検査の規則は`scripts/common/db_guard.py`が正本です。テストの中で接続先を組み立てたり、既定値に
  落としたりしません

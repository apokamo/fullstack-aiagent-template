# CIへの組み込み

この文書は、テンプレートをCIに組み込むときの入口を示します。CIの定義fileは同梱していません。自分の
リポジトリでCIを設定するときに読みます。

## 実行するtarget

CIでは`make check-all`を実行します。lint、型検査、決定的なテスト、migration、文書の検査がこの1つで
揃います。含まれるlaneは[テスト実行マトリクス](test-execution-matrix.md)を参照してください。

## 必要なもの

- Python、uv、Node.js。versionは[技術スタック](../tech-stack.md#versionの正本)に挙げたfileに従います
- PostgreSQL。テスト専用DBを作れる接続先を用意し、`secrets/test.env`の`DATABASE_URL`を渡します。
  DBの作成とmigrationは`make test-db-init`で行います
- `secrets/`の雛形は`make env-secrets-template`で作り、CIのsecretから値を書き込みます。fileの権限は
  700（directory）と600（file）にします

## 任意のlane

- `make test-e2e`はbrowserを起動するため時間がかかります。画面や中継を変えたPRだけで実行するなど、
  条件を付けて組み込みます
- `make test-llm`と`make evals`は実providerのcredentialを使い、費用がかかります。通常のCIには含めず、
  手動で起動するjobにします

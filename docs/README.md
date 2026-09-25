# ドキュメント

目的に合わせて、次の文書から読み始めてください。文書の置き場所と書き方は
[ドキュメントの書き方](dev/docs-workflow.md)にあります。

## 始める

- [開発環境のセットアップ](howto/development-environment.md): toolchain、secret、DB、起動、うまくいかないとき
- [テンプレートの使い方](howto/use-template.md): リポジトリの作成、名前の付け替え、サンプルの置き換え

## 作る

- [toolの追加](howto/add-tool.md): 読み取りtoolと、承認が要る書き込みtool
- [LLM providerとprofileの追加](howto/add-llm-provider.md): provider、profile、単価、ジャッジ
- [evalの追加](howto/add-eval.md): suite、決定的チェック、rubric、baseline
- [APIのendpointの追加](howto/add-api-endpoint.md): router、登録、webからの中継
- [migrationの追加](howto/add-migration.md): ORMの変更、revision、適用と確認

## 規約

- [開発ワークフロー](dev/development-workflow.md): Issueからmergeまでの進め方とworktree
- [git規約](dev/git-conventions.md): branch、commit、PR、コメントの方針
- [テスト規約](dev/test-policy.md): テストの層、何をテストし何をテストしないか
- [テスト実行マトリクス](dev/test-execution-matrix.md): laneの一覧と、変更ごとに実行するlane
- [実LLMとL2 evals](dev/llm-evals.md): 実providerの確認、evalの採点とbaseline
- [CIへの組み込み](dev/ci-integration.md): CIで実行するtargetと必要なもの
- [ドキュメントの書き方](dev/docs-workflow.md): 置き場所、段階的開示、言語、検査
- [ドキュメント更新基準](dev/documentation-update-criteria.md): どの変更で文書を更新するか

## 参照

- [アーキテクチャ](architecture.md): 層、依存の向き、1 turnの流れ、HITL、永続化
- [技術スタック](tech-stack.md): 使っている技術と選定理由、versionの正本
- [バックエンド実装規約](reference/backend/coding.md)と[バックエンドテスト](reference/backend/testing.md)
- [フロントエンド実装規約](reference/frontend/coding.md)、[フロントエンドテスト](reference/frontend/testing.md)、
  [デザインシステム](reference/frontend/design-system.md)
- [エラー処理とログ](reference/error-handling-and-logging.md): エラー応答の契約、ログに出さないもの
- [セキュリティ](reference/security.md): 秘密値、browserに渡さないもの、認証を足すときの方針
- [コンテナservice仕様](reference/container-services.md): Composeのservice

## kaji

- [Kajiワークフロー](dev/workflow-overview.md): workflowの全体像
- [ワークフローの完了基準](dev/completion-criteria.md): 各stepの完了条件
- [共通skill規約](dev/shared-skill-rules.md): skillを書くときの規則
- [Issueラベル](dev/issue-labels.md)と[incidentラベル](dev/incident-labels.md)

# ドキュメント更新基準

コード変更が次の内容へ影響する場合は、同じ変更でドキュメントも更新します。

- 対応コマンド、環境変数、provider設定、失敗時の動作
- 公開API、data schema、tool schema、HITLの振る舞い
- テスト分類、gate選定、coverage、ローカル実行、artifact
- 運用・開発workflow、label、worktree、incident対応
- ユーザーから見えるプロダクトの振る舞い

契約を変えない内部実装の詳細は、コメントとテストだけで十分な場合があります。
過去の計画書を現在の振る舞いの正本にはしません。

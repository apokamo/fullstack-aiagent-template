# ワークフローの完了基準

kajiの開発項目は、次の条件をすべて満たした場合にのみ完了とします。

- 通常Issueにcanonical `type:*`が1個だけあり、devではcanonical `area:*`が1個以上あり、
  [Issueラベル](issue-labels.md)、設計scope、実diff、受け入れ条件が整合している
- 設計、実装、独立レビューの証跡が永続的に記録され、標準dev Issueでは`designs/issues/`の
  design commitとIssue本文のpermalinkが同じrevisionを示している。一意な参照だけの不整合は
  発見工程で同期してよく、そのためだけに再設計・空commit・同一HEADの検証再実行を要求しない。
  tracked設計path修復などでHEADが変わる場合は、新HEADの必要な検証と独立レビューを行う
- 軽量devはIssueの決定、実装報告、独立した統合レビュー/再確認の承認とfull SHAを正本とし、
  設計artifact/precheckは要求しない。レビュー前停止や人間レビューだけでは完了にしない
- 差分から選択した決定的テスト、schema、E2E、実LLM疎通が成功し、evalは
  [LLM検証の目的別契約](llm-evals.md#変更目的とissueの完了条件)を満たしている
- 品質閾値の達成が完了条件のevalでは、必要なidentity（profile／provider／model／protocol／API mode／
  reasoning effort）ごとに、対象commitに対する**最後のattemptで必須の品質指標がすべて合格しており**、そのartifactが
  同じcommit・同じidentityの全attemptを`attempts[]`に含んでいる。別identityの
  runは`attempts_other_identity[]`で開示します。成功runだけを選んで引用したことにはできません
  ——artifact自身が同じidentityの失敗attemptを提示します。観測項目だけが未達ならartifactの
  `passed=false`を保持し、指標ごとの判定と[引き継ぎ](llm-evals.md#観測項目の未達を引き継ぐ)で完了条件を照合します
- branchを考慮したcoverageが設定済みの80%以上を維持している
- 対象clean HEADの`make check-all`成功証跡（実行またはexact record引用）があり、差分から選定した
  追加laneも目的別の完了条件を満たしている。観測項目の閾値未達はFAILのまま全件完走・
  結果記録・follow-upを確認し、他条件も充足すれば完了できる。成功recordは捏造しない。
  別のpre-commit invocationは要求しない
- PR作成は現在の最終承認とclean HEADの一致を確認する。PR修正後は独立再確認がそのSHAの
  full gateと必須laneを満たし、元の指摘と修正による回帰を確認する。docs-onlyはverify-docsを使う
- 対象commitのローカル検証結果がIssueへ記録され、必要なPR reviewが完了している
- 完了扱いにした各Issue項目が証跡を参照している

providerへ到達できない、必須evalをskipした、artifactがない、またはGitHubのstatus checkを
ローカルfull gateの代わりにした状態は完了ではありません。品質判定はGitHub Actionsへ依存せず、
Issue worktreeでkajiが実行したMake targetと条件付きlaneの証跡を正本とします。

merge後または外部環境でしか確認できない基準は、明確な名称のpost-workflow節へ分離し、
実際に確認するまで未完了のままにします。

## 終端lifecycle

dev/docs workflowは`issue-close`が次を完遂した時点で終了します。

- 上流でPR承認と最終検証が完了した引き継ぎを受け、Issue・branch・baseから一意に特定したPRを
  公開HEADの固定とmerge直前の再取得後、`--match-head-commit <merge_head_sha>`付きでmainへ
  mergeし、provider mergedとremote main包含を確認する
- 未チェックのpost-workflow項目をfollow-up Issueへ引き継ぐ。冪等性は親Issue本文のmarker行
  `> follow-up: #<created_issue_id> post-workflow criteria`で担保し、markerがあれば引継ぎ済みとする
- exact known worktreeだけを削除し、dirty/unknown assetは理由付きで残す
- local mainを`origin/main`へff-only同期し、同期後に`HEAD`が`origin/main`と一致することを確認する。
  `--ff-only`は`HEAD`がaheadでも`Already up to date`で成功するため、exit statusだけでは同期を判定しない
- exact known branchは`git merge-base --is-ancestor`で包含を確認したうえで`git branch -D`で削除する。
  branchは`--no-track`で作るため`-d`はupstreamを持たず`HEAD`基準で判定してしまう。remote branchは独立に確認する
- merge、follow-up、cleanup、retained asset、main SHAのsummaryを投稿してIssueを明示closeする

PR承認の所有者は`review-poll`（自動レビュー）、`review`（fallback）、`pr-verify`（修正後検証）です。
同じSHAに対する最終検証の品質要件は、標準devのfinal-check、dev-smallのreview-change / verify-change、
docs最終確認、修正後のpr-verifyが所有します。closeは正常なPASS遷移をその完了の引き継ぎとして扱い、
承認やlaneを再審査しません。formal reviews空、Issue PR-cycle marker不在、previous_verdict未注入、
poll YAMLのfull SHA欠落だけで停止せず、reviews/comments/reactionsを巡回して承認を再構築しません。

closeは対象PR/base/branchの同一性、既存上流報告にある対象SHAとの一致、merge直前の公開HEAD不変を
確認します。既知SHAの不一致、観測したHEAD変化、対象曖昧、provider取得失敗ではmergeせず停止します。
初回の公開HEAD取得は操作対象の固定であり、botの承認SHAの証明ではありません。上流SHAが不明なとき、
初回取得より前の変更をcloseが新しいbot解析で検出する保証は追加しません。
手動再実行はoperatorが示した承認済み対象という使用前提に従い、既に示された承認を重ねて要求しません。
対象・使用前提が不明なら具体的な不足を報告し、既存review経路かoperatorの情報補完へ戻します。
入口と操作の正本は[close skill](../../.claude/skills/issue-close/SKILL.md#upstream-completion-handoff)です。

merge後にcleanupまたはmain同期が失敗した場合は`ABORT`し、同じ
`issue-close`を再実行します。Issueを閉じるのは最終stepだけです。再実行はGitHubとGitから現在状態を再取得し、merge、follow-up、
cleanupを重複実行しません。

# 開発ワークフロー

`origin/main`を基点に、Issue専用worktreeを使用します。main checkoutはオーケストレーションと
確認に使い、実装、生成した設計artifact、commitはIssue worktreeに置きます。唯一の例外は
[実装前の画面モック](#実装前の画面モック)で、workflow開始前に限りmain checkoutで作成・commit・pushします。
`KAJI_WORKTREE_DIR`が注入されている場合はその値を正とします。それ以外の場合は、固定した親directoryを
使わず、Issueの証跡と`git worktree list`からpathを解決します。利用者の既存変更を保持し、
このIssueの作業で上書き・破棄しません。

有人でIssueを起票した直後、one-way doorを含みうるIssueでは`grill-me`を明示起動し、重要判断を
Issue本文の`## 決定事項`へ固定してからworkflowへ渡します（軽微なIssueはスキップします）。
位置づけは[Kajiワークフロー](workflow-overview.md)の有人起動skillを参照してください。

workflowはcanonical main checkoutから起動します。commandは
`uv run --no-sync kaji run .kaji/wf/custom/<family>/<workflow>.yaml <issue-id> --no-auto-recover`です。
起動前にcheckoutが`main` branchにいること（detached HEADや別branchでは起動しない）、
mainがcleanで`origin/main`に対して非divergedであることを確認し、
`git merge --ff-only origin/main`と`uv sync --frozen --group dev`を実行します。条件を満たさない場合は
変更をstash / revertせず、起動しません。command全文と各flagの理由は[Kajiワークフロー](workflow-overview.md)の
起動手順を参照してください。

Kajiはagentを更新済みmain checkoutから起動します。agentの操作対象はIssue worktreeであり、
tracked fileの変更、テスト、commit、pushは絶対pathで解決したそのworktreeだけで行います。
mainへIssue実装のdiffは作りません。この規定はworkflow内のagentに適用し、workflow開始前に人が作る
[実装前の画面モック](#実装前の画面モック)には適用しません。

標準dev workflowは次の順序で進みます。

1. [Issueラベル](issue-labels.md)を含む着手準備をレビューし、必要なら修正する
2. Issue用branchとworktreeを作成または再利用する
3. 要件から設計し、設計を独立レビューする
4. 事前確認、実装、コードの独立レビューを行う
5. 変更をcommitしてから、決定的なfull gateと選択したschema、E2E、実LLM、evalのlaneを
   clean HEADで実行する。後続phaseは同じcommitのlane recordを引用する
6. pushしてPRを作成し、レビュー指摘を処理する
7. 上流工程のPR承認・最終検証完了を`issue-close`が引き継ぎ、対象PRと公開HEADを確認して
   PR merge、follow-up引継ぎ、worktree/branch cleanup、
   main同期、summary投稿、Issueの明示closeまでを完遂する

各stepは証跡を投稿し、workflowで許可されたverdictだけを出力します。設計stepはscopeと
テスト選定、実装stepはコードと局所的な証跡を所有します。review stepはテスト選定を独立して
再計算します。final checkは全gateと受け入れ条件の突き合わせを所有します。

標準devの設計書は`designs/issues/issue-<id>-<slug>.md`へcommitします。repository版は後続AIと実装者が
判断履歴を復元するための正本です。design create/fixはcommit後のSHA、permalinkと20行以内の要旨を
Issue本文の管理blockへ同期します。implement/fix-codeが意味不変な設計修正をcommitした場合も
その工程で同期します。一意に復元できる参照だけの不整合は発見工程で修復し、同一HEADの検証証跡を
引き継ぎます。実質的な設計変更は必要な修正・独立レビューへ送り、参照同期だけでは承認しません。Kajiが互換値として注入する
`draft/design/...`はlegacy入力であり、repository resolverを通してcanonical pathへ変換します。
現在の挙動はcodeと`docs/`を正とし、過去設計だけで上書きしません。

[完了基準](completion-criteria.md)、[テスト実行マトリクス](test-execution-matrix.md)、
[実LLMとevals](llm-evals.md)も参照してください。

## 小修正の軽量経路

決定済みで局所的に検証でき、通常revertで戻せるdev Issueには`dev-small.yaml`を明示選択できます。
Issueの決定と短い修正方針を使い、設計artifact/precheckを作らず、実装・検証と独立レビュー・最終確認を
2つの責務へまとめます。専用worktree、clean HEADの必須検証、PR review、closeは維持します。
適用条件、起動・レビュー前停止・再開、標準devへの手動引継ぎは
[小修正向けdev-small](workflow-overview.md#小修正向けdev-small)を参照してください。
以下の承認設計を使う実装手順は標準dev向けです。軽量経路はIssueを正本として同じdiff-based laneを選びます。

## 実装前の画面モック

UIを新規に作るIssue、レイアウトや操作導線が変わるIssueでは、要件整理の段階、実装設計を書く前に
画面モックの作成を推奨します。全UI変更の必須gateではありません。文言修正や軽微な余白調整のように
モックの効果が小さい変更では省略します。

画面モックは、要件整理の段階ではIssue本文に相当する要件確認資料です。実装の段階では、実装設計書から
pathと確認済みrevisionを参照して、UI設計書の一部として扱います。画面構成、情報の優先順位、操作の配置、
レスポンシブ表示の意図は、設計・実装・レビューで守る条件になります。ただし完全一致やピクセル単位の
一致は求めず、明示した要件を満たす細部の調整は許容します。保存名、形式、範囲、承認記録、実装設計からの
参照方法の正本は[実装設計履歴](../../designs/README.md)です。

workflow開始前の要件確認用モックに限り、canonical main checkoutでの作成、承認前の更新、commitを
認めます。モックだけのために専用worktree、branch、依存環境は作成しません。`make verify-docs`はHTMLを
検査しないので、ブラウザで開く前とcommitする前に、作成者が
[ソース確認](../../designs/README.md#ソース確認)で外部resourceへの参照と実データ・secret・内部URLの
混入がないことを確認します。承認はユーザーが画面を承認した時点で成立し、commit SHAはその承認内容を
特定する記録です。承認済みのモックは更新せず、pathと確認済みrevisionを固定します。承認後はworkflowを
起動する前にmainへcommit・pushし、pathと確認済みcommit SHAをIssueへ記録します。

この例外はworkflow開始前の要件確認用HTMLだけに適用します。製品コード、正式な実装設計書、一般の
ドキュメント変更、workflow内の実装・レビュー工程をmainで行う許可には広げません。モックをmainへ
commit・pushしても、[Kajiワークフロー](workflow-overview.md)の起動手順にあるcleanと
`origin/main`との同期の条件は免除されません。

## 実装時の確認順序

1. Issue worktreeを解決し、既存の変更を確認する
2. `designs/issues/`の承認済み設計と、関連するbackend/frontend referenceを読む
3. 決定的テストとドキュメントを含む、最小の完全な単位を実装する
4. 変更をcommitする。**laneはcommit後のclean HEADで実行する** —— dirtyな実行はlane recordを
   残さないので、後続phaseが引用できない
5. `make verify-backend`または`make verify-frontend`を実行し、テスト実行マトリクスに従って
   schema、E2E、LLM、evalのlaneを追加する
6. PR作成前にIssue worktreeで`uv run python -m scripts.testing.lane_record --check check-all`を
   先に実行する（`make verify-docs`は`check-all`が呼ぶ）。同一clean HEADの成功recordなら引用し、
   引用不能時だけ`make check-all`を実行する。別のpre-commit commandは実行しない。条件付きlaneも
   `uv run python -m scripts.testing.lane_record --check <lane>`が0を返すなら引用してよい
7. 実行command、結果、commit、生成したartifactのpath、引用したrecord pathをIssueへ記録する

GitHubのstatus checkは品質gateとして使用しません。PRはreviewと変更公開、Issueは要件と証跡の
永続化に使い、品質判定は対象commitに対するローカル実行結果から行います。

## Worktree mode

- readinessは`pre-worktree`としてmain checkoutからIssueだけを確認・修正する
- startは`creates-issue-worktree`としてbranch、worktree、ignored実行環境、Issue NOTEを所有する
- design、implementation、docs、PR、closeは`issue-worktree`で絶対pathを解決する
- closeはmerge後にexact known worktree/branchだけを削除し、dirty/unknown assetは理由付きで残す
- incidentは`incident`としてmainをread-onlyにし、設定済みartifact rootを使う

Issue worktree作成時は[開発環境](../howto/development-environment.md)のbootstrapを実行し、
Python/Node依存をworktree内に隔離します。

実LLM/evalの実行要否・品質閾値の位置づけ・未達の引き継ぎは
[目的別契約](llm-evals.md#変更目的とissueの完了条件)に従います。観測目的のevalは失敗artifactを
同一HEADで照合して`OBSERVED`と報告でき、成功recordの引用とは区別します。
final-checkが観測未達のfollow-upを保証し、PRとcloseへリンクを引き継ぎます。

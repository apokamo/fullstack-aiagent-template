# Kajiワークフロー

kajiはIssue worktreeで実行するローカル品質gateと、その永続的な証跡を所有します。
GitHub Actionsのstatus checkは品質判定に使用しません。dev、docs、incidentの3種類を
サポートします。

## Workflow family

| Family | 選択条件 | State flow |
|---|---|---|
| dev | docs以外のsupported `type:*` labelを1個 | readiness → worktree → design loop → implementation loop → final gate → PR loop → close |
| docs | `type:docs` | readiness → worktree → update/review loop → final docs gate → PR loop → close |
| incident | runtimeが管理する`incident` Issueへ明示的に選択 | investigate → review/fix loop → verify/report |

すべてのagent stepは`.claude/skills/_shared/workflow-contract.md`を読み、永続的なIssue reportを
書き、workflowで許可されたverdictを出力します。review stepは判定、mutation stepは修正を所有し、
PR公開は`pr`、mergeとIssue closeは`close`が所有します。incidentは提案と証跡生成までとし、
lifecycle mutationは人が所有します。

標準dev workflowの設計書は`designs/issues/`へcommitし、Issue本文の管理blockにはその
design commitを指すpermalinkと20行以内の要旨だけを置きます。設計の正本はcommitであり、
Issue本文は人間向けの入口です。

通常Issueのtype/area cardinalityとincident runtime labelの正本は
[Issueラベル](issue-labels.md)です。Areaはworkflow familyを変更せず、設計scopeと反復時の
参照先を補助します。Verification laneは実diffから再計算します。

## 対応workflow定義ファイル

`.kaji/wf/custom/<family>/`配下の各YAMLファイルが1個のworkflow定義ファイルです。

| ファイル | 用途 |
|---|---|
| `dev/dev.yaml` | 標準dev。設計・実装・レビューを別工程で回す |
| `dev/dev-thorough.yaml` | 丁寧版dev。標準devの工程を保ち、推論量と一部timeoutを増やす（[丁寧版dev-thorough](#丁寧版dev-thorough)） |
| `dev/dev-small.yaml` | 軽量dev。決定済みの小修正で、設計と実装の工程を統合する（[小修正向けdev-small](#小修正向けdev-small)） |
| `docs/docs.yaml` | docs-onlyの変更 |
| `incident/incident.yaml` | incidentの調査と対応策の提案 |

意味的なstep contractはYAMLに複製せず、`.claude/skills/`の30 step skillと`_shared/`の
共通契約を共有します。

## モデルの tier

workflowのモデルはバージョン番号ではなくtierで割り当てます。複雑な判断を要する工程にはcomplex、
標準的な工程にはstandard、範囲と手順が明確な定型工程にはroutineのtierを使います。

| tier | 割り当てる工程 | Codex | Claude |
|---|---|---|---|
| complex | 設計、実装、修正、incidentの調査など複雑な判断を要する工程 | — | Opus |
| standard | dev・docsのレビュー、検証、最終確認など標準的な工程 | Sol | — |
| routine | worktree作成、実装前の計測、PR作成、close、incidentのreview・verify・reportなど範囲と手順が明確な工程 | — | Sonnet |

各YAMLは先頭の`x-models`にtierごとのモデル名をYAML anchorとして1か所だけ書き、各stepは
`model: *codex-standard`のようにaliasで参照します。モデルを差し替えるときは`x-models`の
値だけを変えます。anchorはファイルをまたげないので、対象の各YAMLで変えます。
標準effortは`medium`とし、推論量を増やすstepではeffortを明示します。各stepの実際の
agent / model / effortは各YAMLを正とします。

frontend/fullstackのIssueも標準devで実行します。frontend専用のworkflow familyは持ちません。
固定`apps/web` workdirとproject-scoped MCPを完遂要件から外した結果、標準devとの実行上の差が
無くなったためです。frontend commandは対象worktreeへの明示的な`cd <absolute-worktree>/apps/web`で
実行し、必要なlaneは実diffから選定します。`apps/web/.mcp.json`のMCP設定は開発者の手動診断と
任意観測のために残しますが、workflow PASS、review、coverageの入力にはしません。Playwright MCPと
`@playwright/test`のE2Eは別物で、後者の決定的gateは維持します。

```text
.kaji/wf/custom/dev/
.kaji/wf/custom/docs/
.kaji/wf/custom/incident/
```

release、staging deploy、domain固有のworkflowはサポートしていません。

## 丁寧版dev-thorough

複雑な設計や横断変更で推論量を増やしたい場合、起動者が`dev-thorough.yaml`を明示選択します。
標準devと同じskill、工程、遷移、review cycle、resume設定、品質gateを使います。
新しいlabelや自動選択は追加しません。`type:docs`はdocs familyを使います。

Claudeは設計・実装・修正を、Codexはレビュー・検証・最終確認を担当します。
標準devに比べて設計・設計修正・実装・コード修正とCodex各工程のeffortを増やし、
実装・コード修正・PR修正にはstep固有のtimeoutを設定します。モデル名、effort、timeoutの正本は
[workflow定義](../../.kaji/wf/custom/dev/dev-thorough.yaml)です。利用時間・利用量が増える可能性があります。

[通常の起動準備](#起動)を済ませたcanonical mainから実行します。

```sh
uv run --no-sync kaji run .kaji/wf/custom/dev/dev-thorough.yaml <issue-id> --no-auto-recover
```

## 小修正向けdev-small

起動者が`dev-small.yaml`を明示選択します。新しいlabelや自動選択は追加しません。
期待動作、対象、維持する挙動、局所的検証、通常revertが明確なdev Issueに使います。
ファイル数や行数では決めず、権限境界・移行・公開互換性などの未決判断は標準devへ送ります。
`type:docs`はdocs familyを使います。

```text
review-ready → start → change → review-change → pr → review-poll → close
                              ↓ RETRY
                           fix-change → verify-change → pr
                              ↑ RETRY ──────┘
```

`change`/`fix-change`は`issue-small-change-execute`、`review-change`/`verify-change`は
別contextの`issue-small-change-review`です。Issueの決定を正本として設計artifact/precheckを要求せず、
実装・commit・必須検証と、独立レビュー・最終確認を分担します。初回レビューは全diff、再確認は
未解決指摘と修正による回帰を見ます。レビュー側で不足laneを実行し、tracked修正は実装側へ戻します。
通常PASS経路のagent起動は標準10回に対し6回（execを除く）。実tokenや時間の削減率ではありません。
修正・fallbackは追加起動です。`small-ready`、`small-execute`、`small-change-review`、
`small-publish`、`small-pr-review`は上限3、枯渇時ABORT。session resumeは設定しません。

[通常の起動準備](#起動)を済ませたcanonical mainから実行します。

```sh
uv run --no-sync kaji run .kaji/wf/custom/dev/dev-small.yaml <issue-id> --no-auto-recover
# 実装後、統合レビュー直前で止める
uv run --no-sync kaji run .kaji/wf/custom/dev/dev-small.yaml <issue-id> --no-auto-recover --before review-change
# 人間レビューの有無にかかわらず統合工程から再開する
uv run --no-sync kaji run .kaji/wf/custom/dev/dev-small.yaml <issue-id> --no-auto-recover --from review-change
```

停止は完了ではなく、`--from pr`で統合工程を省略しません。通常再開でcycleをresetせず、
指摘後はfix-change/verify-changeへ進みます。停止中の追加commitは古い実装報告で承認せず、
変更と不足証跡を特定して修正経路へ戻します。

適用外はABORTで理由・必要判断・未完了事項・branch/worktree/HEAD・dirty状態・報告参照を残し、
assetsを保持します。人が要件と既存worktreeのidentity・変更内容を確認してから標準devを起動します。

```sh
uv run --no-sync kaji run .kaji/wf/custom/dev/dev.yaml <issue-id> --no-auto-recover
```

readinessから入り、startは同じworktreeを安全に再利用し、designは既存diffを含めて設計・レビューします。
例えば局所bug修正commitの後に公開APIの互換性判断が必要と判明した場合、そのcommitと理由を保持し、
標準設計で修正済み部分と必要な互換性対応の両方を扱います。precheckはその設計に必要な回帰信号を確認し、
過去の軽量PASSをdesign PASSに変換しません。dirty変更は出所とscopeを確認し、衝突・identity不明なら
保持して停止します。active state編集・自動再起動・自動cleanupは行いません。
標準cycleの過去回数が残る場合だけ、前工程の完了を確認し、必要cycleへ既存の
`--from <cycle-entry> --reset-cycle`を明示します。`small-*`命名はstate初期化を意味しません。
rollbackは標準devの選択に戻せます。revert時はworkflow定義ファイル/skillと共有契約・監査を対応する単位で戻し、
進行中runのworktreeと証跡を破壊しません。

## 共通PR工程

`pr`は現在の作業を承認した`final-check`/`review-change`/`verify-change`のPASS報告と
clean HEADのfull SHA一致を確認して公開します。投稿時刻が最新の同一SHA PASSを選ぶ方式ではなく、
承認報告以降の関連する差し戻し・再開・修正・最終確認を参照関係から辿ります。
人間の明示的な差し戻しも確認し、古い別producerへfallbackしません。設計文書不在から経路を推測しません。
設計管理blockの最終照合は上流に置き、公開直前の本文だけの編集は再検出しない限界を受け入れます。
公開の根拠は承認報告と承認済みcommitです。

PR修正は現在のPR指摘と修正diffを対象とし、PR再確認は元の指摘と修正による回帰を独立確認します。
修正後SHAの`check-all`と条件付きlaneはPR再確認が所有し、docs-onlyは`verify-docs`です。
PR fallback reviewはIssue・実patch・current-head証跡・上流承認を読み、関連設計リンクを必要時に使います。
PRレビューとcloseのreviewed SHA保護は維持し、初回承認を修正後HEADへ流用しません。

## Step入口とverdict handoff

30本のworkflow step skillは、該当step、workflow内の位置、ハーネス入力、手動入力、解決順を
各`SKILL.md`または入力節から参照する共通契約に持ちます。workflow外の手動実行では引数の第1語だけをIssue IDとして解決し、
非該当または文脈不足なら代替先を示して変更せず終了します。active harnessで同じ不整合があれば、
provider障害時もstdoutと`verdict.yaml`へABORTを残してrunを終端します。

producerは外部副作用後、stdout/YAMLより先にcanonical Issue markerを投稿します。workflowが別途
再実行され、consumerの`resolve-verdict`がexit 4になった場合だけ、そのexact producer 1件について
同一Issueのsession stateとsame/cross-runの最新attempt artifactをstep、attempt、status、内容、時刻で
照合します。指定stepの最新stateはstatus非依存で選ぶため、後続statusは古い判定を失効させます。一意な
non-synthetic recordだけから`recovered_from` metadata付きmarkerを再投稿し、同じproducerの再解決が
同じstatusを返した場合に限り続行します。
exit 5、provider障害、prose、symlink、複数候補では推測しません。この経路はworkflowやagentを
自動再起動する機能ではありません。

全差し戻し元で参照修復・意味不変修正・決定済み事項反映・未決/判断変更を意味で区別します。
本文参照だけなら発見工程で同期し、設計再入や同一HEADの検証再実行を要求しません。
参照同期helperは、管理block先頭の任意の見出し・空行に続く連続した参照行だけを更新します。
参照行の後の空行、または最初の本文行で探索を終了し、要旨内の`Commit:`等は保持します。
参照領域内の重複・不正な参照行は、推測で置換せずエラーにします。
実装工程の意味不変な設計修正もcommit後に同期し、review-code/verify-codeで確認します。
既存の決定は先に照合し、必要な設計修正も指摘とその波及に限定します。

implementation reviewはfindingをseverity、scope、origin、Smallest correctionの4軸で分類します。
決定済み事項の追加反映にinterface・failure・lane等への波及があれば`BACK_DESIGN_FIX -> fix-design`、既存決定の変更・削除は
`BACK -> design`、それ以外のMust Fixは`RETRY -> fix-code`です。設計修正は直前のverdictと
Issueのレビュー・検証・修正報告から対象指摘を確認します。verify-designは修正報告が対応した指摘だけを
検証し、再修正では直前の検証で残った指摘を対象として解決済み指摘を再開しません。
`source_step`は任意の既存情報であり、その有無や値だけで停止しません。
`review-code`のBACK/BACK_DESIGN_FIXはIssue全期間で通算N=2とし、2回目は発行せずABORTします。
fix-codeの根拠付き反論はverify-codeが採用または却下し、採用したfindingは取り下げます。
design-review cycleが既に`max_iterations`へ到達している場合、`fix-design`入場はsynthetic ABORTで終端し、
成功したdesign再入には数えません。これはIssue単位のBACK上限とは独立したrunner側の安全停止です。

## 差し戻しの観測

`count_review_design_reentries`はreview-codeのcanonical markerだけを数え、N=2判定に使います。
拡張観測は独立したread-only helperで実施します。workflowの停止条件には接続しません。

```bash
uv run kaji issue view <issue-id> --json comments > /tmp/issue-comments.json
uv run python -m scripts.kaji.observe_design_returns \
  --comments /tmp/issue-comments.json \
  --run-log <artifacts_dir>/<issue-id>/runs/<run-id>/run.log \
  --run-log <artifacts_dir>/<issue-id>/runs/<other-run-id>/run.log
```

`comments`はIssue全期間の旧指標・全差し戻し判定・発行元別件数です。重複commentも旧指標と同じく数えます。
`runs`は指定runごとの判定と実入場を分離し、`step_start`と直前の遷移から初回設計、通常設計修正、
差し戻し再入、attempt再試行、不明な入場、cycle上限での未入場、入場未確認の判定を表示します。
attempt番号の増加だけで再試行とせず、通常の修正遷移を優先します。ログはrun単位で読み、runを跨ぐ
先行遷移を推測しません。中断・失敗した設計も開始していれば入場に含み、design PASSで代用しません。
`logged_return_entries`は提供ログ内の件数に限り、ログ無しではnullです。Issue全体の完全な入場件数とは
扱いません。provider JSONとログの判定件数は対象期間・重複の条件を揃えて比較します。

保存artifactはgit管理外です。判定経路を変えたときは、合成JSON/log fixtureによる再現可能な回帰テストを
併記します。静的監査・formatterテストはAIの意味判断を保証しないため、具体的な対照ケースの独立レビューも行います。

## 有人起動skill

`.claude/skills/`にはstep skillのほかに、人が明示起動する有人skillを1個置いています。
workflow YAMLのstepにはせず、同期対話を無人runへ混ぜません。

| Skill | 起動 | 位置 | 産物 |
|---|---|---|---|
| `grill-me` | 人が起票直後に明示起動 | readinessの前、workflowの外 | Issue本文の`## 決定事項`とprovenanceコメント |

`grill-me`は重要判断のdecision treeを1問ずつ推奨付きに問い、one-way doorの決定を起票時に
確定させるfront-loadです。軽微なIssueはスキップします。verdictもworktree modeも持たないため、
skill auditは有人skill用の規約（frontmatterの`disable-model-invocation: true`、必須section、
verdict表を持たないこと）で検査します。散文の文言は検査しません。
規約は[共通skill規約](shared-skill-rules.md)を参照してください。

## 起動

dev/docs workflowはcanonical main checkoutから次の手順で起動します。launcher scriptは持ちません。
`<remote>`は`.kaji/config.toml`の`provider.github.git_remote`（現状`origin`）、`<default_branch>`は
そのremoteのdefault branch（現状`main`）です。

通常運用ではKaji 0.20.1とHerdr 0.8.2以上を使用し、Herdr内からKajiを起動します。起動前の
preflightで`herdr --version`と`herdr status`を実行し、version要件とHerdr serverへの接続を
確認します。repository既定のinteractive terminal backendは`.kaji/config.toml`の`herdr`です。
障害切り分け時だけ対象runへ`--interactive-terminal-backend tmux`を明示して比較し、tracked既定は
変更しません。

```sh
cd <canonical-main-checkout>          # git worktree listの先頭。linked worktreeからは起動しない
git symbolic-ref --quiet --short refs/remotes/<remote>/HEAD  # 例 `origin/main`。<default_branch>の正本
git symbolic-ref --quiet --short HEAD # <default_branch>と一致すること。detached HEADならexit 1
git fetch <remote>
git status --porcelain                # 空であること。空でなければ起動しない
git rev-list --count <remote>/<default_branch>..HEAD   # 0であること。0でなければ起動しない
git merge --ff-only <remote>/<default_branch>
uv sync --frozen --group dev          # main checkoutの.venvを更新する期待された副作用
uv run --no-sync kaji --version       # 0.20.1であること
uv run --no-sync kaji issue view <issue-id>  # 対象repositoryの対象Issueが表示されること
herdr --version                       # 0.8.2以上であること
herdr status                          # Herdr serverへ接続できること
uv run --no-sync kaji run .kaji/wf/custom/<family>/<workflow>.yaml <issue-id> --no-auto-recover
```

- `<default_branch>`は1つ目の`git symbolic-ref`の出力から`<remote>/`を除いた部分です。このcommandが
  exit 1で何も返さない場合はrepositoryのdefault branchが不明なので起動せず、
  `git remote set-head <remote> --auto`を実行してからやり直します。
- 2つ目の`git symbolic-ref`はcheckoutがdetached HEADのときexit 1で何も出力しません。出力が
  `<default_branch>`と異なる場合も起動しません。この2つを省くと、後続の
  `git merge --ff-only <remote>/<default_branch>`がdefault branch以外のbranchやdetached HEADを
  fast-forwardします。cleanであることと`git rev-list --count`が0であることではbranch identityは
  決まりません（default branchの祖先にいる別branchでも両方を満たします）。
- `kaji issue view`は、kajiが操作するrepositoryの確認です。repositoryは`.kaji/config.local.toml`で
  指定します（[テンプレートの使い方](../howto/use-template.md#githubリポジトリとつなぐ)）。
  `<owner>/<repo>`を解決できないエラーや別repositoryのIssueが出た場合は起動しません。
- `<family>`は`dev`または`docs`です。incident runはKaji recoveryが所有するため手動起動しません。
- workflow名の選定は起動者が[Issueラベル](issue-labels.md)の規約を読んで手で行います。
- `--no-sync`は直前の`uv sync --frozen`の結果をそのまま使うためです。省略すると起動時に再解決が走ります。
- `--no-auto-recover`は必須です。`.kaji/config.toml`の既定は`auto_recover = true`で、省略すると
  不可逆stepを含むrunが自動resumeされます。
- どれか1つでも条件を満たさない場合はKajiを起動しません。変更をstash / revertしません。

この手順はscriptで強制せず、起動者が実行します。同一repositoryで複数Issueのrunが同時に走ることは
禁止しません。run中にmainが進むとstep間でskill、config、workflowの世代が混在しえますが、これは
受容するdriftです。merge前にlocal mainの状態を検査するgateは持たず、reviewed headの保護は
`uv run kaji pr merge --match-head-commit`が担います。

## 終端lifecycle

`issue-close`だけが終端のlifecycle ownerです。review gate成立後、追加の人間承認なしに
PR merge、未チェック項目のfollow-up引継ぎ、managed worktree/branchのcleanup、local mainの
ff-only同期、summary投稿、Issueの明示closeまでを所有します。別engineや`workflow-finalize` stepは
持ちません。

本repositoryはlinked-PR auto-closeをrepository設定で無効にしています。PR本文の
`Closes #<issue>`はDevelopment link生成のためだけに維持し、commit/merge messageへclosing
keywordを追加しません。merge後もIssueはOPENのままで、cleanupとmain同期が完了してから明示的に
closeします。この設定はGitHub APIから読めないため、skillで検査せず前提として文書化します。
設定が戻された場合はauto-closeでIssueが早く閉じますが、runは完遂し、
異常は完了summaryの欠落として現れます。partial failureからの再実行はGitHubとGitを正本として現在状態を再取得し、merge、
follow-up、cleanupを重複実行しません。

## Worktreeとprovider

- repository: `.kaji/config.local.toml`で`.kaji/config.toml`を上書きした`[provider.github].repo`。
  Issue worktreeはbootstrapが張るsymlinkでmain checkoutと同じ設定を使う
- remote: `origin`
- base: `origin/main`
- worktree: `KAJI_WORKTREE_DIR`を優先し、なければIssue証跡と`git worktree list`から解決する
- Issue/PR操作: `uv run kaji issue|pr ...`

main checkoutはオーケストレーションと確認に使い、実装、artifact、commitはIssue worktreeで行います。
workflow開始前の要件確認用の画面モックだけが例外で、main checkoutでの作成・commit・pushを認めます。
条件は[開発ワークフロー](development-workflow.md)を参照してください。
worktree pathをskillごとの固定文字列として持ってはいけません。

## 品質gate

設計、review、final checkは[テスト規約](test-policy.md)から必要なlaneを選定します。
通常のfull gateに加え、変更内容に応じてschema、E2E、実LLM、L2 evalsを実行し、選定理由と
結果をIssueへ記録します。providerへ到達できないmandatory laneを成功扱いでskipしません。

phaseごとの実行責務は次のとおりです。

- **設計loop（design / review-design / fix-design / verify-design）はlaneを実行しません。**
  laneは選定して設計に書くだけです。
- **implementとfix、軽量changeがproducer**です。commitしてからclean HEADでlaneを実行し、recordを残します。
- **review、verify、final checkの条件付きlaneは既定で引用**します。再実行は禁止しませんが、
  理由を1行記録します。
- **`make check-all`もfinal check・軽量統合レビュー・PR再確認がcheck-first**で扱います。同一clean HEADの成功recordは引用し、
  引用不能時だけ再実行します。

品質判定の正本は、対象commitをcheckoutしたIssue worktreeでの実行結果です。`make check-all`、
条件付きlaneのcommand、終了状態、主要結果、artifact path、commit SHAをkajiが
Issueへ記録します。PR、Issue、labelは共同作業とlifecycle管理に使いますが、GitHub側の
status checkが無いことや成功したことを、品質gateの未実施または成功の根拠にはしません。

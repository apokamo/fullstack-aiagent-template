# 共通skill規約

すべてのkaji skillは`.claude/skills/_shared/workflow-contract.md`を読み、そこからworktree、
重要判断、provider、証跡、side effect、verdictの正本へ進みます。各step skillにはphase固有の
入力、command、失敗分岐、handoff、証跡、status条件を残します。workflow step skill 30本は
`## いつ使うか`で該当stepと非該当時の代替先を示し、`## 入力`をハーネス経由・手動実行・
解決ルールに分けます。ただし新規small-change 2本とPR create/fix/verifyの計5本は、
入力節から共通契約を参照し、入力小見出し・Preconditions・Evidence節や復旧commandの全文複製を要求しません。
「いつ使うか・入力・Procedure・Side effects・Verdict」、worktree mode、必要な証跡内容は維持します。

- 入力はkajiから注入されたcontextを使い、手動時は`$ARGUMENTS`の第1語だけをIssue ID fallbackに
  する。Issue ID/context/stepが不正なactive harnessはstdoutと`verdict.yaml`のABORTまで終端する
- worktree pathは固定文字列として重複させず、解決して記録する
- providerへの書き込みには`uv run kaji issue|pr`を使う
- reviewとmutationの責務を分離する。canonical `type:*` / `area:*`の修正はdesign create / fixが
  所有し、design reviewは指摘して`RETRY`で返すだけで自分では適用しない
- 必須検査を成功扱いのskipへ変換しない
- laneは`uv run python -m scripts.testing.lane_record --check <lane>`を先に実行し、0なら`REUSED`として
  引用、非0なら実行して`RERAN`と理由を1行記録する。`REUSED`はskipではなく、同じcommitで成功した実行の
  引用である。設計loopはlaneを実行しない。正本は`.claude/skills/_shared/lane-evidence.md`
- 無関係な発見事項はscopeを拡大せずに報告する
- 秘密値と非公開のmodel responseをコメントや追跡対象artifactへ含めない
- 各skillのProcedureでworkflow verdict commentを先に投稿し、stdout fallbackの後、completion triggerである
  delimiterなしの`verdict_path` YAMLを最後に保存する
- provider commentが失敗したら要求statusをABORTへ変換し、marker再試行が失敗してもstdoutと
  `verdict.yaml`へ同じABORTを残す
- 設計fixは直前のverdictとレビュー・検証・修正報告から最新の修正要求を確認する。
  `source_step`の有無や値だけで停止しない。他のfixは許可されたproducer stepを
  `kaji issue resolve-verdict`で明示解決する。verifyは既存指摘を収束確認し、PR/軽量再確認は修正による回帰と修正後SHAの最終gateも所有します。
  設計の再修正では解決済み指摘を再開しない
- `resolve-verdict`のexit 4だけは、失敗したexact producer 1件だけを指定し、workflow再実行後の
  same-Issue stateとsame/cross-run artifactがstep・attempt・status・内容・時刻で一意に一致し、
  non-syntheticな最新attemptである場合に限り`scripts.kaji.resolve_verdict_artifact`からmarkerを再生成して
  再解決する。exit 5、provider失敗、prose、symlink、malformed artifact、曖昧な候補にはfallbackしない。
  指定stepの最新stateはstatusに関係なく選び、後続statusが古い判定を失効させる。復元markerには
  `recovered_from` metadataを付ける。workflow自体の自動再起動機能ではない
- one-way decision未決はAI fix loopへ流さず`ABORT`する
- area labelはscope hintに限定し、設計と実diffからverification laneを再計算する。
  `type:docs`とdev familyをまたぐ変更は自動再分類せず`ABORT`して手動再起動へ返す
- Kajiのlegacy `draft/design/...`入力は
  `uv run python -m scripts.kaji.resolve_design_path`で
  `designs/issues/...`へ変換し、変換後のpathだけを設計正本として読み書きする
- design create/fixは設計だけをcommitした後、Issue本文の管理block
  （`<!-- kaji-design:start -->`から`<!-- kaji-design:end -->`）を
  canonical path、full commit SHA、`blob/<design-sha>/<design-path>` permalink、
  20行以内の要旨へ置き換える。設計全文はIssue本文へ複製しない
- implement/fix-codeはOutcome/Scope/interface/failure/lane/acceptance/rollbackを変えない
  表記・lint・typo・path修正や局所的な既存判断の補足を実装commitに含め、commit後のSHAへ
  管理blockを同期・再読・報告する。文字の変更・削除だけで設計判断変更とは判定しない
- 管理blockのpermalinkが現在のdesign commitを指すことの検査は、implementation開始前
  （`issue-implementation-precheck`）と`issue-final-check`の2境界が
  所有する。検査は管理blockをちょうど1組だけ取り出してその中を照合し、Issue本文全体の
  部分一致では代用しない。一意に確認できる正本と承認証跡があれば、この発見工程で古い参照や
  block欠落を修復して続行する。本文同期だけならcommitや設計再入・同一検証の再実行を要求しない。
  正本・承認・境界が曖昧なら具体的な不足を報告し、推測でPASSにしない。手順・工程別の
  tracked path修復経路は[設計証跡](../../.claude/skills/_shared/design-evidence.md)を参照する

全差し戻し元は共有rubricで局所修復と設計変更を区別し、既存ユーザー決定を照合します。
設計に戻る場合も当該指摘と必要な波及だけを変更し、解決済み指摘と有効な証跡を保持します。

Implementation reviewはfindingをseverity（Must/Should）、scope（acceptance/diff regression/別Issue）、
origin（implementation/design）、Smallest correction（参照修復/意味不変修正/決定済み事項反映/未決・判断変更）
の4軸で記録します。別Issue候補とShouldだけではblockしません。mixed findingはABORT、BACK、
BACK_DESIGN_FIX、RETRY、PASSの順に最上流の必要修正を選びます。fix-codeの根拠付き反論はverifierが
採用/却下し、妥当ならfindingを取り下げます。

`review-code`の`BACK`と`BACK_DESIGN_FIX`はIssue全期間で通算し、N=2の2回目は発行せずABORTして
人間判断へ返します。同一Issue内でresetせず、必要なら判断を引き継いだ新Issueを作ります。
design-review cycleが既に`max_iterations`へ到達している場合、`fix-design`入場はrunnerのsynthetic ABORTで
終端します。これは成功したdesign再入として数えず、Issue単位のBACK上限とは別の安全停止です。

`_shared/templates`配下のtemplateは報告形式を定義するもので、実行時の出力先ではありません。

## 簡潔なskillと共有参照

通常の入力・完了はworkflow-contract/verdict、設計参照は必要時だけdesign-evidence、
exit 4の復旧詳細はverdict-recoveryを読みます。5skillの監査は入力節の共有参照、実在link、
workflow由来のstep/status・許可handoff、lane checker先行、副作用の所有者、Codex linkを検査します。
対象外skillの入力・復旧検査は維持します。定型文の存在は意味判断やruntime実行の保証ではありません。
PR作成は現在の最終承認を公開するだけで設計blockを再照合せず、PR fix/verifyはIssue verdictを使いません。
詳細な責務と再開は[workflow](workflow-overview.md#共通pr工程)が正本です。

## 有人起動skill

人が明示起動する有人skill（現在は`grill-me`）はworkflowのstepではないため、上記のstep規約では
なく次に従います。

- workflow YAML（`.kaji/wf/custom/**/*.yaml`）のstepにしない。同期対話を無人runへ混ぜない
- frontmatterへ`disable-model-invocation: true`を宣言する。散文では自動選択を止められず、
  人の明示起動のみに限定できるのはこのkeyだけ
- Codex向けには`agents/openai.yaml`で`policy.allow_implicit_invocation: false`を宣言する。
  Claude用frontmatterをCodexは解釈しないため、両方を独立に監査する
- verdictと`verdict_path`を出力せず、worktree modeも宣言しない。step間のhandoffを所有しない
- 重要判断の正本は`.claude/skills/_shared/critical-decisions.md`を共有する
- 産物は後段stepが読む場所へ固定する。`grill-me`はIssue本文の`## 決定事項`とprovenanceコメント
- providerへの書き込みは`uv run kaji issue`を使い、副作用の境界をSKILL.mdに明記する
- `scripts/docs/check_kaji_skills.py`へ有人skillとして登録し、frontmatterのflag、必須section、
  Codex invocation policy、verdict表を持たないことを検査する。散文の文言は検査しない

Skillの追加・更新・削除、`.agents/skills`の相対symlink、portable frontmatter、Codex discoveryの
詳細手順は[repository skill運用ガイド](../../.claude/skills/README.md)を正本とする。

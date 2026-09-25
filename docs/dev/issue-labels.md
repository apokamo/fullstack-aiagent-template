# Issueラベル

ラベルはIssueの主目的、変更対象、Kaji runtime incidentを表す入力です。実際のdiffから
選ぶverification laneや、その実行結果を代替する品質証跡ではありません。
`.github/labels.yml`を管理対象17件の名称、色、説明の正本とします。

## Type

通常Issueにはcanonical `type:*`を必ず1個だけ付与します。0個、複数、未知のtypeは
readinessで`RETRY`とし、Kajiのprefix優先順位やfallbackに依存しません。

| Label | Prefix | Workflow | 最低確認事項 |
|---|---|---|---|
| `type:feature` | `feat` | dev | outcome、scope、interface、failure、compatibility、acceptance |
| `type:bug` | `fix` | dev | reproduction、actual/expected、原因仮説、regression、修正境界 |
| `type:refactor` | `refactor` | dev | behavioral invariants、構造目的、equivalence、rollback |
| `type:docs` | `docs` | docs | 正本、導線、link、code変更の非混入 |
| `type:test` | `test` | dev | 対象契約、回帰signal、size/marker、production非変更 |
| `type:chore` | `chore` | dev | behavior非変更、compatibility、運用影響、rollback |
| `type:perf` | `perf` | dev | baseline、target、測定条件、tolerance、機能回帰防止 |
| `type:security` | `security` | dev | threat、auth、secret、input boundary、abuse、regression |

`test/chore/perf/security`をfeature rubricへfallbackさせません。独立して完了可能な
複数目的はtypeを重ねずIssueを分割します。

## Area

dev Issueは次のcanonical `area:*`を1個以上持ちます。複数選択でき、`type:docs`では
対象domainを示す価値がある場合だけ使用します。

| Label | 主な対象 | 主なpath | Verification hint |
|---|---|---|---|
| `area:frontend` | browser UI、component、adapter | `apps/web` | frontend。user flow時はE2E |
| `area:backend` | API、service、provider wiring | `apps/api` | backend。DB/provider差分を再判定 |
| `area:database` | schema、ORM、migration | `migrations`、models | schema/migration lane |
| `area:agent-ai` | prompt、tool、HITL、provider、eval | `apps/api/agent` | E2E/real-LLM/evalを差分から判定 |
| `area:workflow` | Kaji、skills、Make、scripts | automation paths | workflow/skill/docs/script checks |

Fullstackはfrontendとbackendの組合せで表し、`area:fullstack`を追加しません。
Areaはworkflow familyを変更しません。設計の`Scope`と実diffが正本であり、labelとの
不一致があっても必要なlaneを省略せず、labelまたはscopeを修正します。

代表的な組合せは次のとおりです。

| 変更 | Area |
|---|---|
| frontendのみ | `area:frontend` |
| backend APIのみ | `area:backend` |
| fullstack user flow | `area:frontend` + `area:backend` |
| migrationを伴うAPI変更 | `area:backend` + `area:database` |
| backendのagent/tool変更 | `area:backend` + `area:agent-ai` |
| AI結果を表示するfullstack変更 | `area:frontend` + `area:backend` + `area:agent-ai` |
| Kaji/skill/local gate変更 | `area:workflow` |

## Epic

`epic`は複数の子Issueを束ねる親Issueだけに付けるmeta labelです。canonical `type:*`や
`area:*`ではなく、既存のcardinality規約と直交します。親Epicにも主目的を表すcanonical
`type:*`を正確に1個付け、dev Issueであればcanonical `area:*`を1個以上付けます。

子Issueには`epic`を付けません。子Issueはそれぞれの主目的と変更対象に応じたcanonical
type/areaを持ちます。このため、readinessは親Epicでも通常Issueと同じくtype 1個、devでは
area 1個以上を要求します。`epic`自体はworkflow familyを変更しません。親Epicは進捗と
横断的な完了条件の集約に使い、実装は原則として子Issue単位で進めます。

## Workflow and verification

Kaji recoveryが管理するincidentはincident workflowを使います。通常Issueはtypeの
cardinalityを確認し、`type:docs`だけがdocs workflow、他の7 typeはdev familyを
使います。標準devを基本とし、決定済みの小修正は起動者が`dev-small.yaml`を明示選択できます。
適用条件と停止・引継ぎは[軽量経路](workflow-overview.md#小修正向けdev-small)を参照してください。
新しいlabelや自動選択は追加せず、type:docsを軽量devへ付け替えません。Areaごとに同じ状態遷移を複製しません。

frontend専用のworkflow familyは持ちません。`area:frontend`や`area:frontend` + `area:backend`の
Issueも標準devで実行し、frontend laneとfake-model Playwright E2Eの要否は実diffから決めます。
Verificationは[テスト実行マトリクス](test-execution-matrix.md)を使い、設計scopeと実diffから
決めます。

`issue-design-create`と`issue-design-fix`は、確定したScopeに合わせてcanonical `type:*` / `area:*`を
追加・削除できます。`issue-design-review`はlabelを判定するだけで適用せず、必要な修正を指摘して
`RETRY`で`issue-design-fix`へ返します。`area:*`の変更は同じworkflowを継続してlaneを再計算し、
非docs間の`type:*`変更はdev family内で継続します。`type:docs`とdev familyをまたぐ変更は`ABORT`とし、既存worktreeの
identityと現在baseを確認したうえでoperatorが正しいfamilyを手動で再起動します。自動の再分類、
active state編集、cross-family自動再起動は行いません。

## Incident

Kaji runtimeが所有するlabelは次の3個です。

| Label | 用途 |
|---|---|
| `incident` | workflow failureの集約Issue |
| `incident:investigating` | 新規incidentの調査中状態 |
| `incident:cause:transient` | 一過性failureの自己回復 |

通常Issueのtype/area cardinalityはincidentへ適用しません。Cause、severity、impact、
lifecycle、containment、corrective actionはIssue本文、comment、artifactを正本とし、
incident workflowはlabelやIssue stateを変更しません。

開始時点では`incident:open/mitigated/resolved`、`severity:*`、汎用の`cause:*`を
管理しません。横断検索の実需が生じた場合だけ、cardinality、適用・解除の所有者、runtime
互換性を設計して追加します。

## Labels not managed

- `priority:*`、`status:*`、`effort:*`はroutingに使わず、必要ならProject/Issue Fieldsを優先します。
- `risk:*`は開始時点で追加せず、security/performanceが主目的ならcanonical typeを使います。
- `scope:fullstack`、`area:fullstack`はfrontendとbackendの組合せで表します。
- `needs:e2e/llm/eval`は追加せず、設計とdiffからlaneを選びます。
- frontend/backend別のworkflow選択labelは追加しません。

GitHub標準の`bug`、`enhancement`、`documentation`はcanonical typeと二重管理しません。
`duplicate`、`invalid`、`question`、`wontfix`、`good first issue`、`help wanted`など、Kaji
routingと直交するcollaboration labelは、実際に使うものを管理者がmanifest外で扱えます。

## Sync and retirement

同期はlocal additive operationです。

```bash
uv run python scripts/github/sync_labels.py --repo <owner>/<repo>
uv run python scripts/github/sync_labels.py --repo <owner>/<repo> --apply
```

先にdry-runを確認します。Syncは作成・更新だけを行い、既存labelを削除・renameしません。
Remoteへのapply、全Issueへの付与・修正、旧labelのinventory/移行/削除は、それぞれ対象と
失われる情報を確認して人が明示的に承認する別作業です。

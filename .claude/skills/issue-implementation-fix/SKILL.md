---
name: issue-implementation-fix
description: "Resolve current implementation review or verify findings with regression evidence."
---

# Fix implementation findings

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `fix-code`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new implementation review is needed. Use `issue-implementation-review`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `fix-code` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context.
- Producer verdicts from `review-code` and, on re-entry, `verify-code`; current diff.

### 手動実行（スラッシュコマンド）

- `$ARGUMENTS = <issue_id>`. Do not depend on placeholder substitution; use only the 第1 (first) argument as
  the Issue ID.

### 解決ルール

1. Use injected `issue_id` when present.
2. Otherwise, use only the first `$ARGUMENTS` value.
3. With no/invalid Issue ID or a ❌ condition and no `verdict_path`, make no provider/file change, name the
   alternative above, and stop.
4. With an active-harness `verdict_path`, non-applicability, Issue/context mismatch, or a wrong `step_id` is a
   contract failure. Convert it to `ABORT`, always emit stdout and `verdict.yaml`, and try the ABORT marker first
   for a valid Issue ID; a provider failure must not remove the completion signal.
5. In manual use, resolve repository values with `uv run kaji issue context <issue_id>`, the Issue NOTE, and
   `git worktree list --porcelain`. Never guess them.
6. Resolve producer verdict, design path, PR, and lane records with `resolve-verdict`,
   `scripts.kaji.resolve_design_path`, exact branch PR lookup, and `lane_record --check`, respectively.
7. In manual use, never invent `verdict_path`, cycle values, or `previous_verdict`. Without `verdict_path`, stop
   after the Issue marker and stdout fallback.

Read [design evidence](../_shared/design-evidence.md) for design references and repairs.

## Preconditions and worktree

Worktree mode: `issue-worktree`.

- Resolve both permitted producer steps and select the current-cycle marker; ambiguity is `ABORT`.
- Read the approved design/type guide and preserve unrelated changes.

## Procedure

For observation-purpose evals, apply the `OBSERVED` branch in
[lane evidence](../_shared/lane-evidence.md) before the success-record rerun rules below.
Preserve failed results and report handoff evidence/candidates to final-check within this phase's scope.
Required quality thresholds, provider/safety failures and confirmed regressions still block.

1. Reproduce each numbered finding and classify its disposition as A (Agree) or B (evidence-backed
   disagreement). B is allowed only for factual error, an already-satisfied canonical contract, conflict with a
   canonical contract, or correction cost/side effects greater than the benefit; record path/command/contract
   evidence, an alternative, and residual risk. Preference or lack of time is not a disagreement.
2. Implement the smallest complete correction and add a regression test when applicable; do not redesign
   behavior. Meaning-preserving edits of existing canonical `designs/` text/path and local settled-decision
   clarifications are allowed within the shared rubric. Text replacement/deletion alone is not a routing
   error. If outcome, Scope/labels, interface, failure policy, lane, acceptance or rollback changes, emit
   `ABORT` with the bounded design correction needed because review routed it incorrectly.
3. Stage only the paths required by the finding. Include a meaning-preserving design edit or local
   clarification with implementation changes when both are needed; a real design-only typo/path correction
   may have its own commit when there is no implementation change. Never create an empty commit or use
   broad staging. If design content/path changed, resolve the post-commit `DESIGN_SHA`, synchronize
   the managed block under the shared reference-repair contract, and re-read it.
   Lanes must run on a clean HEAD.
4. Cite by default. Run `uv run python -m scripts.testing.lane_record --check <lane>` for each required lane
   first: on exit 0 report `REUSED` with the printed record line; on a non-zero exit run the lane (focused
   `make verify-backend` and/or `make verify-frontend` plus every conditional lane introduced by the fix) and
   report `RERAN` with the returned reason. A new commit has no record yet, so this phase is the producer for the
   lanes its own change affects ([lane evidence](../_shared/lane-evidence.md)).
5. Post a finding-by-finding `fix-code` report with A/B disposition, disagreement evidence/alternative/residual
   risk, commands, cited or published record paths, design block update when applicable, and SHA.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `review-code` | `RETRY` | `--producer-step review-code --allow-status review-code=RETRY` |
| `verify-code` | `RETRY` | `--producer-step verify-code --allow-status verify-code=RETRY` |

Append exactly one row's arguments to this command:

```bash
uv run python -m scripts.kaji.resolve_verdict_artifact \
  --issue-id <issue_id> --current-verdict-path <verdict_path> \
  <single-producer-helper-arguments>
```

Exit 5 (malformed), provider failure, no match, or ambiguity is `ABORT`; do not infer
status from prose. On one match, post the exact producer's canonical marker and recovery report with:

```bash
uv run kaji issue comment <issue_id> --commit \
  --verdict-step <returned-step> --verdict-status <returned-status> \
  --verdict-meta recovered_from=<producer_run>/<returned-step>/attempt-NNN \
  --body-file <recovery-report>
```

Include the returned artifact paths in the recovery report, then rerun `resolve-verdict` for the same producer.
Continue only when it returns the same status.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step fix-code --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May edit/commit approved implementation paths, add a boundary-compliant design clarification and update its
  managed block after that commit, and post the resolution report. Meaning-preserving canonical `designs/`
  text/path edits are also allowed; use the shared reference-repair contract and verify-code for verification.
- Must not change labels, silently alter design/product policy, push, resolve unrelated findings, or
  `--amend`/rebase a commit whose lane records exist.

## Evidence

- Selected producer marker, reproduction, finding table, per-lane `REUSED` / `RERAN` lines, checks/artifacts,
  diff, commit SHA, and report URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All current findings are corrected or answered with valid evidence. |
| ABORT | Producer provenance is invalid or resolution needs design/human authority. |

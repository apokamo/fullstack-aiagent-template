---
name: issue-implementation-verify
description: "Verify current code-review findings and regression evidence without reopening full review."
---

# Verify implementation fixes

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `verify-code`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new full implementation review is needed. Use `issue-implementation-review`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `verify-code` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context.
- Original findings, fix report/commit, resulting diff, and affected lane evidence.

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

- Require matching current-cycle review/fix provenance.
- Do not add new findings. New observations are reported separately.

## Procedure

For observation-purpose evals, apply the `OBSERVED` branch in
[lane evidence](../_shared/lane-evidence.md) before the success-record rerun rules below.
Preserve failed results and report handoff evidence/candidates to final-check within this phase's scope.
Required quality thresholds, provider/safety failures and confirmed regressions still block.

Verify fix-code's meaning-preserving design edits/local clarifications against the shared rubric and
post-commit block synchronization within the existing findings. An unambiguous body-only omission may
be repaired here under the shared contract; tracked defects remain `RETRY`. Do not require design-verify
re-entry for reference synchronization.

1. Resolve each original finding and the exact correction or disagreement; reproduce the prior failure or inspect
   equivalent evidence. For each, record `corrected`, `disagreement accepted / finding withdrawn`, or
   `disagreement rejected / remains`, with the reason. A valid disagreement resolves the finding.
2. Cite by default. Run `uv run python -m scripts.testing.lane_record --check <lane>` for each lane needed to
   confirm the correction: on exit 0 report `REUSED` with the printed record line; on a non-zero exit run the
   lane (focused `make verify-backend` and/or `make verify-frontend`) and report `RERAN` with the returned
   reason. Re-evaluate conditional lanes changed by the fix the same way
   ([lane evidence](../_shared/lane-evidence.md)).
3. Verify the finding was not suppressed, moved, or hidden and that its regression test observes the intended
   boundary. If some disagreements are rejected, carry forward only the remaining smallest corrections.
4. Post per-finding OK/NG with `--verdict-step verify-code`; keep new observations outside this verdict.

Do not add new findings to this verdict; verify only the existing implementation-review set.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `fix-code` | `PASS` | `--producer-step fix-code --allow-status fix-code=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step verify-code --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May repair unambiguous body-only design references under the shared contract.
- May cite lane records, run focused checks, and post verification evidence.
- Must not edit code, labels, or expand the finding set.

## Evidence

- Review/fix markers, fix SHA/diff, reproduction or per-lane `REUSED` / `RERAN` results, per-finding proof, and
  comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All original findings are corrected or withdrawn after an accepted disagreement. |
| RETRY | At least one original finding remains. |
| ABORT | Provenance is ambiguous or safe verification is impossible. |

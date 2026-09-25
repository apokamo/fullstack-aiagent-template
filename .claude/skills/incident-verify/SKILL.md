---
name: incident-verify
description: "Verify current incident review findings were resolved without starting a new investigation review."
---

# Verify incident fixes

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `incident` workflow at `verify`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new full review is needed. Use `incident-review`; otherwise use 通常の調査 and make no change. |

**ワークフロー内の位置**: `verify` in the `incident` workflow. `.kaji/wf/custom/incident/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle context.
- Original findings, updated artifact, fix report, and raw evidence.

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

## Preconditions and worktree

Worktree mode: `incident`.

- Require current-cycle producer/fix provenance.
- Do not add new findings. New observations are informational for a later review/report.

## Procedure

1. Resolve original findings and the exact fix artifact.
2. For each finding, verify the correction or rerun one decisive safe check.
3. Ensure uncertainty, containment risk, reviewer metadata, and runtime-label observations remain explicit; reject
   ad hoc cause/severity/lifecycle label proposals.
4. Post per-finding OK/NG with `--verdict-step verify`.

Do not add new findings to this verdict; verify only the existing review set.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step verify --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post verification evidence and use an exact disposable check environment.
- Must not edit the artifact or change labels/lifecycle.

## Evidence

- Producer/fix markers, artifact version, per-finding proof, check result, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All original findings are resolved. |
| RETRY | At least one original finding remains. |
| ABORT | Provenance or evidence cannot be evaluated safely. |

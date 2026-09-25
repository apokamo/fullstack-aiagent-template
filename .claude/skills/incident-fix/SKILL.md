---
name: incident-fix
description: "Revise an incident investigation artifact in response to current review or verify findings."
---

# Fix incident findings

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `incident` workflow at `fix`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new investigation or review is needed. Use `incident-investigate` or `incident-review`; otherwise use 通常の調査 and make no change. |

**ワークフロー内の位置**: `fix` in the `incident` workflow. `.kaji/wf/custom/incident/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle context.
- Producer verdicts from `review` and `verify`, investigation artifact, and raw evidence.

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

- Resolve both producer steps and select the newest current-cycle marker; first-entry absence of `verify` is allowed.
- Main checkout and raw evidence remain read-only.

## Procedure

1. Build a finding-by-finding table from the selected producer; preserve rejected claims and corrections visibly.
2. Run additional safe experiments or narrow unsupported claims.
3. Update the investigation artifact, containment/corrective proposals, impact/severity text, and runtime-label
   observations. Do not add ad hoc label proposals.
4. Post the resolution artifact with `--verdict-step fix`.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step fix --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May update incident artifacts and post the fix report.
- Must not change app code, labels, Issue state, or erase raw/contradicting evidence.

## Evidence

- Selected producer marker, per-finding disposition, new experiments, artifact path, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All current findings are addressed with evidence. |
| ABORT | Producer provenance is ambiguous or evidence cannot support a safe correction. |

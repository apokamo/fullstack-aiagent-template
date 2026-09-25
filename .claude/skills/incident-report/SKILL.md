---
name: incident-report
description: "Publish the reviewed incident conclusion and human-owned next actions without mutating lifecycle."
---

# Report incident conclusion

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `incident` workflow at `report`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の調査 and make no change. |

**ワークフロー内の位置**: `report` in the `incident` workflow. `.kaji/wf/custom/incident/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step context.
- Investigation, review, fix, and verify artifacts/comments.

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

- Require review PASS or verify PASS for the current artifact.
- Keep `INCONCLUSIVE` when the evidence boundary remains unresolved.

## Procedure

1. Resolve the configured artifact root and confirm every referenced artifact belongs to this incident.
2. Compose the final conclusion, confidence, impact/severity, containment, corrective action, validation plan,
   runtime-label anomalies, and artifact paths.
3. Post with `--verdict-step report`; confirm provider persistence.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step report --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post the final proposal.
- Must not apply labels, create/merge/close Issues, modify code, or delete artifacts.

## Evidence

- Accepted artifact/version, review marker, conclusion boundary, proposed human actions, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | The reviewed proposal is durably published. |
| ABORT | Required accepted evidence is missing or provider persistence fails. |

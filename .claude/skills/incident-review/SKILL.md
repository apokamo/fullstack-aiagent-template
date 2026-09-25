---
name: incident-review
description: "Independently challenge an incident investigation and its corrective proposal."
---

# Review incident investigation

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `incident` workflow at `review`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Existing fixes need verification. Use `incident-verify`; otherwise use 通常の調査 and make no change. |

**ワークフロー内の位置**: `review` in the `incident` workflow. `.kaji/wf/custom/incident/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/reviewer context.
- Investigation artifact, immutable raw evidence, and incident label policy.

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

- Require a valid investigation artifact and identity.
- The workflow supplies a separate reviewer session. Record reviewer/model and any same-model degradation. New
  findings are allowed.

## Procedure

1. Resolve the artifact root and verify artifact identity against the Issue marker and raw run.
2. Independently reproduce one decisive observation or verify it from immutable logs in a disposable environment.
3. Challenge hypothesis coverage, causal leaps, timeline, environment/version, blast radius, uncertainty,
   containment risk, and label-policy compliance.
4. Post numbered Must Fix findings or approval with `--verdict-step review`.

New findings are allowed. This is the full incident evidence review.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step review --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May create/remove the exact disposable review environment and post findings.
- Must not rewrite the investigation, change labels/lifecycle, or implement corrective action.

## Evidence

- Reviewer/model route, degradation, reproduced observation, artifact/raw paths, findings, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | The investigation and proposal meet the evidence acceptance criteria. |
| RETRY | Numbered corrections can make the artifact acceptable. |
| ABORT | The Issue is not a valid incident or review cannot be performed safely. |

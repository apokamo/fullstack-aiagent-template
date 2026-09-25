---
name: incident-investigate
description: "Investigate a Kaji runtime incident from raw artifacts with falsifiable hypotheses and a bounded
conclusion."
---

# Investigate incident

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `incident` workflow at `investigate`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の調査 and make no change. |

**ワークフロー内の位置**: `investigate` in the `incident` workflow. `.kaji/wf/custom/incident/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step context; ignore synthetic Issue worktree values.
- Incident Issue, identity marker, labels, comments, and raw run artifacts.

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

- Require the first-line Kaji incident identity marker and runtime labels allowed by `docs/dev/issue-labels.md`.
- Resolve `ART=$(uv run kaji config artifacts-dir)`; main checkout is read-only.
- Sanitize evidence before any provider post.

## Procedure

1. Read the failed run timeline, workflow/step, environment/version facts, and prior occurrences from the artifact root.
2. Form competing hypotheses and record confirming and falsifying evidence; do not collapse correlation into cause.
3. Attempt a minimal safe reproduction in a disposable detached worktree or scratch environment. Record success,
   failure, or why it was unsafe/impossible.
4. Write `$ART/<issue_id>/investigation/report.md` with identity, timeline, hypotheses, blast radius, root cause or
   `INCONCLUSIVE`, impact/severity evidence, containment, corrective action, and observed runtime-label anomalies.
5. Post the sanitized artifact with `--verdict-step investigate`; preserve raw artifacts.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step investigate --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May create incident artifacts, a disposable reproduction environment, and the investigation comment.
- Must not modify application code, runtime labels, Issue state, or raw evidence.

## Evidence

- Artifact root/path, raw inputs, reproduction command/result, falsification attempts, conclusion boundary, and
  comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | A sanitized, evidence-bounded investigation artifact is durable. |
| ABORT | Identity/evidence is unavailable or investigation cannot proceed safely. |

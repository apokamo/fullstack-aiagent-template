---
name: pull-request-fix
description: "Resolve current PR feedback and publish the verified correction."
---

# Resolve current PR feedback and publish the verified correction

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Dev/docs dispatch at `pr-fix`, or manual execution of this phase with a valid Issue ID. |
| ❌ | Otherwise use 通常の会話 without mutations. |

## 入力

Read [the shared workflow contract](../_shared/workflow-contract.md) for injected-first
Issue/worktree resolution, manual input and completion. Worktree mode: `issue-worktree`.

Exact branch PR, current-head bot/fallback/pr-verify findings, fix history, current diff and reports.
This cycle consumes PR reviews/comments, not Issue producer verdicts or a required design path.

## Procedure

1. Resolve the exact branch PR and newest permitted current-head finding source. Inspect all unresolved
   actionable feedback and identify the current correction set; stale-head reviews are context only.
2. Reproduce defects and implement the smallest complete code/tests/docs fixes with regression evidence.
   Apply [the rubric](../_shared/review-rubric.md); evidence-backed disagreement is allowed and reported.
   Large unresolved design decisions, unsafe provenance/state or mandatory provider failures are ABORT.
3. Inspect the diff, stage named owned paths and commit. On clean HEAD first run
   `uv run python -m scripts.testing.lane_record --check <lane>` for every affected lane.
   Use [lane evidence](../_shared/lane-evidence.md): REUSED on exit 0; otherwise RERAN with reason for
   affected `make verify-backend`, `make verify-frontend`, docs-only `make verify-docs` and
   [matrix-selected](../_shared/verification-matrix.md) conditional lanes. Read LLM/eval details only when
   selected.
   New observation shortfalls or changed acceptance require the existing final-reconciliation handoff
   before push/PASS. Preserve actual failures; prior approval does not approve a new SHA.
4. Push the verified commit to the configured remote, re-read the PR SHA and reply per finding with
   source identity, fix SHA, proof/disagreement, commands/results and REUSED/RERAN record/log paths.
   Leave uncorrected threads unresolved and identify them in the report.

Last, publish the report and actual step marker, stdout and injected YAML through
[verdict output](../_shared/verdict.md). Use only the current step's allowed status.

## Side effects

May edit/commit/push scoped Issue branch changes and reply to PR findings. Must not merge,
force-push, change labels, resolve uncorrected/unrelated threads or amend/rebase recorded commits.

## Verdict

| Status | Condition |
|---|---|
| PASS | Current actionable feedback is fixed or answered and the verified correction is pushed and reported. |
| ABORT | Provenance, unresolved design, authority, required verification/provider or repository state prevents completion. |

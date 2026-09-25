---
name: issue-small-change-review
description: "Independently review a small change and reconcile final verification at its current SHA."
---

# Independently review a small change and reconcile final verification at its current SHA

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Explicit dev-small dispatch at `review-change` or `verify-change`, or manual execution of that phase with a valid Issue ID. |
| ❌ | Otherwise use 通常の会話 without mutations. |

## 入力

Read [the shared workflow contract](../_shared/workflow-contract.md) for injected-first
Issue/worktree resolution, manual input and completion. Worktree mode: `issue-worktree`.

Issue decisions/acceptance, actual diff, current implementation or fix report and full SHA.
Use a context independent of the implementer. No independent design artifact is required.

## Procedure

1. Resolve `uv run kaji issue resolve-verdict <issue_id> --step <producer>` for the actual handoff:

   | Producer | Allowed status | When |
   |---|---|---|
   | change | PASS | review-change |
   | fix-change | PASS | verify-change |

   Trace the fix report to its current review-change/verify-change findings and correction commit.
   If HEAD changed during a review barrier, identify the additional diff and missing evidence and
   RETRY to fix-change; never approve the old implementation report as the new SHA.
2. At review-change inspect Issue decisions, the complete `git diff origin/main...HEAD` and actual files,
   independently checking acceptance, invariants, scope and lane selection with
   [the rubric](../_shared/review-rubric.md) and [the matrix](../_shared/verification-matrix.md).
   At verify-change inspect unresolved findings and regression risk from the fix diff, then reconcile
   final conditions on the latest SHA. Decide evidence-backed disagreement; keep resolved findings closed.
   Preferences, future improvements and unrelated observations alone do not RETRY.
3. For every required lane first run `uv run python -m scripts.testing.lane_record --check <lane>`.
   Apply [lane evidence](../_shared/lane-evidence.md): REUSED on exit 0, otherwise RERAN with reason.
   Own `make check-all` and matrix-required conditional lanes on clean HEAD. Missing/unusable records
   alone call for execution, not ABORT. Apply the existing observation-eval evidence/follow-up contract
   only when relevant; never convert provider failure to PASS.
   If execution changes tracked files, preserve them and RETRY to implementation rather than commit.
4. Route by root cause: required code/tests/docs corrections or regressions are concrete RETRY findings;
   unsuitable scope, unknown authority/provenance or mandatory provider failure is ABORT. On unsuitable
   scope preserve branch/worktree/HEAD/dirty state and give the standard-dev manual handoff.
5. Confirm a clean tree, full current SHA, acceptance and required lane evidence. Update only verified
   acceptance checkboxes in the freshly read Issue body; external/post-workflow items remain unchecked.
   Report numbered findings or approval, full SHA, source report links, commands/results, REUSED/RERAN
   record/log references and remaining constraints. Human review never waives this integrated final check.

Last, publish the report and actual step marker, stdout and injected YAML through
[verdict output](../_shared/verdict.md). Use only the current step's allowed status.

## Side effects

May post Issue review reports, update verified acceptance criteria and run/cite required lanes.
May create/reuse observation-quality investigation Issues and update their evidence/parent links
with invocation authority under the [LLM follow-up contract](../../../docs/dev/llm-evals.md#観測項目の未達を引き継ぐ);
no unrelated Issue or lifecycle mutations.
Must not edit or commit tracked files, push, create PRs, merge, change labels or create/delete worktrees.

## Verdict

| Status | Condition |
|---|---|
| PASS | Acceptance and required verification complete on the reviewed clean full SHA, with report. |
| RETRY | Concrete tracked correction, unresolved finding, fix regression or changed-HEAD evidence needs implementation. |
| ABORT | Unsuitable scope, unsafe/unavailable provenance, state or mandatory provider. |

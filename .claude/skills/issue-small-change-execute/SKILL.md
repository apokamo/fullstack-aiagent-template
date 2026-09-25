---
name: issue-small-change-execute
description: "Implement a bounded small change from Issue decisions and verify the committed result."
---

# Implement a bounded small change from Issue decisions and verify the committed result

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Explicit dev-small dispatch at `change` or `fix-change`, or manual execution of that phase with a valid Issue ID. |
| ❌ | Otherwise use 通常の会話 without mutations. |

## 入力

Read [the shared workflow contract](../_shared/workflow-contract.md) for injected-first
Issue/worktree resolution, manual input and completion. Worktree mode: `issue-worktree`.

Issue decisions and acceptance criteria, resolved branch/worktree, current diff and relevant reports.
The Issue is the design source; do not require a separate design artifact or precheck.

## Procedure

1. Identify the actual phase from context and current reports. Resolve its direct handoff with
   `uv run kaji issue resolve-verdict <issue_id> --step <producer>` using the pairs below.
   On fix reentry, follow the current correction cycle's report links, not an older finding.

   | Producer | Allowed status | When |
   |---|---|---|
   | start | PASS | Initial change |
   | change | RETRY | Self retry, also inspect existing results |
   | review-change | RETRY | Fix requested by initial review |
   | verify-change | RETRY | Fix requested by verification |

2. Check that expected behavior, scope, invariants, local verification and ordinary revert are clear.
   `type:docs` belongs to docs. Unresolved architecture, permission boundaries, migrations or public
   compatibility decisions require standard dev. If unsuitable, ABORT with reason, needed decisions,
   unfinished work, branch/worktree/full HEAD, dirty state and report links. Preserve assets; do not
   edit active state, restart workflows or translate a small PASS into design approval.
3. State briefly what changes, what remains invariant and how to verify, citing settled Issue decisions.
   Read only relevant type guidance under `../_shared/implementation-by-type/`, canonical references and
   [verification selection](../_shared/verification-matrix.md). Establish the type-appropriate regression
   signal or baseline before editing; do not add substitute design/precheck reports or approval waits.
4. Implement the bounded code/tests/docs change. In `fix-change`, address the current findings and their
   consequences; explain evidence-backed disagreement using [the rubric](../_shared/review-rubric.md).
   Preserve user changes, inspect the full diff, stage named owned paths and commit.
5. On clean HEAD, run `uv run python -m scripts.testing.lane_record --check <lane>` first for each
   required lane. Apply [lane evidence](../_shared/lane-evidence.md): exit 0 is REUSED, otherwise run the
   supported target and record RERAN with the reason. Use affected `make verify-backend` and/or
   `make verify-frontend`, `make verify-docs` for workflow/docs, and matrix-selected conditional lanes.
   Required provider failures never pass.
6. Reconcile acceptance and report full SHA, change reasons, commands/exits, lane selection/omission
   reasons, record/log paths and remaining constraints. Report correction-source links on fixes.
   Local failures may RETRY only at `change`; `fix-change` repairs locally or ends ABORT.
   Do not PASS with a dirty tree, failed required checks or incomplete evidence.

Last, publish the report and actual step marker, stdout and injected YAML through
[verdict output](../_shared/verdict.md). Use only the current step's allowed status.

## Side effects

May edit and commit scoped code/tests/docs and post Issue reports. Must not push, publish a PR,
merge, change labels, create/delete worktrees, clean up assets or rewrite commits with lane records.

## Verdict

| Status | Condition |
|---|---|
| PASS | Scoped implementation, commit, required verification and report complete on clean HEAD. |
| RETRY | At change only: a locally correctable implementation/check/report failure remains. |
| ABORT | Unsuitable scope, unresolved authority/provenance, provider failure, unsafe state or incomplete fix-change. |

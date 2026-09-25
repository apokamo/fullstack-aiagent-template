---
name: pull-request-create
description: "Publish the final-approved SHA in exactly one pull request."
---

# Publish the final-approved SHA in exactly one pull request

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Dev/docs dispatch at `pr`, or manual execution of this phase with a valid Issue ID. |
| ❌ | Otherwise use 通常の会話 without mutations. |

## 入力

Read [the shared workflow contract](../_shared/workflow-contract.md) for injected-first
Issue/worktree resolution, manual input and completion. Worktree mode: `issue-worktree`.

Resolved Issue/branch/worktree, configured remote/base, current final approval and matching PR inventory.
Use approval evidence, not workflow-name branching or design-file absence, to establish readiness.

## Procedure

1. Identify the final confirmation for the current work from Issue progress and implementation/fix/review
   report references. Resolve that exact producer with
   `uv run kaji issue resolve-verdict <issue_id> --step <producer>`:

   | Producer | Allowed status | When |
   |---|---|---|
   | final-check | PASS | Standard dev or docs final approval |
   | review-change | PASS | Initial integrated final approval |
   | verify-change | PASS | Integrated approval after correction |
   | pr | RETRY | Publication retry, also recheck actual remote/PR state |

   Require that approval covers the current implementation/fix and its full SHA equals clean HEAD.
   From its comment URL/time, inspect subsequent related reports/markers on this Issue and branch in
   posting order, following any resumed work, RETRY/ABORT, fixes and final approvals. Include explicit
   human returns or changed requirements without markers. Unrelated comments and resolved past failures
   do not invalidate approval. Recovery reposts retain their original provenance; their new timestamp
   cannot renew old approval. Read referenced originals only as needed, not all history unconditionally.
   If standard dev has resumed, an old small-change PASS cannot replace its final confirmation.
   Missing approval, HEAD mismatch, unresolved work and unknown provenance are distinct ABORT reasons.
   Never choose the newest same-SHA PASS across producers or fall back to an older producer on failure.
2. Confirm the intended branch/diff and absence of secrets/private generated artifacts. Resolve the exact
   branch with `uv run kaji pr list`; reuse one matching PR and ABORT on duplicates or mismatched identity.
   Prepare title/body from the approval and implementation reports: problem, resulting behavior,
   validation, material limits, relevant links and `Closes #<issue_id>`. Carry verified observation FAIL
   and follow-up links as reported. Upstream owns design/reference/acceptance/lane reconciliation;
   publication does not recheck/repair the design block or revalidate lane details.
3. Verify push authority from the invocation, recheck clean full HEAD against approval, then push that SHA
   to the configured `git_remote` and create/update through `uv run kaji pr create` or supported update
   against `default_branch`. Reuse partial publication safely; never create a duplicate on retry.
4. Re-read PR head/base/full SHA/body and confirm published SHA equals approval. Report approval URL/SHA,
   clean state, remote/base/branch, push result, PR URL/ID and any limits to the Issue.

Last, publish the report and actual step marker, stdout and injected YAML through
[verdict output](../_shared/verdict.md). Use only the current step's allowed status.

## Side effects

May push the exact Issue branch and create/update one PR and Issue report. Must not edit tracked
files or design blocks, merge, force-push, change labels or rewrite history.

## Verdict

| Status | Condition |
|---|---|
| PASS | Exactly the approved clean SHA is published in one confirmed PR and reported. |
| RETRY | A locally recoverable publication/body failure remains with unambiguous state. |
| ABORT | Approval, provenance, HEAD, authority, secrets, remote/PR identity or provider is unsafe/unavailable. |

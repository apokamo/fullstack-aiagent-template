---
name: issue-close
description: "Merge the reviewed pull request, hand off follow-ups, clean up managed assets, resynchronize main, and
explicitly close the Issue."
---

# Close Issue

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

This is the only terminal lifecycle owner. No other step, engine, or finalize phase performs these mutations.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev/docs` workflow at `close`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `close` in the `dev/docs` workflow. `.kaji/wf/custom/{dev,docs}/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- Use injected `pr_id` and `pr_ref` only after PR resolution.
- Phase-specific inputs:

- Injected Issue/worktree/branch context, `git_remote`, and `default_branch`.
- Issue, exact PR, expected head branch, base, published head SHA, and upstream completion reports.
- Unchecked post-workflow criteria that must be handed off instead of silently dropped.

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
6. Resolve the exact branch PR and carry the upstream completion handoff. Use the final confirmation
   report for follow-up links; close does not require or resolve a design path.
7. In manual use, never invent `verdict_path`, cycle values, or `previous_verdict`. Without `verdict_path`, stop
   after the Issue marker and stdout fallback.

## Preconditions and worktree

Worktree mode: `issue-worktree` until step 6 deletes it. From there on, including every re-entry, this skill runs
against the canonical main checkout and the provider only.

- Re-read Issue, PR, branch, base, published head SHA and completed lifecycle operations from the provider and Git
  on every entry and re-entry. Carry the existing upstream reports and follow-up links forward.
- Resolve the canonical main checkout with `git worktree list`, whose first entry is always the main worktree, per
  [worktree.md](../_shared/worktree.md). The answer does not depend on the Issue worktree existing, so it is the same
  before and after step 6. Every command uses `git -C <absolute-path>` and absolute tool paths.
- Require exactly one open-or-merged PR whose base is `<default_branch>` and whose head is the expected branch at the
  selected published SHA. Ambiguity, wrong base/head, a known upstream SHA mismatch, observed head drift, or provider
  failure is `ABORT`. Confirm the PR belongs to this Issue; an injected PR number alone does not establish identity.
- Do not make the canonical main checkout's state an entry condition. Step 7 owns the clean check, immediately
  before the fast-forward that could destroy uncommitted work, and that is the only place it is needed. Require the
  configured remote. Remote containment is not a gate condition here: `<git_remote>/<default_branch>` is a
  remote-tracking ref that an interruption before step 4's fetch leaves stale, so gating on it would abort ahead of
  the fetch that makes it knowable. Step 4 owns that confirmation and reads it after fetching. An absent managed
  worktree is a completed step 6, not a missing input; continue from the first incomplete step instead of aborting.

### Upstream completion handoff

PR approval belongs to `review-poll`, fallback `review`, or corrected-head `pr-verify`. Final verification belongs
to standard dev `final-check`, dev-small `review-change` / `verify-change`, docs final confirmation, or corrected-head
`pr-verify`. Close consumes their completion and performs terminal operations; it does not reassess approval or lanes.

| Entry into close | Handoff and action |
|---|---|
| Normal harness transition `review-poll PASS → close` | Inherit automatic review completion and upstream final confirmation; resolve the operation target and proceed to merge. |
| `review PASS → close` | Inherit fallback approval; no additional review-poll or pr-verify is required. |
| `pr-verify PASS → close` | Inherit corrected-head approval and final verification; use the corrected target and current reports, not a pre-fix PASS. |
| Manual close or retry for an explicitly approved Issue/PR | Use the operator's approved-target premise and any explicitly supplied original run/report. Do not ask again for approval already supplied. |
| Manual entry with an unclear target or approval premise | Stop with the specific missing target or execution premise; return to the existing review route or operator information, without performing review inside close. |
| Re-entry after merge | Confirm PR identity and merged state, then resume the first incomplete operation. Removed worktree/branches do not invalidate the handoff. |

A normal harness PASS transition is the upstream completion handoff. An arbitrary input containing only
`step_id=close` is not approval proof. `previous_verdict` is not always injected, and a review-poll YAML need not
contain a PR number or full SHA; their absence alone is not a failure. Empty formal reviews and absent Issue
PR-cycle markers likewise do not undo the handoff. Do not reconstruct upstream execution from Issue markers,
resolve PR approval with `kaji issue resolve-verdict`, or tour PR reviews/comments/reactions to judge approval again.
Do not add an approval resolver, bot identity/freshness analysis, exhaustive artifact search, or mandatory new evidence.

Carry existing upstream reports, lane references and observation follow-ups without re-auditing or rerunning lanes.
Before pinning, read the upstream completion reports you already carry for a target full SHA. That is reading the
handoff you inherited, not a new approval search, and their SHA is the merge target: compare it with the current
published head and, on a mismatch, report both SHAs and stop without merging instead of adopting the newer head.
Use current correction reports rather than superseded ones. Only when no carried report names a SHA, pin the first
observed published full head as `merge_head_sha`. Either way, re-read the published head immediately before merge.
This SHA identifies the operation target; do not describe its acquisition as proof of the bot's approved SHA.
A missing upstream SHA is still not a failure by itself; in that case changes made before the first observation are
outside close's detection guarantee, and the report says which of the two cases applied. Stronger structured
approval/SHA provenance belongs upstream, not to a new close gate.

## Procedure

1. Acquire Issue, exact PR, expected head branch, base and published full head SHA. Apply the handoff above:
   after identifying the unique target, pin `merge_head_sha` to the carried upstream target SHA when one is known
   and stop on a mismatch, and only otherwise to the first observed published head.
2. Re-read the published full head SHA immediately before merge. If it differs from `merge_head_sha`, report both
   values and `ABORT` without merging. A merged PR with the same identity and pinned head skips step 3.
3. Merge with `uv run kaji pr merge <pr_number> --merge --match-head-commit <merge_head_sha>` without asking for
   further human approval. The head match pins the operation target on the provider side, so a push landing between
   the last read and the merge request fails the merge. Never add a closing keyword to the commit or merge message;
   the PR body keeps `Closes #<issue>` only for the Development link.
4. Confirm the provider reports the PR merged and that `<git_remote>/<default_branch>` contains the pinned head after
   `git fetch <git_remote>`. Never revert automatically; a failed confirmation is `ABORT`.
   Preserve the final confirmation owner's observation-eval follow-up links and nonblocking rationale in the close summary.
   Do not recreate them as post-workflow criteria or wait for their investigation to finish.
5. Hand off every unchecked post-workflow criterion to the single follow-up Issue for this parent. Idempotency is
   anchored on the parent, not on a search: the parent Issue body carries the marker line
   `> follow-up: #<created_issue_id> post-workflow criteria` once the handoff is complete, so a parent already
   carrying it is a completed handoff and this step is a skip. Reading the parent is the whole check; no reconstructed
   identity is needed.

   With no marker present, look for an earlier attempt's Issue before creating one, because a create that succeeded
   before the marker write would otherwise be duplicated:

   ```bash
   uv run kaji issue list --state all --json number,title,state,url \
     --search '"follow-up: #<issue_id> post-workflow criteria" in:title'
   ```

   Keep only results whose title matches `follow-up: #<issue_id> post-workflow criteria` exactly. No result creates
   one with `uv run kaji issue create`; exactly one result is reused; more than one is ambiguous and is `ABORT`.
   Then write the marker into the parent body with `uv run kaji issue edit <issue_id>`. A failed create or a failed
   marker write is `ABORT`: an unmarked handoff is indistinguishable from no handoff on the next entry.
6. Delete the exact managed worktree with `git worktree remove <absolute-worktree>` only when it is clean, identified,
   and its branch is merged into `<git_remote>/<default_branch>`. Retain a dirty, unknown, or mismatched worktree and
   report the reason. First confirm that `<worktree>/test-artifacts/` holds no measurement artifact (eval evidence,
   calibration packets, labels, scoring results) that was not yet moved into tracked `evals-evidence/`: `test-artifacts/`
   is ignored, so `git worktree remove` deletes it without treating it as dirty. An unmoved artifact retains the
   worktree and is reported; lane records, logs and raw HTML are not measurement artifacts.
7. Confirm the main checkout is clean, run `git fetch <git_remote>`, and fast-forward it with
   `git merge --ff-only <git_remote>/<default_branch>`. That command reports `Already up to date` and succeeds when
   `HEAD` is ahead of the remote, so this step is complete only once `HEAD` equals `<git_remote>/<default_branch>`.
   A remaining local commit is reported and `ABORT`; never reset, discard, or push it. A non-ff-only outcome or dirty
   main is `ABORT` before closing.
8. Clean up the local and remote branch independently, each after confirming existence and merged ancestry. Prove
   containment explicitly with `git merge-base --is-ancestor <branch_name> <git_remote>/<default_branch>` and only
   then delete with `git branch -D <branch_name>`. The explicit ancestry check is what makes the delete safe, and it
   is the reason `-D` is correct here: the branch is created `--no-track`, so `git branch -d` has no upstream to judge
   against and falls back to `HEAD`, which refuses a merged branch whenever the main checkout has not been
   fast-forwarded yet. A branch that fails the ancestry check is retained with the reason. An already absent worktree
   or branch is a skip, not a failure.
9. Post the summary of merge, follow-ups, cleanup, retained assets, and the resulting main SHA to the Issue.
10. Run `uv run kaji issue close <issue_id>` and re-read provider state to confirm `CLOSED`.

A failure after the merge is `ABORT`, and this skill closes the Issue only at step 10. Re-running it re-reads
provider and Git state and must not merge twice, duplicate a follow-up, or repeat completed cleanup.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step close --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

Owned terminal side effects: `merge-pr`, `handoff-follow-up`, `cleanup-worktree-branch`, `sync-main`, `close-issue`.

- Merges the exact reviewed PR, posts the final summary, and closes this Issue.
- Creates or reuses one follow-up Issue for unchecked post-workflow criteria.
- Deletes only the exact known managed worktree and branch, and fast-forwards the canonical main checkout.
- Must not revert a merge, force-push, force-update a shared ref, discard user changes, edit labels, or delete an
  unknown or dirty asset. Deleting a local branch whose commits are already contained in
  `<git_remote>/<default_branch>` is not a forced update; the ancestry check in step 8 is the safety condition.

## Evidence

- Issue/PR identity, base, expected head branch, pinned `merge_head_sha` and the immediately pre-merge head read.
- Normal workflow handoff or explicit manual approved-target premise, existing upstream report/follow-up links,
  and which pinning case applied: the carried upstream target SHA and its comparison with the published head, or the
  recorded absence of any carried SHA. Distinguish a pinned operation SHA from approval proof.
- Merge command including `--match-head-commit`, its result or the confirmed pre-existing merged state, and remote
  containment of the pinned head.
- Follow-up handoff: the parent marker read, the reuse/creation decision with the search that resolved it, and the
  parent body edit that wrote the marker.
- Main sync result with the confirmed `HEAD == <git_remote>/<default_branch>` SHA, the ancestry check that authorized
  each branch delete, cleanup and retention decisions with reasons, summary comment URL, close command result, and
  re-read provider state.

## Verdict

| Status | Condition |
|---|---|
| PASS | The reviewed PR is merged, handoff and cleanup are complete, main is synchronized, and the provider confirms the Issue closed. |
| ABORT | Identity, handoff premise, head comparison, merge, confirmation, handoff, cleanup, main sync, or provider closure fails. |

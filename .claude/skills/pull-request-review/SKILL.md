---
name: pull-request-review
description: "Perform the fallback full PR review when automated review polling cannot produce a decision."
---

# Review pull request

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev/docs` workflow at `review`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Existing PR fixes need verification. Use `pull-request-verify`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `review` in the `dev/docs` workflow. `.kaji/wf/custom/{dev,docs}/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- Use injected `pr_id` and `pr_ref` only after PR resolution.
- Phase-specific inputs:

- Injected Issue/provider/worktree context and PR ID when available.
- Current-head PR metadata/patch/reviews, Issue and local final-gate evidence; upstream approval reports and
  their related design links when relevant. Design artifact existence is not a publication/review gate.

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
6. Resolve the exact branch PR and current-head review evidence. Use upstream approval links
   and relevant design context only when needed; do not infer the route from a missing design.
7. In manual use, never invent `verdict_path`, cycle values, or `previous_verdict`. Without `verdict_path`, stop
   after the Issue marker and stdout fallback.

## Preconditions and worktree

Worktree mode: `issue-worktree`.

- Use only after `review-poll` returns `BACK_FALLBACK`; require GitHub provider and exact current-head PR.
- New findings are allowed. GitHub checks are metadata, not substitutes for required local evidence.

## Procedure

1. Resolve the PR by exact branch/Issue and confirm head SHA matches the reviewed worktree.
2. Collect the Issue decisions, full patch, current-head PR evidence, upstream approval report and
   unresolved discussions. Follow related design links when needed; the absence of an independent
   design artifact alone does not reject a small change. Standard dev design requirements remain upstream.
3. Review correctness, security, compatibility, tests, docs, acceptance criteria, and local lane evidence
   independently. Run a focused local check only when needed to resolve uncertainty.
4. Post numbered findings or approval through the supported Kaji PR review/comment path with a deterministic review
   marker tied to current head.

New findings are allowed. This is the full fallback PR review.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step review --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post one current-head PR review/comment and verdict.
- Must not edit code, resolve threads, merge, or treat absent GitHub checks as failure.

## Evidence

- Provider/PR/head identity, patch reviewed, local evidence inspected, focused command if any, findings, and review URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | The current head is approvable with no actionable blocker. |
| RETRY | Actionable current-head findings require `pull-request-fix`. |
| ABORT | Provider/PR/head/evidence cannot be resolved safely. |

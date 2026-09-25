---
name: issue-readiness-review
description: "Check label, requirement, decision, and dependency readiness before creating an Issue worktree."
---

# Review Issue readiness

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev/docs` workflow at `review-ready`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Existing readiness findings need correction. Use `issue-readiness-fix`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `review-ready` in the `dev/docs` workflow. `.kaji/wf/custom/{dev,docs}/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected `issue_id`, `step_id`, provider and cycle context; manual Issue ID is fallback.
- Issue body, comments, labels, dependencies, and active branch/worktree/PR inventory.

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

Worktree mode: `pre-worktree`.

- Run from the main checkout without requiring or editing an Issue worktree.
- Read `docs/dev/issue-labels.md`, completion criteria, and critical-decision rules. New findings are allowed.

## Procedure

1. Fetch body/comments/labels with `uv run kaji issue view <issue_id> ...`. Require exactly one canonical `type:*`;
   require at least one canonical `area:*` for dev and allow none for docs.
2. Apply the matching type minimum: feature outcome/interface, bug reproduction/actual/expected, refactor
   invariants, test production non-change, chore compatibility, perf baseline, or security threat boundary.
3. Check objective, non-goals, verifiable criteria, dependencies, duplicate active PR/worktree, secret/authority
   requirements, and label/scope/path consistency. Area does not select the workflow or prove a lane.
4. Separate correctable text/label defects from unresolved one-way decisions. Post numbered findings using
   `--verdict-step review-ready`.

New findings are allowed. This is the complete pre-worktree readiness review.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `fix-ready` | `PASS` | `--producer-step fix-ready --allow-status fix-ready=PASS` |

Append exactly one row's arguments to this command:

```bash
uv run python -m scripts.kaji.resolve_verdict_artifact \
  --issue-id <issue_id> --current-verdict-path <verdict_path> \
  <single-producer-helper-arguments>
```

Exit 5 (malformed), provider failure, no match, or ambiguity is `ABORT`; do not infer
status from prose. On one match, post the exact producer's canonical marker and recovery report with:

```bash
uv run kaji issue comment <issue_id> --commit \
  --verdict-step <returned-step> --verdict-status <returned-status> \
  --verdict-meta recovered_from=<producer_run>/<returned-step>/attempt-NNN \
  --body-file <recovery-report>
```

Include the returned artifact paths in the recovery report, then rerun `resolve-verdict` for the same producer.
Continue only when it returns the same status.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step review-ready --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post readiness findings only.
- Must not create/edit a worktree, code, or labels. Label/body correction belongs to `issue-readiness-fix`.

## Evidence

- Issue/label snapshot, type rubric applied, duplicate/dependency checks, decision classification, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Labels, requirements, decisions, dependencies, and criteria are ready. |
| RETRY | Explicit body or canonical label corrections can make the Issue ready. |
| ABORT | A one-way decision, missing authority, unsafe requirement, or external blocker needs a human. |

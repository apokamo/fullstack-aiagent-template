---
name: issue-worktree-create
description: "Create or safely reuse the injected Issue branch/worktree and make its ignored runtime assets executable."
---

# Create and bootstrap Issue worktree

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev/docs` workflow at `start`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `start` in the `dev/docs` workflow. `.kaji/wf/custom/{dev,docs}/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected `issue_id`, `git_remote`, `default_branch`, `branch_name`, and absolute `worktree_dir`.
- Main checkout root and current branch/worktree/PR inventory.

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

Worktree mode: `creates-issue-worktree`.

- Run from the main checkout; require all injected repository values.
- Inspect main tracked status, `git worktree list --porcelain`, local/remote branch refs, and matching PR before
  mutation.
- Never overwrite a mismatched path, branch, symlink, or unexplained dirty Issue worktree.

## Procedure

1. Run `git fetch <git_remote>` and resolve `<git_remote>/<default_branch>`; failure is `ABORT`.
2. If branch and worktree are absent, run `git worktree add --no-track -b <branch_name> <worktree_dir>
   <git_remote>/<default_branch>`. If both exist, require the same repository, expected branch/path, and valid base
   ancestry. One-sided or conflicting state is `ABORT`.
3. Invoke the absolute main-checkout script `scripts/kaji/bootstrap_worktree_env.sh <main-repo> <worktree_dir>`.
4. Verify `.venv`, `.env`, four required secret links, optional PEM links, the `.kaji/config.local.toml` link when
   the main checkout has one, root `node_modules`, web `node_modules`, and branch/base.
5. Run `uv run kaji issue prepend-note <issue_id> --worktree <basename> --branch <branch_name>` and post the start
   report. Re-entry must converge without duplicate NOTE or replaced assets.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `review-ready` | `PASS` | `--producer-step review-ready --allow-status review-ready=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step start --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May fetch, create/reuse the named branch/worktree, create ignored assets inside it, and update the Issue NOTE/report.
- Must not alter main assets, force-replace collisions, push, create a PR, or delete any worktree/branch.

## Evidence

- Injected context, base SHA, inventory/collision decision, bootstrap exit, asset verification, NOTE, and report
  URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | The exact worktree is safely reusable, fully bootstrapped, verified, and recorded. |
| ABORT | Fetch/context/collision/bootstrap/verification/provider recording fails. |

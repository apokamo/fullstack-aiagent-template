---
name: issue-readiness-fix
description: "Apply only explicit readiness corrections to an Issue body or canonical labels."
---

# Fix Issue readiness findings

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev/docs` workflow at `fix-ready`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new readiness review is needed. Use `issue-readiness-review`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `fix-ready` in the `dev/docs` workflow. `.kaji/wf/custom/{dev,docs}/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle context.
- Current `review-ready` verdict marker and full Issue history.

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

- Resolve `uv run kaji issue resolve-verdict <issue_id> --step review-ready`; missing/ambiguous producer is `ABORT`.
- Read the label policy. Never infer a primary type or product decision.
- A one-way decision cannot enter this fix loop; return `ABORT` for human input.

## Procedure

1. Create a finding-by-finding plan and distinguish formatting/clarification from human-owned decisions.
2. Edit only requested outcome, non-goals, criteria, dependency text, or canonical type/area labels through `uv run
   kaji issue edit`. Change labels only when the latest finding names the exact correction.
3. Re-read the provider state, confirm no history or unrelated labels were lost, and post a `fix-ready` resolution
   table.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `review-ready` | `RETRY` | `--producer-step review-ready --allow-status review-ready=RETRY` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step fix-ready --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May edit the current Issue body and explicitly requested canonical labels, then post a report.
- Must not create a worktree or invent missing decisions. It never performs bulk label operations.

## Evidence

- Producer marker, before/after fields and labels, finding table, provider confirmation, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Every explicit correctable finding is applied and confirmed. |
| ABORT | A human decision is required, provenance is ambiguous, or provider mutation fails. |

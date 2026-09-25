---
name: issue-implementation-precheck
description: "Measure design-required baselines and safety nets before implementation without changing product files."
---

# Implementation precheck

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `implement-precheck`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `implement-precheck` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step/worktree context and `design_path`.
- Reviewed design, `review-design` or `verify-design` PASS, labels, and current tree state.

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

Read [design evidence](../_shared/design-evidence.md) for design references and repairs.

## Preconditions and worktree

Worktree mode: `issue-worktree`.

- Resolve the worktree and inspect all existing changes.
- Resolve `design_path` with `scripts.kaji.resolve_design_path`; require the approved canonical design commit and
  the managed `<!-- kaji-design:start -->` block's `blob/<design-sha>/<design-path>` permalink to identify the
  same full SHA before implementation may start, after reference repair under the shared workflow contract.
  A stale/missing block alone is repaired here; uncertain source/approval is `ABORT`.
- Require canonical type/area labels, valid Scope, matching type guide, reachable `origin/main`, and no unresolved
  design finding.
- This phase is read-only for tracked product/design files.

## Procedure

Apply the [review rubric](../_shared/review-rubric.md) before routing any finding.

1. Read the design precheck section and `../_shared/implementation-by-type/<type>.md`. Reconcile type/area/Scope
   but treat the design/diff as lane authority. Apply the shared review rubric before any return: repair
   references here, and send only consequential design gaps or necessary canonical file repairs via
   `BACK_DESIGN`. Cite settled decisions and limit the requested correction to the finding and its consequences.
2. For types without a special baseline, confirm the selected safety net and return a documented no-op. For bug,
   reproduce actual behavior; refactor, record equivalence baseline; perf, record workload measurements;
   security/test/chore/feature, execute the design-specified precondition or safety check.
3. Write full output under the injected artifact directory or a named `/tmp/precheck-<issue_id>-*.log`; keep only a
   concise summary and path in context.
4. Post `implement-precheck` with commands, exit states, baseline summary, log path, and SHA.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `review-design` | `PASS` | `--producer-step review-design --allow-status review-design=PASS` |
| `verify-design` | `PASS` | `--producer-step verify-design --allow-status verify-design=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step implement-precheck --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May synchronize the managed design block under the shared reference-repair contract.
- May create ignored/log artifacts and post the precheck report.
- Must not edit or commit tracked files, labels, or Issue requirements.

## Evidence

- Type/area/Scope map, commands/exits, baseline/safety summary, log path, tree status, SHA, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Required baseline/safety evidence exists and implementation may start. |
| BACK_DESIGN | A consequential design gap or bounded canonical file repair is required; body-only reference repair is completed here. |
| ABORT | Repository/provider/evidence state is unsafe or the required precheck cannot run. |

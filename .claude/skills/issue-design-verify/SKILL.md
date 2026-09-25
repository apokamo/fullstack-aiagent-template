---
name: issue-design-verify
description: "Verify resolution of current design findings without starting another full design review."
---

# Verify design fixes

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `verify-design`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new full design review is needed. Use `issue-design-review`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `verify-design` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context and `design_path`.
- Original review findings, `fix-design` report, and design fix diff.

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

- Resolve `design_path` with `scripts.kaji.resolve_design_path`; require the latest `fix-design` marker and exact
  canonical design SHA.
- Do not add new findings. Record new observations separately.

## Procedure

1. Run `uv run kaji issue resolve-verdict <issue_id> --step fix-design` and read its report with the Issue's
   review and verification reports. Existing `source_step` metadata is optional; do not require it or reject
   a report because of its value. No metadata-specific compatibility branch is needed.
2. Identify the findings addressed by the latest fix report. For a `review-design` request, use its design
   findings; for a `review-code BACK_DESIGN_FIX` request, use that design correction. On a `verify-design RETRY`,
   verify the remaining findings and keep resolved findings closed. A later metadata-only ABORT
   does not replace the outstanding content findings. If the reports genuinely cannot identify the findings
   or their corrections, return `ABORT` and explain the missing information.
3. Inspect the design/source evidence and record OK/NG for each finding, including any evidence-backed disagreement.
4. Confirm fixes did not weaken scope, provenance, failure behavior, docs, criteria, or required lanes.
   For every fix-design correction, confirm its block names the committed design SHA; an unambiguous
   synchronization omission is `RETRY` for fix-design, not a new content review. Implement edits belong
   to review-code and fix-code edits to verify-code; do not require entry here solely for synchronization.
5. Post a `verify-design` marker report; unrelated new observations do not affect this cycle verdict.

Do not add new findings to this verdict; verify only the existing design-review set.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `fix-design` | `PASS` | `--producer-step fix-design --allow-status fix-design=PASS` |

Append exactly one row's arguments to this command:

```bash
uv run python -m scripts.kaji.resolve_verdict_artifact \
  --issue-id <issue_id> --current-verdict-path <verdict_path> \
  <single-producer-helper-arguments>
```

Exit 5 (malformed), provider failure, no match, or ambiguity is `ABORT`; do not infer status from prose.
On one artifact match, post the exact producer's canonical marker and recovery report with:

```bash
uv run kaji issue comment <issue_id> --commit \
  --verdict-step <returned-step> --verdict-status <returned-status> \
  --verdict-meta recovered_from=<producer_run>/<returned-step>/attempt-NNN \
  --body-file <recovery-report>
```

Include the returned artifact paths in the recovery report, then rerun `resolve-verdict` for the same producer.
Continue only when it returns the same status.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step verify-design --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post verification evidence.
- Must not edit the design or expand the finding set.
- Must not run any recorded quality lane:
  `make verify-backend`, `make gate-backend`, `make verify-frontend`,
  `make verify-docs`, `make check-all`, `make test-on-schema-change`,
  `make test-e2e`, `make test-llm`, `make evals`.
  The design loop selects lanes and writes them into the design; implementation and the fix phases produce
  the records under [lane evidence](../_shared/lane-evidence.md).

## Evidence

- Review/fix markers, design SHA/diff, per-finding result, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All original design findings are resolved. |
| RETRY | At least one original finding remains. |
| ABORT | The reports cannot identify the findings or safe verification is impossible. |

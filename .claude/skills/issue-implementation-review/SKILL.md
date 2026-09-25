---
name: issue-implementation-review
description: "Independently review the complete implementation and execute risk-based verification."
---

# Review implementation

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `review-code`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Existing code-review fixes need verification. Use `issue-implementation-verify`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `review-code` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context and `design_path`.
- Issue/labels, approved design, precheck and implementation reports, and `git diff origin/main...HEAD`.

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

- Require an identifiable implementation SHA and understood worktree state.
- Resolve the canonical design with `scripts.kaji.resolve_design_path`; read it with matching implementation
  type rubrics plus relevant code references. New findings are allowed.

## Procedure

For observation-purpose evals, apply the `OBSERVED` branch in
[lane evidence](../_shared/lane-evidence.md) before the success-record rerun rules below.
Preserve failed results and report handoff evidence/candidates to final-check within this phase's scope.
Required quality thresholds, provider/safety failures and confirmed regressions still block.

Apply the [review rubric](../_shared/review-rubric.md) before routing any finding.

1. Trace every acceptance criterion, decision, interface, failure mode, and documentation obligation to the diff
   and tests.
2. Recompute affected areas and required lanes from the actual diff. Report label/Scope mismatch but never omit a
   lane because an area label is absent.
3. Cite by default. For each required lane run `uv run python -m scripts.testing.lane_record --check <lane>`
   first: on exit 0 report `REUSED` with the printed record line and do not run the lane; on a non-zero exit run
   the lane (focused `make verify-backend` and/or `make verify-frontend` as applicable) and report `RERAN`
   with the returned reason. Rerunning a citable lane is allowed with a one-line reason
   ([lane evidence](../_shared/lane-evidence.md)).
   Inspect schema, security/HITL, secrets, API compatibility,
   test markers, frontend flow, and AI/eval evidence by risk.
4. Give every finding severity (`Must Fix` / `Should Fix`), scope (acceptance unmet, diff regression, or separate
   Issue), origin (implementation/design), and `Smallest correction` under the shared review rubric
   (reference repair, meaning-preserving edit, settled-decision reflection, or unresolved/changed decision).
   A separate-Issue candidate is non-blocking; a
   `Should Fix` alone is non-blocking. Include path/line, impact, and reproducible evidence.
   Inspect implement's design diff and its post-commit block synchronization; repair an unambiguous
   body-only omission under the shared contract, without reopening design review.
5. Select one mixed-finding verdict: unsafe provenance is `ABORT`; existing-decision change/deletion is `BACK`;
   consequential additions reflecting settled decisions are `BACK_DESIGN_FIX`; other Must Fix findings are `RETRY`; otherwise
   `PASS`. Preserve implementation findings when routing upstream.
6. Before emitting `BACK` or `BACK_DESIGN_FIX`, fetch the complete Issue comment JSON and pipe it to
   `uv run python -m scripts.kaji.count_review_design_reentries --candidate-status <BACK|BACK_DESIGN_FIX>`.
   This counts exact first-line `review-code BACK` and `review-code BACK_DESIGN_FIX` markers across all old runs,
   including duplicate comments. With N=2, if existing count `c` makes `c + 1 >= 2`, do not emit another design
   re-entry; emit `ABORT` and request a human decision. Invalid provider JSON/counting also becomes `ABORT`.

   ```bash
   uv run kaji issue view <issue_id> --json comments \
     | uv run python -m scripts.kaji.count_review_design_reentries \
       --candidate-status <BACK|BACK_DESIGN_FIX>
   ```

New findings are allowed. This is the full independent implementation review.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `implement` | `PASS` | `--producer-step implement --allow-status implement=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step review-code --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May cite lane records, run read-only/focused checks, and post findings.
- May repair only unambiguous body-only design references under the shared contract.
- Must not edit reviewed files, labels, or lifecycle state.

## Evidence

- Reviewed SHA/diff, acceptance trace, type/area/lane recomputation, per-lane `REUSED` / `RERAN` lines with
  independent commands/results, findings, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | No blocking code, test, docs, security, or evidence finding remains. |
| RETRY | Numbered implementation defects can be corrected by `fix-code`. |
| BACK_DESIGN_FIX | A blocking finding needs consequential additions reflecting settled decisions and independent design review in `fix-design`. |
| BACK | A blocking finding requires an existing design decision to change or be deleted. |
| ABORT | The state is unsafe, unauthorized, or cannot be independently verified. |

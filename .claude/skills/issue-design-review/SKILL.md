---
name: issue-design-review
description: "Independently review design sources, decisions, scope, and verification before implementation."
---

# Review implementation design

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `review-design`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Existing design fixes need verification. Use `issue-design-verify`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `review-design` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context and `design_path`.
- Issue/labels, readiness evidence, design, primary sources, and base diff.

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

- Resolve `design_path` with `scripts.kaji.resolve_design_path`. Require the exact committed canonical design
  and matching type rubric.
- Verify decision provenance under the critical-decision contract. New findings are allowed.

## Procedure

1. Gate on the canonical design commit `DESIGN_SHA=$(git -C <worktree> log -1 --format=%H -- <design-path>)`
   and accessible primary sources; missing required citations are blocking.
2. Recompute type/area/Scope/path consistency, reporting the canonical label correction the settled Scope
   requires, then interfaces, compatibility, failure/safety, slices, docs, precheck needs, acceptance criteria,
   and verification lanes against current code.
3. Classify findings as Must Fix or non-blocking. A correctable design defect is `RETRY`; a true one-way decision
   filled without human provenance is `ABORT`, not an AI fix loop.
4. Post numbered findings and source evidence using `--verdict-step review-design`.

New findings are allowed. This is the full independent design review.

Canonical labels follow the settled Scope: exactly one `type:*` and, for a dev Issue, at least one `area:*`.
This phase judges them but never applies them. Report a required `area:*` or non-docs `type:*` correction as a
numbered finding and `RETRY` so `issue-design-fix` applies it; the lanes are then recomputed from the design and
actual diff. A change between `type:docs` and a dev type is `ABORT` for a manual restart of the correct family;
never edit Kaji state or restart another family automatically.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `design` | `PASS` | `--producer-step design --allow-status design=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step review-design --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May post design findings and verdict evidence.
- Must not edit the design, implementation, or labels. Canonical label correction belongs to design create/fix.
- Must not run any recorded quality lane:
  `make verify-backend`, `make gate-backend`, `make verify-frontend`,
  `make verify-docs`, `make check-all`, `make test-on-schema-change`,
  `make test-e2e`, `make test-llm`, `make evals`.
  The design loop selects lanes and writes them into the design; implementation and the fix phases produce
  the records under [lane evidence](../_shared/lane-evidence.md).

## Evidence

- Design/SHA, primary sources, rubric and lane recomputation, the required label correction with its family
  decision, decision classification, findings, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | No blocking design finding remains. |
| RETRY | Numbered design or canonical label corrections can resolve the findings. |
| ABORT | A one-way decision, a docs/dev family boundary change, or an unsafe/unverifiable premise requires a human. |

---
name: issue-implementation-execute
description: "Implement the reviewed design with type-specific tests, focused checks, documentation, and durable
evidence."
---

# Implement approved design

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `implement`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `implement` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step/worktree/design context.
- Approved design, latest design PASS, and explicit `implement-precheck` verdict.

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

- Resolve `uv run kaji issue resolve-verdict <issue_id> --step implement-precheck`; fallback to its durable report
  only if unambiguous.
- Inspect worktree changes and read `../_shared/implementation-by-type/<type>.md` plus relevant backend/frontend
  references.
- Resolve `design_path` through `scripts.kaji.resolve_design_path` and require type/area/Scope/canonical design
  consistency; area never suppresses a required lane. `issue-implementation-precheck` already gated the managed
  design block, so this step reads the canonical design commit without repeating that check.

## Procedure

For observation-purpose evals, apply the `OBSERVED` branch in
[lane evidence](../_shared/lane-evidence.md) before the success-record rerun rules below.
Preserve failed results and report handoff evidence/candidates to final-check within this phase's scope.
Required quality thresholds, provider/safety failures and confirmed regressions still block.

Apply the [review rubric](../_shared/review-rubric.md) before routing any finding.

1. Translate each acceptance criterion and safety decision into code/tests/docs tasks; preserve unrelated changes.
2. Establish the failing signal or baseline first: regression for bug, invariants for refactor, repeated baseline
   for perf, threat/negative tests for security, and production non-change for test/chore.
3. Implement the smallest complete approved slice, then refactor without weakening tests or contracts. Update
   canonical docs with behavior/config/interface changes. Apply the shared review rubric before `BACK`:
   repair references and meaning-preserving design text locally; cite existing Issue decisions before
   declaring a gap. Consequential design reflection uses bounded `BACK` with required review, not a new
   human choice about an already settled direction.
4. Reconcile acceptance criteria, inspect the complete diff, stage only named owned paths, and commit. Lanes run
   after that commit on a clean HEAD: a dirty or uncommitted run publishes no record, so the later phases would
   have nothing to cite ([lane evidence](../_shared/lane-evidence.md)). If canonical `designs/` content or
   path changed within the rubric boundary, resolve its post-commit SHA, synchronize the managed block
   under the shared reference-repair contract, re-read and report it. Review-code verifies this change.
5. On that clean commit run `make verify-backend` and/or `make verify-frontend` by actual diff. Add schema, `make
   test-e2e`, `make test-llm`, or `make evals` exactly when the matrix requires them.
   Mandatory provider failure is not success. Final `make check-all` belongs to final-check.
6. Post the implementation report with commands, artifacts, selected/skipped lane reasons, published record paths,
   and SHA.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `final-check` | `BACK_IMPLEMENT` | `--producer-step final-check --allow-status final-check=BACK_IMPLEMENT` |
| `implement` | `RETRY` | `--producer-step implement --allow-status implement=RETRY` |
| `implement-precheck` | `PASS` | `--producer-step implement-precheck --allow-status implement-precheck=PASS` |

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
`uv run kaji issue comment <issue_id> --commit --verdict-step implement --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May edit/commit approved code, tests, migration, and docs paths, including canonical `designs/` lint,
  typo, wording and path fixes that preserve meaning, or rubric-local clarifications; synchronize the
  managed block after commit and post the implementation report.
- Must not expand product decisions, modify labels, run broad staging, push, or create/merge a PR.
- Must not `--amend` or rebase a commit whose lane records exist. Records are keyed by commit SHA, so rewriting
  the commit orphans them and forces every later phase to rerun.

## Evidence

- Precheck marker, acceptance map, diff paths, commands/exits, conditional lane rationale/artifacts, published
  lane record paths, commit SHA, and report URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Approved implementation, tests, docs, focused lanes, commit, and report are complete. |
| RETRY | A locally correctable implementation/check/report failure remains. |
| BACK | Consequential design reflection or an authorized decision change requires bounded design correction and review after checking existing decisions. |
| ABORT | Unsafe state, missing authority, or mandatory evidence/provider prevents progress. |

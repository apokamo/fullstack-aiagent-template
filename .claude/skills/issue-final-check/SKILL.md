---
name: issue-final-check
description: "Reconcile all development evidence, run final local gates, and route defects by root cause before PR
creation."
---

# Final development gate

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `final-check`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `final-check` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step/worktree/design context.
- All phase verdict reports, Issue criteria, labels, approved design, complete diff, and current SHA.

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

- Require implementation review PASS or verify-code PASS for the current implementation.
- On a fix/verify path, require the current verify PASS marker, not recovery of the preceding review RETRY marker;
  that RETRY was already consumed by fix/verify and is not a final success gate. Apply the same rule to a current
  `verify-design` PASS and its preceding `review-design` RETRY.
- Resolve every required producer marker; missing phase evidence is not inferred from GitHub status.
- Resolve `design_path` with `scripts.kaji.resolve_design_path`; require its commit and the managed
  `<!-- kaji-design:start -->` block's `blob/<design-sha>/<design-path>` permalink to name the same full design
  SHA after any reference repair under the shared workflow contract.
- Read completion criteria, verification matrix, LLM/eval policy, and type rubric.

## Procedure

Apply the [review rubric](../_shared/review-rubric.md) before routing any finding.

1. Build an evidence ledger from readiness, design, precheck, implementation, review/fix/verify reports. Map every
   workflow-verifiable Issue criterion to concrete evidence.
2. Reconcile canonical type/area, design Scope/expected paths, and `git diff origin/main...HEAD`. The diff decides
   lanes; label mismatch never suppresses a check.
3. Apply the purpose-based LLM contract before lane checks: map each eval threshold to acceptance or
   observation. For observation evals first reconcile exact-HEAD latest artifacts under lane-evidence;
   report valid completed measurements as `OBSERVED`, preserving FAIL and actual exit. No success record
   is required for this measurement evidence. Otherwise use the check-first execution rules below.
   Run `uv run python -m scripts.testing.lane_record --check check-all` first. On exit 0 report `REUSED` with
   the printed exact clean-HEAD record and do not rerun it. On non-zero, record the reason, run `make check-all`
   at the exact SHA, and report `RERAN`. For each conditional lane selected by the actual change, apply the same
   check-first rule; otherwise run `make test-e2e`, `make test-llm`, and/or `make evals` with
   provider/model/dataset/scorer/repeats/artifact evidence and report `RERAN` with the returned reason
   ([lane evidence](../_shared/lane-evidence.md)). Do not add a separate pre-commit invocation.
4. Inspect secrets/generated artifacts and tree status. Apply the shared review rubric and current user
   decisions before classifying failures as final-local, design-rooted, implementation-rooted, or unsafe/external.
5. Before PASS, create/reuse and verify observation-only quality follow-ups under the canonical
   [LLM follow-up contract](../../../docs/dev/llm-evals.md#観測項目の未達を引き継ぐ)
   (stable key, run marker, parent link, sanitized evidence). This requires
   invocation provider-write authority. Provider/authority failure or ambiguous targets is ABORT;
   recover partial publication by searching before creating again. Required threshold failures and
   confirmed regressions stay in the current Issue. Record nonblocking grounds and links in the ledger.
6. Repair an unambiguous stale/missing managed block here under the shared reference-repair contract;
   re-read it and continue on the same HEAD using valid lane records. Body-only repair requires no
   design/implement/review-code/fix-code re-entry. Unreviewed semantic changes use bounded `BACK_DESIGN`;
   meaning-preserving tracked text/path repairs use `BACK_IMPLEMENT`; uncertain source/approval is `ABORT`.
   Update only evidence-backed checkboxes, leave
   post-workflow/external criteria unchecked, and post the final ledger.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `design` | `PASS` | `--producer-step design --allow-status design=PASS` |
| `final-check` | `RETRY` | `--producer-step final-check --allow-status final-check=RETRY` |
| `fix-code` | `PASS` | `--producer-step fix-code --allow-status fix-code=PASS` |
| `fix-design` | `PASS` | `--producer-step fix-design --allow-status fix-design=PASS` |
| `fix-ready` | `PASS` | `--producer-step fix-ready --allow-status fix-ready=PASS` |
| `implement` | `PASS` | `--producer-step implement --allow-status implement=PASS` |
| `implement-precheck` | `PASS` | `--producer-step implement-precheck --allow-status implement-precheck=PASS` |
| `review-code` | `PASS` | `--producer-step review-code --allow-status review-code=PASS` |
| `review-design` | `PASS` | `--producer-step review-design --allow-status review-design=PASS` |
| `review-ready` | `PASS` | `--producer-step review-ready --allow-status review-ready=PASS` |
| `start` | `PASS` | `--producer-step start --allow-status start=PASS` |
| `verify-code` | `PASS` | `--producer-step verify-code --allow-status verify-code=PASS` |
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
`uv run kaji issue comment <issue_id> --commit --verdict-step final-check --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May create/reuse observation-quality investigation Issues and update their evidence/parent links with
  invocation authority under the canonical LLM contract; no unrelated Issue or lifecycle mutations.
- May synchronize the managed design block under the shared reference-repair contract.
- May run final gates, cite conditional lane records, update evidence-backed Issue body fields, and post the
  final report.
- Must not edit product code during review, publish/merge a PR, change labels, or mark external criteria complete.

## Evidence

- Producer markers, criterion ledger, type/area/Scope/diff map, exact SHA, canonical design/permalink revision,
  commands/exits, per-lane `REUSED` / `RERAN` lines, conditional artifacts, tree status, body update, and report
  URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Every required criterion and purpose-specific lane obligation is satisfied at the recorded SHA; observation FAIL remains FAIL with completed handoff and durable evidence. |
| RETRY | Only final-check-local reporting/body or rerunnable transient correction remains. |
| BACK_DESIGN | The root cause is a missing/incorrect design decision or lane. |
| BACK_IMPLEMENT | The root cause requires implementation/test/docs changes, including meaning-preserving tracked design text/path repairs. |
| ABORT | Authority, provider, secrets, or repository state prevents safe completion. |

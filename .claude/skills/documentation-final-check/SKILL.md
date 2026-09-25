---
name: documentation-final-check
description: "Reconcile documentation workflow evidence and completion criteria before PR publication."
---

# Final documentation gate

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `docs` workflow at `final-check`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `final-check` in the `docs` workflow. `.kaji/wf/custom/docs/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/worktree context.
- Issue criteria, all docs phase reports, complete diff, and current SHA.

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

Worktree mode: `issue-worktree`.

- Require `doc-review` or `doc-verify` PASS and a docs-only understood diff.
- On a fix/verify path, require the current `doc-verify` PASS marker, not recovery of the preceding `doc-review`
  RETRY marker; that RETRY was already consumed by fix/verify and is not a final success gate.
- Externally verifiable post-workflow criteria remain unchecked.

## Procedure

1. Aggregate phase markers and map each completion criterion to durable evidence.
2. Confirm the diff is docs-only and canonical references, commands, and navigation remain consistent.
3. Run `make verify-docs` and record the exact SHA.
4. Update only evidence-backed Issue checkboxes and post the `final-check` report.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `doc-fix` | `PASS` | `--producer-step doc-fix --allow-status doc-fix=PASS` |
| `doc-review` | `PASS` | `--producer-step doc-review --allow-status doc-review=PASS` |
| `doc-update` | `PASS` | `--producer-step doc-update --allow-status doc-update=PASS` |
| `doc-verify` | `PASS` | `--producer-step doc-verify --allow-status doc-verify=PASS` |
| `final-check` | `RETRY` | `--producer-step final-check --allow-status final-check=RETRY` |
| `fix-ready` | `PASS` | `--producer-step fix-ready --allow-status fix-ready=PASS` |
| `review-ready` | `PASS` | `--producer-step review-ready --allow-status review-ready=PASS` |
| `start` | `PASS` | `--producer-step start --allow-status start=PASS` |

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

- May update evidence-backed Issue checkboxes and post the final docs report.
- Must not change code, publish/merge a PR, or mark external criteria complete.

## Evidence

- Phase markers, criterion map, diff/SHA, command result, body update, and report URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | All workflow-verifiable criteria and docs checks pass at the recorded SHA. |
| RETRY | Only final-report or checkbox reconciliation needs correction. |
| BACK | The documentation update itself must change. |
| ABORT | The Issue cannot be completed safely as docs-only. |

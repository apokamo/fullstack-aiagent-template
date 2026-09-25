---
name: documentation-update
description: "Execute a documentation-only Issue against canonical repository sources and report reproducible evidence."
---

# Update documentation

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `docs` workflow at `doc-update`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Another phase applies, the request is general, or required Issue context is absent. Use 通常の会話 and make no change. |

**ワークフロー内の位置**: `doc-update` in the `docs` workflow. `.kaji/wf/custom/docs/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected `issue_id`, `step_id`, `worktree_dir`; manual Issue ID is fallback.
- Issue body/comments, latest docs update context, and `design_path` only when a design artifact actually exists.

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

- Require `type:docs`; area labels are optional.
- Resolve the worktree and inspect `git status --short` and `git diff origin/main...HEAD`.
- Read `docs/dev/docs-workflow.md` and the implementation, CLI, workflow, or policy that is the source of each claim.

## Procedure

1. Classify the requested content and select the canonical document; replace duplicated policy with links.
2. Confirm commands and paths from source. If the truth needs a code/config/test change, stop with `ABORT`.
3. Edit only documentation and documentation-owned workflow/skill text in scope; preserve unrelated changes.
4. Run `make verify-docs` from the absolute worktree. A pre-existing unrelated failure is reported under the shared
   rule, not silently fixed.
5. Stage only named owned paths, commit, and post a `doc-update` verdict report with changed paths, command result,
   and SHA.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `final-check` | `BACK` | `--producer-step final-check --allow-status final-check=BACK` |
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
`uv run kaji issue comment <issue_id> --commit --verdict-step doc-update --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May edit and commit documentation-owned paths and post the phase report.
- Must not modify product behavior, labels, PRs, Issue lifecycle, or unrelated files.

## Evidence

- Canonical sources consulted, changed paths, `make verify-docs` exit state, commit SHA, and report URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Docs are current, docs-only, committed, reported, and the required check passed. |
| ABORT | The requested truth is unavailable, unsafe, or requires non-documentation changes. |

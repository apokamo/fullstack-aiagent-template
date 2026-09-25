---
name: issue-design-fix
description: "Resolve current design review findings in the design artifact with explicit provenance."
---

# Fix design findings

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `fix-design`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | A new design or independent review is needed. Use `issue-design-create` or `issue-design-review`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `fix-design` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- For a cycle step, use injected `cycle_count` and `max_iterations`.
- Use injected `previous_verdict` only when a resume transition supplies it.
- Phase-specific inputs:

- Injected Issue/cycle/worktree context and `design_path`.
- Current review or verification findings and the previous fix report, when present.

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

- Read the supplied `previous_verdict` and the Issue's review, verification, and fix reports to identify
  the requested design correction. On a verification retry, use the remaining findings from that verification.
- Resolve the injected path with `scripts.kaji.resolve_design_path`; read the canonical design, type rubric,
  primary sources, and design diff.

## Procedure

1. Identify the findings being addressed from the latest current request and reports: `review-design RETRY`,
   `verify-design RETRY`, or `review-code BACK_DESIGN_FIX`. Create a finding-by-finding disposition and identify
   any requested human decision. On a retry, keep resolved findings closed and address the remaining findings.
   Existing `source_step` metadata is optional; its absence or value is not a reason to stop. If the reports
   genuinely do not identify the requested correction, return `ABORT` and explain what information is missing.
2. Apply the shared review rubric to every return source: update only the current findings and necessary
   consequences, preserving implementation, resolved findings and valid evidence. Reflect settled decisions
   without requesting the same choice again. Update the affected design sources, provenance, type/area/Scope,
   safety, lanes, and criteria, and apply
   any canonical label correction it requires; do not close a finding only in a comment.
3. Inspect the design diff, stage only the resolved canonical design, and commit. If re-entered after a provider
   failure, reuse the commit containing the exact design instead of creating an empty commit.
4. Point the Issue at that commit. Resolve `DESIGN_SHA=$(git -C <worktree> log -1 --format=%H --
   <canonical-design-path>)`, read the body into a `mktemp` file with `uv run kaji issue view <issue_id> --json
   body --jq .body`, replace the single `<!-- kaji-design:start -->` / `<!-- kaji-design:end -->` pair (append the
   block when the markers are absent) with the canonical path, that full SHA, its `blob/<sha>/<path>` permalink,
   and a summary of at most 20 lines, then write it back with `uv run kaji issue edit <issue_id> --body-file`.
   Unbalanced, duplicated, or inverted markers are `ABORT`. Never mirror the design contents. Re-read the body and
   require the permalink for that SHA before posting the `fix-design` resolution table with SHA and the
   review or verification report it addresses.

Canonical labels follow the settled Scope: keep exactly one `type:*` and, for a dev Issue, at least one
`area:*`. This phase applies the correction `issue-design-review` reported, and `issue-design-create` applies
its own. An `area:*` change continues this workflow and recomputes verification lanes from the design and actual
diff. A `type:*` change between non-docs types continues this dev workflow. A change between `type:docs` and a
dev type is `ABORT` for a manual restart of the correct family; never edit Kaji state or restart another family
automatically.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `review-code` | `BACK_DESIGN_FIX` | `--producer-step review-code --allow-status review-code=BACK_DESIGN_FIX` |
| `review-design` | `RETRY` | `--producer-step review-design --allow-status review-design=RETRY` |
| `verify-design` | `RETRY` | `--producer-step verify-design --allow-status verify-design=RETRY` |

Append exactly one row's arguments to this command:

```bash
uv run python -m scripts.kaji.resolve_verdict_artifact \
  --issue-id <issue_id> --current-verdict-path <verdict_path> \
  <single-producer-helper-arguments>
```

Exit 5 (malformed), provider failure, no match, or ambiguity is `ABORT`; do not infer status from prose.
On one match, post the exact producer's canonical marker and recovery report with:

```bash
uv run kaji issue comment <issue_id> --commit \
  --verdict-step <returned-step> --verdict-status <returned-status> \
  --verdict-meta recovered_from=<producer_run>/<returned-step>/attempt-NNN \
  --body-file <recovery-report>
```

Include the returned artifact paths in the recovery report, then rerun `resolve-verdict` for the same producer.
Continue only when it returns the same status.

As the final Procedure action after every external side effect, publish the report and canonical marker with
`uv run kaji issue comment <issue_id> --commit --verdict-step fix-design --verdict-status <STATUS>
--body-file <report>`, using only a status in this skill's Verdict table.
Keep the marker, report, stdout block, and YAML status identical.
A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May update/commit the canonical design, update its managed Issue design block, add or remove canonical `type:*` /
  `area:*` labels, and post the fix report.
- Must not implement code, apply non-canonical labels, use a label change to widen Scope, or invent one-way
  decisions.
- Must not run any recorded quality lane:
  `make verify-backend`, `make gate-backend`, `make verify-frontend`,
  `make verify-docs`, `make check-all`, `make test-on-schema-change`,
  `make test-e2e`, `make test-llm`, `make evals`.
  The design loop selects lanes and writes them into the design; implementation and the fix phases produce
  the records under [lane evidence](../_shared/lane-evidence.md).

## Evidence

- Producer marker, finding table, primary sources, design diff, applied label changes with the resulting family
  decision, commit SHA, managed block permalink, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | Every review finding is resolved in the design or answered with valid evidence. |
| ABORT | The requested correction cannot be identified, the Scope crosses the docs/dev family boundary, or a human-owned decision is required. |

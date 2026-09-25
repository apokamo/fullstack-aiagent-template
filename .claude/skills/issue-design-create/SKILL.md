---
name: issue-design-create
description: "Create a decision-complete, type-specific implementation design and deterministic handoff."
---

# Create implementation design

Read [the shared workflow contract](../_shared/workflow-contract.md) before this phase.

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Kaji explicitly dispatches the `dev` workflow at `design`, or a human runs this exact phase with a valid Issue ID. |
| ❌ | Current review findings require a correction. Use `issue-design-fix`; otherwise use 通常の会話 and make no change. |

**ワークフロー内の位置**: `design` in the `dev` workflow. `.kaji/wf/custom/dev/*.yaml` is authoritative for transitions.

## 入力

### ハーネス経由（コンテキスト変数）

- Always-injected values are `issue_id`, `issue_ref`, `step_id`, `issue_input`, `branch_prefix`, `branch_name`,
  `worktree_dir`, `design_path`, `provider_type`, `default_branch`, `git_remote`, and `verdict_path`.
- This phase has no phase-specific conditional variables.
- Phase-specific inputs:

- Injected Issue/step/worktree context and `design_path`; manual Issue ID is fallback.
- Issue body/comments/labels, readiness PASS, and any current-run design return marker.

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

- Resolve the worktree and require one canonical dev type plus area labels.
- Read `../_shared/design-by-type/<type>.md`, verification matrix, relevant backend/frontend references, and
  critical decisions.
- If re-entered from implementation/final review, resolve the current run source step/status and marker; never
  reuse an older cycle.

## Procedure

1. Run `uv run python -m scripts.kaji.resolve_design_path "$design_path" --issue-id "$issue_id"`; require the
   returned `designs/issues/` path inside the resolved worktree and inspect its existing Git/Issue history.
2. Gather primary repository sources and decisions/constraints in explicitly referenced related Issues.
   Apply current user decisions before reporting a gap; missing reflection is not missing authority.
   If an important source is inaccessible or conflicts remain unresolved, report the concrete missing evidence.
3. Write outcome/non-goals, Scope, evidence, interfaces/data flow, failure/safety, slices, docs impact,
   type-specific plan, verification lanes, acceptance criteria, and decision provenance. Reconcile
   type/area/Scope/expected paths; area never suppresses a lane. Apply any canonical label correction the
   settled Scope requires.
4. For bug/refactor/perf and other applicable types, specify implementation precheck baseline and safety-net
   commands. For frontend flow, schema, AI wiring, prompt/tool/HITL, or provider changes, select the required
   conditional lanes.
5. Reconcile the current return finding from any source (`implement`, `implement-precheck`, `review-code`,
   or `final-check`) under the shared review rubric. Change only that finding and necessary consequences;
   preserve existing implementation, resolved findings and valid evidence. A canonical path repair does
   not authorize unrelated redesign. If existing content already satisfies the request, repair only the
   reference/report and reuse the design commit. Stage only needed canonical design changes and commit
   when there is a real diff. On re-entry after a provider failure,
   reuse the commit that already contains the exact working design instead of creating an empty commit.
6. Point the Issue at that commit. Resolve `DESIGN_SHA=$(git -C <worktree> log -1 --format=%H --
   <canonical-design-path>)`, read the body into a `mktemp` file with `uv run kaji issue view <issue_id> --json
   body --jq .body`, replace the single `<!-- kaji-design:start -->` / `<!-- kaji-design:end -->` pair (append the
   block when the markers are absent) with the canonical path, that full SHA, its `blob/<sha>/<path>` permalink,
   and a summary of at most 20 lines, then write it back with `uv run kaji issue edit <issue_id> --body-file`.
   Unbalanced, duplicated, or inverted markers are `ABORT`. Never mirror the design contents. Re-read the body and
   require the permalink for that SHA before posting the path, decisions, lanes, SHA, and `design` verdict marker.

Canonical labels follow the settled Scope: keep exactly one `type:*` and, for a dev Issue, at least one
`area:*`. This phase and `issue-design-fix` are the only steps that apply them. An `area:*` change continues
this workflow and recomputes verification lanes from the design and actual diff. A `type:*` change between
non-docs types continues this dev workflow. A change between `type:docs` and a dev type is `ABORT` for a manual
restart of the correct family; never edit Kaji state or restart another family automatically.

Before consuming a required Issue verdict listed below, run `uv run kaji issue resolve-verdict
<issue_id> --step <producer-step>` for that exact producer. Only exit 4 (`not found`) may use artifact recovery.
Use exactly one producer per helper call: select only the row for the producer whose lookup returned exit 4, and
never combine rows. Rows list eligible sources; they do not make an optional phase mandatory when that phase did not run.

| Producer | Allowed status | Single-producer helper arguments |
|---|---|---|
| `final-check` | `BACK_DESIGN` | `--producer-step final-check --allow-status final-check=BACK_DESIGN` |
| `implement` | `BACK` | `--producer-step implement --allow-status implement=BACK` |
| `implement-precheck` | `BACK_DESIGN` | `--producer-step implement-precheck --allow-status implement-precheck=BACK_DESIGN` |
| `review-code` | `BACK` | `--producer-step review-code --allow-status review-code=BACK` |
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
`uv run kaji issue comment <issue_id> --commit --verdict-step design --verdict-status <STATUS> --body-file
<report>`, using only a status in this skill's Verdict table. Keep the marker, report, stdout block, and YAML
status identical. A provider failure must replace the requested status with sanitized `ABORT`; try its marker,
then print the same `ABORT` to stdout and atomically write `verdict.yaml` even when the provider remains down.

## Side effects

- May create/update and commit the resolved canonical design, update its managed Issue design block, add or
  remove canonical `type:*` / `area:*` labels, and post its report.
- Must not implement product code, choose one-way policy, apply non-canonical labels, or use a label change to
  justify out-of-Scope work.
- Must not run any recorded quality lane:
  `make verify-backend`, `make gate-backend`, `make verify-frontend`,
  `make verify-docs`, `make check-all`, `make test-on-schema-change`,
  `make test-e2e`, `make test-llm`, `make evals`.
  The design loop selects lanes and writes them into the design; implementation and the fix phases produce
  the records under [lane evidence](../_shared/lane-evidence.md).

## Evidence

- Primary sources, label/scope map, applied label changes with the resulting family decision, decision provenance,
  selected lanes, canonical design path, commit SHA, managed block permalink, and comment URL.

## Verdict

| Status | Condition |
|---|---|
| PASS | The design is executable, provenance-complete, type-specific, and safely testable. |
| ABORT | A one-way decision/source/precondition is unresolved, the Scope crosses the docs/dev family boundary, or design cannot be safely produced. |

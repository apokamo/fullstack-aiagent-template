# Workflow contract

Read this file for every Kaji skill.

## Inputs and repository

- Use injected `issue_id`, `issue_ref`, `step_id`, `issue_input`,
  `branch_prefix`, `branch_name`, `worktree_dir`, `design_path`,
  `provider_type`, `default_branch`, `git_remote`, and `verdict_path` when
  supplied. Cycle, resume, and PR values are conditional. Manual arguments are
  fallback only; never invent a missing required value.
- Outside an active harness, the 第1 (first) manual argument (`$ARGUMENTS =
  <issue_id>`) is the only Issue ID fallback. Resolve remaining values through
  `kaji issue context`, the Issue NOTE, and `git worktree list --porcelain`.
  Missing/invalid/non-applicable manual input is a mutation-free handoff to the
  alternative named in `## いつ使うか`. The same mismatch with an injected
  `verdict_path` is a workflow-contract failure and must terminate as ABORT in
  stdout and `verdict.yaml`.
- Repository is the effective `[provider.github].repo`: the ignored
  `.kaji/config.local.toml` overlays the tracked `.kaji/config.toml`, whose
  `<owner>/<repo>` placeholder never names a real repository. Configured
  defaults are remote `origin` and base `main`.
- In manual use, resolve repository values with `uv run kaji issue context <issue_id>`,
  the Issue NOTE and `git worktree list --porcelain`; never guess a worktree.
  Never invent `verdict_path`, cycle values, or `previous_verdict`. Without an
  injected verdict path, publish only the Issue marker and stdout fallback.
- Read [the development workflow](../../../docs/dev/development-workflow.md),
  [Issue labels](../../../docs/dev/issue-labels.md), and phase references before
  mutation.
- Resolve the applicable mode with [worktree.md](worktree.md).

## Decisions, evidence, and handoff

- Apply [critical decisions](critical-decisions.md). Unresolved one-way doors
  are `ABORT`, not AI-authored fixes.
- Preserve user changes. Stage only phase-owned paths; never use broad
  `git add .` or `git add -A`.
- Provider writes use `uv run kaji issue|pr`. Never expose credentials,
  secrets, private model responses, or unsanitized incident evidence.
- Record commands, exit states, relevant results, commit SHA, artifacts, and
  report/comment location. Follow [verdict.md](verdict.md) and write the
  completion verdict last.
- Report unrelated findings through [unrelated-issues.md](unrelated-issues.md).
- Review phases apply the shared [review rubric](review-rubric.md); verification phases remain limited to their
  documented findings and, for PR/small-change verification, fix regressions.
- Standard dev design phases and consumers that use a design read
  [design evidence](design-evidence.md) when needed. Dev-small uses Issue decisions
  and implementation/review reports; it requires no design artifact or precheck.

## Labels and verification

- Normal Issues have exactly one canonical `type:*`. Development Issues have
  at least one canonical `area:*`; docs Issues may omit area.
- Area labels are scope hints only. Issue decisions (and the approved design when applicable) plus actual diff decide
  required lanes through [verification-matrix.md](verification-matrix.md).
- A mandatory provider or test failure is never a passing skip.
- Citing a lane record is not a skip. Check first, then run only what is not
  citable, and report each lane as `REUSED` or `RERAN` under
  [lane evidence](lane-evidence.md).

Design create/fix may add or remove canonical `type:*` / `area:*` labels to
match the settled Scope. `issue-design-review` judges labels but never applies
them; it reports the correction and returns `RETRY` so `issue-design-fix` owns
the mutation. Nothing else changes labels, and a label change never justifies
out-of-Scope diff; return to design or implementation instead.

| Label change | Handling |
|---|---|
| `area:*` added or removed | Continue the same workflow and recompute verification lanes from the design and actual diff. |
| `type:*` changed between non-docs types | Continue the same dev workflow. |
| `type:docs` changed to or from a dev type | `ABORT`. Re-confirm the existing worktree identity and current base, then restart the correct family manually. |

Never edit active Kaji state, emit a `RECLASSIFY` status, archive state, or
restart another family automatically.

## Side-effect boundary

Dev-small `change` / `fix-change` own implementation and commits;
`review-change` / `verify-change` own independent review and final reconciliation,
including verified acceptance checkboxes and required lanes, without tracked edits.

Only the current phase may perform its documented mutations. Do not merge a PR,
close an Issue, change labels, create/delete a worktree, delete a branch, or
fast-forward the main checkout unless that exact side effect is owned by the
step. `issue-worktree-create` owns worktree/branch creation and `issue-close`
owns every terminal side effect: merge, post-workflow follow-up handoff, worktree/branch
cleanup, main synchronization, and Issue closure. Incident steps propose and
record; they do not change application code, labels, or lifecycle state.

## Purpose-based LLM acceptance

For changes requiring LLM/eval lanes, apply the [canonical LLM contract](../../../docs/dev/llm-evals.md#変更目的とissueの完了条件).
Readiness checks explicit requirements; design records per-metric acceptance versus observation and
review-design confirms it. Implementation, review, fix and verify preserve that contract within their
existing scope. The final confirmation owner (standard final-check or small-change review)
reconciles the entire diff and ensures observation follow-ups before PASS;
PR and close carry their links. No phase silently upgrades observation to quality acceptance or
waives a required threshold after seeing failure. Follow-up creation does not cure an acceptance
failure or confirmed regression. Failed observations can satisfy measurement obligations under the
artifact checks in that contract; their eval result remains FAIL, separately from workflow PASS.

After final approval, a new observation shortfall or changed acceptance basis requires renewed final
reconciliation before publication/completion. A downstream phase without that handoff authority
uses its existing ABORT route with the missing reconciliation; it does not silently publish or
create a new transition. Existing verified observation links remain reusable.

## Completion

Read [verdict output](verdict.md) for producer resolution and the final completion
action. Use the actual `step_id`; compact skills inherit this action rather than
copying its command. Workflow/Issue mismatch with an active verdict path is ABORT;
without a valid manual Issue or applicability, make no changes and use ordinary conversation.

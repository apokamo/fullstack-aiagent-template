---
name: grill-me
description: "Human-invoked front-load interview that walks the critical-decision tree one question at a time with a recommended answer, then fixes the resulting decisions into the Issue body and a provenance comment before any workflow step runs."
disable-model-invocation: true
---

# Grill Me

Front-load interview for a freshly filed Issue, run before any Kaji workflow starts. Walk the
critical-decision tree relentlessly, extract every choice only a human can make, and fix the result into the
Issue body `## 決定事項` section plus a provenance comment. The later phases then read settled decisions
instead of stopping at an unresolved one-way door.

This skill is not a workflow step. It produces no verdict, writes no `verdict_path`, and is invoked by a
human as `/grill-me [issue_id]`. Its source of questions is
[critical decisions](../_shared/critical-decisions.md); its consumer is `issue-readiness-review`.

> Source: adapted from the `grill-me` / `grilling` skills by Matt Pocock
> ([mattpocock/skills](https://github.com/mattpocock/skills), MIT License), compared against the
> upstream implementation. This is an independent implementation that keeps
> the same five disciplines, not a verbatim copy. The correspondence table is at the end of this file.

## When to use

| Situation | This skill |
|---|---|
| Human-filed Issue, before the workflow starts, that can contain a category 3 one-way door | Invoke explicitly |
| Minor Issue where category 3 is unlikely: typo, link fix, wording clarification, formatting | Skip with a one-line reason |
| Inside a workflow step, unattended | Never |

```text
file Issue → grill-me (optional, explicit) → issue-readiness-review → issue-worktree-create → …
```

## Human-invoked only

Frontmatter sets `disable-model-invocation: true`, which is what actually keeps the skill out of automatic
selection: only a human running `/grill-me` can start it, so an ordinary planning conversation cannot reach
the Issue-body and comment mutations below. Prose alone does not enforce that boundary, so the flag is
required, and `scripts/docs/check_kaji_skills.py` fails the audit when a human-invoked skill omits it. Never
self-invoke this skill either.

Keeping it out of `.kaji/wf/custom/**/*.yaml` keeps synchronous dialogue out of unattended runs. Unattended
steps must not settle category 3 decisions on their own; this skill settles them beforehand, with a human, so
the workflow that follows can run unattended.

## Five disciplines

Do not thin these to fit repository convenience.

1. **Cover every aspect relentlessly.** Keep asking until shared understanding is reached; skip no material
   decision.
2. **Walk each branch of the decision tree.** Resolve dependencies one at a time and in order, because an
   upstream decision changes the downstream questions.
3. **One question at a time.** Ask, wait for the answer, then ask the next. Batching questions is forbidden.
4. **Answer from the repository whatever the repository can answer.** Facts available in code, `docs/`, or
   past Issues/PRs are researched, not asked. Reserve the human's attention for what only a human can decide.
5. **Attach a recommended answer to every question**, with a short reason, so `yes` is a complete reply.

Relentless means no question is skipped, not that the tone is aggressive. Keep each question short, drop
preambles, and work with the human to close unknowns rather than cornering them.

## Ammunition: the critical-decision source

[critical decisions](../_shared/critical-decisions.md) is the source of the questioning angles, reused here as
the decision tree.

- **Fix category 3 one-way doors first**: user value, source-of-truth selection, public API compatibility,
  schema/data migration, authentication/authorization, secret exposure, destructive operations,
  production/provider policy, screen structure, operational impact, and scope boundary.
- **Category 2 two-way-door items may stay open** in the Issue when written as an assumption with its
  rationale and a later review point. Over-grilling them adds rework.
- Type-specific angles follow the per-type minimum requirements in
  [Issue labels](../../../docs/dev/issue-labels.md); area labels are scope hints only.

## Gatekeeper

Grill an Issue that can carry a category 3 one-way door: source-of-truth selection, public API or data
contract change, changed user value or screen structure, operational impact such as scheduling, monitoring, or
deployment, incompatible change, or a vague scope boundary.

Skip an Issue where category 3 is unlikely: typo, link fix, wording clarification, formatting. Say
"minor Issue, grill not required" in one line and hand off.

When in doubt, grill. A missed front-load costs more than a light interview on a small Issue.

## Inputs

- Issue ID supplied by the human; there is no injected Kaji context before the workflow starts.
- Issue body, comments, labels, linked Issues/PRs, `docs/`, and the repository code.
- Repository is the effective `[provider.github].repo` (`.kaji/config.local.toml` overlays `.kaji/config.toml`);
  provider reads and writes use `uv run kaji issue`.

## Procedure

1. **Gate.** Read the Issue and apply the gatekeeper. If minor, state the one-line skip and stop.
2. **Understand the target.** Read the body, comments, related Issues/PRs, and the relevant documentation,
   then explore the code and answer every repository-answerable point yourself (discipline 4). Reduce the
   question list to human-only decisions.
3. **Interview.** Build the decision tree from the critical-decision source, walk each branch, and resolve
   dependencies one at a time (disciplines 1 and 2). Present exactly one question, with a recommended answer
   and a short reason, and wait for the reply before the next (disciplines 3 and 5). Continue until shared
   understanding is reached.
4. **Fix the decisions.** Append or update the Issue body `## 決定事項` section with the human decisions that
   touch category 3, preserving the existing body, then post one provenance comment holding the dialogue
   record, the basis of each decision, and any category 2 assumption with its later review point.

   ```bash
   # 1) Read the current body, append `## 決定事項`, and write it back. This runs in the main checkout
   #    before the Issue worktree exists, so keep the temporary file outside the repository.
   grill_body="$(mktemp "${TMPDIR:-/tmp}/grill-body.XXXXXX")"
   uv run kaji issue view [issue_id] --json body -q '.body' > "$grill_body"
   #    → append the `## 決定事項` section to "$grill_body", then:
   uv run kaji issue edit [issue_id] --body-file "$grill_body"
   rm -f "$grill_body"

   # 2) Record provenance as a separate comment.
   uv run kaji issue comment [issue_id] --body "$(cat <<'EOF'
   ## grill-me provenance

   | 判断 | 決定 | 根拠（人間決定 / 二方向仮定） |
   |---|---|---|
   | … | … | … |
   EOF
   )"
   ```

   Done means the decisions are in the body that `issue-readiness-review` reads, not that a comment exists.
5. **Hand off.** Point the human at the readiness phase, `issue-readiness-review`, as the next action.

## Output targets

| Target | Content | Reason |
|---|---|---|
| Issue body `## 決定事項` | Human decisions covering category 3 one-way doors | `issue-readiness-review` inspects the body; a decision that lives only in a comment is invisible to it |
| Provenance comment | Dialogue record, basis of each decision, why it was chosen, category 2 assumptions | Keeps the trail auditable without inflating the body |

## Side effects

- May append or update the Issue body `## 決定事項` section, preserving all existing content, and post one
  provenance comment.
- Must not create or edit a branch, worktree, or code, change labels, close the Issue, create a PR, run a
  workflow step, or emit a workflow verdict.
- Must not include secrets or private model responses in the body or comment.

## Evidence

- Gate decision, the repository facts resolved without asking, each question with its recommendation and the
  human answer, the resulting `## 決定事項` content, the provenance comment URL, and every category 2
  assumption with its review point.

## Single-layer structure

The original ships a thin `grill-me` entry point over a reusable `grilling` engine so that other skills such
as `grill-with-docs` can share the interview discipline. This repository starts single-layer: this file holds
the discipline and no separate engine file exists.

That is a category 2 two-way-door assumption. Splitting the discipline into `_shared/` or a separate skill is
a cheap Markdown reorganization, and the migration trigger is the moment a second skill needs to share the
interview discipline. Until then, keep one layer and avoid premature abstraction.

## Source and fidelity check

This skill is independently implemented from the MIT-licensed method described by Matt Pocock.
The original `grill-me` is one line, `Run a /grilling session.`, plus `disable-model-invocation: true`; the
discipline lives in `grilling`.

| Original `grilling` (summary) | Discipline | Where it is implemented here |
|---|---|---|
| Relentlessly question every aspect until shared understanding | 1 | Five disciplines §1, Procedure 3 |
| Walk each branch of the design tree, resolving dependencies one at a time | 2 | Five disciplines §2, Procedure 3, Ammunition |
| Attach a recommended answer to each question | 5 | Five disciplines §5, Procedure 3 |
| One question at a time, waiting for the answer | 3 | Five disciplines §3, Procedure 3 |
| Research code-answerable questions instead of asking | 4 | Five disciplines §4, Procedure 2 |
| Two layers: user-invoked `grill-me` starting `grilling` | Structure | Single layer here, keeping `disable-model-invocation: true` |

Adaptations that the original does not have, required by this repository and not a thinning of it: fixing
output into the Issue body `## 決定事項` and a provenance comment, the gatekeeper for minor Issues, using
the repository critical-decision source as ammunition, and keeping the skill out of workflow YAML so
attended and unattended work stay separated.

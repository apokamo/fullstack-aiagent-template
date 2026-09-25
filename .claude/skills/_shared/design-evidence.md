# Design evidence

Read when a phase creates, reviews, modifies, or reconciles an existing design.
Standard dev requires a design; dev-small uses the Issue decisions and reports.
PR publication consumes final approval and does not recheck or repair the design block.

- Kaji injects `draft/design/issue-<id>-<slug>.md` as a legacy compatibility
  value. Resolve it with `uv run python -m scripts.kaji.resolve_design_path
  "$design_path" --issue-id "$issue_id"` and use only the returned
  `designs/issues/...` path. Never write the legacy path or patch site-packages.

- A design commit is the AI/developer source of truth; the Issue body points
  at it with one `<!-- kaji-design:start -->` / `<!-- kaji-design:end -->`
  block containing canonical path, full design SHA, `blob/<sha>/<path>`
  permalink, and a summary of at most 20 lines. Never mirror the full design.
- Design create/fix publish their committed design. Implement and fix-code
  also own synchronization after committing a meaning-preserving design edit
  or a local clarification allowed by [the review rubric](review-rubric.md).
  Read the design diff; a newer SHA alone is not approval of changed decisions.
- At implement-precheck and standard final-check, compare the block
  with `git -C <worktree> log -1 --format=%H -- <canonical-design-path>`.
  Resolve the canonical path with `scripts.kaji.resolve_design_path`.
  A reference mismatch alone is not a design defect: apply the repair below.
  Review-code checks implement's design edits and synchronization; verify-code
  checks fix-code's edits. Neither needs a new design-verify cycle for a
  reference-only repair. Design-verify checks fixes from its own design cycle.

## Reference repair at the discovering phase

1. Read the current Issue body, canonical committed design, existing approval
   reports and subsequent design diff. Establish one source and its approval
   state: unchanged approved content, meaning-preserving edits, or previously
   reviewed changes may be synchronized. A cited user decision does not waive
   independent review of its interface/failure/lane/acceptance consequences.
   Unreviewed semantic changes go to the phase's existing design correction
   route; genuinely uncertain source/authority is `ABORT` with the missing
   evidence. Do not demand a new approval or metadata for already settled facts.
2. When only the reference is wrong, update only its path/SHA/permalink fields.
   Preserve the existing summary, headings and commit annotations inside the
   block as well as all bytes outside it. Insert missing reference fields after
   a leading block heading, or at the block start when no leading heading exists.
   The formatter scans only consecutive reference fields after the optional
   leading heading and blank lines. A blank line after a field or the first
   prose line ends that metadata region; reference-like summary lines remain
   untouched. Malformed or duplicate fields within the metadata are rejected.
   Do not reconstruct the block or
   replace its summary for reference-only repair. If both markers are absent,
   append a block with a nonempty summary from the canonical design, preserving
   user decisions and progress. Duplicate, inverted or broken
   markers whose boundary cannot be established are `ABORT`, not a reason
   to regenerate the design. Never select a source by recency alone.
   An optional deterministic body formatter is available as
   `uv run python -m scripts.kaji.sync_design_reference --help`; it formats
   references only and cannot establish semantic approval. Its repository is
   `[provider.github].repo` in `.kaji/config.toml`; the template placeholder is rejected.
3. Before writing, re-fetch the body and rebase the block-only edit if it has
   changed. Use `uv run kaji issue edit <issue_id> --body-file <file>`; re-read
   and check exactly one marker pair and its full SHA/path permalink inside
   that block. Report source evidence, old/new references, and the re-read.
   Provider failure follows the phase's existing failure contract.
4. Continue the discovering phase. A body-only repair changes no HEAD, needs
   no commit, and does not rerun implement/review-code/fix-code or citable
   same-HEAD lanes. Missing references are repairable on the same basis.
   If canonical path repair requires a tracked rename, distinguish it from
   body-only repair: precheck routes `BACK_DESIGN` for that bounded file repair;
   final-check routes `BACK_IMPLEMENT`; PR publication uses `ABORT` because
   its final-check-approved HEAD cannot be changed there. Implement/fix-code
   can perform an unambiguous meaning-preserving rename, commit and synchronize;
   design re-entry changes only that file/path and necessary references.
   New HEADs require their own applicable lane evidence and independent review.
   These routes do not authorize unrelated redesign or empty commits.

Until the branch is pushed, a new design permalink may not resolve remotely;
its full SHA and local commit are the evidence, not HTTP availability.

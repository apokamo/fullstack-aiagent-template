# Worktree resolution

## Modes

- `pre-worktree`: readiness runs from the main checkout and does not require an
  Issue worktree.
- `creates-issue-worktree`: only `issue-worktree-create` may create one.
- `issue-worktree`: all tracked-file and command operations run in the
  resolved Issue worktree.
- `incident`: ignore the Issue worktree; keep main read-only and use the
  configured incident artifact root.

## Launch directory

Kaji starts every agent in the canonical main checkout, so the repository-owned
skills, configuration, and workflows are read from that checkout's current
content. Main can move while a run is in progress, so those generations may
differ between steps; that drift is accepted and no step gates on it. The launch
directory is never the operation target: resolve the exact Issue worktree and
address it by absolute path.

Resolve the canonical main checkout from `git worktree list`, whose first entry
is always the main worktree:

```bash
MAIN_CHECKOUT=$(git -C <absolute-worktree> worktree list | head -1 | awk '{print $1}')
```

Never resolve it as a fixed string, as `pwd`, or with `git rev-parse
--show-toplevel`; inside an Issue worktree the last of these returns that
worktree, not main. The listing describes the repository rather than the
current worktree, so the same command answers before and after `issue-close`
deletes the Issue worktree.

## Issue-worktree resolution

1. Prefer injected absolute `worktree_dir` / `KAJI_WORKTREE_DIR`.
2. Otherwise read the Issue NOTE and `git worktree list --porcelain`; match the
   recorded branch and Issue, never a number substring alone.
3. Resolve with `pwd -P`. Require a Git worktree root sharing the main Git
   common directory, the expected branch, configured remote, and a merge base
   with `<git_remote>/<default_branch>`.
4. Inspect tracked and untracked changes before mutation. An unexplained
   collision or ambiguous match is `ABORT`.

Every command uses `git -C <absolute-worktree>` or an explicit
`cd <absolute-worktree> && ...`; tool file paths are absolute. Frontend commands
use an explicit `cd <absolute-worktree>/apps/web`.

## Creation and deletion boundary

No consumer guesses a worktree. Exactly two steps mutate worktree existence:

- `issue-worktree-create` creates or safely reuses the injected worktree and
  branch.
- `issue-close` deletes the exact managed worktree and branch after the merge,
  and only when they are clean, identified, and merged into
  `<git_remote>/<default_branch>`. A dirty, unknown, or mismatched asset is
  retained with a reason.

Every other step treats the worktree and branch as read-write content but never
creates or deletes them.

For incident mode, obtain the root with
`uv run kaji config artifacts-dir`. A disposable detached worktree is allowed
only for safe reproduction and must have an exact recorded path.

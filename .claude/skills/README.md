# Repository skills

`.claude/skills/` is the single source of truth for repository skills. Claude
discovers them here directly. Codex discovers the same files through the
matching relative links in `.agents/skills/`:

```text
.agents/skills/<name> -> ../../.claude/skills/<name>
```

`_shared/` is internal support material, not a discoverable skill, so it has
no `.agents/skills/_shared` link.

## Adding, updating, and removing a skill

1. Add or update the canonical `.claude/skills/<name>/SKILL.md` directory.
   Never copy it into `.agents/skills`.
2. For a new discoverable skill, add the relative symbolic link:

   ```sh
   mkdir -p .agents/skills
   ln -s ../../.claude/skills/<name> .agents/skills/<name>
   ```

3. When removing a skill, remove its canonical directory and matching link in
   the same change. Do not remove `_shared` through this process.
4. Run `make verify-docs`. Its skill audit verifies that every canonical public
   skill has a symbolic link with the exact expected target, and distinguishes
   missing, broken, mismatched, and orphaned links. Additional valid Codex-only
   skills or compatibility aliases are allowed.

## Frontmatter convention

Every `SKILL.md` starts with YAML frontmatter. Standard skills use only the
portable `name` and `description` keys. Do not add ecosystem-specific metadata
or execution keys such as `compatibility`, `metadata`, `allowed-tools`,
`argument-hint`, `model`, `context`, `agent`, or `hooks`; they would make the
shared source non-portable.

`grill-me` is the documented exception: as a human-invoked Claude skill it must
retain `disable-model-invocation: true`. Codex does not use that frontmatter
key. Its separate `agents/openai.yaml` must set
`policy.allow_implicit_invocation: false`. According to the
[Codex skill specification](https://developers.openai.com/codex/skills/), this
prevents automatic selection while preserving explicit `$grill-me` invocation.
Both controls are audited by `scripts/docs/check_kaji_skills.py` and must not be
added to ordinary workflow skills.

## Verification

Run the repository documentation gate after any skill or link change:

```sh
make verify-docs
```

Inspect Codex discovery deterministically from the repository root without a
model call:

```sh
codex debug prompt-input
```

The `<skills_instructions>` block must list the 30 workflow skills and omit
`grill-me` because that skill disables implicit invocation. Depending on the
Codex CLI version, a locator may retain the
`.agents/skills/<name>/SKILL.md` symlink path or show its resolved canonical
`.claude/skills/<name>/SKILL.md` path. Either form is valid when it identifies
the canonical skill in the current checkout; the link audit separately
verifies the exact layout of all 31 public skill links. This command proves
discovery and initial-list exclusion only; explicit `$grill-me` availability
follows the Codex skill specification linked above and is not locally
exercised by this check.

The link layout is relative, so the same checkout works in the main repository
and issue worktrees without machine-specific absolute paths.

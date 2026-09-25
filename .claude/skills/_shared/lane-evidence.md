# Lane evidence

Read this file in every phase that runs or cites a quality lane. It is the
canonical rule for reusing a lane result instead of running the lane again.

`make` writes the record. The check is a repository command, so it works with or
without kaji, and kaji verdict evidence stays ordinary prose.

## Observation evidence is not a successful lane record

Before applying the success-record rules below to an observation-purpose eval, apply the
[canonical artifact checks](../../../docs/dev/llm-evals.md#完走と観測証跡の照合).
An exact clean-HEAD latest completed observation artifact may be reported as `OBSERVED`, including
its actual failed exit/result, all attempts, per-metric disposition and follow-up. This is a separate
measurement obligation, not `REUSED`, `SKIP`, or a successful lane. Do not rerun solely because its
failed eval has no success record. Changed HEAD/identity/conditions or uncertain provenance requires
the selected lane to run; known provider/safety/incomplete failures remain blocking. No older commit
is accepted. The final confirmation owner guarantees the handoff before workflow PASS. The success-record checker
and its exit meanings are unchanged; all rules below govern successful lane citation.

## The single citation condition

Run this in the worktree root, once per lane you need:

```bash
uv run python -m scripts.testing.lane_record --check <lane>
```

| Exit | stdout | Meaning |
|---|---|---|
| 0 | `REUSABLE <lane> record=<path> commit=<sha> exit=0 artifact=<path or ->` | Cite it. Do not run the lane. |
| 1 | `RERUN <lane> reason=<reason>` | Run the lane. |
| 2 | usage error | The lane name is not one of the recorded lanes. |

**Never read the record yourself to decide.** The exit code is the decision; the
printed line is the evidence to copy. The recorded lanes are `verify-backend`,
`gate-backend`, `verify-frontend`, `verify-docs`, `check-all`,
`test-on-schema-change`, `test-e2e`, `test-llm`, and `evals`.

Records live under `test-artifacts/lanes/<lane>/<commit_sha>.json` and raw logs under
`test-artifacts/logs/<lane>/`. A real-LLM lane adds the profile identity hash:
`test-artifacts/lanes/<lane>/<identity>/<commit_sha>.json`, so the same SHA keeps one
record per profile. Run its `--check` with the same `LLM_PROFILE` you ran the lane with.

## `REUSED` is not `SKIP`

- `SKIP` means the lane did not run and **no result exists for this code state**.
  [The test policy](../../../docs/dev/test-policy.md) forbids skipping a
  mandatory lane and calling it a pass. That prohibition is unchanged.
- `REUSED` means **the lane ran to completion and succeeded on this exact
  commit**; the evidence is the record instead of a second execution. A
  mandatory lane is satisfied by `REUSED`.
- "The provider is unreachable, so I will cite an older result" is not `REUSED`.
  A mandatory provider failure still fails, exactly as before.

## Evidence format

One line per lane in the phase report.

- Cited: `REUSED make <lane> — <record path> (commit_sha <sha>, exit 0, artifact <path or none>)`
- Executed: `RERAN make <lane> — reason: <one line>`

**Rerunning is allowed.** The default is citation, not a prohibition: when you
run a lane whose record is citable, write the one-line reason yourself. When
`--check` returned non-zero, that `reason` value is the line.

Write only the record path, `commit_sha`, `exit`, and `artifact_path`. **Never
paste record contents or raw lane logs** into an Issue comment or a tracked file;
they stay under `test-artifacts/`.

## Order: check first, run second

1. A producer (`issue-implementation-execute`, `issue-implementation-fix`,
   `pull-request-fix`, `issue-small-change-execute`) commits its change first. Lanes run on a clean HEAD,
   because a dirty or uncommitted run writes no record at all.
2. For each required lane, run `--check <lane>` **before** the lane.
3. Exit 0: do not run the lane; copy the printed line as `REUSED`.
4. Non-zero: run `make <lane>` and report `RERAN ... reason: <reason>`.
5. `issue-final-check`, `issue-small-change-review` and `pull-request-verify` apply
   the same check-first rule to `check-all`: exact
   clean-HEAD success is `REUSED`; any non-zero reason is recorded and the
   phase runs `make check-all` as `RERAN`.

Never invert this into "run the lane, then look for a record". Producers keep
their role: a fresh commit has no record yet, so `--check` returns `no-record`
and the lane runs.

**Do not `--amend` or rebase a commit whose record you intend to cite.** The
record is keyed by commit SHA; rewriting the commit orphans every lane result.

## Degradation

Uncertainty always falls back to rerunning. A record failure must never stop a
run; the worst case is today's cost.

| Situation | `--check` reason | Behavior |
|---|---|---|
| No record for this commit | `no-record` | Run the lane |
| Record unreadable or from an unknown schema | `unreadable-record` / `unknown-schema` | Run the lane |
| Record contradicts its own path | `inconsistent-record` | Run the lane |
| Record does not show a successful run | `failed-record` | Run the lane |
| A declared artifact was not newly published | `missing-artifact` | Run the lane |
| Real-LLM lane with an unknown/absent `LLM_PROFILE`, `SKIP_LLM_TESTS=1`, or a fake model | `env-mismatch` | Run the lane |
| Real-LLM lane with a different `LLM_PROFILE` identity | `no-record` | Run the lane |
| Working tree is dirty, or there is no readable HEAD | `dirty-worktree` / `no-head` | Run the lane |
| Lane failed | (no record was written, and any record for the same commit was discarded) | Run the lane |
| The tree was dirty or unreadable, or the lane log was incomplete | (no record was written) | Run the lane |
| `make clean` removed the records | `no-record` | Run the lane |
| A research run (`--record-reference`, `--compare-candidate`, `--observe`) | (no record was written; an existing record is kept) | Run the lane |
| Provider unreachable | — | Fail as before; `REUSED` is not available |
| A `REUSED` claim with no matching record | — | **`ABORT`**: that is falsified evidence |

Only the last row stops a run.

---
name: pull-request-verify
description: "Independently verify PR fixes and final gates on the corrected SHA."
---

# Independently verify PR fixes and final gates on the corrected SHA

## いつ使うか

| Applies | Condition |
|---|---|
| ✅ | Dev/docs dispatch at `pr-verify`, or manual execution of this phase with a valid Issue ID. |
| ❌ | Otherwise use 通常の会話 without mutations. |

## 入力

Read [the shared workflow contract](../_shared/workflow-contract.md) for injected-first
Issue/worktree resolution, manual input and completion. Worktree mode: `issue-worktree`.

Exact branch PR, original findings, fix commits/replies, current patch and local evidence.
Use an independent context and current-head PR evidence, not Issue producer verdicts or mandatory design path.

## Procedure

1. Confirm local clean HEAD equals the latest PR head containing the reported fixes. Map original
   findings to corrections/replies and inspect the patch, including regressions introduced by fixes.
   Apply [the rubric](../_shared/review-rubric.md) to evidence-backed disagreement. Keep resolved findings
   closed; unrelated new observations are separate reports, not a reason to restart the full review.
2. First run `uv run python -m scripts.testing.lane_record --check <lane>` for each required lane.
   Own final `make check-all` for dev and `make verify-docs` for docs-only, plus all conditional lanes
   required by the current diff under [the matrix](../_shared/verification-matrix.md).
   Use [lane evidence](../_shared/lane-evidence.md): REUSED on exit 0, otherwise execute and report RERAN
   with reason. A missing record calls for execution. If checks modify tracked files, preserve them and
   RETRY to pr-fix, without committing.
   Required provider failure is ABORT. Relevant observation evidence must retain its actual result and
   verified final-confirmation follow-up; unresolved new shortfalls cannot silently pass downstream.
3. Confirm original findings resolved, no fix regressions, complete final lanes, clean local tree and
   unchanged PR full SHA. Post per-finding OK/NG and current-head verification via supported Kaji PR
   review/comment commands. Resolve only corrected threads; record review URL, full SHA, source/fix
   links, proof and commands/exits/record/log paths. Unresolved findings or fix regressions are RETRY.
4. Report unrelated observations separately. Do not broaden this cycle into a fresh full review.

Last, publish the report and actual step marker, stdout and injected YAML through
[verdict output](../_shared/verdict.md). Use only the current step's allowed status.

## Side effects

May post verification, resolve corrected threads and run/cite required lanes. Must not edit/commit
tracked files, push, merge, change labels or resolve uncorrected/unrelated threads.

## Verdict

| Status | Condition |
|---|---|
| PASS | Original findings and fix regressions resolved; final verification complete on the clean current PR SHA. |
| RETRY | An original finding, fix regression or tracked correction remains. |
| ABORT | PR/head/provenance, mandatory provider or final-verification state cannot be established. |

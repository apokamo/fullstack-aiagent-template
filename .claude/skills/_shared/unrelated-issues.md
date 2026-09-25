# Unrelated findings

Classify a finding against the approved scope and
`git diff <git_remote>/<default_branch>...HEAD`. Do not modify unrelated code
or broaden the current Issue.

Record the path/symbol or failing test, reproduction command, relevant output,
branch, and commit. Search existing Issues by the stable error or summary.
Report an existing Issue when one is known; otherwise include a follow-up
candidate in the current phase report. Create or edit another Issue only when
the current step and invocation explicitly authorize that provider mutation.

New findings discovered by a verify step are informational and do not change
the current fix-cycle verdict. A new full review may evaluate them later.

Observation-only eval shortfalls have a specific handoff owned by the final confirmation phase
(final-check or small-change review) under the
[LLM follow-up contract](../../../docs/dev/llm-evals.md#観測項目の未達を引き継ぐ).
With provider-write authority from the invocation, that phase creates/reuses the investigation Issue
before PASS, using its stable key and run marker to recover partial publication without duplicates.
This is distinct from close's post-workflow follow-up. Other phases report observations/candidates;
they do not expand their mutation scope. Authority/provider failure is ABORT, never a completed handoff.

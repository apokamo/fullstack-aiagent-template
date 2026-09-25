# Verdict output

Complete external side effects before publishing the completion trigger.

1. Post the phase report. Issue verdict reports use
   `uv run kaji issue comment <issue_id> --commit --verdict-step <step_id>
   --verdict-status <STATUS> --body-file <report>`.
2. Print the same delimited verdict block to stdout as a fallback.
3. Atomically write the equivalent delimiter-free YAML to injected
   `verdict_path` (or `KAJI_VERDICT_PATH`) last.

Every workflow skill invokes this completion action last, directly or by reference. If
the provider write fails, do not preserve the requested success/retry status:
replace it with a sanitized `ABORT`, try the ABORT marker, print the ABORT block
to stdout, and atomically write the same ABORT to `verdict_path`. The stdout and
file completion signals remain mandatory even while the provider is down.

The YAML fields are `status`, `reason`, `evidence`, and `suggestion`.
Use only statuses exposed by the current workflow step. Evidence names commands,
exit states, commit SHA, report/comment URL, and artifact paths without secrets.

Consumers resolve Issue-cycle handoffs with
`uv run kaji issue resolve-verdict <issue_id> --step <producer-step>`.
For design fixes, identify the latest requested correction from `previous_verdict`
and the review, verification, and fix reports as described in `issue-design-fix`.
On verification retries, keep resolved findings closed. Existing `source_step`
metadata is optional and its absence or value alone does not cause ABORT.
For other fixes where review and verify can both re-enter a fix, resolve both permitted producers
and select the current cycle marker; missing or ambiguous provenance is
`ABORT`. PR review cycles use current-head PR reviews/comments, not Issue
verdict resolution.

Close consumes the [upstream completion handoff](../issue-close/SKILL.md#upstream-completion-handoff).
The normal harness PASS transition carries PR approval and final verification; close does not resolve PR-cycle
Issue markers or reconstruct approval from reviews/comments/reactions. Manual entry uses the explicit approved-target
premise. Existing upstream reports and follow-up links are carried forward, including known target SHAs for comparison.

Only exit 4 from the exact producer lookup permits [artifact recovery](verdict-recovery.md).
Read that procedure only on this exception. Exit 5, provider failure, ambiguity,
or an unpermitted status is ABORT; never substitute prose or an older PASS.
Allowed producer/status pairs belong to the consuming skill. Optional phases
are not mandatory merely because they appear in its table.

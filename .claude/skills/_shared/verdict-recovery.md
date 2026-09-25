# Verdict recovery

Read only after an exact producer lookup returns exit 4.

If Issue resolution returns exit 4 only, a dev/docs consumer may run
`scripts.kaji.resolve_verdict_artifact` with its injected current
`verdict_path`, the exact producer that returned exit 4, and that producer's
permitted statuses. Never combine producers in one helper call. The helper
selects that step's latest same-Issue state record regardless of status, then
requires its status to be permitted and its normalized four verdict fields,
step, attempt, and timestamp to match one non-synthetic latest-attempt
`verdict.yaml` / `result.json` pair. It ignores `latest` and all symlinks, does
not use prose or `recovery-chain.json`, and fails closed on malformed artifacts,
missing matches, or multiple matches. Exit 5 and provider failures
never use this artifact fallback.

On one match, the consumer posts the producer marker with the returned status,
artifact paths, and `--verdict-meta recovered_from=<run>/<step>/attempt-NNN`, then runs
`resolve-verdict` again. It continues only if the re-read status agrees. The
helper never starts or recovers a workflow run and never writes to a provider.
PR current-head review markers and incident identity markers keep their
separate contracts.

Use `uv run python -m scripts.kaji.resolve_verdict_artifact --issue-id <issue_id>
--current-verdict-path <verdict_path> --producer-step <producer>
--allow-status <producer>=<status>` for exactly one producer. Without an injected
current verdict path, do not invent one: only an unambiguous durable canonical
report can recover the manual handoff; otherwise ABORT.

After a unique match, post with `uv run kaji issue comment <issue_id> --commit
--verdict-step <returned-step> --verdict-status <returned-status>
--verdict-meta recovered_from=<run>/<step>/attempt-NNN --body-file <recovery-report>`,
then rerun `resolve-verdict` for that producer. A mismatch is ABORT.

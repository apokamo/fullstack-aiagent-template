# Review rubric

Review independently from `git diff origin/main...HEAD` and the issue/design.
Prioritize:

1. safety, security, secret handling, destructive actions, and HITL bypasses;
2. user-visible correctness and acceptance criteria;
3. data/migration and API compatibility;
4. test classification, coverage, and selected LLM/E2E/eval lanes;
5. docs, operational evidence, and maintainability.

For every finding, record four independent axes plus path/line, impact, and
reproduction or evidence:

| Axis | Values |
|---|---|
| Severity | `Must Fix` / `Should Fix` |
| Scope | acceptance unmet / regression introduced by this diff / separate-Issue candidate |
| Origin | implementation / design |
| Smallest correction | reference/report repair / meaning-preserving edit / settled-decision reflection (local or consequential) / unresolved or changed decision |

Only acceptance failures and regressions introduced by the current diff can be
blocking. A separate-Issue candidate is reported through the unrelated-Issue
contract and cannot block this verdict. Record the disposition of every
`Should Fix`, but a Should Fix alone does not cause `RETRY`. Preferences and
future improvements without evidence remain Should Fix or separate-Issue
candidates.

Apply the canonical type guide as a review weight, not as permission to inflate
severity: feature emphasizes outcome/interfaces/failure/compatibility; bug
reproduction/root cause/regression; refactor invariants/equivalence/rollback;
test production invariance/signal/markers/execution; chore production
invariance/compatibility/operations/rollback; perf baseline/target/tolerance;
security threat/auth/secrets/input/abuse.

Classify by meaning before selecting a phase's existing verdict:

| Smallest correction | Boundary and action |
|---|---|
| Reference/report repair | Canonical source and approval are established; repair at the discovering phase under the workflow contract. No design re-entry for body-only synchronization. |
| Meaning-preserving edit | Lint, typo, wording or unambiguous path repair changes no design decision. Existing text may change or be deleted. Implement/fix-code may commit it and synchronize the block. Read-only phases route only the required file correction. |
| Settled-decision reflection | Cite the current Issue/user decision or explicitly linked source. A local clarification leaves outcome, Scope/labels, interfaces, failure, lanes, acceptance and rollback unchanged. Consequential reflection needs bounded design correction and independent review, without asking the human to choose the same direction again. |
| Unresolved or changed decision | First check current decisions and referenced constraints. A genuinely unresolved one-way door is ABORT; an authorized decision change requires bounded design work and review. |

For review-code's blocking mixed set, unsafe authority/provenance is `ABORT`;
required changes to existing design decisions are `BACK`; consequential
additions are `BACK_DESIGN_FIX`; remaining tracked implementation/docs fixes
(including meaning-preserving design edits and local clarifications) are
`RETRY`; otherwise `PASS`. Repair unambiguous body-only references locally
before deciding, preserving implementation-rooted findings when routing upstream.
The existing review-code-only N=2 counter is unchanged.

Implement and implement-precheck use their existing `BACK` / `BACK_DESIGN`
for consequential design work; final-check uses `BACK_DESIGN`. These routes
carry only the finding and necessary consequences. They do not require a
full design rewrite or a new human decision when the direction is settled.
Line count and text insertion/deletion do not decide semantic significance.

For LLM findings apply the [purpose-based contract](../../../docs/dev/llm-evals.md#変更目的とissueの完了条件).
Threshold failure is `acceptance unmet` only when that threshold is required by the current contract.
An observation-only shortfall is not evidence of a regression introduced by this diff. Record unknown
causality without inventing it; final-check ensures the investigation handoff. Provider failure,
incomplete evidence, safety violations and confirmed implementation regressions remain blocking.
Verification remains bounded to original findings; PR verification and small-change verification
also judge regressions introduced by fixes and own final lanes on the corrected SHA.
Unrelated new observations stay outside the correction verdict. Small-change review uses
RETRY for bounded tracked corrections and ABORT for unsuitable scope or unsafe provenance;
it does not invent a design loop.

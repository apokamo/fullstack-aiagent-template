# Verification selection matrix

Classify the diff, record why each lane applies, and satisfy every required
lane. Canonical `area:*` labels are scope hints only. Recompute lanes from the
Issue decisions (or the approved design) and actual diff, and report or correct mismatches under
[the Issue label policy](../../../docs/dev/issue-labels.md).

This matrix selects lanes. Whether a selected lane is executed or cited from the
record of the current commit is decided by
[lane evidence](lane-evidence.md), which also owns the `REUSED` / `SKIP`
distinction. The design loop selects lanes and writes them into the design; it
does not run them.

| Change | Required verification |
|---|---|
| Backend deterministic logic or fake model | `make verify-backend`; final gate uses `make gate-backend` |
| Frontend logic | `make verify-frontend` |
| Schema or migration | Backend lane plus `make test-on-schema-change` |
| Frontend/fullstack user flow | Relevant gates plus `make test-e2e` |
| Existing-profile selection, proxy, credential isolation, or client lifecycle | L1 gates plus `make test-llm`; observation evals for affected profiles |
| Prompt, tool schema/selection, agent loop, or HITL policy | L1 gates, `make test-e2e`, `make test-llm`, and `make evals` |
| New model/provider, endpoint, or reasoning configuration | `make test-llm` and comparison evals on the same dataset/scorer/repeats |
| Eval dataset, scorer, rubric, or judge | Deterministic scorer tests, `make evals-judge-validate`, and `make evals-score` on saved observations (`make evals-observe`); `make evals` for the baseline comparison |
| Docs or workflow policy only, unchanged model execution | `make verify-docs`; no real-LLM/eval lane |

For an eval, record provider, model, dataset/scorer versions, repeats, summary,
baseline/tolerance, and artifact path. `SKIP_LLM_TESTS=1` is an explicit local
opt-out, never evidence for an AI-affecting kaji gate. See
[docs/dev/llm-evals.md](../../../docs/dev/llm-evals.md).

Apply the [purpose-based LLM contract](../../../docs/dev/llm-evals.md#変更目的とissueの完了条件).
Design records the impact classification, identities, and whether each metric threshold is an acceptance
criterion or observation only; design review checks it. All later phases preserve that decision and
reconcile the actual diff. A quality-affecting mixed change retains its quality gates. Existing explicit
Issue requirements remain binding unless an authorized decision changes them. A policy edit alone is
not a model execution change. Observation failures use `OBSERVED` evidence and final-check handoff,
not invented successful records; quality-gate failures still block.

Small-change review owns final `make check-all` and required conditional lanes. PR
verification owns the same gates on the corrected dev SHA; docs-only uses
`make verify-docs`. Publication consumes that approval without rerunning reconciliation.

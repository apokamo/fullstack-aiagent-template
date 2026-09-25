# Critical decisions

Workflow design elaborates decisions already made; it does not invent product,
data, API, UI, security, or operational policy.

Classify every material choice by reversibility:

1. A decided direction may be detailed and must cite its Issue, comment, or
   existing contract.
2. A cheap two-way-door assumption may proceed only when it is marked as an
   assumption with rationale and a later review point.
3. An unresolved one-way door must return `ABORT`. Examples include user value,
   source-of-truth selection, public API compatibility, schema/data migration,
   authentication/authorization, secret exposure, destructive operations, and
   production/provider policy.

Do not send category 3 to an AI fix loop. Put the decision required from a
human in the verdict suggestion. A missing citation for an existing decision is
correctable; the absence of the decision itself is not.

Design artifacts record a provenance table with the decision, selected
direction, source or explicit assumption, and the detail added by the design.

Before asking for a human decision or declaring a design gap, check the current
Issue decisions and constraints in the related Issues it explicitly references.
Cite settled directions; missing reflection is a bounded correction, not a new
choice. Do not require unrelated Issue searches or complete source inventories.
Explicit later user corrections and named follow-ups supersede withdrawn gate
requirements. Preserve failed artifacts as failed and record the handoff; this
is not permission to waive an unwithdrawn mandatory gate, provider failure,
incomplete run, or implementation regression.

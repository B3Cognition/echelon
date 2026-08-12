# Worked-On Summary Agent Design (Superseded)

## Status

This document is retained only as the origin record for the dedicated
`echelon.summarizer` agent. It is not an active terminal-output contract.

The normative design is
[`2026-08-12-terminal-handoff-summary-design.md`](./2026-08-12-terminal-handoff-summary-design.md).
If this document and that design disagree, the terminal-handoff design wins.

## Current Contract

The controller constructs a closed, evidence-grounded menu of narrative lines.
The model may select only identifiers from that menu and returns exactly:

```json
{"line_ids":["outcome","progress","verification","readiness"]}
```

The root object contains only `line_ids`. A valid selection has four through
eight unique, known identifiers and includes every controller-marked required
identifier. Model-authored prose is never rendered. Invalid output, provider
failure, timeout, or missing prompt selects the deterministic controller
fallback without a retry.

The final `Worked on` value contains four through eight plain controller-owned
lines without bullets. Each line is at most 280 characters and the complete
value is at most 900 characters. Required blocker, provider-limit,
verification-failure, and next-action facts survive deterministic compaction.

## Durable Evidence

Phase A derives outcomes, decisions, artifacts, quality evidence, blockers, and
recovery from production controller fields such as completed phases, published
spec paths, the issue-resolution ledger, resolved blocked decisions, certified
quality scores, and lifecycle commits. Generic ad-hoc `outcomes`, `decisions`,
or `artifacts` keys are not treated as Phase A facts.

Delivery includes exact bounded verification failures from the selected
strategy. The complete selection packet remains capped at 12 KiB.

Provider-limit text is untrusted terminal data. It is cleaned at extraction and
again before evidence/rendering, bounded to 240 characters, and displayed only
when its persisted phase and termination provenance match the current
transition.

## Lifecycle Surface

Every valid `spec run`, `spec continue`, `spec resume`, `delivery run`,
`delivery continue`, and `delivery resume` terminal handoff emits exactly one
lifecycle card. Direct checkpoint, rewind, manual-recovery, and human-answer
paths integrate `Worked on` and `next` into that card rather than adding a
standalone summary card.

Standalone `spec status` / `_print_next_steps` behavior remains unchanged.

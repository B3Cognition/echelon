# Issue Resolution Queue Design

**Goal:** Let a Phase A run resolve several SAGE escalations one at a time without a selected issue permanently blocking `echelon spec continue` or being mistaken for a completed repair.

## State Contract

The controller owns the issue ledger. An entry moves through these states:

`pending -> selected -> repaired -> validated`

`validated` is terminal. `selected` records one accepted human or Banzai decision. `repaired` means CARTOGRAPHER changed the canonical spec after the selection; it is not proof that SAGE accepts the change. A later WHY2 pass validates the selected issue. A WHY2 failure leaves it non-terminal so the next `echelon spec continue` remains focused on that issue.

Only one entry may be `selected` or `repaired` at a time. The remaining entries stay in their original SAGE order and are never implicitly accepted.

## Flow

1. `echelon spec resolve ISS-n "decision"` records the selected entry and a repair baseline, then creates the existing WHY2-to-WHAT controller recovery edge.
2. The controller dispatches WHAT. When canonical Phase A artifacts progress after the baseline, it changes the entry to `repaired` and consumes the recovery edge; no separate CLI retry is required.
3. WHY2 passes only after the repair. The controller changes the entry to `validated`, clears the active selection, and resumes the ordinary graph.
4. If WHY2 fails, the entry stays non-terminal. The run remains or returns blocked with the issue queue still intact, so the same issue must be repaired again before later entries can be selected.
5. Once blocked again, CLI guidance hides validated entries and exposes the first pending issue. `echelon spec resolve` preserves SAGE order.

## Eligibility

The queue contains only actionable SAGE findings. An issue marked resolved, containing `No action required`, or whose required action is `None` is advisory and does not block the queue. Conditional or informational findings must be emitted that way by SAGE rather than routed as an unconditional repair.

## Banzai

Banzai may select only one explicitly evidence-backed, auto-eligible candidate. Its selection is normalized into the same ledger entry, repair baseline, and controller recovery edge as `echelon spec resolve`. It never clears the dispatch cap directly.

## Verification

Regression tests cover: selection records a baseline; a WHAT artifact change consumes the recovery edge and marks only the selected entry repaired; a succeeding WHY2 validates and clears it; later unresolved entries remain queued; and a conditional/no-action issue is not queued.

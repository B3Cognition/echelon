# Worked-On Summary Agent Plan (Archived)

## Status

This implementation plan is complete and superseded. It records the original
feature boundary but is not a source of current response-schema or terminal UX
requirements.

Use these documents for current work:

- [`../specs/2026-08-12-terminal-handoff-summary-design.md`](../specs/2026-08-12-terminal-handoff-summary-design.md)
- [`2026-08-12-terminal-handoff-summary.md`](./2026-08-12-terminal-handoff-summary.md)

## Current Implementation Baseline

The shipped implementation has these invariants:

- `harness.worked_on_summary` builds controller-owned narrative candidates from
  bounded durable evidence.
- `echelon.summarizer` is a fast/low selector. It returns one closed object whose
  only field is `line_ids`; it cannot author terminal prose.
- A valid selection contains four through eight unique known identifiers and
  retains every required identifier.
- The controller fallback uses the same candidate set and ordering.
- Rendered lines contain no bullet glyphs, are individually bounded to 280
  characters, and collectively fit within 900 characters.
- Selection evidence is at most 12 KiB and summary dispatch remains one-shot
  with a 30-second timeout.
- Phase A derives rich facts from completed phases, published spec state,
  controller decisions/audit records, certified quality state, and lifecycle
  commits.
- Delivery promotes exact bounded verification failures into selectable facts.
- Provider-limit observations carry phase and termination provenance, are
  cleaned and bounded at trust boundaries, and are cleared before new dispatch
  or recovery transitions and on non-provider terminal publication.
- Valid direct checkpoint, rewind, manual-recovery, and human-answer paths emit
  one integrated lifecycle card containing `Worked on` and `next`.
- Summary failures never alter the underlying command result or trigger a repair
  invocation.

Historical task-by-task instructions were removed because they described the
retired open-prose response format and conflicted with the closed selection
contract above.

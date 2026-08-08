# SUE Dossier

- **Specification:** specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-21
- **Profile:** deep
- **Dialogue model:** claude --model claude-sonnet-5
- **Measurement model:** (cli default)

## Tier outcomes

- v2: ok
- v3: ok
- drills: ok

## Fix-ready summary

- APORIA_CONTRADICTED — parmenides drill on FR-036: FR-036 requires the report header to state 'exactly 5 base facts' including a resolved model provider, but AC-002 requires the header to state 'exactly 4 facts' (spec path, run date, question count, finding count) with no provider fact at all. Which count governs the header's contents — 4 or 5? (socratic-dialogue.md)
- APORIA_CONTRADICTED — theaetetus drill on FR-008: A-001 states as an unvalidated assumption that 'the model command can be driven non-interactively with prompt in, extractable JSON out,' yet FR-008 and FR-026 are written as if this always holds. If the designated acceptance run's real model command turns out not to satisfy A-001, which requirement governs the resulting behavior rather than leaving it as an open spike outcome? (socratic-dialogue.md)
- APORIA_UNDEFINED — theaetetus drill on FR-013: FR-013 classifies empty stdout as an automatic failed call. Does stdout consisting only of whitespace or newlines count as 'empty' and skip extraction, or does it proceed to FR-026/FR-027 extraction and fail there instead? (socratic-dialogue.md)
- [CONTRADICTED] FR-036 (support 3): FR-036 requires the report header to state 'exactly 5 base facts' including a resolved model provider, but AC-002 requires the header to state 'exactly 4 facts' (spec path, run date, question count, finding count) with no provider fact at all. Which count governs the header's contents — 4 or 5? (socratic-consensus.md)
- [UNANSWERABLE] FR-036 (support 3): FR-036 introduces 'resolved model provider' as a header fact, but no requirement defines what a 'provider' is, how it is derived from an arbitrary FR-003 command line, or what value it takes when the command is a test stub rather than a real vendor CLI. (socratic-consensus.md)
- [UNANSWERABLE] FR-008 (support 2): A-001 states as an unvalidated assumption that 'the model command can be driven non-interactively with prompt in, extractable JSON out,' yet FR-008 and FR-026 are written as if this always holds. If the designated acceptance run's real model command turns out not to satisfy A-001, which requirement governs the resulting behavior rather than leaving it as an open spike outcome? (socratic-consensus.md)
- [UNANSWERABLE] FR-013 (support 2): FR-013 classifies empty stdout as an automatic failed call. Does stdout consisting only of whitespace or newlines count as 'empty' and skip extraction, or does it proceed to FR-026/FR-027 extraction and fail there instead? (socratic-consensus.md)
- stable-low unit AC-001 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-002 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-003 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-004 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-005 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-006 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-007 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-008 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-009 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-010 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-011 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-012 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-013 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-014 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-015 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-017 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-018 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-019 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-020 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-021 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit AC-023 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit ERR-001 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit ERR-002 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit ERR-003 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit ERR-004 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit ERR-005 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-002 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-003 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-004 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-007 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-009 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-010 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-012 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-015 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-016 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-022 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-023 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-025 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-026 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-027 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-030 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-034 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit FR-039 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)
- stable-low unit NFR-001 — interpretations reliably diverge (semantic-reproducibility.md fracture lines)

## v2 stable findings

| Target | Verdict | Support | Question |
|---|---|---|---|
| FR-036 | CONTRADICTED | 3 | FR-036 requires the report header to state 'exactly 5 base facts' including a resolved model provider, but AC-002 requires the header to state 'exactly 4 facts' (spec path, run date, question count, finding count) with no provider fact at all. Which count governs the header's contents — 4 or 5? |
| FR-036 | UNANSWERABLE | 3 | FR-036 introduces 'resolved model provider' as a header fact, but no requirement defines what a 'provider' is, how it is derived from an arbitrary FR-003 command line, or what value it takes when the command is a test stub rather than a real vendor CLI. |
| FR-008 | UNANSWERABLE | 2 | A-001 states as an unvalidated assumption that 'the model command can be driven non-interactively with prompt in, extractable JSON out,' yet FR-008 and FR-026 are written as if this always holds. If the designated acceptance run's real model command turns out not to satisfy A-001, which requirement governs the resulting behavior rather than leaving it as an open spike outcome? |
| FR-013 | UNANSWERABLE | 2 | FR-013 classifies empty stdout as an automatic failed call. Does stdout consisting only of whitespace or newlines count as 'empty' and skip extraction, or does it proceed to FR-026/FR-027 extraction and fail there instead? |

## v3 measurement

- SR mean 0.423 ± 0.027 · noise floor 0.094 · stable-low 45 unit(s)

## Dialectic drills

| Lens | Target | Terminal | Turns | Source |
|---|---|---|---|---|
| parmenides | FR-036 | APORIA_CONTRADICTED | 2 | v2-stable |
| theaetetus | FR-008 | APORIA_CONTRADICTED | 4 | v2-stable |
| theaetetus | FR-013 | APORIA_UNDEFINED | 1 | v2-stable |

_Diagnose-only dossier: individual tool reports sit beside the spec; nothing was edited or dispatched._

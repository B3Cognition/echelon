# ADR-001 Amendment Record

**Produced by**: IMPLEMENTER (ORCHESTRATOR task T-003)
**Date**: 2026-04-03
**Spec**: 017-ns003-ca-overlays
**Constitution version**: 1.1.0
**Source ADR**: research.md ADR-001 (IS-003 resolution)

---

## Purpose

This document records the formal amendment to spec.md Section 1 novelty claim text
mandated by ADR-001 (IS-003 resolution). The ORCHESTRATOR rule prohibits direct
modification of spec.md; this file serves as the authoritative amendment record that
IMPLEMENTER uses when generating documentation and experiment metadata.

All downstream templates (experiment runners, report generators, CLI help text) MUST
use the amended framing defined below, not the original framing.

---

## Amendment

### Original text (superseded)

> "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph
> across a spec run and emits pre-commit conflict signals when new assertions contradict
> existing beliefs"

### Amended text (canonical from this point forward)

> "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph
> across a spec run and detects post-hoc contradictions when new artifact-stage
> assertions conflict with existing beliefs already committed to the artifact store"

---

## Reason

ADR-001 — IS-003 resolution, Model B write-wrapper rejected, post-hoc mode only.

GATEKEEPER confirmed that Echelon agents self-write artifact files via the Claude Write
tool within their own LLM context. COMMANDER receives a completion signal after the
write occurs — not a pre-write content stream. This is Model B (write-wrapper required),
not Model A (COMMANDER-controlled write).

The write-wrapper path was rejected as out of scope and disproportionate to the spec 017
deliverable budget. Pre-commit mode (AC-2.2, FR-NS3B-004 pre-commit branch) is formally
removed from the implementation scope.

---

## Effect

1. All experiment report templates (ns003-report.md generator in T-015, uca004-negative-report.md
   in T-019) must reference the amended framing ("post-hoc contradictions"), not the
   original ("pre-commit conflict signals").

2. All metadata files and CLI help text must use the amended framing.

3. The `--mode pre-commit` flag in `ns003_agm.py` MUST NOT silently proceed as post-hoc.
   It must print the notice:
   "pre-commit mode not available in v1 — IS-003 resolution descoped this"
   and then proceed as post-hoc mode (deprecation-warning path per ADR-001 Consequences).

4. The patent novelty claim is unaffected: the novelty is the combination of structured
   schema enforcement and AGM belief revision logic on the artifact graph, not the
   timing mode. Post-hoc detection preserves this claim in full (GATEKEEPER confirmed,
   feasibility.md §2.1).

---

## Verification

This record is the authoritative source of the amendment. Any file in the spec 017
implementation that uses the original framing ("pre-commit conflict signals") without
the amendment notice is non-conformant.

`ns003_agm.py --mode pre-commit` MUST print a deprecation/not-available notice
(not a silent mode switch) before proceeding as post-hoc.

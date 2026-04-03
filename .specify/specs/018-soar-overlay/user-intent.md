# User Intent Model — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: TRACKER (INTENT-TRACKER)
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay
**Run phase**: Pre-WHAT intent capture

---

## Explicit Statements (what the user literally said)

- "SOAR would be a natural 6th overlay (production rules, working memory, chunking)."
- "Want me to spec and build it as an addition?"
- "Yes specify with full new echelon"

---

## Inferred Intent (what they probably mean)

- **6th overlay, not a standalone system.** The user explicitly framed SOAR as the "6th overlay," signaling that the pattern, interface, and integration approach of the existing five overlays must be followed exactly. This is not a greenfield design.
- **Full spec + full build.** "Full new echelon" means the complete speckit.echelon pipeline: DISCOVER → SYNTHESIZE → WHAT → HOW → BUILD → VERIFY. Not a partial or shortcut run.
- **The three named mechanisms are the scope.** The user enumerated exactly three SOAR concepts: production rules, working memory, chunking. These three are the required deliverables. Nothing beyond them is implied.
- **ADR-005 uniform interface is assumed.** By calling it a "6th overlay," the user implicitly expects `enrich_context(context_pack, run_id) -> dict` as the primary interface — the same contract as overlays 1-5.
- **Python, stdlib only.** Consistent with all prior overlays; the user did not request or imply any dependency on external SOAR packages. "Natural addition" implies seamless fit into the existing codebase.
- **Integration with COMMANDER.md.** Position-6 insertion in the COMMANDER pre-dispatch sequence is the implied integration point. The user did not say "integrate it" separately — they assumed it would be wired correctly.
- **No reduction of scope.** The user answered "Yes" to the full scope question without qualification. There is no signal of a subset or MVP-first approach.

---

## Intent vs Spec Alignment

| User Intent | Current Spec State | Aligned? |
|-------------|-------------------|----------|
| 6th overlay — same pattern as overlays 1-5 | ADR-005 interface confirmed (A-001 validated); position-6 assumed (A-009 unvalidated) | PARTIAL — position-6 not yet confirmed against COMMANDER.md |
| Production rules | ProceduralMemoryStore + seed rules + matching algorithm defined in mental-model.md | YES |
| Working memory | WME extraction from context_pack defined; stable keys identified | YES |
| Chunking | ChunkingEngine + ChunkRecord defined; generalization strategy OPEN (U-003) | PARTIAL — mechanism defined but key design decision deferred |
| Python, stdlib only | A-002 validated | YES |
| Full echelon pipeline | Squad run in progress (DISCOVER complete, SYNTHESIZER complete) | YES — on track |
| COMMANDER.md integration | Amendment drafted as gap G-003; not yet written | PARTIAL — not yet done |
| No scope reduction | Spec covers all three user-named mechanisms | YES |

---

## Red Flags (intent divergence detected)

### RF-001: Chunking implementation deferred to v2 — user explicitly named it
- **Signal:** The SYNTHESIZER recommends defaulting `chunking_enabled: false` in v1 (R-004 mitigation). The user explicitly listed "chunking" as one of the three required mechanisms.
- **Risk:** If chunking ships as a disabled flag in v1, the user may correctly say "you built the SOAR overlay without chunking — that's not what I asked for."
- **TRACKER ruling:** Chunking must ship as an implemented mechanism in v1. The `chunking_enabled` flag may default to `true` or `false` — but the code must exist and work. Disabling by default is acceptable as a safety valve; not implementing it is NOT acceptable.
- **Action required:** Ensure the WHAT spec includes chunking as a functional requirement, not a "v2 future work" item. The HOW spec may recommend disabling by default; the BUILD agent must implement the code regardless.

### RF-002: Position-6 COMMANDER.md amendment not yet confirmed
- **Signal:** A-009 is UNVALIDATED. COMMANDER.md has not been read to confirm the slot is available or what amendment is needed.
- **Risk:** If the COMMANDER amendment is deferred until BUILD, the overlay may be built without ever being wired in — technically complete but not integrated.
- **TRACKER ruling:** COMMANDER.md integration is part of the user's stated intent ("add it as an addition"). The overlay must be callable by COMMANDER, not just a standalone module. SCIENTIST must confirm position-6 before HOW is finalized.

### RF-003: Semantic legitimacy of "SOAR overlay" label (U-010)
- **Signal:** The spec acknowledges the overlay omits substates and full preference calculus. U-010 asks whether the label is appropriate.
- **Risk:** The squad may label the output "SOAR-inspired overlay" or add disclaimers that the user did not ask for, reducing the value signal of the deliverable.
- **TRACKER ruling:** The user said "SOAR overlay." Unless the user revises this, the deliverable is a SOAR overlay. Implementor disclaimers about approximations belong in internal documentation, not in the public-facing capability name. Do NOT rename it without explicit user instruction.

---

## Scope Boundaries (TRACKER-enforced)

### In scope (explicitly stated by user)
- Production rules (matching engine, seed rules, ProceduralMemoryStore)
- Working memory (WME extraction from context_pack)
- Chunking (SOAR-inspired procedural compilation, post-dispatch learning)
- Full echelon run (WHAT → HOW → BUILD → VERIFY)
- Integration as 6th overlay in COMMANDER pre-dispatch sequence

### Out of scope (not stated and not implied)
- Official SOAR C++ kernel integration (violates ADR-005 — excluded by constraint, not intent)
- Cross-run ProceduralMemoryStore persistence (A-008 — user did not specify this)
- Full SOAR preference calculus (simplification is architecturally sound; user did not ask for canonical fidelity)
- Substate creation (absent by constraint; acknowledged deviation)
- Multi-cycle elaboration quiescence (single-pass is sufficient for enrichment use case)
- Endocrine system wiring for SOAR events (not mentioned; can be added in v1.1 if user requests)
- AQS measurement experiment (R-001) — user did not request this; TRACKER recommends raising it as a decision point, not blocking the build

---

## Assumptions TRACKER Challenges

### Challenge on A-008 (cross-run persistence out of scope)
- **Status:** TRACKER accepts this assumption. The user did not mention cross-run learning. "Addition" implies parity with existing overlays; existing overlays do not persist across runs.
- **Ruling:** A-008 is intent-consistent. No action needed.

### Challenge on R-004 mitigation (disable chunking by default)
- **Status:** TRACKER partially accepts this as a technical safety valve but REJECTS it as a scope reduction.
- **Ruling:** The code implementing chunking MUST ship. The default configuration may disable it. This preserves the user's stated intent while managing the R-004 technical risk.

### Challenge on R-001 (AQS experiment before completing spec)
- **Status:** The SYNTHESIZER flags this as requiring a user decision before spec 018 is marked COMPLETE. TRACKER agrees this should be raised, but it must NOT block the build.
- **Ruling:** Raise R-001 as an explicit decision point at the end of the run. Do not gate BUILD or VERIFY on this decision. The user said "specify with full new echelon" — that means build it.

---

## Stakeholder Model

Single stakeholder project. The user is the sole stakeholder and decision authority. No competing priorities detected.

| Stakeholder | Role | Primary Goal | Key Constraint | Potential Conflicts |
|-------------|------|-------------|----------------|---------------------|
| User | Owner / Architect | Add SOAR as functional 6th overlay | Must follow existing overlay pattern; stdlib only | None — sole stakeholder |

---

## Intent Correction Log

| Date | Correction | Source | Impact |
|------|------------|--------|--------|
| (none yet) | — | — | — |

_This section will be updated if the user provides feedback that revises the intent model._

---

## TRACKER Sign-off

Intent is clear and unambiguous. The user wants a full SOAR overlay (production rules + working memory + chunking) built as the 6th overlay in echelon-proto, following ADR-005 uniform interface, integrated with COMMANDER.md, using Python stdlib only. The full echelon pipeline should execute without scope reduction. Three red flags have been raised (RF-001 through RF-003) requiring squad attention before HOW is finalized.

# MVP Scope — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Gatekeeper: speckit-echelon-gatekeeper (GATEKEEPER)
- Mode: first-pass
- Date: 2026-07-18

## Must-Ship

The must-ship set is the complete v1 scope. This is deliberate: user-intent.md UI-004 ("Implement exactly the v1 scope … no expansion AND no silent trimming") and its Scope Preferences table prohibit MVP-style tiering within the six designed areas; TRACKER intent was checked before scoping per Rule 3.

| Feature | Rationale | Requirement IDs |
|---------|-----------|-----------------|
| F1 Command interface & pre-flight validation | Entry point and fail-fast guarantee: a failed pre-flight costs zero model calls | FR-001–FR-007, ERR-001, ERR-002, NFR-003, NFR-005 |
| F2 Model invocation & isolation | The two isolated calls are the entire analytical mechanism; isolation is the property that distinguishes SUE from an ordinary in-repo model call | FR-008–FR-013, ERR-003, ERR-005, NFR-001 |
| F3 Round schemas, extraction, validation & retry | Model output is untrusted input; strict validation with identifier bijection plus a bounded corrective retry is the sole recovery mechanism in v1 | FR-014–FR-031, ERR-004 |
| F4 Deterministic assembly & report | The product's payload: partition, contradictions-first ranking, report with collapsed audit appendix, terminal summary — all pure local computation | FR-032–FR-042, NFR-004 |
| F5 Test seam & unit tests | Explicitly enumerated deliverable ("and pytest unit tests as designed"); the stub seam keeps every deterministic behavior offline-verifiable | FR-043–FR-045, NFR-002, SC-002, SC-005 |
| F6 Manual live acceptance run | The only live-model validation in v1; success criterion is tolerance-bounded to absorb model nondeterminism | SC-001, AC-023 |

## Should-Ship

| Feature | Rationale | Requirement IDs |
|---------|-----------|-----------------|
| (none) | The v1 design admits no partial tier between must-ship and the later SUE tiers; every v1 requirement is marked MVP in spec.md | — |

## Could-Ship

| Feature | Rationale | Requirement IDs |
|---------|-----------|-----------------|
| (none) | Delighter-class additions (JSON output mode, report history, run locking) were considered and are explicitly fenced out as v2+ or non-goals; adding any would violate the no-expansion intent | — |

## Won't-Ship

| Feature | Rationale | User Intent Risk |
|---------|-----------|------------------|
| Multi-reader consensus, interpretation graphs, convergence scoring | Later SUE tiers; the v1 interface (spec path in, markdown report out) is designed to stay stable under all of them | None — deferral is the designed roadmap (UI-012) |
| Workflow integration / echelon CLI verb | The script stays a host tool; standalone is a first-class requirement (FR-045) | None deferred; HIGH if harness coupling creeps in during build |
| Encoding answers back into challenged specifications | Findings are advisory only — the grounding rule assigns judgment to the human | None — core design principle |
| Report history / versioning | Reruns overwrite; the report is regenerable, never a record (U-010 decision) | None |
| Concurrent-run protection | Single-operator manual tool; explicit non-goal | None |
| Context-window guard for oversized specifications | Documented limitation (A-005), observed at acceptance rather than guarded | None — measurement folded into the OQ-001 spike per issues.md ISS-209 |

## MVP Coherence Check

- Usable without should/could features: yes — the must-ship set is the entire pipeline from invocation to report plus its verification; there are no should/could features to lean on.
- User intent preserved: yes — the must-ship set maps one-to-one onto the six areas the user enumerated (interface, JSON schemas, isolation contract, report format, error handling, pytest unit tests) plus the design's own acceptance run; nothing trimmed, nothing added.
- Constitution conflicts: none — the existing constitution (ratified 2026-06-18, echelon Builder FE domain) was verified by CHIEF this run as non-conflicting with the standalone SUE script: its FE-scoped NON-NEGOTIABLE principles do not bind a standalone host tool with no harness imports and no echelon state-file writes (reasoning journal entry 32). No constitution-mandated capability is dropped by this scope.

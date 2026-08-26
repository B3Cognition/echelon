# Stakeholder Model

## Metadata

- Spec: 030-build-sue-challenge-script
- Tracker: speckit-echelon-tracker (TRACKER)
- Date: 2026-07-18

Scope note: git evidence shows a single-maintainer repository (people-and-teams.md, bus-factor 1). Distinct stakeholder *roles* are still detectable — the same person wears several hats with genuinely competing priorities, and two downstream role-holders exist even if currently embodied by the maintainer. Modeled by role, not by headcount.

## Stakeholders

| Stakeholder | Role | Primary Goal | Key Constraint | Potential Conflicts |
|-------------|------|--------------|----------------|---------------------|
| Maintainer as designer (SUE roadmap owner) | Authored the approved design; owns the v1-to-later-tier vision | v1 built exactly as designed; CLI interface stable so later tiers (graphs, convergence, workflow integration) bolt on without rework | Design doc is the only durable rationale record (bus-factor 1) | vs implementer-role pragmatism when design premises prove shaky (strict JSON, cwd isolation) |
| Maintainer as implementer/reviewer | Builds and reviews the script under repo conventions | Testable, minimal, stdlib-shaped script matching `scripts/` precedent; deterministic parts fully unit-tested | Design silences (U-003…U-007) must be pinned before tests can be enumerated | Minimal-resolution instinct vs design fidelity — the smallest fix may reword an approved detail (RF-4 pattern) |
| Script operator (future user of SUE, incl. other engineers) | Runs `sue_challenge.py` against arbitrary specs | Trustworthy findings; clear failures (exit codes, install pointer, debug dumps); no silent contamination of the reading | Inherits claude CLI session's data-handling posture — spec content egresses to the model provider (risks.md) | Wants robustness (noise-tolerant extraction, isolation guarantees) that may exceed "exactly v1" scope |
| Spec authors whose specs get challenged | Receive `socratic-challenge.md` verdicts on their specs | Findings grounded in their text (grounding rule) — no hallucinated criticism; auditable filter (audit appendix) | Findings are advisory: "the human decides" — the report must not overstate authority | None material in v1; would conflict with any future auto-encoding of answers back into specs (explicit non-goal) |

## Priority Conflicts

| Conflict | Stakeholder A | Stakeholder B | Current Resolution | Risk |
|----------|----------------|----------------|--------------------|------|
| Design fidelity vs mechanism feasibility (strict JSON, cwd-only isolation) | Designer: implement the approved mechanism exactly | Implementer/operator: mechanism as written may be fragile (MODELER alerts V-1/V-2) — needs extraction tolerance or suppression flags | Unresolved — routed to INVESTIGATOR spikes (U-001, U-002) before ARCHITECT freezes the subprocess runner | Silent deviation in either direction violates user intent (see user-intent.md RF-3) |
| Approved acceptance criterion vs testability | Designer: one live run overlapping three named issues | Implementer: nondeterministic model makes that flaky by construction | Proposed: CARTOGRAPHER encodes explicit tolerance in the AC | AC edit must be a traceable clarification, not a silent rewording (RF-4) |
| Operator robustness wishes vs "exactly v1" | Operator: noise-hardened extraction, richer diagnostics | Designer: v1 scope is fixed; interface stable | Non-goals list wins; robustness limited to what the designed retry/exit-3 path provides | Scope creep through unknown resolution (RF-2) |
| Data egress vs convenience | Operator/spec authors: challenged spec content leaves the machine via the claude CLI | Designer: mechanism inherently requires sending spec text to the model | Document egress as a stated limitation in the spec; operators judge per-spec suitability | Specs containing confidential or personal data challenged without awareness — flag in spec limitations (data-protection relevant if such content ever appears in a challenged spec) |

## Tradeoff Decisions

| Decision | Winner | Loser / Risk | Evidence |
|----------|--------|--------------|----------|
| Standalone script over harness reuse | Designer (stable, decoupled seam) + implementer (simple stub testing) | Loses harness's battle-tested claude-CLI handling; SUE re-derives CLI quirks from scratch | Design non-goals (IN-REQ-D9CE68110258); risks.md knowledge risk on `ai_cli_backend` expertise |
| Two isolated calls over one conversational session | Designer (grounding-rule integrity — blind round-2 reader) | Costs a second model call and forbids cross-round repair (round-2 failure never re-runs round 1) | IN-REQ-3709F66E4C4E, IN-REQ-7906C2CCFEBC; mental-model retry pattern |
| Overwrite-on-rerun, no history | Implementer simplicity | Operators lose run-to-run comparison; concurrent runs interleave writes (accepted for a manual tool) | IN-REQ-AF7AFAF68FBD; unknowns.md concurrency note |

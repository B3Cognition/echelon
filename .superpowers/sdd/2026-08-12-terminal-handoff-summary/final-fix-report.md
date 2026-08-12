# Terminal Handoff Summary — Final Fix Report

Date: 2026-08-13
Branch: `feat/worked-on-summary-agent`
Starting commit: `3c065a0a`

## Outcome

All Critical, Important, and requested minor-bound findings from the final
whole-branch review are addressed. The implementation was developed with a
RED/GREEN loop and checked against the focused, integration, bundle, and broad
repository suites.

## Finding Resolution

1. **Duplicate direct lifecycle cards**
   - Added one shared direct Phase A terminal-handoff renderer.
   - Integrated `Worked on` and `next` into schema-v2 human/manual recovery,
     legacy safe rewind, legacy human/manual recovery, and submitted-human-answer
     cards.
   - Added real Typer front-door tests through the production wrapper/handler
     boundary. Every family asserts one lifecycle card, one `Worked on` section,
     and no standalone `WORKED ON` or `NEXT STEP` card.

2. **Stale provider provenance**
   - Added the shared `harness.provider_limits` lifecycle API.
   - Provider observations now persist a cleaned message plus exact phase and
     termination provenance.
   - New dispatch and recovery transitions, successful convergence, and every
     non-provider terminal publication clear the message, provenance, and reset
     hint together.
   - Readers fail closed unless both current phase and reason exactly match.
   - The controller-state-contract/provider dual-cause path is retained: the
     authoritative controller failure remains the stop and the matching provider
     observation remains supplemental evidence.

3. **Unsafe provider text**
   - Centralized extraction/render cleaning for OSC, DCS/SOS/PM/APC, CSI,
     two-byte ESC forms, C0, DEL, and C1 controls, including unterminated string
     sequences.
   - Normalized whitespace and bounded provider text to 240 characters at
     adapter, fulfillment extraction, Ralph extraction, evidence, aggregation,
     and rendering boundaries.
   - Exact already-safe provider messages remain unchanged.

4. **Ungrounded Phase A and delivery evidence**
   - Phase A now derives outcomes, decisions, and artifacts from completed
     phases, publication state, the issue-resolution ledger, resolved decisions,
     quality records, and lifecycle commits.
   - Generic ad-hoc `outcomes`, `decisions`, and `artifacts` keys are ignored.
   - Delivery exposes exact bounded verification failures as stable candidates;
     the first failure is required for a failed verification result.

5. **Superseded documentation**
   - Replaced the obsolete worked-on design and implementation-plan contracts
     with concise supersession records pointing to the terminal-handoff design.
   - The retained baseline documents the closed `{"line_ids": [...]}` schema,
     four-to-eight plain lines, controller-owned prose, current evidence sources,
     lifecycle integration, provenance, and bounds.

6. **Minor output bounds**
   - Every candidate and final rendered line is bounded to 280 characters.
   - The complete `Worked on` value is bounded to 900 characters.
   - Uniform deterministic compaction preserves selected ordering, line count,
     and all required facts across fallback, valid-model, and defensive render
     paths. Selection evidence remains at or below 12 KiB.

## TDD Evidence

- Lifecycle direct-card tests failed before the integrated renderer and passed
  after all five continue families plus resume were migrated.
- Provider provenance tests failed before transition-scoped persistence/clearing
  and passed after squad, Ralph, coordinator, CLI, and delivery aggregation used
  the shared API.
- Hostile provider tests failed before shared cleaning, including a separately
  discovered C1 OSC payload and non-CSI/unterminated escape regression; all pass
  with the centralized cleaner.
- Production-state evidence and exact verification-failure candidate tests failed
  against generic-key extraction and passed after source-specific derivation.
- Oversized fallback/model/format tests failed before final compaction and pass
  while preserving ordering and required facts.
- A broad-suite ordering failure exposed `ECHELON_SQUAD_ACTIVE` leakage in the new
  resume E2E fixture; the isolated test passed before the fix but failed in the
  full suite. Explicit environment cleanup fixed the suite-order regression.
- Final diff review added fail-closed missing-phase provenance, terminal Phase A
  reason precedence, manual-phase pre-guard clearing, complete ECMA-48 string
  stripping, and composed fulfillment-reason bounds as new RED regressions.

## Verification

- `pytest tests/unit/test_worked_on_summary.py ... tests/unit/test_run_skill.py -q`
  — **263 passed**.
- `pytest tests/integration/test_squad_controller.py -k 'provider or preparation or advance_failure' -q`
  — **38 passed, 342 deselected** before the final manual-phase regression;
  final selected rerun — **39 passed, 342 deselected**.
- Provider cleaner/adapter/fulfillment focused run — **56 passed** at the first
  complete sanitizer milestone; final affected-path suite included below.
- `./scripts/bash/dry-run.sh` — **9/9 bundle checks passed**.
- First broad run, `pytest tests/unit tests/integration/test_squad_controller.py -q`
  — **6568 passed, 3 failed**. One branch-owned E2E environment-isolation failure
  was fixed. The remaining two capability-policy failures reproduce identically
  at untouched branch baseline `3c065a0a`.
- Broad clean-signal rerun excluding only that reproduced baseline file —
  **6568 passed** in 10m31s.
- Final affected-path suite across CLI, orchestrator, coordinator, squad, Ralph,
  provider, fulfillment, and summary modules — **929 passed**.
- Final post-review provider/fulfillment/Ralph focused suite — **226 passed**;
  final sanitizer/evidence/adapter suite — **129 passed**.
- Python `compileall` — passed.
- `git diff --check` — passed.
- Prescribed `ruff check` could not run because `ruff` is not installed in the
  worktree virtual environment or on `PATH`.

## Remaining Concerns

- Two tests in `tests/unit/test_extension_capability_policy.py` fail on the
  feature branch baseline itself because the branch's generated Prosaic model
  tiers do not match that older test contract. This is unrelated to terminal
  handoffs and was not modified. Current `main` has since changed that baseline
  and its capability-policy test passes.
- The plan's live disposable provider exercise was not repeated in this final
  fix wave; the existing complete transcript regression and real Typer
  front-door tests cover the terminal structure deterministically without
  consuming provider capacity.

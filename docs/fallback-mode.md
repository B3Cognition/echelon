# Fallback Mode: External Dependency Degradation

## Purpose

Document mandatory degraded behavior when external dependencies are unavailable, with immediate focus on spec-kit for Tier 1 stories 001a-001c.

## Detection Policy

1. COMMANDER runs dependency preflight before WHAT dispatch.
2. spec-kit probe executes availability and version checks with 2-second timeout.
3. Failures are classified as unavailable, timeout, or incompatible.

## Runtime Behavior

1. System sets fallback_mode=true and execution_mode=manual_specification.
2. CARTOGRAPHER still produces required artifacts without spec-kit automation.
3. No phase skipping is allowed; quality gates still execute.

## Artifact Marking

All fallback artifacts include:

1. FALLBACK STATUS: UNVALIDATED_DEPENDENCY
2. dependency name
3. run identifier
4. generation timestamp

## Logging

1. state.json includes dependency_checks and dependency_fallbacks.
2. reasoning-journal.json includes dependency_failure and fallback_recovery entries.
3. quality degradation is surfaced in checkpoint summary.

## Recovery

1. On successful probe in a later run, fallback_mode is cleared.
2. Recovery event is logged as `fallback_recovery` with `prior_run_id` and `recovery_run_id`.
3. Run the reconciliation checklist in `templates/recovery-checklist.md` for all fallback artifacts.
4. Re-run artifact comparison and capture reconciliation notes in `reasoning-journal.json`.

## Remediation Steps

1. Re-run preflight to confirm spec-kit is available.
2. Execute normal CARTOGRAPHER path to regenerate authoritative artifacts.
3. Use `templates/recovery-checklist.md` to compare and reconcile prior fallback outputs.
4. Confirm `fallback_recovery` entry exists and references both run IDs.
5. Close remediation by updating checkpoint summary with reconciliation outcome.

## Constitution Mapping

1. Principle VII: fallback documented and never silent.
2. Principle VI: quality gates remain active in degraded mode.
3. Principle XII: unresolved repeated dependency failures escalate to human.

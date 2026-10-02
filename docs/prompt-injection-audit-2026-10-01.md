# Prompt-injection boundary check, 2026-10-01

Scope: focused Echelon provider/acceptance regression checks and a synthetic
macOS host-boundary probe. No real model, private credential, live production
run, human checkpoint approval or publication was used. Existing pending Python
Prosaic installer/dependency changes were preserved, not recreated.

## Results and fixes

Local focused verification: **148 passed**, covering Python Prosaic bundle
installation, optional-codegen installer contracts, real macOS Claude scope
probes, provider artifact/result admission, Runtime adapter compatibility,
provider policies and controlled delivery boundaries. This is not the full
Echelon suite and does not include a real model red-team trial.

`tests/unit/test_prompt_injection_boundaries.py` checks that hostile prompt text
cannot enable Bash or the unsafe bypass in exclusive Claude review mode, even
when the host has its unsafe flag set. A real sandbox-exec probe also records
the residual ability to read an unrelated synthetic host file.

The probe exposed invalid `(require-all)` rules when sandbox exclusion lists
are empty. The profile now emits unfiltered allow rules for empty exclusions,
preserving intended behavior rather than producing invalid Seatbelt syntax.
This is a syntax/availability fix, not new isolation.

The existing real-Claude-boundary rejection test had stale expectations of
three rounds and a stop after the spec guard. Current controller code collects
all independent reviews and allows five rounds. Its assertions now follow
`MAX_GATE_ROUNDS`, retaining the key safety assertion: a spec guard FAIL cannot
be erased by later passing reviews, and the candidate remains rejected.

## Remaining gap — do not treat this as full host isolation

`_workspace_sandbox_profile` excludes selected forbidden paths and restricts
review writes, but also allows other host reads and `(allow network*)`. Native
provider tool rules add controls, but this host boundary alone does not isolate
credentials or prevent egress. The synthetic read is evidence of available
host authority, not a claim that a real Claude/Codex model exfiltrated data.

Next priority: a consumer-owned sandbox contract that isolates host secrets,
protects controller state, limits mounts/writes, and controls tool egress while
preserving necessary provider authentication. Follow with adversarial local,
Codex and Claude trials in disposable canary workspaces. Keep spec truth,
assignment admission, approval and publication policy in Echelon; do not move
these product rules into neutral Prosaic or Runtime.

The audit began against Echelon's Runtime v0.2.0 pin. The subsequent integration
now pins Python Prosaic v0.3.0 and Runtime v0.5.1 to immutable release commits;
the Echelon adapter regressions exercise those installed dependencies. Standalone
Runtime tests are not a substitute for these downstream checks.

# Feature-Scoped Harness Policy Design

## Goal

Make a clarification an authoritative, immutable decision for one Phase A run,
while rejecting unsafe `spec run` invocations before any agent dispatch.

## Design

`echelon spec resume` will derive a versioned policy from the recorded answer
and persist both a machine-readable policy and a human-readable decision receipt
under that run's staging directory. The policy is copied into controller state
only as an integrity-checked projection; the receipt remains the provenance
record. It never changes `.echelon/config.yml`.

The policy derives explicit scope exclusions (for example deployment and
backend) and verification waivers (compliance, accessibility suite, and visual
regression) from unambiguous clarification language. The controller rebuilds
run context after persistence, so every subsequent phase receives the rendered
policy. Existing Phase A artifacts are scanned deterministically for rejected
production-scope terms. Their findings are retained in a reconciliation report;
the resumed route is a narrow repair at WHAT when contradictions exist, and the
report requires replacements to label the prior assumption `refuted` or
`descoped` rather than erase it.

Quality thresholds stay global defaults. Per-feature waived dimensions are
removed only from the effective threshold set used by WHY scoring and routing.
No numeric threshold is requested for a waived or inapplicable dimension.

## CLI Safety

`spec run` accepts only documented options. Unknown option tokens, notably
`--source`, fail with an error that directs users to `--target`; they must not
be appended to the description. Target resolution returns exactly one discovered
source or requested target; it exits when no source root exists and never
silently chooses `.`.

## Verification

Unit tests will cover target rejection, missing target resolution, policy
derivation/persistence, context propagation, reconciliation, effective quality
waivers, and the repair route. Existing CLI/controller tests cover integration
contracts around resumption and Phase routing.

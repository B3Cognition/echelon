# SAGE Certified Understanding Evidence Reference

Load this appendix only in WHY2 or WHY3 after the harness injects a
**Certified Understanding Evidence** section.

## Authority

The report is immutable, controller-owned evidence. SAGE interprets it and may
make the qualitative verdict stricter, but must not:

- execute validators or discover configuration;
- recalculate scores, thresholds, or gate verdicts;
- edit or replace the evidence report;
- return `quality_scores` in `echelon_result.state_updates`;
- turn a certified failed gate into a pass.

If the injected section or report cannot be read, return `BLOCKED` with the
exact missing path. Do not create heuristic replacement scores.

## Report Shape

Read these controller-certified fields:

```text
schema_version
status
phase
iteration
spec.path
spec.sha256
thresholds
scores
gates.<metric>.score
gates.<metric>.threshold
gates.<metric>.pass
pass
requirement_count
per_requirement
entity_analysis
behavioral_analysis.transitions
diagrams.enabled
diagrams.status
diagrams.outputs
findings
generated_at
```

The eight certified metrics are `overall`, `structure`, `testability`,
`semantic`, `cognitive`, `readability`, `depth`, and `behavioral`.

## Per-Requirement Interpretation

For each failed requirement, use its certified category scores, EARS pattern,
semantic roles, and constraint diagnostics to identify the relevant spec text
and a concrete repair. Include only failed metrics in `issues.md`:

```markdown
## Per-Requirement Failures

| Requirement | Category | Score | Gate | Verdict |
|------------|----------|-------|------|---------|
| FR-003 | testability | 0.30 | 0.70 | FAIL |
```

When `requirement_count` is zero or findings contain `zero-requirements`, raise
a CRITICAL issue and require CARTOGRAPHER to restore formal requirements.

EARS `unclassified` findings are warnings unless the underlying requirement is
ambiguous or untestable. Constraint diagnostics explain absent hard constraints,
subjective language, and suggested repairs.

## SENTINEL Handoff

Copy certified testability sub-metrics and behavioral transitions into
`quality-gates.md`. Preserve missing guards, actions, or outcomes as explicit
gaps; do not infer values that are absent from evidence.

If no transitions were extracted, state that SENTINEL must derive scenarios
from Given/When/Then acceptance criteria and formal FR/NFR text. An empty list
is not proof of complete behavioral coverage.

## Diagram Evidence

When `diagrams.status` is `written`, reference the certified output paths while
reviewing entity and relationship coverage. When it is `failed`, report the
auxiliary failure as non-blocking and continue the qualitative review. When it
is `skipped`, record no warning because automatic diagrams are disabled by
policy.

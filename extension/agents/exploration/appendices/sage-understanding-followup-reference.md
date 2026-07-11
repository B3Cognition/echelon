# SAGE Understanding Follow-Up Reference

Load this appendix only after `speckit.echelon.understanding-validate` succeeds in spec-validation mode and `/tmp/u_validate.json` exists.

## Validation Output

The validation run writes its machine-readable output here:

```bash
understanding "$SPEC_PATH" --validate --json --output /tmp/u_validate.json
```

Do not read `/tmp/understanding_output.json`; that path is not part of the Understanding contract.

`understanding --validate` exits with code 1 when quality gates fail. If
`/tmp/u_validate.json` exists and parses as JSON, validation completed; use the
scores in the file and report gate failures. Do not mark Understanding
unavailable for this case.

## Per-Requirement Analysis

Invoke Understanding with per-requirement mode and write to a temp file to avoid stdout/stderr mixing:

```bash
understanding "$SPEC_PATH" --enhanced --per-req --json --output /tmp/u_perreq.json
```

The output is a JSON list. The first element `[0]` contains all data:

```text
[0].metrics.overall_weighted_average
[0].metrics.category_averages
[0].requirement_count
[0].per_requirement[].requirement_id
[0].per_requirement[].requirement_text
[0].per_requirement[].metrics.category_averages
[0].per_requirement[].ears_pattern
[0].per_requirement[].constraint_diagnostics.hard_constraints
[0].per_requirement[].constraint_diagnostics.soft_words
[0].per_requirement[].constraint_diagnostics.diagnosis
```

There is no top-level `quality_gates`, `category_scores`, or `requirements` key.

Extract scores with jq:

```bash
jq -r '.[0].metrics.overall_weighted_average' /tmp/u_perreq.json
jq -r '.[0].metrics.category_averages' /tmp/u_perreq.json
jq -r '.[0].requirement_count' /tmp/u_perreq.json
```

If `requirement_count == 0`, `_parse_requirements` found no bullet-form requirements. Flag this as a CRITICAL issue in `issues.md` and require CARTOGRAPHER to restore `- **ID**: text` bullet form for all requirements.

Load thresholds from config:

```bash
bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh quality_gates
```

For each requirement, compare category scores against config thresholds. Include only failing requirements and failing metrics in `issues.md`:

```markdown
## Per-Requirement Failures

| Requirement | Category | Score | Gate | Verdict |
|------------|----------|-------|------|---------|
| FR-003 | testability | 0.30 | <threshold from config> | FAIL |
```

If all requirements pass, write: `## Per-Requirement Failures\n\nNone - all requirements pass all category gates.`

For failing requirements, include constraint diagnostics:

- `hard_constraints`: number of numeric thresholds found; 0 means untestable.
- `soft_words`: subjective words such as `fast` or `appropriate`.
- `diagnosis`: human-readable fix suggestion.

## Behavioral Diagram

Use the Skill tool:

```text
speckit.echelon.understanding-diagram <spec_directory>/spec.md
```

Pass diagram output through `--diagram <path.ext>`; do not pass standalone `--png`, `--svg`, or similar flags.

Required outputs:

- `<spec_directory>/spec-diagram.svg`
- `<spec_directory>/spec-diagram.png`

Use the diagram to verify completeness, testability, and implementation traceability. If diagram generation fails after validation succeeds, log a `diagram_skipped` journal entry and continue. Missing Graphviz `dot` is not blocking.

```json
{"type": "diagram_skipped", "agent": "speckit-echelon-sage (SAGE)", "reason": "<brief reason>", "phase": "<current phase>"}
```

## Quality Gate Metrics

Load thresholds from config and record actual scores for:

- `overall`
- `structure`
- `testability`
- `semantic`
- `cognitive`
- `readability`
- `depth`
- `behavioral`

For metrics below threshold, identify the spec sections pulling the score down and suggest specific improvements.

## EARS Pattern Gaps

If per-requirement JSON includes `ears_pattern`, count requirements by category: ubiquitous, event_driven, state_driven, optional, unwanted, unclassified.

If any requirements are `unclassified`, add:

```markdown
## EARS Pattern Gaps

{N} of {total} requirements match no EARS pattern (Mavin et al., 2009).
Unclassified requirements may have unclear intent - review for clarity.

| Requirement | Text Preview | Suggested Pattern |
|------------|-------------|-------------------|
| FR-007 | "The system should handle..." | Consider: ubiquitous (add SHALL) or event_driven (add WHEN trigger) |
```

EARS gaps are review warnings, not automatic failures.

## SENTINEL Handoff Metrics

Extract testability sub-metrics and include them in `quality-gates.md`:

```markdown
## Testability Sub-Metrics (for speckit-echelon-sentinel (SENTINEL) consumption)

| Sub-Metric | Score | Interpretation |
|-----------|-------|---------------|
| hard_constraint_ratio | {score} | Proportion of requirements with numeric/quantitative thresholds |
| constraint_density | {score} | Average measurable constraints per requirement |
| negative_space_coverage | {score} | Proportion of requirements specifying error/edge/boundary cases |
```

Extract `.[0].behavioral_analysis.transitions` from enhanced JSON and include:

```bash
jq -r '
  (.[0].behavioral_analysis.transitions // [])[]
  | [
      (.guard // "-"),
      (.action // "-"),
      (.outcome // "-"),
      ((.is_complete // false) | tostring),
      ((.requirement_index // "-") | tostring)
    ]
  | @tsv
' /tmp/u_perreq.json
```

The Understanding JSON root is a list. Do not query `.behavioral_analysis.transitions[]`
as a top-level object path; that causes jq errors and empty handoff evidence.

If `.[0].behavioral_analysis.transitions // []` is empty, write `None extracted -
Understanding returned no behavioral transitions; SENTINEL must derive tests from
Given/When/Then acceptance criteria and FR/NFR bullets.` Do not treat an empty
transition list as complete behavioral coverage. If any cell is `-`, preserve it
in the table and call out the missing guard/action/outcome data as a SENTINEL
handoff warning.

```markdown
## Behavioral Transitions (for speckit-echelon-sentinel (SENTINEL) consumption)

| # | Guard | Action | Outcome | Complete | Requirement |
|---|-------|--------|---------|----------|-------------|
| 1 | when | validate | display | true | requirement_index: 3 |
```

SENTINEL maps transitions to Given/When/Then test case templates.

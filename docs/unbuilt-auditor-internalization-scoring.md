# Unbuilt Feature: Auditor Per-Agent Internalization Scoring

**Status:** Planned, not implemented
**Tracked by:** `tests/unit/test-auditor-internalization.sh` (currently failing — 16 assertions)
**Related agents:** `agents/learning/auditor.md`, `agents/learning/internalizer.md`

---

## What it is

The Per-Agent Internalization Scoring protocol is a planned subsystem that measures how accurately each agent absorbs and applies its prompt instructions across runs. It extends the existing calibration system (which tracks domain-level accuracy) down to the per-agent level.

The design defines 16 metrics grouped into 4 categories:

| Category | Metrics | What it measures |
| --- | --- | --- |
| **Absorption** (I-01 – I-04) | requirement_coverage, constraint_adherence, dependency_awareness, format_compliance | Did the agent read and apply its instructions? |
| **Accuracy** (I-05 – I-08) | numeric_contradiction, keyword_scope, temporal_consistency, context_preservation | Did the agent produce correct outputs? |
| **Calibration** (I-09 – I-12) | confidence_accuracy, escalation_precision, threshold_application, evidence_grading | Did the agent know what it didn't know? |
| **Transfer** (I-13 – I-16) | first_pass_acceptance, priority_alignment, cross_agent_consistency, retrospective_fit | Did the agent's work hold up downstream? |

A composite score per agent (weighted average across categories) would feed trend tracking (`improving`, `declining`, `stable`) stored in `knowledge-base/agent-scores.yaml` under an `internalization:` sub-object.

## What exists today

- `agents/learning/internalizer.md` — the INTERNALIZER agent is defined and registered in `extension.yml`
- `commander.md` §"Per-Agent Internalization Data Handoff" — the dispatch sequence (INTERNALIZER → AUDITOR) is documented
- `phase4-document.md` §12.4 — the FINALIZE step that invokes INTERNALIZER before AUDITOR is described
- `knowledge-base/agent-scores.yaml` — the file exists but does not yet contain an `internalization:` sub-object

## What is missing

- The `## Per-Agent Internalization Scoring` section in `auditor.md` (the 16-metric protocol itself)
- The `internalization:`, `category_scores:`, `metric_values:`, and `history:` schema in `agent-scores.yaml`
- Composite score computation logic
- Trend classification rules (`improving` / `declining` / `stable`)
- Null-vs-zero distinction and history cap (20 entries) rules

## Why the tests are failing

`tests/unit/test-auditor-internalization.sh` was written ahead of the implementation — it specifies the desired behaviour so the feature has a clear acceptance contract when built. This is intentional: the test defines what "done" looks like.

The 16 failing assertions should all pass once the implementation is complete. Do not delete the tests; they are the spec.

## Implementation notes

When building this:

1. Add the `## Per-Agent Internalization Scoring` section to `auditor.md` with all 4 categories and the 16 metrics.
2. Define the `internalization:` sub-object schema in `knowledge-base/agent-scores.yaml` (or document it in a schema file).
3. Implement composite score = weighted average: Absorption 0.30, Accuracy 0.30, Calibration 0.20, Transfer 0.20.
4. Trend: `improving` if last 3 composite means are monotonically increasing; `declining` if monotonically decreasing; `stable` otherwise.
5. `null` (metric could not be measured) is distinct from `0.0` (metric was measured and scored zero).
6. Cap history at 20 entries; remove oldest on overflow.

The INTERNALIZER agent itself should compute metrics I-01 through I-16 per agent and write results; AUDITOR reads them and produces `calibration-dashboard.md`.

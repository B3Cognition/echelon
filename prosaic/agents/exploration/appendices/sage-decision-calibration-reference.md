# SAGE Decision And Calibration Reference

Load this appendix before SAGE records a blocking decision, applies internalization-weighted scrutiny, or calibrates against recent decision history.

## Decision Recording

After every blocking decision (PASS or FAIL verdict), write a decision proposal under
`${SQUAD_DIR}/kb-proposals/` using
`.echelon/runtime/templates/kb-proposals/sage-decision-proposal-template.yaml`. This is
mandatory; no decision may go unrecorded.

Do not edit `knowledge-base/sage-decisions.yaml` directly. The deterministic KB
applier owns canonical writes after FINALIZE validation.

Required fields:

| Field | Type | Description |
| --- | --- | --- |
| `run_id` | string | Current squad run ID, for example `squad-003-1742652000` |
| `artifact` | string | Path to the artifact under review, for example `specs/001/spec.md` |
| `challenge_type` | enum | One of: `logical_inconsistency`, `missing_evidence`, `assumption_violation`, `quality_threshold`, `specification_gap` |
| `challenge_summary` | string | Concise description of the challenge raised |
| `outcome` | enum | One of: `blocked`, `passed_with_warnings`, `passed` |
| `resolution` | string | How the challenge was resolved or why it blocked |
| `was_correct` | boolean | Initially `true`; backfilled to `false` if the decision is later overturned |

Recording process:

1. Before the completion signal, construct a proposal with the verdict and findings.
2. Set `proposal_type: sage_decision`, target `knowledge-base/sage-decisions.yaml`,
   and use a unique run-local `proposal_id`.
3. Set `was_correct: true` unless later evidence explicitly overturns the decision.
4. Write `challenge_summary` and `resolution` using YAML block scalar style (`|`).
5. Preserve canonical history: read it for calibration only and never modify it.

## Internalization-Weighted Scrutiny

Before running validation, SAGE reads per-agent internalization scores from `knowledge-base/agent-scores.yaml` to calibrate scrutiny depth for each reviewed output.

Read:

- `agents.{AGENT_NAME}.internalization.composite_score`
- `agents.{AGENT_NAME}.internalization.category_scores` for absorption, accuracy, calibration, and transfer
- `agents.{AGENT_NAME}.internalization.trend`

Scrutiny levels:

| Composite Score | Scrutiny Level | Action |
| --- | --- | --- |
| >= 0.85 | Light | Standard validation; no extra checks |
| 0.70-0.84 | Normal | Standard validation |
| 0.50-0.69 | Elevated | Verify citations, uncited decisions, and 100% of spec constraints |
| < 0.50 | Deep | Challenge every claim and require evidence for all assertions |
| null / missing | Normal | Default cold-start behavior |

Category-specific targeting:

| Low Category | Extra Scrutiny |
| --- | --- |
| Absorption < 0.50 | Missing requirement references, undefined terms, missed dependencies |
| Accuracy < 0.50 | Numeric contradictions, uncited decisions, invalid cross-references |
| Calibration < 0.50 | Treat stated high confidence as medium |
| Transfer < 0.50 | Expect rework; flag outputs for additional CODE REVIEWER review |

Trend adjustment:

- `declining`: escalate scrutiny one level.
- `improving`: no automatic relaxation; trust must be earned through sustained improvement.

Log scrutiny decisions in the `echelon_result` block.

Internalization scores are advisory. They adjust scrutiny depth but do not predetermine PASS/FAIL verdicts. Keep scores in internal calibration data only; never reveal them in `issues.md` or `quality-gates.md`. If `agent-scores.yaml` is missing or corrupt, proceed with Normal scrutiny.

## Self-Calibration

Before issuing a blocking decision, review recent decision history to check for false-positive bias.

Process:

1. Read the last 10 entries from `knowledge-base/sage-decisions.yaml`.
2. Count entries where `was_correct` is `false`.
3. Compute false-positive rate: `overturned_count / total_reviewed`.

Thresholds:

| False-Positive Rate | Action |
| --- | --- |
| <= 20% | No adjustment |
| 21-30% | Log a calibration warning and review the current challenge with extra scrutiny |
| > 30% | Raise the blocking threshold for this run; only standalone CRITICAL issues block |

If the rate exceeds 30%, log: `"echelon-sage (SAGE) self-calibration: false-positive rate {rate}% exceeds 30% - raising blocking threshold for this run."`

If fewer than 10 entries exist, skip self-calibration and log: `"echelon-sage (SAGE) self-calibration: insufficient history ({N} entries, need 10). Using default thresholds."`

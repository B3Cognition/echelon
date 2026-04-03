# API Contracts — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: ARCHITECT (HOW agent)
**Date**: 2026-04-03
**Spec**: 017-ns003-ca-overlays
**Constitution version**: 1.1.0

These contracts define the CLI interfaces for all scripts in spec 017. IMPLEMENTER must match these interfaces exactly. Any deviation requires a new ADR entry.

---

## 1. `scripts/ns003_critic.py` — NS-003-A Schema Validator

### Purpose

Validates a single Echelon agent artifact against its category JSON schema. Produces a per-field PASS/FAIL report with confidence scores. Implements the two-component design from ADR-002 (deterministic JSON Schema + Claude API prose assessment).

### CLI Interface

```
usage: ns003_critic.py [-h] --artifact ARTIFACT --schema-dir SCHEMA_DIR
                        [--category {DISCOVER,ASSESS,HOW,PLAN,BUILD,LEARN}]
                        [--output OUTPUT]
                        [--timeout TIMEOUT]
                        [--dry-run]
                        [--verbose]

NS-003-A Schema Validator — validates a single Echelon artifact against its
category JSON schema using deterministic field validation and Claude API
prose-structure assessment.

required arguments:
  --artifact ARTIFACT   Absolute or relative path to the Markdown artifact
                        file to validate. Must be a readable .md file.
                        (FR-NS3A-001)

  --schema-dir SCHEMA_DIR
                        Path to the directory containing the 6 category JSON
                        schemas: discover.json, assess.json, how.json,
                        plan.json, build.json, learn.json.
                        Exit code 2 if any required schema is missing.
                        (FR-NS3A-ERR-003)

optional arguments:
  -h, --help            Show this help message and exit. Must complete without
                        error even if ANTHROPIC_API_KEY is absent.
                        (FR-DEP-002)

  --category {DISCOVER,ASSESS,HOW,PLAN,BUILD,LEARN}
                        Force the artifact category for schema selection.
                        If omitted, the validator infers the category from
                        the artifact filename using ARTIFACT_STAGE_MAP.
                        If inference fails, exit with code 1.

  --output OUTPUT       Path to write the JSON validation report.
                        If omitted, prints report to stdout.
                        If a partial run was interrupted by API auth failure,
                        writes PARTIAL_RESULTS to this path.
                        (FR-NS3A-ERR-002)

  --timeout TIMEOUT     Per-artifact API call timeout in seconds.
                        Default: 30. Must be a positive integer.
                        (FR-NS3A-004)

  --dry-run             Run schema parsing and JSON Schema validation only.
                        Skip the Claude API prose-assessment component.
                        Useful for schema calibration without API cost.

  --verbose             Print per-field verdict details to stderr during
                        processing.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Validation completed successfully (PASS or FAIL verdict produced) |
| 1 | Runtime error: ANTHROPIC_API_KEY absent, artifact not found, category inference failed |
| 2 | Schema configuration error: a required schema file is missing or malformed (FR-NS3A-ERR-003) |

### Output JSON Format (to `--output` or stdout)

```json
{
  "schema_version": "1.0.0",
  "artifact_path": "<path>",
  "artifact_category": "DISCOVER",
  "validation_timestamp": "<ISO 8601>",
  "model_identifier": "claude-sonnet-4-6",
  "overall_verdict": "PASS | FAIL | TIMEOUT | SKIP",
  "elapsed_seconds": 0.0,
  "structured_to_prose_ratio": 0.0,
  "per_field_verdicts": [
    {
      "field_name": "scope_statement",
      "verdict": "PASS | FAIL",
      "confidence": 0.95,
      "component": "deterministic | prose_assessment",
      "reason": "Field present and non-empty | Field absent | Prose section ABSENT"
    }
  ],
  "partial_results": false,
  "error": null
}
```

When `partial_results = true`: the error field contains the API error string and `overall_verdict` is `"PARTIAL"`.

When `overall_verdict = "SKIP"`: artifact had fewer than 10 characters (FR-NS3A-ERR-004). `per_field_verdicts` is empty.

### Environment Variables Required

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | YES (unless `--dry-run`) | Claude API authentication key. Checked at startup; exit code 1 if absent. |

---

## 2. `scripts/ns003_agm.py` — NS-003-B AGM Belief Revision Engine

### Purpose

Processes Echelon artifacts in pipeline order, extracts field assertions, maintains a BeliefGraph with AGM K*2 minimal revision, and produces a contradiction report. Post-hoc mode only (ADR-001).

### CLI Interface

```
usage: ns003_agm.py [-h] --artifact-dir ARTIFACT_DIR
                     [--mode {post-hoc,pre-commit}]
                     [--belief-graph BELIEF_GRAPH]
                     [--output OUTPUT]
                     [--run-id RUN_ID]
                     [--verbose]

NS-003-B AGM Belief Revision Engine — detects post-hoc contradictions across
Echelon pipeline artifact stages using AGM K*2 minimal revision logic.

IMPORTANT: pre-commit mode is NOT implemented in v1 per ADR-001 (IS-003
resolution). Specifying --mode pre-commit will print a deprecation notice
and proceed in post-hoc mode.

required arguments:
  --artifact-dir ARTIFACT_DIR
                        Path to a directory containing Echelon artifact .md
                        files from a single spec run. Files are processed in
                        pipeline stage order: DISCOVER → ASSESS → HOW →
                        PLAN → BUILD → LEARN. Unrecognized filenames are
                        skipped with a warning.

optional arguments:
  -h, --help            Show this help message and exit.

  --mode {post-hoc,pre-commit}
                        Operating mode. Default: post-hoc.
                        post-hoc: reads completed artifact files and produces
                        a contradiction report. (AC-2.1, FR-NS3B-004)
                        pre-commit: NOT IMPLEMENTED IN V1 — prints notice and
                        proceeds as post-hoc. (ADR-001 IS-003 resolution)

  --belief-graph BELIEF_GRAPH
                        Path to the BeliefGraph JSON persistence file.
                        If the file exists, the existing graph is loaded and
                        extended. If absent, a new graph is initialized.
                        Default: .specify/squad/belief-graph-<run_id>.json
                        (FR-NS3B-ERR-002 atomic write requirement applies)

  --output OUTPUT       Path to write the contradiction report JSON.
                        Default: experiments/ns003-contradiction-report.json
                        (FR-NS3B-006)

  --run-id RUN_ID       Run identifier string (UUID4 or human-readable).
                        Used for BeliefGraph filename default and record
                        metadata. If omitted, generated as UUID4 at startup.

  --verbose             Print per-assertion extraction details to stderr.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Processing completed successfully |
| 1 | Runtime error: artifact-dir not found, BeliefGraph write failure |
| 2 | Configuration error (reserved for future schema dependency) |

### Output JSON Format (to `--output`)

```json
{
  "schema_version": "1.0.0",
  "run_id": "<uuid4>",
  "mode": "post-hoc",
  "artifact_dir": "<path>",
  "belief_graph_path": "<path>",
  "processing_timestamp": "<ISO 8601>",
  "artifacts_processed": 0,
  "assertions_extracted": 0,
  "conflicts_detected": 0,
  "contradiction_report": [
    {
      "field_identifier": "req_scope",
      "contradiction_type": "scope_conflict",
      "confidence": 0.7,
      "existing_value": "auth_only",
      "existing_stage": "DISCOVER",
      "existing_artifact": "<path>",
      "new_value": "auth_and_api",
      "new_stage": "ASSESS",
      "new_artifact": "<path>",
      "recommended_action": "revert"
    }
  ]
}
```

### Environment Variables Required

None. The AGM engine is fully deterministic and requires no API access.

---

## 3. `scripts/ns003_experiment.py` — NS-003 Experiment Runner

### Purpose

Orchestrates N=30 Echelon invocations (live or historical_artifacts fallback), validates each artifact via `ns003_critic.py`, runs the AGM engine, computes FPCR / CCR / FPR metrics, and produces the experiment result package. Implements FR-NS3E-001 through FR-NS3E-004.

### CLI Interface

```
usage: ns003_experiment.py [-h] [--n N]
                            [--calibration-set CALIBRATION_SET]
                            [--schema-dir SCHEMA_DIR]
                            [--output-dir OUTPUT_DIR]
                            [--model MODEL]
                            [--timeout TIMEOUT]
                            [--dry-run]
                            [--verbose]

NS-003 Experiment Runner — runs N=30 Echelon invocations and measures FPCR,
CCR, and FPR for the NS-003 schema validator and AGM belief revision engine.

optional arguments:
  -h, --help            Show this help message and exit.
                        Must complete without error even if ANTHROPIC_API_KEY
                        is absent. (FR-DEP-002)

  --n N                 Number of invocations to run.
                        Default: 30. Must be a positive integer.
                        Note: per AC-3.1 / A-010, this value is fixed at 30
                        per the pre-registered design. Changing it requires a
                        documented deviation. (FR-NS3E-001)

  --calibration-set CALIBRATION_SET
                        Path to a directory containing known-good calibration
                        artifacts. Used for Phase 1 false rejection rate check.
                        If omitted, the runner searches for artifacts from
                        spec runs 015-016 in .specify/specs/.
                        If no calibration artifacts are found, exits with
                        code 1 and instructions to provide --calibration-set.
                        (FR-NS3A-005, IS-010)

  --schema-dir SCHEMA_DIR
                        Path to the directory containing category JSON schemas.
                        Default: scripts/schemas/
                        Exit code 2 if any required schema is missing.

  --output-dir OUTPUT_DIR
                        Directory where result files are written.
                        Default: experiments/
                        Creates the directory if it does not exist.
                        Writes: ns003-results.json, ns003-report.md
                        (FR-NS3E-002, FR-NS3E-003)

  --model MODEL         Claude model identifier for API calls.
                        Default: claude-sonnet-4-6
                        Recorded in ns003-results.json. (NFR-REPRO-003)

  --timeout TIMEOUT     Per-artifact API call timeout in seconds.
                        Default: 30. (FR-NS3A-004)

  --dry-run             Run Phase 1 calibration check only. Do not execute
                        live invocations. Useful for schema validation before
                        committing to N=30 API calls.

  --verbose             Print per-invocation progress to stderr.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Experiment completed; results written to output-dir |
| 1 | Runtime error: ANTHROPIC_API_KEY absent, git unavailable for commit hash, calibration set not found |
| 2 | Schema configuration error: required schema file missing or malformed |

### Outputs Written to `--output-dir`

| File | Description |
|------|-------------|
| `ns003-results.json` | Full experiment result package (FR-NS3E-002) |
| `ns003-report.md` | Human-readable report with FPCR classification (FR-NS3E-003) |
| `ns003-contradiction-report.json` | AGM engine output for the full artifact set |

### Phase Sequence (built into the runner)

1. Capture `git rev-parse HEAD` → store as `codebase_commit_hash`. Exit 1 if unavailable.
2. Run Phase 1 calibration: validate calibration set, compute FRR. If FRR > 5%, print warning and require `--proceed-anyway` flag (not default) to continue.
3. Measure structured-to-prose ratio on calibration set. Log per-category ratios.
4. Run N invocations (live or historical_artifacts fallback).
5. Compute FPCR, CCR, FPR.
6. Write `ns003-results.json` and `ns003-report.md`.

### Environment Variables Required

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | YES | Claude API authentication key. Checked at startup. |

---

## 4. `scripts/uca004_runner.py` — U-CA-004 Experiment Runner

### Purpose

Runs N=20 Echelon invocations per condition (BASELINE, CA-ACTIVE), scores each output via the AQS proxy scorer (P-021), applies Mann-Whitney U and Cohen's d statistics, and emits a POSITIVE / NEGATIVE / VOID verdict. Implements FR-UCA-001 through FR-UCA-007 and all FR-UCA-ERR requirements.

### CLI Interface

```
usage: uca004_runner.py [-h] [--conditions CONDITIONS [CONDITIONS ...]]
                         [--n N]
                         [--output-dir OUTPUT_DIR]
                         [--model MODEL]
                         [--timeout TIMEOUT]
                         [--verbose]

U-CA-004 Experiment Runner — controlled experiment comparing BASELINE and
CA-ACTIVE Echelon conditions. Uses automated AQS proxy scorer (P-021).
Produces POSITIVE/NEGATIVE/VOID verdict gating CA overlay implementation.

optional arguments:
  -h, --help            Show this help message and exit.
                        Must complete without error even if ANTHROPIC_API_KEY
                        is absent. (FR-DEP-002)

  --conditions CONDITIONS [CONDITIONS ...]
                        Space-separated list of conditions to run.
                        Valid values: BASELINE CA-ACTIVE
                        Default: BASELINE CA-ACTIVE (both conditions)
                        Example: --conditions BASELINE CA-ACTIVE
                        (FR-UCA-001)

  --n N                 Number of invocations per condition.
                        Default: 20. Fixed per pre-registered design (A-010).
                        Minimum for non-VOID verdict: 16 per condition.
                        (FR-UCA-ERR-002)

  --output-dir OUTPUT_DIR
                        Directory where result files are written.
                        Default: experiments/
                        Creates the directory if it does not exist.
                        Writes: uca004-results.json,
                                uca004-scoring-audit.jsonl,
                                uca004-negative-report.md (if NEGATIVE)
                        (FR-UCA-006, FR-UCA-007, NFR-AUD-001)

  --model MODEL         Claude model identifier for both invocations and
                        AQS proxy scoring.
                        Default: claude-sonnet-4-6
                        Recorded in uca004-results.json. (NFR-REPRO-003)
                        Note: same model produces artifacts and scores them —
                        evaluator circularity limitation applies (ADR-004).

  --timeout TIMEOUT     Per-invocation timeout in seconds.
                        Default: 60.
                        TIMEOUT invocations count against N=20.
                        (FR-UCA-ERR-003)

  --verbose             Print per-invocation AQS scores to stderr.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Experiment completed; verdict written (POSITIVE, NEGATIVE, or VOID) |
| 1 | Runtime error: ANTHROPIC_API_KEY absent, git unavailable for commit hash |

### Outputs Written to `--output-dir`

| File | Description |
|------|-------------|
| `uca004-results.json` | Full experiment result package with verdict (FR-UCA-006) |
| `uca004-scoring-audit.jsonl` | Append-only audit trail, one JSON per line per scoring call (NFR-AUD-001) |
| `uca004-negative-report.md` | Produced only if verdict == NEGATIVE (FR-UCA-007) |

### Verdict Logic (built into the runner)

```
if n_completed_baseline < 16 or n_completed_ca_active < 16:
    verdict = VOID
    void_reason = "<condition> had <N> completions, minimum 16 required"
elif p_value < 0.05 and cohens_d >= 0.5:
    verdict = POSITIVE
    authorized_overlays = [list of 5 overlay paths]
else:
    verdict = NEGATIVE
```

INCONCLUSIVE is not a valid verdict (P-020 binary gate). The negative report MUST include the power limitation disclosure.

### Environment Variables Required

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | YES | Claude API authentication key. Checked at startup; exit 1 if absent. |

---

## 5. `scripts/ca/verify_gate.sh` — CA Overlay Gate-Check Service

### Purpose

Verifies that U-CA-004 has resolved POSITIVE before any CA overlay implementation file may be created. This is the mandatory first step of any CA overlay implementation task (FR-CAO-000, NFR-SCOPE-001).

### CLI Interface

```
usage: verify_gate.sh [--results-file RESULTS_FILE]
                       [--verbose]

CA Overlay Gate-Check Service — verifies U-CA-004 POSITIVE verdict before
any scripts/ca/ implementation file is created.

No arguments are required for standard usage. The script reads
experiments/uca004-results.json relative to the git repository root.

optional arguments:
  --results-file RESULTS_FILE
                        Explicit path to uca004-results.json.
                        Default: <git root>/experiments/uca004-results.json

  --verbose             Print detailed check results to stdout.
```

### Check Sequence

The script performs exactly three checks in order. Fails on first failed check.

| Check | Pass condition | Fail message |
|-------|----------------|--------------|
| 1. Results file exists | `experiments/uca004-results.json` is a readable file | `GATE FAIL: uca004-results.json not found at <path>. Run uca004_runner.py first.` |
| 2. Verdict is POSITIVE | `jq -r '.verdict' uca004-results.json` equals `"POSITIVE"` | `GATE FAIL: verdict is <value>, not POSITIVE. CA overlay implementation is blocked per P-020.` |
| 3. Commit hash matches | `jq -r '.codebase_commit_hash'` equals `git rev-parse HEAD` | `GATE FAIL: commit hash mismatch. Results were produced on <results_hash>; current HEAD is <head_hash>. Re-run uca004_runner.py on the current codebase.` |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All three checks pass. CA overlay implementation is authorized. |
| 1 | One or more checks failed. CA overlay implementation is BLOCKED. |

### No Arguments Required for Standard Usage

The script locates the git repository root via `git rev-parse --show-toplevel` and constructs all paths from that root. IMPLEMENTER must not require the caller to set any environment variable or pass any argument for the standard gate-check use case.

### Environment Variables Required

None beyond a functional `git` binary in PATH.

---

## 6. Shared Module Contracts

### `scripts/md_parser.py` — Shared Markdown Parser

This module is NOT a standalone CLI script. It is imported by `ns003_critic.py` and `ns003_agm.py`. It exposes:

```python
def extract_kv_pairs(markdown_text: str) -> dict[str, str]:
    """
    Extract key-value assertions from Markdown text using the three regex
    patterns from contradiction-scanner.py:
    - Bold-key pairs: **Key**: value
    - KV lines: Key: value (at line start)
    - Table rows: | key | value | (two-column tables only)
    
    Returns: dict mapping normalized key (lowercase, underscores) to value string.
    Generic stop-keys (from _GENERIC_STOP_KEYS in contradiction-scanner.py) are
    excluded from the output dict.
    """
    ...

def extract_section_headers(markdown_text: str) -> list[str]:
    """
    Extract ## and ### level section header names from Markdown text.
    Returns: list of header strings (without # characters), in document order.
    """
    ...

def compute_prose_ratio(markdown_text: str) -> float:
    """
    Compute the ratio of prose characters to total characters.
    Prose = text not in headers, tables, bold-key pairs, or KV lines.
    Returns: float in [0.0, 1.0].
    """
    ...
```

No external dependencies. Standard library only (`re`, `typing`).

---

## 7. Dependency File Contract

### `scripts/requirements.txt`

Must contain exactly these pinned versions (no ranges wider than minor version):

```
anthropic>=0.25.0,<1.0.0
jsonschema>=4.21.0,<5.0.0
scipy>=1.13.0,<2.0.0
pyyaml>=6.0.1,<7.0.0
```

No credentials, API keys, or tokens may appear in this file (P-014, FR-DEP-001).

### `scripts/setup.sh`

Must:
1. Run `pip install -r scripts/requirements.txt`.
2. Run `python3 scripts/ns003_critic.py --help` and exit non-zero if it fails.
3. Run `python3 scripts/uca004_runner.py --help` and exit non-zero if it fails.
4. Print `SETUP OK: all dependencies installed and smoke tests passed.` on success.

(FR-DEP-002, AC-6.1)

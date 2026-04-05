# Implementation Tasks — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: ORCHESTRATOR (PLAN agent)
**Date**: 2026-04-03
**Spec**: 017-ns003-ca-overlays
**Constitution version**: 1.1.0
**Input artifacts**: spec.md, research.md (ADRs 1-6), data-model.md, contracts/ns003_interfaces.md, feasibility.md

---

## Critical Path

The primary critical path through this implementation is:

**T-001 → T-002 → T-003 → T-004 → T-005 → T-006 → T-007 → T-008 → T-009 → T-010 → T-011 → T-012 → T-013 → T-014**

- Phase 0 prerequisites unblock all other phases.
- T-003 (shared Markdown parser) unblocks both NS-003-A (T-004) and NS-003-B (T-009) in parallel after Phase 0.
- NS-003-A validator (T-004 → T-005 → T-006 → T-007 → T-008) feeds the experiment runner (T-013).
- NS-003-B AGM engine (T-009 → T-010 → T-011 → T-012 → T-013) converges into the same runner.
- The experiment runner output (T-013 → T-014) gates Phase 4 (U-CA-004) and by extension Phase 5 (CA Overlays).
- CA Overlay tasks (T-021 through T-027) are CONDITIONAL — blocked by FR-CAO-000 gate check (T-021).

---

## Phase 0 — Foundation Prerequisites

**No dependencies. These tasks must complete before any other phase begins.**

---

### T-001 — Dependency File: `scripts/requirements.txt`

**Phase**: 0 — Foundation
**File path**: `scripts/requirements.txt`
**Dependencies**: none

**Description**: Create the dependency file with the four pinned package version constraints defined in research.md Technology Stack Decision and contracts/ns003_interfaces.md §7.

The file must contain exactly:
- `anthropic>=0.25.0,<1.0.0`
- `jsonschema>=4.21.0,<5.0.0`
- `scipy>=1.13.0,<2.0.0`
- `pyyaml>=6.0.1,<7.0.0`

No additional third-party packages. No credentials, API keys, or tokens (P-014, FR-DEP-001).

**Acceptance Criteria**:
- AC-6.1: `pip install -r scripts/requirements.txt` completes without error.
- FR-DEP-001: File contains no credentials or API keys.
- All four packages are present with the exact version constraints from the contract.

---

### T-002 — Setup Script: `scripts/setup.sh`

**Phase**: 0 — Foundation
**File path**: `scripts/setup.sh`
**Dependencies**: T-001

**Description**: Create the setup and smoke-test script per the contract in ns003_interfaces.md §7. The script must:
1. Run `pip install -r scripts/requirements.txt`.
2. Run `python3 scripts/ns003_critic.py --help` and exit non-zero if it fails.
3. Run `python3 scripts/uca004_runner.py --help` and exit non-zero if it fails.
4. Print `SETUP OK: all dependencies installed and smoke tests passed.` on success.

The `--help` smoke tests must succeed even when `ANTHROPIC_API_KEY` is absent (FR-DEP-002).

**Acceptance Criteria**:
- AC-6.1: Running `./scripts/setup.sh` produces the `SETUP OK` message with all dependencies installed.
- FR-DEP-002: `--help` flag completes without error regardless of API key presence.
- Script exits non-zero if any step fails.

---

### T-003 — ADR-001 Spec Amendment: Update Spec Section 1 Novelty Claim Text

**Phase**: 0 — Foundation
**File path**: `experiments/adr001-amendment-record.md` (new file — amendment record only; spec.md itself is NOT modified per ORCHESTRATOR NEVER rules; this task creates the amendment record that IMPLEMENTER uses when generating documentation and experiment metadata)
**Dependencies**: none

**Description**: ADR-001 (research.md) formally amends the NS-003-B framing in spec.md Section 1. Since ORCHESTRATOR must not modify spec.md, this task creates an amendment record at `experiments/adr001-amendment-record.md` documenting:

- **Original text**: "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph across a spec run and emits pre-commit conflict signals when new assertions contradict existing beliefs"
- **Amended text**: "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph across a spec run and detects post-hoc contradictions when new artifact-stage assertions conflict with existing beliefs already committed to the artifact store"
- **Reason**: ADR-001 — IS-003 resolution, Model B write-wrapper rejected, post-hoc mode only.
- **Effect**: All experiment report templates, metadata files, and CLI help text must use the amended framing. The `--mode pre-commit` flag prints a notice and proceeds as post-hoc (per ADR-001 Consequences).

**Acceptance Criteria**:
- Amendment record file exists and contains both original and amended text strings verbatim.
- All downstream templates (T-014, T-019) reference the amended framing, not the original.
- `ns003_agm.py --mode pre-commit` prints a deprecation/not-available notice (not a silent mode).

---

## Phase 1 — NS-003-A Schema Validator

**Critical path phase. Unblocks Phase 3 experiment runner.**

---

### T-004 — Shared Markdown Parser: `scripts/md_parser.py`

**Phase**: 1 — NS-003-A Schema Validator
**File path**: `scripts/md_parser.py`
**Dependencies**: T-001

**Description**: Implement the shared Markdown extraction module per the contract in ns003_interfaces.md §6. This module is NOT a standalone CLI. It is imported by `ns003_critic.py` (T-005) and `ns003_agm.py` (T-010). Reuse the `_BOLD_KEY_RE`, `_KV_LINE_RE`, and `_TABLE_ROW_RE` regex patterns from `contradiction-scanner.py` (cite source in comments per research.md Design Integration Notes).

Expose three functions per the contract:
- `extract_kv_pairs(markdown_text: str) -> dict[str, str]`: bold-key, KV-line, and table-row extraction with generic stop-key filtering.
- `extract_section_headers(markdown_text: str) -> list[str]`: `##` and `###` level headers in document order.
- `compute_prose_ratio(markdown_text: str) -> float`: ratio of prose characters (text not in headers, tables, bold-key pairs, KV lines) to total characters; result in [0.0, 1.0].

Standard library only (`re`, `typing`). No external dependencies.

**Acceptance Criteria**:
- `extract_kv_pairs` produces normalized keys (lowercase, underscores replace spaces).
- Generic stop-keys from `_GENERIC_STOP_KEYS` in `contradiction-scanner.py` are excluded from output.
- `compute_prose_ratio` returns a float in [0.0, 1.0] for any non-empty Markdown input.
- Module imports cleanly (no side effects on import).

---

### T-005 — Artifact Category JSON Schemas (6 files)

**Phase**: 1 — NS-003-A Schema Validator
**File paths**:
- `scripts/schemas/discover.json`
- `scripts/schemas/assess.json`
- `scripts/schemas/how.json`
- `scripts/schemas/plan.json`
- `scripts/schemas/build.json`
- `scripts/schemas/learn.json`

**Dependencies**: T-001

**Description**: Create the six artifact category JSON schemas exactly as defined in data-model.md §5 (§5.1 through §5.6). Each schema uses JSON Schema draft-07. Required fields and property types for each category:

| Category | Required fields |
|----------|-----------------|
| DISCOVER | `spec_id`, `agent`, `timestamp`, `scope_statement`, `assumptions`, `unknowns` |
| ASSESS   | `spec_id`, `agent`, `timestamp`, `verdict`, `risks`, `effort_estimate` |
| HOW      | `spec_id`, `agent`, `timestamp`, `adrs`, `technology_stack`, `data_model_ref` |
| PLAN     | `spec_id`, `agent`, `timestamp`, `tasks`, `critical_path`, `mvp_scope` |
| BUILD    | `spec_id`, `agent`, `timestamp`, `implementation_notes`, `test_results` |
| LEARN    | `spec_id`, `agent`, `timestamp`, `learnings`, `pattern_updates`, `quality_delta` |

Each schema JSON must also include a `required_sections` array as defined in data-model.md §5 (used by the prose assessment component — not part of `jsonschema.validate()` processing).

**Acceptance Criteria**:
- AC-1.6: `ns003_critic.py` launched with all six schemas present exits without a schema-load error (exit code ≠ 2).
- AC-1.6 inverse: if any schema file is removed, `ns003_critic.py` exits with code 2 before processing any artifacts.
- Each schema validates correctly against a minimal conforming artifact (pass) and against a missing-field artifact (fail).

---

### T-006 — Deterministic JSON Schema Validator Component

**Phase**: 1 — NS-003-A Schema Validator
**File path**: `scripts/ns003_critic.py` (deterministic component only — prose component added in T-007)
**Dependencies**: T-004, T-005

**Description**: Implement Component 1 of the two-component NS-003-A validator (ADR-002). This component:

1. Accepts a Markdown artifact file path and artifact category label.
2. Calls `md_parser.extract_kv_pairs()` to produce a structured dict.
3. Loads the category JSON schema from `--schema-dir` (`SchemaLoadError` → exit code 2 if missing or malformed per FR-NS3A-ERR-003).
4. Calls `jsonschema.validate()` against the extracted dict.
5. For each required field in the schema: emits PASS/FAIL verdict with confidence=0.95 (deterministic — both PASS and FAIL carry this fixed confidence per ADR-002).
6. Calls `md_parser.compute_prose_ratio()` and logs the structured-to-prose ratio in the output record.

Implements the CLI interface from ns003_interfaces.md §1 for the `--artifact`, `--schema-dir`, `--category`, `--output`, `--timeout`, `--dry-run`, `--verbose`, and `--help` flags. Checks `ANTHROPIC_API_KEY` at startup and exits with code 1 if absent (unless `--dry-run`). The `--help` flag must complete without error even if the API key is absent (FR-DEP-002).

Category inference from filename uses `ARTIFACT_STAGE_MAP` (maps filename substrings to DISCOVER/ASSESS/HOW/PLAN/BUILD/LEARN). If inference fails and `--category` is not supplied, exit code 1.

**Acceptance Criteria**:
- AC-1.1 (deterministic portion): Per-field PASS/FAIL verdicts with confidence=0.95 are produced for all required fields.
- AC-1.4: Known-good calibration artifact from runs 015-016 receives PASS on all structured fields (FRR ≤ 5% on calibration set).
- AC-1.5: `ANTHROPIC_API_KEY` absent with `--dry-run` → completes normally (skips prose component).
- AC-1.6: Missing schema file → exit code 2 before processing.
- Output JSON matches the format specified in ns003_interfaces.md §1.

---

### T-007 — Claude API Prose Structure Assessment Component

**Phase**: 1 — NS-003-A Schema Validator
**File path**: `scripts/ns003_critic.py` (prose component, extending T-006)
**Dependencies**: T-006

**Description**: Implement Component 2 of the two-component NS-003-A validator (ADR-002). Extend `ns003_critic.py` with the prose assessment logic:

1. Assemble the fixed prose-assessment prompt template from ADR-002 (exact text defined in research.md ADR-002 Prompt Template section), substituting `{CATEGORY}`, `{REQUIRED_SECTIONS}` (from schema's `required_sections` array), and `{ARTIFACT_TEXT}`.
2. Call `anthropic.Anthropic().messages.create()` with `model="claude-sonnet-4-6"`, `temperature=0`, `max_tokens=512`, with the configured `--timeout` (default 30 seconds) per FR-NS3A-004.
3. Parse response using regex: one line per required section in format `SECTION_VERDICT: <section_name> | <PRESENT|ABSENT|EMPTY> | <confidence>`, plus `OVERALL_PROSE: <PASS|FAIL> | <confidence>`.
4. Each prose-section verdict carries confidence in [0.5, 0.85] (capped below 0.95 to distinguish from deterministic component per ADR-002).
5. On API timeout: record TIMEOUT verdict for that artifact, continue batch (FR-NS3A-004).
6. On HTTP 401: write PARTIAL_RESULTS to `--output` with completed verdicts, stop batch with clear authentication error (AC-1.5).

**Acceptance Criteria**:
- AC-1.1: Per-field verdicts for prose sections have confidence in [0.5, 0.85].
- AC-1.3: Single artifact API call completes within 30 seconds (or produces TIMEOUT verdict).
- AC-1.5: HTTP 401 → PARTIAL_RESULTS file written, batch stops with authentication error message.
- `--dry-run` flag skips this component entirely (no API call made).

---

### T-008 — Combined Validator and Calibration Measurement

**Phase**: 1 — NS-003-A Schema Validator
**File path**: `scripts/ns003_critic.py` (combined output + calibration logic)
**Dependencies**: T-007

**Description**: Finalize `ns003_critic.py` as the complete two-component combined validator per ADR-002 Score Combination rules:

1. Combine verdicts: deterministic verdicts carry confidence=0.95; prose verdicts carry API-returned confidence in [0.5, 0.85]. FPCR computation uses only PASS/FAIL — confidence scores are stored in output for audit but do not affect FPCR numerator/denominator.
2. Implement structured-to-prose ratio instrumentation: log per-category ratio using `md_parser.compute_prose_ratio()`. If any category shows prose fraction > 40%, flag `coverage_limitation_flag = true` in the output record (IS-007 / RSK-010 mitigation — mandatory pre-Phase-2 check per ADR-002).
3. Implement calibration set measurement: when `--calibration-set` is provided, compute false rejection rate (FRR = known-good artifacts rejected / total known-good artifacts). FRR must be ≤ 5% before the experiment proceeds (AC-1.4 / FR-NS3A-005).
4. Output JSON must match the format in ns003_interfaces.md §1 in full (including `structured_to_prose_ratio`, `partial_results`, `error` fields).

**Acceptance Criteria**:
- AC-1.2: Validation report includes computed FPCR labeled as PATENT_GRADE / PROTOTYPE_VIABLE / INCONCLUSIVE.
- AC-1.4: FRR ≤ 5% on calibration set (or `coverage_limitation_flag = true` logged if prose > 40%).
- Combined output JSON matches ns003_interfaces.md §1 format exactly.
- IS-007: structured-to-prose ratio logged per artifact category; `coverage_limitation_flag` set correctly.

---

## Phase 2 — NS-003-B AGM Engine

**Can start in parallel with Phase 1 after T-004 (shared parser) is complete.**
**T-010 through T-013 depend on T-004. T-010 has no dependency on Phase 1 schema tasks.**

---

### T-009 — BeliefNode and ConflictSignal Dataclasses

**Phase**: 2 — NS-003-B AGM Engine
**File path**: `scripts/ns003_agm.py` (dataclass definitions section)
**Dependencies**: T-001

**Description**: Implement the `BeliefNode` and `ConflictSignal` Python dataclasses exactly as specified in data-model.md §1 (§1.1 and §1.2), plus the error classes from data-model.md §7.

`BeliefNode` fields: `field_identifier`, `value`, `stage` (Literal of 6 values), `confidence` (float in [0.5, 0.95]), `status` (ACTIVE/SUPERSEDED), `superseded_chain`, `superseded_by`, `version_counter`, `artifact_path`.

`ConflictSignal` fields: `field_identifier`, `new_value`, `new_stage`, `existing_value`, `existing_stage`, `contradiction_type` (Literal of 3 values), `confidence`, `recommended_action` (Literal of accept/revert/escalate), `existing_node_ref`, `artifact_path_new`.

Error classes: `MalformedAssertionError(field_identifier, reason)`, `BeliefGraphWriteError(path, cause)`.

`recommended_action` derivation: confidence ≥ 0.80 → `escalate`; 0.65-0.79 → `revert`; < 0.65 → `accept` (per ADR-003 ConflictSignal fields).

**Acceptance Criteria**:
- Dataclasses are importable and instantiatable with the fields defined in data-model.md.
- `confidence` outside [0.5, 0.95] is rejected (data-model.md §1.1 Constraints).
- `superseded_chain` is initialized as empty list (not shared mutable default).
- `MalformedAssertionError` and `BeliefGraphWriteError` are subclasses of `Exception`.

---

### T-010 — BeliefGraph Class

**Phase**: 2 — NS-003-B AGM Engine
**File path**: `scripts/ns003_agm.py` (BeliefGraph class)
**Dependencies**: T-009

**Description**: Implement the `BeliefGraph` class per the full interface specification in data-model.md §2, implementing all four AGM K*2 postulates as operationalized in FR-NS3B-003 (research.md ADR-003):

- `__init__(graph_path)`: load existing JSON graph or initialize empty. Persistence path stored.
- `add_belief(node)`: Vacuity path (no existing ACTIVE node → insert); or conflict path (existing ACTIVE node → call `check_conflict()`, then `apply_revision()`). Raises `MalformedAssertionError` on null/empty `field_identifier` or `value`.
- `check_conflict(incoming)`: returns `ConflictSignal` or `None`. Applies contradiction detectors in order: assertion_conflict (0.80) → scope_conflict (0.70) → architecture_conflict (0.60).
- `apply_revision(incoming)`: K*2 Minimal Contraction — moves existing ACTIVE node to SUPERSEDED, increments `version_counter`, updates `superseded_chain`, adds incoming to ACTIVE. Persists atomically (temp file + rename) per FR-NS3B-ERR-002.
- `get_active(field_identifier)`: returns ACTIVE node or None.
- `get_superseded_chain(field_identifier)`: returns list of SUPERSEDED nodes, oldest first.
- `to_dict()` / `from_dict()`: serialize/deserialize full graph to/from the JSON format in data-model.md §3.

Persistence format must match data-model.md §3 exactly (schema_version, run_id, spec_id, created_at, last_updated_at, active dict, conflict_signals list).

**Acceptance Criteria**:
- AC-2.4: After `apply_revision()`, the superseded node remains in graph with status SUPERSEDED and `superseded_by` reference — not deleted.
- FR-NS3B-ERR-002: Atomic write via temp file + rename. On write failure, `BeliefGraphWriteError` is raised; original graph file is untouched (temp file is never renamed on failure).
- Consistency postulate: ACTIVE dict has at most one entry per `field_identifier` at all times.
- Minimality postulate: `apply_revision()` moves only the node with matching `field_identifier` to SUPERSEDED.

---

### T-011 — Assertion Extractor

**Phase**: 2 — NS-003-B AGM Engine
**File path**: `scripts/ns003_agm.py` (assertion extractor section)
**Dependencies**: T-004, T-010

**Description**: Implement the Assertion Extractor (Layer 1 of the three-layer AGM architecture from ADR-003). This component:

1. Reads artifact files from `--artifact-dir` in pipeline order: DISCOVER → ASSESS → HOW → PLAN → BUILD → LEARN. Files matching `ARTIFACT_STAGE_MAP` keys are processed in stage order; unrecognized filenames are skipped with a warning.
2. For each artifact file, calls `md_parser.extract_kv_pairs()` to extract key-value pairs (reusing the shared parser from T-004).
3. Converts each extracted pair to a candidate `BeliefNode`: `field_identifier` = normalized key; `value` = extracted value string; `stage` = pipeline stage label from `ARTIFACT_STAGE_MAP`; `confidence` = 0.70 initial.
4. Excludes field identifiers in `_GENERIC_STOP_KEYS` (per ADR-003 — stop keys generate false positives across artifacts).
5. Passes each candidate node to `BeliefGraph.add_belief()`.

**Acceptance Criteria**:
- AC-2.1: Artifact files are processed in DISCOVER → ASSESS → HOW → PLAN → BUILD → LEARN order.
- Unrecognized filenames produce a warning (not an error); processing continues.
- Stop-key exclusion prevents generic fields (e.g., `date`, `author`) from polluting the belief graph.
- Each extracted pair maps to a `BeliefNode` with `confidence=0.70`.

---

### T-012 — Contradiction Classifier (Three Detector Types)

**Phase**: 2 — NS-003-B AGM Engine
**File path**: `scripts/ns003_agm.py` (contradiction classifier, implemented within `BeliefGraph.check_conflict()`)
**Dependencies**: T-010

**Description**: Implement the three contradiction type detectors inside `BeliefGraph.check_conflict()` per ADR-003 Layer 3 design. Applied in order when an existing ACTIVE node is found:

1. **assertion_conflict** (confidence 0.80): detect via negation patterns (`_NEGATION_RE`), status-term inversions (PASS↔FAIL, ENABLED↔DISABLED), and numerical divergence > 20% of existing value. Returns `ConflictSignal` with `contradiction_type="assertion_conflict"` and `confidence=0.80`.
2. **scope_conflict** (confidence 0.70): detect when the incoming assertion contains explicit scope boundary terms (`only`, `all`, `none`, `any`, `within`, `excluding`) incompatible with scope terms in the existing value. Returns `ConflictSignal` with `contradiction_type="scope_conflict"` and `confidence=0.70`.
3. **architecture_conflict** (confidence 0.60): detect when the incoming assertion names an architectural component (database, queue, API, cache, service) not present in the existing value. Returns `ConflictSignal` with `contradiction_type="architecture_conflict"` and `confidence=0.60`.

If no detector fires, returns `None` (no conflict).

**Acceptance Criteria**:
- AC-2.1: Contradiction report lists `contradiction_type` and `confidence` for each detected conflict.
- AC-2.3: Contradiction catch rate (detected / planted) ≥ 0.80 on the calibration set with planted contradictions. False positive rate ≤ 0.20 (spurious signals / total non-conflicting assertions).
- Detectors are applied in the defined order (assertion_conflict checked first).
- `recommended_action` is set from confidence: ≥0.80 → `escalate`, 0.65-0.79 → `revert`, <0.65 → `accept`.

---

### T-013 — NS-003-B CLI (`ns003_agm.py`)

**Phase**: 2 — NS-003-B AGM Engine
**File path**: `scripts/ns003_agm.py` (CLI entry point and output writer)
**Dependencies**: T-011, T-012

**Description**: Implement the CLI entry point for `ns003_agm.py` per the contract in ns003_interfaces.md §2. Wire together the Assertion Extractor (T-011), BeliefGraph (T-010), and Contradiction Classifier (T-012).

CLI flags: `--artifact-dir` (required), `--mode {post-hoc,pre-commit}` (default: post-hoc), `--belief-graph` (default: `.specify/squad/belief-graph-<run_id>.json`), `--output` (default: `experiments/ns003-contradiction-report.json`), `--run-id` (UUID4 if omitted), `--verbose`.

Per ADR-001: `--mode pre-commit` MUST NOT silently proceed as post-hoc. It must print a clear message: "pre-commit mode not available in v1 — IS-003 resolution descoped this" and then proceed as post-hoc mode (ADR-001 Consequences: "either alias to post-hoc mode with a deprecation warning or exit with a clear message"). Use the deprecation-warning path (alias, not exit) to preserve usability.

Output JSON to `--output` must match the format in ns003_interfaces.md §2 (schema_version, run_id, mode, artifact_dir, belief_graph_path, processing_timestamp, artifacts_processed, assertions_extracted, conflicts_detected, contradiction_report array).

Exit codes: 0 on success, 1 on runtime error (artifact-dir not found, BeliefGraph write failure), 2 reserved.

**Acceptance Criteria**:
- AC-2.1: `--mode post-hoc` produces contradiction report with type, confidence, recommended_action per detected conflict.
- AC-2.2 (amended per ADR-001): `--mode pre-commit` prints deprecation notice and proceeds as post-hoc — does NOT silently proceed without notice.
- AC-2.4: SUPERSEDED nodes retained in BeliefGraph JSON with `superseded_by` reference.
- Output JSON matches ns003_interfaces.md §2 format.
- No `ANTHROPIC_API_KEY` requirement (AGM engine is fully deterministic).

---

## Phase 3 — NS-003 Experiment Runner

**Depends on Phase 1 (T-008) and Phase 2 (T-013). Both must be complete.**

---

### T-014 — NS-003 Experiment Runner: `scripts/ns003_experiment.py`

**Phase**: 3 — NS-003 Experiment Runner
**File path**: `scripts/ns003_experiment.py`
**Dependencies**: T-008, T-013

**Description**: Implement the NS-003 experiment orchestrator per the contract in ns003_interfaces.md §3 and the phase sequence defined therein.

The runner must execute six internal phases in order:
1. Capture `git rev-parse HEAD` → store as `codebase_commit_hash`. Exit 1 if git unavailable (IS-006).
2. Run Phase 1 calibration: validate calibration set via `ns003_critic.py`, compute FRR. If FRR > 5%, print warning and require `--proceed-anyway` flag to continue (FR-NS3A-005). If no calibration set found in `.specify/specs/015-*/` or `016-*/`, exit 1 with instructions.
3. Measure structured-to-prose ratio on calibration set. Log per-category ratios.
4. Run N=30 invocations (live Echelon artifacts or historical_artifacts fallback). Label data source as `"historical_artifacts"` in results JSON if fallback is used.
5. Run `ns003_agm.py` against the collected artifact set. Compute CCR and FPR.
6. Compute FPCR, write `ns003-results.json` and generate `ns003-report.md`.

CLI flags: `--n` (default 30), `--calibration-set`, `--schema-dir` (default `scripts/schemas/`), `--output-dir` (default `experiments/`), `--model` (default `claude-sonnet-4-6`), `--timeout` (default 30), `--dry-run`, `--verbose`.

`--dry-run` runs Phase 1 calibration only — no live invocations.

Output files in `--output-dir`: `ns003-results.json`, `ns003-report.md`, `ns003-contradiction-report.json`.

**Acceptance Criteria**:
- AC-3.1: `experiments/ns003-results.json` contains: per-invocation schema validation verdicts, computed FPCR, contradiction catch rate, false positive rate, experiment date, codebase commit hash, model identifier.
- AC-3.2: `experiments/ns003-report.md` states FPCR classification (PATENT_GRADE / PROTOTYPE_VIABLE / INCONCLUSIVE) against both the 0.70 and 0.80 thresholds per P-022, plus codebase commit hash.
- AC-3.3: Same commit hash + model → FPCR differs by no more than ±0.05 across runs (NFR-REPRO-001).
- IS-007: If prose fraction > 40% in any category, `coverage_limitation_flag = true` in results JSON and a coverage limitation section appears in `ns003-report.md`.
- IS-010: If calibration set falls back to non-015/016 artifacts, `data_source = "historical_artifacts"` and DEVIATION statement appears in `ns003-report.md` (FR-NS3E-001).

---

### T-015 — NS-003 Report Template and Generator

**Phase**: 3 — NS-003 Experiment Runner
**File path**: `scripts/ns003_experiment.py` (report generation function within runner)
**Dependencies**: T-014

**Description**: Implement `ns003-report.md` generation as a function within `ns003_experiment.py`. The report must be generated from `ns003-results.json` and must include:

- Experiment header: spec ID (017), experiment ID (NS-003), date, model identifier, codebase commit hash.
- FPCR section: numeric value, classification label (PATENT_GRADE / PROTOTYPE_VIABLE / INCONCLUSIVE), both threshold checks (≥0.80 and ≥0.70).
- CCR section: numeric value, PASS/FAIL verdict against ≥0.80 target.
- FPR section: numeric value, PASS/FAIL verdict against ≤0.20 target.
- Calibration section: FRR value, calibration set source label, calibration set size.
- Per-category structured-to-prose ratio table.
- Coverage limitation section (when `coverage_limitation_flag = true`).
- DEVIATION section (when `data_source = "historical_artifacts"`).
- NS-003-B amended framing (post-hoc, not pre-commit) per ADR-001 amendment record (T-003).

**Acceptance Criteria**:
- AC-3.2: Report states FPCR classification against both P-022 thresholds.
- Report uses ADR-001 amended framing ("post-hoc contradictions") throughout — not the original "pre-commit conflict signals" language.
- Report includes codebase commit hash for reproducibility (AC-3.2).
- Coverage limitation section present whenever `coverage_limitation_flag = true`.
- DEVIATION section present whenever `data_source = "historical_artifacts"`.

---

## Phase 4 — U-CA-004 Experiment Infrastructure

**Depends on Phase 3 complete (T-014, T-015). Can begin after T-001 for the runner skeleton, but AQS scorer and statistical logic depend on Phase 3 completion to validate assumptions.**

---

### T-016 — AQS Proxy Scorer Component

**Phase**: 4 — U-CA-004 Experiment Infrastructure
**File path**: `scripts/uca004_runner.py` (AQS scorer section)
**Dependencies**: T-001

**Description**: Implement the AQS proxy scorer per ADR-004 and ns003_interfaces.md §4 (implicitly, as the scorer is embedded in `uca004_runner.py`).

1. The fixed versioned prompt template (version 1.0.0, exact text from research.md ADR-004) must be defined as a string constant. Compute its SHA-256 hash at startup and store as `scoring_prompt_hash` — must be identical across all records in a batch.
2. Assemble prompt by substituting `{ARTIFACT_TEXT}`.
3. Call `anthropic.Anthropic().messages.create()` with `model="claude-sonnet-4-6"`, `temperature=0`, `max_tokens=512`.
4. Parse response with regex: `^(COMPLETENESS|CONSISTENCY|SPECIFICITY|ACTIONABILITY|INNOVATION):\s*([0-5])\s*$` per dimension line. If any line fails to match or integer is out of [0,5]: mark `extraction_status = "OUT_OF_RANGE"`, discard, retry once. If retry also fails: `extraction_status = "SCORING_FAILED"`.
5. Append one JSON record to `experiments/uca004-scoring-audit.jsonl` per call per the format in research.md ADR-004 (run_id, condition, invocation_index, scoring_prompt_version, scoring_prompt_hash, model_identifier, request_timestamp, response_timestamp, raw_prompt, raw_response, extracted_scores, extraction_status, retry_count).

**Acceptance Criteria**:
- AC-4.2: Fixed versioned prompt used for all invocations; raw prompt and response logged per call.
- AC-4.2: Audit trail file `experiments/uca004-scoring-audit.jsonl` contains one JSON object per scoring call.
- `scoring_prompt_hash` is identical across all records in a batch (mixed-version batches are invalid per data-model.md §1.3 Constraint).
- FR-UCA-ERR-001: Out-of-range or parse-failure → retry once; second failure → `SCORING_FAILED`.

---

### T-017 — U-CA-004 Experiment Runner: `scripts/uca004_runner.py`

**Phase**: 4 — U-CA-004 Experiment Infrastructure
**File path**: `scripts/uca004_runner.py`
**Dependencies**: T-016

**Description**: Implement the full U-CA-004 experiment runner per ns003_interfaces.md §4.

1. Capture `git rev-parse HEAD` → `codebase_commit_hash`. Exit 1 if unavailable (IS-006).
2. Check `ANTHROPIC_API_KEY` at startup; exit 1 with human-readable message if absent (FR-DEP-003).
3. Run N=20 invocations per condition (BASELINE, CA-ACTIVE). TIMEOUT invocations count against N=20 (FR-UCA-ERR-003).
4. Score each invocation output via AQS proxy scorer (T-016).
5. Compute `total_aqs = sum(five dimensions) / 25.0` per invocation.

CLI flags: `--conditions` (default: BASELINE CA-ACTIVE), `--n` (default 20), `--output-dir` (default `experiments/`), `--model` (default `claude-sonnet-4-6`), `--timeout` (default 60), `--verbose`.

Output files: `uca004-results.json`, `uca004-scoring-audit.jsonl`, `uca004-negative-report.md` (only if NEGATIVE verdict).

`--help` must complete without error even if `ANTHROPIC_API_KEY` is absent (FR-DEP-002).

**Acceptance Criteria**:
- AC-4.1: `experiments/uca004-results.json` contains: per-invocation AQS scores (5 dimensions), condition label, run_id, codebase commit hash, model identifier, Mann-Whitney U statistic, p-value.
- AC-4.6: If either condition has fewer than 16 completions: `verdict = "VOID"`, no Mann-Whitney computed, no POSITIVE or NEGATIVE verdict emitted.
- Output JSON matches data-model.md §4.2 format (schema_version, experiment_id, conditions_run, baseline, ca_active, statistics, verdict, authorized_overlays, limitations, per_invocation_records).

---

### T-018 — Verdict Computation Logic

**Phase**: 4 — U-CA-004 Experiment Infrastructure
**File path**: `scripts/uca004_runner.py` (verdict computation section)
**Dependencies**: T-017

**Description**: Implement the statistical verdict computation within `uca004_runner.py` per the exact logic from ns003_interfaces.md §4 and ADR-004.

1. VOID check FIRST: if `n_completed_baseline < 16` or `n_completed_ca_active < 16`: set `verdict = "VOID"`, set `void_reason`, skip all statistics.
2. Mann-Whitney U: `scipy.stats.mannwhitneyu(baseline_aqs_totals, ca_active_aqs_totals, alternative='two-sided')`.
3. Cohen's d: `(mean_ca - mean_baseline) / pooled_std` where `pooled_std = sqrt(((n1-1)*var1 + (n2-1)*var2) / (n1+n2-2))`. Standard library math only.
4. POSITIVE if `p_value < 0.05 AND cohens_d >= 0.5`; NEGATIVE otherwise. INCONCLUSIVE is NOT a valid verdict state (P-020 binary gate).
5. If POSITIVE: populate `authorized_overlays` with the five overlay paths from data-model.md §4.2.
6. Populate `limitations` field with the exact circularity disclosure statement from ADR-004 (verbatim text required in `uca004-results.json`).

**Acceptance Criteria**:
- AC-4.3: POSITIVE iff p < 0.05 AND Cohen's d ≥ 0.5. NEGATIVE otherwise. No INCONCLUSIVE.
- AC-4.4: POSITIVE verdict → `authorized_overlays` lists all five CA overlay script paths.
- AC-4.6: VOID when N < 16 for either condition; statistics NOT computed.
- `limitations` field contains verbatim circularity disclosure text from ADR-004.

---

### T-019 — NEGATIVE Report Template and Generator

**Phase**: 4 — U-CA-004 Experiment Infrastructure
**File path**: `scripts/uca004_runner.py` (negative report generator) + `experiments/uca004-negative-report.md` (output)
**Dependencies**: T-018

**Description**: Implement `uca004-negative-report.md` generation, triggered only when `verdict == "NEGATIVE"`. The report must include:

- Experiment header: spec ID (017), experiment ID (U-CA-004), date, model identifier, codebase commit hash.
- Verdict statement: NEGATIVE.
- Statistics section: Mann-Whitney U statistic, p-value, Cohen's d, per-condition AQS means and standard deviations.
- Statistical power limitation disclosure (verbatim per ADR-004): "Statistical power at N=20 with alpha=0.05 is approximately 0.56 for detecting a medium effect (d=0.5). A NEGATIVE verdict at this sample size is genuinely inconclusive for small effects — it does not rule out d<0.5 improvements."
- Limitations section with verbatim evaluator circularity disclosure from ADR-004.
- Recommendation: no CA overlay component implementation code to be committed (AC-4.5).

**Acceptance Criteria**:
- AC-4.5: NEGATIVE verdict → report records U statistic, p-value, Cohen's d, per-condition AQS means, and recommendation against CA overlay implementation.
- Power limitation disclosure appears verbatim.
- Limitations section contains verbatim circularity disclosure from ADR-004.
- Report is NOT generated when verdict is POSITIVE or VOID.

---

## Phase 5 — CA Overlay Implementations

**CONDITIONAL — all tasks in this phase are blocked by FR-CAO-000.**
**T-021 (gate check) must pass before any other Phase 5 task begins.**
**No Phase 5 task may be started until `scripts/ca/verify_gate.sh` exits 0.**

---

### T-020 — CA Overlay Gate Check: `scripts/ca/verify_gate.sh`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/ca/verify_gate.sh`
**Dependencies**: T-018

**Description**: Implement the gate-check script per the contract in ns003_interfaces.md §5. This script is the mandatory prerequisite for all CA overlay implementation tasks (T-021 through T-026). It performs exactly three checks in order:

1. `experiments/uca004-results.json` exists and is readable. Fail message: `GATE FAIL: uca004-results.json not found at <path>. Run uca004_runner.py first.`
2. `verdict` field equals `"POSITIVE"`. Fail message: `GATE FAIL: verdict is <value>, not POSITIVE. CA overlay implementation is blocked per P-020.`
3. `codebase_commit_hash` field matches `git rev-parse HEAD`. Fail message: `GATE FAIL: commit hash mismatch. Results were produced on <results_hash>; current HEAD is <head_hash>. Re-run uca004_runner.py on the current codebase.`

Locates git repo root via `git rev-parse --show-toplevel`. Requires no environment variables beyond a functional `git` in PATH. Exit 0 if all three pass; exit 1 on first failure. `--verbose` flag prints detailed check results. `--results-file` allows explicit path override.

**Acceptance Criteria**:
- FR-CAO-000: Exit 0 only when all three checks pass simultaneously.
- Check 1 failure produces the exact fail message specified.
- Check 2 failure produces the exact fail message with the actual verdict value.
- Check 3 failure produces the exact fail message with both hash values.
- No arguments required for standard usage (all paths derived from git root).

---

### T-021 — Goal Stack Overlay: `scripts/ca/goal_stack.py`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/ca/goal_stack.py`
**Dependencies**: T-020 (gate check must pass; exit 0)

**Description**: CONDITIONAL. Implement the Goal Stack cognitive architecture overlay per ADR-005. Exposes the uniform `enrich_context(context_pack: dict, run_id: str) -> dict` interface.

- Persistent goal hierarchy per run stored at `.specify/squad/goal-stack-<run_id>.json` (gitignored — per ADR-005 Consequences).
- Initialized at first dispatch: root goal = spec feature name from `spec.md` header.
- `enrich_context()`: reads the JSON, extracts the current active goal (top of stack), inserts `context_pack["active_goal"] = {goal_text, priority, depth}`.
- Separate `update_goal_stack(outcome, run_id)` function called post-dispatch by COMMANDER to update the stack JSON.
- Function is read-only on all COMMANDER state — only writes to the returned context_pack dict.

**Acceptance Criteria**:
- AC-5.1 (as specified in spec.md §Scenario 5): CA overlay enriches the context_pack without modifying COMMANDER routing logic, quality gate thresholds, or endocrine triggers.
- `enrich_context` returns a dict with `active_goal` key populated.
- FR-CAO-002: returned context_pack does NOT exceed the token count of the standard COMMANDER context_pack.
- `.specify/squad/goal-stack-<run_id>.json` is listed in `.gitignore` (or equivalent exclusion).
- T-020 gate check passed (exit 0) before this file is created.

---

### T-022 — ACT-R Typed Buffer Overlay: `scripts/ca/actr_buffer.py`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/ca/actr_buffer.py`
**Dependencies**: T-020 (gate check must pass; exit 0)

**Description**: CONDITIONAL. Implement the ACT-R Typed Buffer overlay per ADR-005. Exposes `enrich_context(context_pack: dict, run_id: str) -> dict`.

- Restructures a flat context_pack into four typed buffers: `declarative` (factual content from prior artifacts), `procedural` (agent role + task instructions), `goal` (current task + success criteria), `imaginal` (current artifact under construction or empty).
- TF-IDF retrieval ranking for `retrieval_buffer` (read-only lookup, not a fifth buffer): manual implementation using word frequency counts across prior artifacts. Returns top-3 most relevant prior artifact excerpts by TF-IDF cosine similarity to current task description. Standard library only — no sklearn or numpy (ADR-005 OQ-005 resolution).
- Token count verification: count words using 4-chars/token heuristic across all four buffers. If total exceeds standard context_pack word count, evict from `declarative` first (recency = lower priority).
- FR-CAO-002: returned context_pack MUST NOT exceed the token count of the standard COMMANDER context_pack.

**Acceptance Criteria**:
- AC-5.1: Overlay enriches context_pack without modifying COMMANDER routing logic, quality gates, or endocrine triggers.
- Four typed buffers are present in the returned context_pack.
- `retrieval_buffer` contains top-3 relevant excerpts by TF-IDF cosine similarity.
- Token count verification is applied; `declarative` buffer eviction occurs when bound is exceeded.
- FR-CAO-002: token count constraint enforced.
- T-020 gate check passed (exit 0) before this file is created.

---

### T-023 — LIDA Broadcast Overlay: `scripts/bash/lida_broadcast.sh`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/bash/lida_broadcast.sh`
**Dependencies**: T-020 (gate check must pass; exit 0)

**Description**: CONDITIONAL. Implement the LIDA Broadcast overlay as a Bash script per ADR-005.

- File-based mechanism. Broadcast payload written to `.specify/squad/lida-payload.json`.
- Replace-not-append semantics: each `broadcast` call overwrites the file entirely (FR-CAO-003).
- Bash interface:
  - `lida_broadcast.sh broadcast <payload_json_string>`: writes payload to `.specify/squad/lida-payload.json`.
  - `lida_broadcast.sh cleanup <run_id>`: deletes any remaining payload file.
- COMMANDER integration note (for COMMANDER.md documentation in T-026): one `if [ -f .specify/squad/lida-payload.json ]` check at the top of each dispatch cycle; reads file into shell variable; deletes file; injects into context_pack.
- Run-end cleanup: COMMANDER calls `lida_broadcast.sh cleanup <run_id>` in run-end protocol.

**Acceptance Criteria**:
- AC-5.1: Overlay does not modify COMMANDER routing logic, quality gates, or endocrine triggers.
- FR-CAO-003: Each broadcast call overwrites (not appends) the payload file.
- `cleanup` subcommand deletes the payload file if it exists; no-ops if absent.
- `broadcast` subcommand with valid JSON string produces a readable `.specify/squad/lida-payload.json`.
- T-020 gate check passed (exit 0) before this file is created.

---

### T-024 — GWT Bounded Workspace Overlay: `scripts/ca/gwt_workspace.py`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/ca/gwt_workspace.py`
**Dependencies**: T-020 (gate check must pass; exit 0)

**Description**: CONDITIONAL. Implement the GWT Bounded Workspace overlay per ADR-005. Exposes `enrich_context(context_pack: dict, run_id: str) -> dict`.

- Token-bounded workspace stored at `.specify/squad/gwt-workspace-<run_id>.json` (gitignored).
- Maximum token bound: read from `squad-config.yml` key `ca_overlays.gwt.max_tokens` (default: 2000 tokens ≈ 8000 chars using 4-char/token heuristic).
- Content items have `priority = timestamp` (recency = higher priority). When adding content that would exceed the bound, evict the oldest (lowest timestamp) item first. Repeat until bound is satisfied.
- `enrich_context()`: reads workspace JSON, inserts `context_pack["gwt_workspace"] = [list of current workspace items]`.

**Acceptance Criteria**:
- AC-5.1: Overlay enriches context_pack without modifying COMMANDER routing logic, quality gates, or endocrine triggers.
- Token bound is respected: workspace never exceeds `max_tokens` after eviction.
- Eviction policy is oldest-first (lowest timestamp first).
- `gwt-workspace-<run_id>.json` is gitignored.
- T-020 gate check passed (exit 0) before this file is created.

---

### T-025 — Episodic Memory Overlay: `scripts/ca/episodic_memory.py`

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `scripts/ca/episodic_memory.py`
**Dependencies**: T-020 (gate check must pass; exit 0)

**Description**: CONDITIONAL. Implement the Episodic Memory overlay per ADR-005. Exposes `enrich_context(context_pack: dict, run_id: str, agent_type: str) -> dict`.

- Temporal artifact index stored at `.specify/squad/episodic-index-<run_id>.json` (gitignored).
- Append-only index: each agent-produced artifact is indexed with `{agent_type, artifact_path, stage_timestamp, artifact_category}`.
- `enrich_context()` with `agent_type` parameter: returns the single most-recent artifact path for that agent type. Query: `max(entries where agent_type == requested_type, key=stage_timestamp)`.
- No cross-run persistence in v1 (spec §2 Out-of-Scope).
- Separate `index_artifact(agent_type, artifact_path, stage_timestamp, artifact_category, run_id)` function for COMMANDER to call post-dispatch.

**Acceptance Criteria**:
- AC-5.1: Overlay enriches context_pack without modifying COMMANDER routing logic, quality gates, or endocrine triggers.
- `enrich_context()` returns the most-recent artifact path for the given agent type, or None if no prior artifacts for that type.
- Index is append-only; no deletions.
- `episodic-index-<run_id>.json` is gitignored.
- T-020 gate check passed (exit 0) before this file is created.

---

### T-026 — COMMANDER Integration Documentation

**Phase**: 5 — CA Overlay Implementations (CONDITIONAL)
**File path**: `COMMANDER.md` (amendment — new overlay integration section)
**Dependencies**: T-021, T-022, T-023, T-024, T-025

**Description**: CONDITIONAL. Add the CA overlay integration hook-point documentation to `COMMANDER.md` per ADR-005 Consequences ("ADR-005 hook-point per overlay"). Document the following for each overlay:

- **Goal Stack**: call `goal_stack.enrich_context(context_pack, run_id)` before dispatch; call `goal_stack.update_goal_stack(outcome, run_id)` post-dispatch.
- **ACT-R Buffer**: call `actr_buffer.enrich_context(context_pack, run_id)` before dispatch.
- **LIDA Broadcast**: check `if [ -f .specify/squad/lida-payload.json ]` at top of dispatch cycle; read and delete payload; inject into context_pack. Call `lida_broadcast.sh cleanup <run_id>` at run end.
- **GWT Workspace**: call `gwt_workspace.enrich_context(context_pack, run_id)` before dispatch.
- **Episodic Memory**: call `episodic_memory.enrich_context(context_pack, run_id, agent_type)` before dispatch; call `episodic_memory.index_artifact(...)` post-dispatch.

The amendment must explicitly state that overlays are read-only on COMMANDER state — they enrich only the context_pack dict returned to COMMANDER (FR-CAO-006).

**Acceptance Criteria**:
- AC-5.2: COMMANDER documentation describes the hook-point for each overlay without modifying routing logic, quality gate thresholds, or endocrine triggers.
- FR-CAO-006: Amendment states that overlays cannot modify COMMANDER routing logic.
- All five overlays documented with their pre-dispatch and post-dispatch integration points.
- T-020 gate check status (POSITIVE verdict precondition) referenced in the amendment.

---

## Phase 6 — Endocrine Phase 3 Wiring (IS-005)

**Depends on Phase 3 complete (NS-003 experiment results available). Human activation step required before Phase 3 hooks fire.**

---

### T-027 — COMMANDER Amendment: Endocrine Phase 3 Hook Wiring

**Phase**: 6 — Endocrine Phase 3 Wiring
**File path**: `COMMANDER.md` (Post-Dispatch Protocol section amendment)
**Dependencies**: T-014 (NS-003 experiment complete, `experiments/ns003-results.json` exists)

**Description**: Amend `COMMANDER.md` §Post-Dispatch Protocol per ADR-006. Add two new steps immediately after the existing `decay_hormones` call, both gated on `endocrine.phase >= 3`:

**Step 2** (insert after current Step 1 — decay_hormones):

Gate event dispatch: read quality gate result from the just-completed agent dispatch.
- If gate PASSED: run `scripts/bash/endocrine.sh on_gate_pass <agent>`. Log `ENDOCRINE_GATE_PASS` in reasoning-journal.json.
- If gate FAILED: run `scripts/bash/endocrine.sh on_gate_fail <agent>`. Log `ENDOCRINE_GATE_FAIL` in reasoning-journal.json.
- Note: gate result read from agent return state, not re-evaluated.

**Step 3** (insert after Step 2):

Quality improvement signal: compare current dispatch quality score against previous dispatch quality score for same agent role.
- Improved by ≥ 0.05: run `scripts/bash/endocrine.sh on_quality_improvement`. Log `ENDOCRINE_QUALITY_IMPROVEMENT`.
- Regressed by ≥ 0.05: run `scripts/bash/endocrine.sh on_quality_regression`. Log `ENDOCRINE_QUALITY_REGRESSION`.
- No prior score for this agent role: skip.

The amendment must also document the mandatory activation sequence (ADR-006):
1. NS-003 experiment completes → `experiments/ns003-results.json` written.
2. Human manually sets `endocrine_phase: 3` in `squad-config.yml`.
3. COMMANDER reads updated phase on next run initialization.
4. Phase 3 hooks activate from that run forward.

Note: `on_rework` is NOT wired in this amendment (deferred to future ADR — rework detection criterion not yet defined).

**Acceptance Criteria**:
- IS-005: Phase 3 endocrine hooks (`on_gate_pass`, `on_gate_fail`, `on_quality_improvement`, `on_quality_regression`) are called from COMMANDER post-dispatch protocol when `endocrine.phase >= 3`.
- ADR-006: Amendment uses `endocrine.phase >= 3` guard (forward-compatible with future Phase 2 activation).
- Activation sequence documented in the amendment.
- `on_rework` hook explicitly excluded with "deferred to future ADR" note.
- RSK-003 mitigation documented: NS-003 calibration and experiment runs execute with `endocrine_phase: 1`; Phase 3 activation requires human action.

---

### T-028 — Endocrine Phase 3 Integration Test

**Phase**: 6 — Endocrine Phase 3 Wiring
**File path**: `scripts/test_endocrine_phase3.py` (or shell equivalent)
**Dependencies**: T-027

**Description**: Implement the integration test that verifies endocrine event dispatch fires correctly after a mock gate pass/fail. The test must:

1. Set up a mock COMMANDER dispatch context with `endocrine_phase = 3` in a test config.
2. Simulate a gate PASS event: verify `endocrine.sh on_gate_pass <agent>` is called (via subprocess or mock) and `ENDOCRINE_GATE_PASS` is written to a test reasoning-journal.json.
3. Simulate a gate FAIL event: verify `endocrine.sh on_gate_fail <agent>` is called and `ENDOCRINE_GATE_FAIL` is written.
4. Simulate a quality improvement event (delta ≥ 0.05): verify `endocrine.sh on_quality_improvement` is called and `ENDOCRINE_QUALITY_IMPROVEMENT` is written.
5. Verify that with `endocrine_phase = 1`, none of the Phase 3 hooks are called.

**Acceptance Criteria**:
- IS-005: Integration test passes, confirming Phase 3 hooks fire on gate pass/fail events when `endocrine_phase >= 3`.
- Test confirms Phase 3 hooks are silent when `endocrine_phase < 3`.
- Test uses mock gate pass/fail events (does not require a live Echelon agent dispatch).
- Test exits 0 on success, non-zero on any assertion failure.

---

## Task Summary

| Task ID | Phase | Title | Critical Path | CONDITIONAL |
|---------|-------|-------|---------------|-------------|
| T-001 | 0 | `scripts/requirements.txt` | Yes | No |
| T-002 | 0 | `scripts/setup.sh` | No | No |
| T-003 | 0 | ADR-001 amendment record | No | No |
| T-004 | 1 | `scripts/md_parser.py` | Yes | No |
| T-005 | 1 | 6 artifact category JSON schemas | Yes | No |
| T-006 | 1 | Deterministic validator component | Yes | No |
| T-007 | 1 | Claude API prose assessment component | Yes | No |
| T-008 | 1 | Combined validator + calibration | Yes | No |
| T-009 | 2 | BeliefNode + ConflictSignal dataclasses | Yes | No |
| T-010 | 2 | BeliefGraph class | Yes | No |
| T-011 | 2 | Assertion extractor | Yes | No |
| T-012 | 2 | Contradiction classifier | Yes | No |
| T-013 | 2 | `ns003_agm.py` CLI | Yes | No |
| T-014 | 3 | `scripts/ns003_experiment.py` | Yes | No |
| T-015 | 3 | NS-003 report template + generator | No | No |
| T-016 | 4 | AQS proxy scorer component | Yes | No |
| T-017 | 4 | `scripts/uca004_runner.py` | Yes | No |
| T-018 | 4 | Verdict computation logic | Yes | No |
| T-019 | 4 | NEGATIVE report template + generator | No | No |
| T-020 | 5 | `scripts/ca/verify_gate.sh` | Yes (CONDITIONAL entry) | Yes |
| T-021 | 5 | `scripts/ca/goal_stack.py` | No | Yes |
| T-022 | 5 | `scripts/ca/actr_buffer.py` | No | Yes |
| T-023 | 5 | `scripts/bash/lida_broadcast.sh` | No | Yes |
| T-024 | 5 | `scripts/ca/gwt_workspace.py` | No | Yes |
| T-025 | 5 | `scripts/ca/episodic_memory.py` | No | Yes |
| T-026 | 5 | COMMANDER overlay integration docs | No | Yes |
| T-027 | 6 | COMMANDER Phase 3 endocrine wiring | No | No |
| T-028 | 6 | Endocrine Phase 3 integration test | No | No |

**Total tasks**: 28 across 7 phases (Phase 0 through Phase 6).
**CONDITIONAL tasks**: 7 (T-020 through T-026) — blocked by FR-CAO-000 gate check.
**Critical path tasks**: 16 (T-001, T-004 through T-018, T-020).

---

## Dependency Graph Summary

```
T-001 ──┬─── T-002
        ├─── T-004 (md_parser) ──┬─── T-006 ── T-007 ── T-008 ── T-014 ── T-015
        ├─── T-005 (schemas)  ───┘               │              │
        ├─── T-003 (ADR-001 record)              │              │
        └─── T-009 (dataclasses)                 │              │
                    │                            │              │
                    T-010 (BeliefGraph) ──────── T-012 ── T-013 ┘
                              │                              │
                    T-004 ──── T-011 (extractor) ────────────┘
                                                             │
                                    T-014 (ns003_experiment) ┘
                                          │
                                    T-016 (AQS scorer)
                                          │
                                    T-017 (uca004_runner) ── T-018 (verdict) ── T-019 (neg report)
                                                                     │
                                                             T-020 (verify_gate.sh) [CONDITIONAL]
                                                                     │
                                          ┌──────────────────────────┼───────────────────────┐
                                       T-021              T-022   T-023   T-024   T-025   T-026
                                    (goal_stack)         (actr)  (lida)  (gwt)  (episodic)(docs)
                                          [all CONDITIONAL — require T-020 exit 0]

T-014 ── T-027 (COMMANDER Phase 3 wiring) ── T-028 (integration test)
```

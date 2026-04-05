# Spec 017: NS-003 Prototype and U-CA-004 Cognitive Architecture Overlay Experiment

**Type**: Prototype Implementation + Controlled Experiment
**Spec ID**: 017
**Feature**: ns003-ca-overlays
**Date**: 2026-04-03
**Status**: WHAT-phase — normative requirements
**Depends on**: Spec 015 (ca-outcomes-validation), Spec 016 (echelon-proto-reverse-eng)
**Constitution version**: 1.1.0 (P-020, P-021, P-022 in effect)

---

## 1. Overview

This spec delivers two major capability expansions for the Echelon prototype system. The first is the NS-003 prototype: a Generator-Critic schema validator (NS-003-A) that enforces write-time compliance of agent artifact outputs against deterministic JSON schemas, combined with an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph across a spec run and emits pre-commit conflict signals when new assertions contradict existing beliefs. The second is the U-CA-004 experiment infrastructure: an automated controlled experiment that determines whether five cognitive architecture overlays (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) improve Echelon artifact quality enough to meet the patent-grade evidence bar (P-020). The CA overlay implementations themselves are conditionally authorized — they may only be committed if the U-CA-004 experiment resolves POSITIVE.

The two sub-systems share three integration points: the endocrine event system, the COMMANDER dispatch protocol, and the Echelon artifact store. Both sub-systems must be designed to coexist at these integration points.

The NS-003 novelty claim (the Generator-Critic plus AGM belief revision combination applied to multi-agent artifact stores) has zero prior literature as of 2026-04-03 (U-015-008, systematic search). This combination is the primary IP asset (P-019). Spec 017 operationalizes its measurement under constitution principles P-020 through P-022.

Per P-022: FPCR ≥ 0.70 = PROTOTYPE_VIABLE; FPCR ≥ 0.80 = PATENT_GRADE PASS. Both thresholds are in effect simultaneously — the experiment reports against both; PROTOTYPE_VIABLE is sufficient for continued build-phase execution; PATENT_GRADE is required for patent filing.

---

## 2. Scope

### In-Scope

- NS-003-A: Schema validator script that applies deterministic JSON schemas to Echelon agent outputs across 6 artifact categories
- NS-003-B: AGM belief revision module implementing BeliefNode persistence, ConflictSignal emission, and AGM minimal contraction/revision
- NS-003 experiment runner: N=30 invocations measuring FPCR, contradiction catch rate, and false positive rate
- U-CA-004 experiment runner: N=20 per condition (BASELINE, CA-ACTIVE), AQS proxy scoring via automated LLM judge (P-021), Mann-Whitney U statistical analysis
- Dependency management: `scripts/requirements.txt` and `scripts/setup.sh`
- CA overlay implementations (CONDITIONAL on U-CA-004 POSITIVE verdict per P-020):
  - Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory
- Negative outcome report if U-CA-004 resolves NEGATIVE or INCONCLUSIVE

### Out-of-Scope

- Production deployment of NS-003 or CA overlays to live squad runs
- Changes to the endocrine.sh structure (integration is via existing command calls only)
- Cross-run BeliefGraph persistence (v1 scope is run-scoped only)
- Fine-tuning, weight changes, or learned model parameters (API-only constraint per ADR-003)
- The 40-70% token reduction claim (P5 SPECULATION per P-005 — beyond current evidence)
- Evaluation of CA overlays 2-5 (Goal Stack, LIDA Broadcast, GWT, Episodic Memory) before ACT-R Typed Buffer experiment completes

---

## 3. User Scenarios & Testing

### Scenario 1: NS-003 Schema Validator Catches a Non-Compliant Artifact

**As a** squad researcher measuring NS-003 artifact compliance,
**I want to** run the NS-003 Critic validator against a set of Echelon agent outputs,
**So that** I can quantify the First-Pass Compliance Rate and determine whether NS-003-A meets the PROTOTYPE_VIABLE or PATENT_GRADE threshold.

#### Acceptance Criteria

- **AC-1.1:** Given a set of N=30 Echelon agent invocations producing artifact outputs, when `scripts/ns003_critic.py` is executed against those outputs, then the schema validator module produces a validation report enumerating per-field PASS/FAIL verdicts for every field in each artifact's schema, with a confidence score in [0.5, 0.95] for each verdict.
- **AC-1.2:** Given a validation report produced by `scripts/ns003_critic.py`, when the FPCR is computed as (invocations accepted on first attempt / total invocations), then the report includes the computed FPCR value labeled with its classification: PATENT_GRADE if ≥ 0.80, PROTOTYPE_VIABLE if ≥ 0.70 and < 0.80, INCONCLUSIVE if < 0.70.
- **AC-1.3:** Given a single artifact invocation that fails schema validation, when the validator processes it, then the API call for that validation completes within 30 seconds; and the total run for N=30 artifacts completes within 10 minutes.
- **AC-1.4:** Given a known-good artifact from a prior Echelon spec run (runs 015-016 or equivalent calibration set), when the schema validator module processes the artifact, then the module assigns a PASS verdict to the artifact (false rejection rate on known-good calibration set ≤ 5%).
- **AC-1.5:** Given the Anthropic API returns an HTTP 401 authentication error during a batch run, when `scripts/ns003_critic.py` processes that batch, then the schema validator module SHALL write a PARTIAL_RESULTS result file containing verdicts for completed artifacts, and the batch SHALL stop with a clear authentication error message — not a silent failure.
- **AC-1.6:** Given a schema definition file for one artifact category is missing from the schemas directory, when `scripts/ns003_critic.py` is launched, then the schema validator module SHALL exit with code 2 before processing any artifacts, with an error message identifying the missing schema file path.

---

### Scenario 2: NS-003 Belief Revision Engine Detects a Cross-Stage Contradiction

**As a** squad researcher evaluating artifact consistency enforcement,
**I want to** run the AGM belief revision module against Echelon pipeline artifacts,
**So that** I can verify that contradictions between artifact stages are detected and the contradiction catch rate meets the ≥ 0.80 target.

#### Acceptance Criteria

- **AC-2.1:** Given a set of Echelon artifacts containing at least one assertion conflict (same field_identifier populated with incompatible values by two different pipeline stages), when `scripts/ns003_agm.py` is executed in post-hoc mode (`--mode post-hoc`), then the conflict is detected and a contradiction report is produced listing: contradiction type (assertion_conflict, scope_conflict, or architecture_conflict), confidence score, and recommended action (accept, revert, or escalate).
- **AC-2.2:** Given `scripts/ns003_agm.py` is executed in pre-commit mode (`--mode pre-commit`), when a new assertion for a field_identifier that already has an ACTIVE BeliefNode is submitted, then a ConflictSignal is emitted before the new assertion is committed to the artifact store.
- **AC-2.3:** Given a set of N=30 Echelon invocations with planted contradictions, when the AGM module processes them, then the contradiction catch rate (detected contradictions / planted contradictions) is ≥ 0.80; and the false positive rate (spurious conflict signals / total non-conflicting assertions) is ≤ 0.20.
- **AC-2.4:** Given a conflict is resolved by AGM revision (K*2 minimal contraction), when the resolution is applied, then the AGM belief revision module retains the superseded BeliefNode in the graph with status SUPERSEDED and a superseded_by reference to the new node — the original assertion is not deleted.

---

### Scenario 3: NS-003 Experiment Produces a Measurable FPCR Result

**As a** patent-track researcher requiring reproducible experimental evidence,
**I want to** run the NS-003 experiment across N=30 Echelon invocations and receive a structured results file,
**So that** the FPCR, contradiction catch rate, and false positive rate are documented with reproducibility metadata sufficient for external validation.

#### Acceptance Criteria

- **AC-3.1:** Given `scripts/ns003_experiment.py` is executed with access to the Echelon extension codebase (locked to a recorded commit hash), when the experiment run completes, then the NS-003 experiment service produces `experiments/ns003-results.json` containing: per-invocation schema validation verdicts, computed FPCR, contradiction catch rate, false positive rate, experiment date, codebase commit hash, and model identifier string.
- **AC-3.2:** Given `experiments/ns003-results.json` exists, when `experiments/ns003-report.md` is generated, then the NS-003 experiment service states the FPCR classification (PATENT_GRADE / PROTOTYPE_VIABLE / INCONCLUSIVE) against both the 0.70 and 0.80 thresholds per P-022, and records the codebase commit hash for reproducibility.
- **AC-3.3:** Given the experiment is re-run against the same commit hash with the same model identifier, when results are compared, then the NS-003 experiment service reports FPCR differing by no more than ±0.05 across runs (reproducibility bound).

---

### Scenario 4: U-CA-004 Experiment Produces a POSITIVE or NEGATIVE Verdict

**As a** researcher gating cognitive architecture overlay implementation on experimental evidence,
**I want to** run the U-CA-004 controlled experiment comparing BASELINE and CA-ACTIVE conditions,
**So that** the experiment produces a statistically valid verdict (POSITIVE or NEGATIVE) that authorizes or blocks CA overlay implementation per P-020.

#### Acceptance Criteria

- **AC-4.1:** Given `scripts/uca004_runner.py` is executed with `--conditions BASELINE CA-ACTIVE --n 20`, when N=20 invocations per condition complete, then the U-CA-004 experiment service produces `experiments/uca004-results.json` containing: per-invocation AQS scores (completeness, consistency, specificity, actionability, innovation, each 0-5), condition label, run_id, codebase commit hash, model identifier, and Mann-Whitney U statistic and p-value.
- **AC-4.2:** Given AQS scoring in the CA-ACTIVE condition, when the automated LLM judge evaluates each invocation output, then the AQS proxy scorer module uses a fixed, versioned scoring prompt template, evaluates each AQS dimension independently, and logs the raw scoring prompt and response for each invocation in an audit trail file.
- **AC-4.3:** Given the Mann-Whitney U test is applied to the two AQS distributions, when the verdict is computed, then the U-CA-004 experiment service classifies the experiment as POSITIVE if and only if p < 0.05 (two-tailed) AND Cohen's d ≥ 0.5; and as NEGATIVE otherwise; INCONCLUSIVE is not a valid verdict state for the binary POSITIVE/NEGATIVE gate.
- **AC-4.4:** Given the experiment produces a POSITIVE verdict, when `experiments/uca004-results.json` is reviewed, then the U-CA-004 experiment service lists all five CA overlay component paths as authorized for implementation, in a state suitable for a human to authorize CA overlay build-phase execution per P-020(b).
- **AC-4.5:** Given the experiment produces a NEGATIVE verdict, when `experiments/uca004-negative-report.md` is generated, then the U-CA-004 experiment service records the U statistic, p-value, Cohen's d, per-condition AQS means, and a recommendation that no CA overlay component implementation code be committed.
- **AC-4.6:** Given fewer than N=16 invocations complete successfully for either condition, when `scripts/uca004_runner.py` finishes processing, then the U-CA-004 experiment service SHALL declare the experiment VOID, write a VOID verdict to `experiments/uca004-results.json`, and SHALL NOT compute a Mann-Whitney U statistic or emit a POSITIVE or NEGATIVE verdict.

---

### Scenario 5: CA Overlay Implementations Hook into COMMANDER Dispatch (Conditional)

**As a** squad engineer deploying validated cognitive architecture overlays,
**I want to** have CA overlay scripts integrated with the COMMANDER dispatch protocol,
**So that** each overlay augments agent context preparation without breaking existing COMMANDER behavior.

**Note**: This scenario is CONDITIONAL. It executes only if U-CA-004 resolves POSITIVE per P-020.

#### Acceptance Criteria

- **AC-5.1:** Given U-CA-004 has resolved POSITIVE and CA overlay scripts are present, when COMMANDER dispatches an agent with a CA overlay active, then the CA overlay component modifies the context pack passed to the agent without altering the routing decision, quality gate thresholds, or endocrine system triggers.
- **AC-5.2:** Given `scripts/ca/goal_stack.py` is active, when an agent run begins, then the Goal Stack component initializes a persistent goal hierarchy for that run and includes the current goal in the agent's context pack.
- **AC-5.3:** Given `scripts/ca/actr_buffer.py` is active, when an agent's context pack is assembled, then the context pack is structured into four typed buffers — declarative, procedural, goal, and imaginal — with total token count no greater than the standard COMMANDER context pack for that agent type.
- **AC-5.4:** Given `scripts/bash/lida_broadcast.sh` is invoked, when a global workspace broadcast event is triggered, then the LIDA broadcast service makes the broadcast payload available to all agents dispatched in the subsequent pipeline step.
- **AC-5.5:** Given `scripts/ca/gwt_workspace.py` is active, when the bounded global workspace is populated, then the GWT workspace component respects a configured maximum token bound and evicts lowest-priority content when the bound is exceeded.
- **AC-5.6:** Given `scripts/ca/episodic_memory.py` is active, when an agent produces an artifact, then the episodic memory module indexes the artifact in the temporal store; and when a subsequent agent queries the episodic memory module, then the module returns the most recent matching artifact for that agent type.

---

### Scenario 6: Dependency Management Enables Reproducible Experiment Execution

**As a** researcher attempting to reproduce NS-003 or U-CA-004 experiment results,
**I want to** run a single setup command and have all required dependencies installed,
**So that** the experiment can be executed in a new environment without manual dependency resolution.

#### Acceptance Criteria

- **AC-6.1:** Given a clean environment with Python 3 and pip available and `ANTHROPIC_API_KEY` set, when `scripts/setup.sh` is executed, then all dependencies listed in `scripts/requirements.txt` are installed and both `scripts/ns003_critic.py` and `scripts/uca004_runner.py` complete their `--help` invocations without error.
- **AC-6.2:** Given `scripts/requirements.txt` exists, when it is inspected, then it contains pinned version constraints for all direct dependencies required by NS-003 and U-CA-004; and no credential, API key, or token appears anywhere in the file.
- **AC-6.3:** Given `ANTHROPIC_API_KEY` is not set in the environment, when any script that requires the Anthropic API is executed, then it exits with a clear error message identifying the missing variable — not with a silent failure or cryptic authentication error.

---

## 4. Functional Requirements

### NS-003-A: Schema Validator

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-NS3A-001 | The schema validator module SHALL read a JSON schema definition for each of the 6 Echelon artifact categories (DISCOVER-class, ASSESS-class, HOW-class, PLAN-class, BUILD-class, LEARN-class) and SHALL validate a given agent artifact output against the corresponding schema. Each schema specifies required fields, field types, and minimum content constraints for that artifact category. The module is implemented in `scripts/ns003_critic.py`. (See also: FR-NS3A-002, FR-NS3A-005) | Scenario 1 | MVP |
| FR-NS3A-002 | The schema validator module SHALL produce a per-field PASS/FAIL verdict for every field defined in the schema. Each verdict SHALL include a confidence score in [0.5, 0.95] calibrated to the contradiction type detected. | Scenario 1 | MVP |
| FR-NS3A-003 | The schema validator module SHALL use a two-component design: (1) a deterministic JSON Schema validator (`jsonschema` library) for required-field and type compliance checking, and (2) the Anthropic Claude API (model: claude-sonnet-4-6) for prose-section structure assessment and confidence scoring. The API key SHALL be read from the `ANTHROPIC_API_KEY` environment variable; no credential SHALL appear in any script or configuration file (P-014). (See also: FR-DEP-003, NFR-SEC-001) | Scenario 1 | MVP |
| FR-NS3A-004 | The schema validator module SHALL implement a per-artifact API call latency limit of 30 seconds. If the API call for a single artifact exceeds 30 seconds, the validator SHALL record a TIMEOUT verdict for that artifact and SHALL continue to the next. The total run for N=30 artifacts SHALL complete within 10 minutes. | Scenario 1 | MVP |
| FR-NS3A-005 | The schema validator module SHALL report false rejection rate on a calibration set of known-good prior run artifacts. The false rejection rate on this calibration set SHALL NOT exceed 5%. If the false rejection rate exceeds 5%, the schema SHALL be flagged for recalibration before the full N=30 experiment run proceeds. | Scenario 1 | MVP |
| FR-NS3A-ERR-001 | The schema validator module SHALL exit with exit code 1 and print a human-readable error to stderr when `ANTHROPIC_API_KEY` is absent from the environment. The module SHALL NOT make any API call after detecting the missing key. | Scenario 6 | MVP |
| FR-NS3A-ERR-002 | When the Anthropic API returns an authentication error (HTTP 401) during a batch run, the schema validator module SHALL stop processing and write a PARTIAL_RESULTS result file containing verdicts for completed artifacts plus an error entry for the failed artifact. The module SHALL NOT silently discard completed verdicts. | Scenario 1 | MVP |
| FR-NS3A-ERR-003 | When a schema definition file is missing or malformed (invalid JSON), the schema validator module SHALL raise a SchemaLoadError and exit with exit code 2, logging the path of the missing/malformed file. The artifact run SHALL NOT proceed with a missing schema. | Scenario 1 | MVP |
| FR-NS3A-ERR-004 | When an input artifact file is empty or contains fewer than 10 characters, the schema validator module SHALL record a SKIP verdict for that artifact with reason "empty_artifact" and SHALL continue processing remaining artifacts. | Scenario 1 | MVP |

---

### NS-003-B: AGM Belief Revision Engine

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-NS3B-001 | The AGM belief revision module SHALL maintain a persistent BeliefNode graph for the duration of a spec run. Each BeliefNode SHALL store: field_identifier, value, stage (pipeline stage that wrote it), confidence score (0.5-0.95), and superseded_chain (ordered list of prior BeliefNodes for the same field_identifier that were superseded). The module is implemented in `scripts/ns003_agm.py`. (See also: FR-NS3B-002, FR-NS3B-005) | Scenario 2 | MVP |
| FR-NS3B-002 | The AGM belief revision module SHALL detect three contradiction types when a new assertion is evaluated against an existing BeliefNode: assertion_conflict (the new value is logically incompatible with the existing value), scope_conflict (the new assertion claims a different scope boundary than the existing one), and architecture_conflict (the new assertion implies an architectural decision that contradicts the existing decision). Each type SHALL be reported with a confidence score. | Scenario 2 | MVP |
| FR-NS3B-003 | The AGM belief revision module SHALL implement four AGM revision postulates for minimal revision (K*2). The consistency predicate is: the ACTIVE belief set contains at most one BeliefNode per field_identifier at all times. Minimality is defined as: when a revision is performed, the module removes from ACTIVE only the BeliefNode whose field_identifier matches the incoming assertion — no other BeliefNodes are removed or modified. The four postulates implemented are: (1) Success — the incoming assertion SHALL enter the revised ACTIVE belief set if it is not self-contradictory; (2) Consistency — the ACTIVE belief set SHALL satisfy the consistency predicate after every revision; (3) Relevance — the module SHALL remove from ACTIVE only BeliefNodes whose field_identifier matches the incoming assertion; (4) Vacuity — if no BeliefNode with matching field_identifier exists in ACTIVE, the incoming assertion SHALL be added without removing any existing BeliefNode. Postulates K*3 (Inclusion) and K*5 (Extensionality) are explicitly out-of-scope for v1. Test oracle: given an existing ACTIVE belief that field "req_scope" equals "auth_only" (written by DISCOVER stage), when an incoming assertion claims field "req_scope" equals "auth_and_api" (from ASSESS stage), then the module SHALL produce an ACTIVE set containing only the new "auth_and_api" belief and a SUPERSEDED set containing the original "auth_only" belief. (See also: FR-NS3B-001, FR-NS3B-006) | Scenario 2 | MVP |
| FR-NS3B-004 | The AGM belief revision module SHALL accept a mode parameter (`--mode [pre-commit\|post-hoc]`) to select its operating mode. In pre-commit mode, the module evaluates assertions before they are committed to the artifact store and emits a ConflictSignal synchronously. In post-hoc mode, the module reads completed artifact files and produces a contradiction report. Default mode is post-hoc. The interface flag design must accommodate IS-003 write-mechanism investigation findings without requiring a module redesign. If HOW-phase investigation (IS-003 resolution) determines that pre-commit mode is architecturally infeasible (i.e., agents self-write artifact files and no synchronous write intercept hook exists), then: (a) the pre-commit mode implementation is removed from scope; (b) the spec Section 1 novelty claim SHALL be amended to replace 'pre-commit' with 'post-hoc'; (c) the HOW ARCHITECT SHALL document this feasibility verdict in an Architecture Decision Record before any NS-003-B implementation begins. The post-hoc mode (AC-2.1) remains in scope regardless of the pre-commit feasibility verdict. | Scenario 2 | MVP |
| FR-NS3B-005 | The AGM belief revision module SHALL retain a superseded BeliefNode in the graph with status SUPERSEDED and a reference to the superseding node when that node is superseded by AGM revision. The superseded node SHALL NOT be deleted. This preserves the full provenance chain for audit and reproducibility. | Scenario 2 | MVP |
| FR-NS3B-006 | The AGM belief revision module SHALL produce a contradiction report that lists for each detected contradiction: contradiction type, confidence score, field_identifier, the two conflicting assertions, the pipeline stages that produced them, and the recommended action (accept, revert, or escalate). | Scenario 2 | MVP |
| FR-NS3B-ERR-001 | When the AGM belief revision module receives a malformed assertion missing required fields (field_identifier, value, or stage), the module SHALL reject the malformed assertion by emitting a MalformedAssertionError to stderr. The BeliefGraph SHALL remain unmodified after rejection. (See also: FR-NS3B-001, FR-NS3B-005) | Scenario 2 | MVP |
| FR-NS3B-ERR-002 | When the BeliefGraph write operation fails (disk I/O error, serialization error), the AGM belief revision module SHALL roll back the attempted write, log the error to the contradiction report, and return a WRITE_FAILED status. No partial BeliefGraph state SHALL be persisted. | Scenario 2 | MVP |

---

### NS-003 Experiment Runner

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-NS3E-001 | The NS-003 experiment service SHALL execute NS-003 schema validation and belief revision against N=30 Echelon invocations using live runs as the primary data source. Each live run is a fresh invocation of an Echelon squad agent producing an artifact output; the service validates that output in real time via the schema validator module. The service SHALL record the codebase commit hash at execution time and store it in `experiments/ns003-results.json`. If live invocations are unavailable (defined as: API quota exhausted or ANTHROPIC_API_KEY absent), the service MAY fall back to using existing spec artifacts from prior runs (runs 015-016 or later) as test cases; in this case the service SHALL label the data source as 'historical_artifacts' in `ns003-results.json` and SHALL include the statement 'DEVIATION FROM PRE-REGISTERED PROTOCOL: historical artifacts used in lieu of live invocations' in `experiments/ns003-report.md`. The service is implemented in `scripts/ns003_experiment.py`. | Scenario 3 | MVP |
| FR-NS3E-002 | The NS-003 experiment service SHALL produce `experiments/ns003-results.json` containing: per-invocation verdicts (PASS/FAIL/TIMEOUT), computed FPCR, contradiction catch rate (detected / planted), false positive rate (spurious signals / total non-conflicting assertions), experiment date and time, codebase commit hash, and model identifier string. | Scenario 3 | MVP |
| FR-NS3E-003 | The NS-003 experiment service SHALL produce `experiments/ns003-report.md` summarizing the experiment results. The report SHALL state the FPCR classification against both thresholds per P-022: PATENT_GRADE (≥ 0.80), PROTOTYPE_VIABLE (≥ 0.70 and < 0.80), or INCONCLUSIVE (< 0.70). The report SHALL include the contradiction catch rate verdict (PASS if ≥ 0.80, FAIL otherwise) and the false positive rate verdict (PASS if ≤ 0.20, FAIL otherwise). | Scenario 3 | MVP |
| FR-NS3E-004 | The NS-003 experiment service SHALL measure FPCR against both the PROTOTYPE_VIABLE threshold (0.70) and the PATENT_GRADE threshold (0.80) per P-022. The service SHALL NOT select one threshold as authoritative — both are reported. The human determines which threshold governs the subsequent action. | Scenario 3 | MVP |

---

### U-CA-004 Experiment Infrastructure

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-UCA-001 | The U-CA-004 experiment service SHALL execute N=20 Echelon invocations per condition. Two conditions are defined: BASELINE (standard Echelon invocations without CA overlay modifications) and CA-ACTIVE (invocations with one CA overlay mechanism injected per batch). The service SHALL accept `--conditions` and `--n` arguments to control which conditions are run and how many invocations per condition. The service is implemented in `scripts/uca004_runner.py`. | Scenario 4 | MVP |
| FR-UCA-002 | The U-CA-004 experiment service SHALL use an automated AQS proxy scorer implemented as an LLM judge using the Anthropic Claude API (P-021). The proxy SHALL evaluate each invocation output on five AQS dimensions: completeness, consistency, specificity, actionability, and innovation. Each dimension SHALL be scored independently on a 0-5 integer scale. The proxy SHALL use a fixed, versioned scoring prompt template for all invocations across all conditions. (See also: FR-UCA-003, NFR-AUD-001) | Scenario 4 | MVP |
| FR-UCA-003 | The U-CA-004 experiment service SHALL log every AQS scoring call in an audit trail file: the exact scoring prompt, the model response, the extracted per-dimension scores, the run_id, and the condition label. The audit trail enables post-hoc verification of proxy scoring decisions (P-021). | Scenario 4 | MVP |
| FR-UCA-004 | The U-CA-004 experiment service SHALL apply the Mann-Whitney U test (via scipy.stats.mannwhitneyu) to the AQS score distributions of the BASELINE and CA-ACTIVE conditions. The test SHALL be two-tailed with significance threshold p < 0.05. The service SHALL also compute Cohen's d as the effect size measure. (See also: FR-UCA-005, FR-UCA-ERR-002) | Scenario 4 | MVP |
| FR-UCA-005 | The U-CA-004 experiment service SHALL classify the experiment verdict as POSITIVE if p < 0.05 (two-tailed) AND Cohen's d ≥ 0.5. Any other outcome SHALL be classified as NEGATIVE. INCONCLUSIVE is not a valid verdict category for the binary gate. If fewer than N=16 invocations complete successfully for either condition, the experiment VOID rule (FR-UCA-ERR-002) applies and no POSITIVE or NEGATIVE verdict is computed. | Scenario 4 | MVP |
| FR-UCA-006 | The U-CA-004 experiment service SHALL produce `experiments/uca004-results.json` containing: per-invocation AQS scores by dimension, condition label, run_id, codebase commit hash, model identifier, Mann-Whitney U statistic, p-value, Cohen's d, the final verdict (POSITIVE, NEGATIVE, or VOID), and a `void_reason` field (nullable string, non-null only when verdict is VOID). | Scenario 4 | MVP |
| FR-UCA-007 | The U-CA-004 experiment service SHALL produce `experiments/uca004-negative-report.md` if the U-CA-004 experiment resolves NEGATIVE, containing: U statistic, p-value, Cohen's d, per-condition AQS means and standard deviations, and an explicit statement that no CA overlay implementation code may be committed per P-020(c). | Scenario 4 | MVP |
| FR-UCA-ERR-001 | When the AQS proxy scorer returns a score outside the valid range [0, 5] for any dimension, the U-CA-004 experiment service SHALL discard that invocation's scoring result, log the anomaly to the audit trail, and re-run the scoring call once. If the second call also returns an out-of-range score, the invocation is marked SCORING_FAILED and excluded from Mann-Whitney analysis. | Scenario 4 | MVP |
| FR-UCA-ERR-002 | When fewer than N=16 invocations complete successfully for either condition (due to timeouts, API failures, or SCORING_FAILED exclusions), the U-CA-004 experiment service SHALL declare the experiment VOID. A VOID result is not a NEGATIVE verdict — it does not block or authorize CA overlay implementation. The service SHALL NOT compute Mann-Whitney U on N < 16 invocations. | Scenario 4 | MVP |
| FR-UCA-ERR-003 | When an individual invocation exceeds 60 seconds, the U-CA-004 experiment service SHALL mark that invocation TIMEOUT, record the elapsed time, and continue to the next invocation. TIMEOUT invocations count against the N=20 target and may trigger the FR-UCA-ERR-002 VOID condition. | Scenario 4 | MVP |

---

### CA Overlay Implementations (CONDITIONAL — REQ-017-005)

**Gate condition**: All requirements in this section are CONDITIONAL on U-CA-004 resolving POSITIVE per P-020. If U-CA-004 resolves NEGATIVE, none of these requirements apply and `experiments/uca004-negative-report.md` is the terminal deliverable for this domain area.

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-CAO-000 | The gate-check service (`scripts/ca/verify_gate.sh`) SHALL verify that `experiments/uca004-results.json` exists, contains `verdict: POSITIVE`, and that the commit hash in that file matches the current git HEAD commit hash before any CA overlay implementation file (*.py or *.sh) is created in the `scripts/ca/` directory. If the gate-check service returns non-zero, no CA overlay file may be created. The `scripts/ca/` directory SHALL NOT contain any implementation file unless this gate check passes. (See also: FR-UCA-006, NFR-SCOPE-001) | Scenario 5 | MVP (CONDITIONAL gate check) |
| FR-CAO-001 | The Goal Stack component (`scripts/ca/goal_stack.py`) SHALL maintain a persistent goal hierarchy for each agent run. The hierarchy SHALL be initialized at the start of each agent dispatch and the current active goal SHALL be included in the agent's context pack. The component SHALL NOT alter COMMANDER routing decisions or quality gate thresholds. | Scenario 5 | Should-Have (CONDITIONAL) |
| FR-CAO-002 | The ACT-R buffer component (`scripts/ca/actr_buffer.py`) SHALL structure the agent context pack into four typed buffers: declarative, procedural, goal, and imaginal. The total token count of the structured context pack SHALL NOT exceed the token count of the standard COMMANDER context pack for the same agent type. | Scenario 5 | Should-Have (CONDITIONAL) |
| FR-CAO-003 | The LIDA broadcast service (`scripts/bash/lida_broadcast.sh`) SHALL implement a global workspace broadcast mechanism. When invoked, the LIDA broadcast service SHALL make the broadcast payload available to all agents dispatched in the subsequent pipeline step. The broadcast payload SHALL be stored in a file accessible to COMMANDER during the next dispatch cycle. The payload file SHALL be consumed (read and deleted) at the start of the next COMMANDER dispatch cycle following the broadcast. If no subsequent dispatch cycle occurs within the run, the payload file SHALL be discarded at run end. Subsequent LIDA broadcast calls within the same pipeline step SHALL replace the payload file — subsequent calls SHALL NOT append to it. | Scenario 5 | Should-Have (CONDITIONAL) |
| FR-CAO-004 | The GWT workspace component (`scripts/ca/gwt_workspace.py`) SHALL maintain a bounded global workspace that, when content is added and the workspace exceeds its configured maximum token bound, SHALL evict the lowest-priority content to restore compliance with the bound. Priority is determined by recency of contribution. | Scenario 5 | Should-Have (CONDITIONAL) |
| FR-CAO-005 | The episodic memory module (`scripts/ca/episodic_memory.py`) SHALL index agent-produced artifacts in a temporal store. When a subsequent agent queries the episodic memory for a given agent type, the module SHALL return the most recent indexed artifact for that agent type. The temporal index SHALL use the artifact's pipeline stage timestamp as the primary sort key. | Scenario 5 | Should-Have (CONDITIONAL) |
| FR-CAO-006 | Each CA overlay component SHALL integrate with the COMMANDER dispatch protocol via the protocol defined in `agents/control/commander.md`. No component SHALL modify COMMANDER's routing decisions, quality gate thresholds, or endocrine system triggers. | Scenario 5 | Should-Have (CONDITIONAL) |

---

### Dependency Management

| ID | Requirement | User Story | Priority |
|----|-------------|------------|----------|
| FR-DEP-001 | The requirements file (`scripts/requirements.txt`) SHALL list all Python package dependencies required by NS-003 and U-CA-004 scripts, with pinned version constraints for each direct dependency. No credentials, API keys, or tokens SHALL appear in this file (P-014). | Scenario 6 | MVP |
| FR-DEP-002 | The setup script (`scripts/setup.sh`) SHALL install all dependencies from `scripts/requirements.txt` when executed in an environment with Python 3 and pip available. After execution, both the schema validator module (`scripts/ns003_critic.py --help`) and the U-CA-004 experiment service (`scripts/uca004_runner.py --help`) SHALL complete without error. | Scenario 6 | MVP |
| FR-DEP-003 | Every module that requires `ANTHROPIC_API_KEY` SHALL check for its presence at startup and SHALL exit with a clear, human-readable error message identifying the missing variable if it is absent. No module SHALL silently fall back to unauthenticated behavior. | Scenario 6 | MVP |

---

## 5. Non-Functional Requirements

| ID | Category | Requirement | Measurable Target |
|----|----------|-------------|-------------------|
| NFR-PERF-001 | Performance | The schema validator module must complete each API call within a bounded time per artifact (See also: FR-NS3A-004) | ≤ 30 seconds per artifact validation call |
| NFR-PERF-002 | Performance | The NS-003 experiment service must complete the full experiment run across all test artifacts within a bounded total time (See also: FR-NS3E-001) | ≤ 10 minutes for N=30 artifacts |
| NFR-QUAL-001 | Experiment Quality | The schema validator module false rejection rate on the calibration set must be low enough not to confound FPCR measurement | ≤ 5% false rejections on known-good calibration set |
| NFR-QUAL-002 | Experiment Quality | The AGM belief revision module contradiction catch rate must meet the pre-registered target | ≥ 0.80 CCR across N=30 invocations |
| NFR-QUAL-003 | Experiment Quality | The AGM belief revision module false positive rate must be low enough to make signals actionable | ≤ 0.20 FPR across N=30 invocations |
| NFR-REPRO-001 | Reproducibility | The NS-003 experiment service SHOULD produce FPCR results with variance no greater than ±0.05 when re-run on the same commit hash. The schema validator module uses the jsonschema library for deterministic field compliance checks. The Claude API module provides prose-section assessment with temperature=0 where supported. If temperature=0 is unavailable for the selected model, the reproducibility bound is a best-effort target documented in `experiments/ns003-report.md`. | FPCR variance ≤ ±0.05 on deterministic Critic component; best-effort target for prose-assessment component |
| NFR-REPRO-002 | Reproducibility | The NS-003 experiment service must lock and record the codebase version used in both experiments (See also: FR-NS3E-001, FR-UCA-001) | Commit hash recorded in both `ns003-results.json` and `uca004-results.json` |
| NFR-REPRO-003 | Reproducibility | The API module must use a consistent model identifier for all invocations within a single experiment batch | Same model identifier string for all invocations within a batch |
| NFR-SEC-001 | Security | The system must not store credentials, API keys, or tokens in any committed file (See also: FR-DEP-001, NFR-SEC-002) | Zero credential strings in any file under `.specify/`, `scripts/`, or `experiments/` (P-014) |
| NFR-SEC-002 | Security | Every module must read the `ANTHROPIC_API_KEY` exclusively from the environment variable and must not fall back to config files or hardcoded strings | All scripts read the key exclusively from the environment; no fallback to config files or hardcoded strings |
| NFR-AUD-001 | Auditability | The U-CA-004 experiment service must log every AQS proxy scoring call with its full prompt and response (See also: FR-UCA-003) | Complete audit trail in `experiments/uca004-scoring-audit.jsonl` (P-021) |
| NFR-AUD-002 | Auditability | The NS-003 experiment service must store sufficient metadata in the results file for an external researcher to reproduce the experiment (See also: FR-NS3E-002) | `ns003-results.json` contains date, commit hash, model identifier, N count, and per-invocation verdicts |
| NFR-SCOPE-001 | Constitutional Compliance | The CA overlay component implementation files SHALL NOT be created in the `scripts/ca/` directory before U-CA-004 resolves POSITIVE. The gate-check service (FR-CAO-000) validates this constraint. | Zero CA overlay implementation files committed before POSITIVE verdict (P-020) |
| NFR-SCOPE-002 | Constitutional Compliance | The NS-003 experiment service must state FPCR results against both the 0.70 PROTOTYPE_VIABLE and 0.80 PATENT_GRADE thresholds | Both thresholds appear in `ns003-report.md`; neither is suppressed (P-022) |

---

## 6. Key Entities

### BeliefNode
- **Attributes:** field_identifier (unique key for a schema field within a pipeline run), value (assertion content), stage (pipeline stage that wrote the assertion), confidence (0.5-0.95), status (ACTIVE or SUPERSEDED), superseded_chain (ordered list of prior BeliefNodes for this field_identifier)
- **Relationships:** One BeliefNode per field_identifier per run; superseded nodes reference their successor; ConflictSignal references the conflicting BeliefNode pair
- **Lifecycle:** Created at artifact commit time → ACTIVE → SUPERSEDED (when AGM revision selects the incoming assertion over it); SUPERSEDED nodes are never deleted
- **Constraints:** field_identifier must be unique per run in the ACTIVE set; SUPERSEDED nodes may share field_identifier with the ACTIVE node; version_counter is monotonically increasing per field_identifier

### ConflictSignal
- **Attributes:** field_identifier, new_assertion text, existing_node reference, contradiction_type (assertion_conflict / scope_conflict / architecture_conflict), confidence (0.5-0.95), recommended_action (accept / revert / escalate)
- **Relationships:** Produced by the belief revision module when a new assertion conflicts with an existing ACTIVE BeliefNode; consumed by COMMANDER to determine endocrine event to fire
- **Lifecycle:** Emitted at assertion evaluation time → consumed by COMMANDER → archived in contradiction report; not persisted independently after consumption
- **Constraints:** recommended_action must be one of exactly three values; confidence must be in [0.5, 0.95]

### AQS Evaluation Record
- **Attributes:** run_id, condition (BASELINE or CA-ACTIVE), five dimension scores (completeness, consistency, specificity, actionability, innovation — each 0-5), total AQS (sum / 25), scoring_prompt_hash (hash of the prompt template version used), model_identifier
- **Relationships:** One record per invocation per condition; N=20 records per condition for Mann-Whitney analysis; archived in audit trail with full prompt and response
- **Lifecycle:** Created by AQS proxy scorer during experiment run → stored in `uca004-results.json` → consumed by Mann-Whitney U computation
- **Constraints:** Each dimension score is an integer in [0, 5]; total AQS is in [0.0, 1.0]; scoring_prompt_hash must be identical across all records in a single experiment batch

### Experiment Result Package
- **Attributes:** experiment_id (NS-003 or UCA-004), verdict (PATENT_GRADE / PROTOTYPE_VIABLE / INCONCLUSIVE for NS-003; POSITIVE / NEGATIVE for UCA-004), FPCR (NS-003 only), CCR (NS-003 only), FPR (NS-003 only), U_statistic (UCA-004 only), p_value (UCA-004 only), cohens_d (UCA-004 only), codebase_commit_hash, model_identifier, experiment_date
- **Relationships:** Produced by the respective experiment runner; referenced by the human decision to authorize or block CA overlay implementation
- **Lifecycle:** Created at experiment completion → archived as JSON → used as evidence artifact in patent documentation
- **Constraints:** verdict must be one of the defined classification values; codebase_commit_hash must be a valid git commit hash; no verdict field may be null or empty

---

## 7. Success Criteria

### MVP Success
- [ ] `scripts/ns003_critic.py` produces per-field PASS/FAIL verdicts with confidence scores for all 6 artifact categories, completing N=30 validations within 10 minutes
- [ ] `scripts/ns003_agm.py --mode post-hoc` detects planted contradictions with a catch rate ≥ 0.80 and false positive rate ≤ 0.20
- [ ] `experiments/ns003-results.json` is produced with FPCR classified against both P-022 thresholds (PROTOTYPE_VIABLE ≥ 0.70, PATENT_GRADE ≥ 0.80)
- [ ] `scripts/uca004_runner.py` runs N=20 invocations per condition and produces `experiments/uca004-results.json` with a POSITIVE or NEGATIVE verdict
- [ ] `scripts/requirements.txt` and `scripts/setup.sh` enable one-command setup in a clean environment
- [ ] No credentials appear in any committed file (P-014 compliance verified)

### Full Product Success (CONDITIONAL on U-CA-004 POSITIVE)
- [ ] All 5 CA overlay scripts are implemented and integrated with COMMANDER dispatch per FR-CAO-001 through FR-CAO-006
- [ ] FPCR achieves PATENT_GRADE (≥ 0.80) classification enabling patent filing prerequisites per P-022
- [ ] The AQS scoring audit trail is complete and enables independent verification of all proxy scoring decisions per P-021
- [ ] The NS-003 experiment results are reproducible: re-run on the same commit hash produces FPCR within ±0.05 of the original result

### Negative Path Success (if U-CA-004 NEGATIVE)
- [ ] `experiments/uca004-negative-report.md` is produced with full statistical findings
- [ ] No CA overlay implementation code is committed per P-020(c)
- [ ] The negative result is documented with sufficient statistical detail for a third-party researcher to verify the verdict

---

## 8. Open Questions

| ID | Question | Impact | Source |
|----|----------|--------|--------|
| OQ-001 | What is the write-time interception hook mechanism in COMMANDER for NS-003 pre-commit mode? | Determines whether NS-003-B pre-commit mode (FR-NS3B-004) is feasible via Model A (COMMANDER-controlled write) or requires Model B (write-wrapper utility). Architecture decision for HOW. | unknowns.md U-009, U-012, issues.md IS-003 |
| OQ-002 | Are known-good sample artifacts from spec runs 008-014 accessible for Phase 1 schema calibration? | If unavailable, Phase 1 calibration must use runs 015-016 as the calibration set. HOW phase must document this deviation if it occurs. | unknowns.md U-007, issues.md IS-010 |
| OQ-003 | Does the Anthropic SDK invocation pattern propagate `ANTHROPIC_API_KEY` correctly from the speckit dispatch environment? | If not, NS-003 Generator and U-CA-004 experiment invocations fail at authentication. FR-DEP-003 captures the error-handling requirement; the propagation mechanism is a HOW-phase concern. | unknowns.md U-011, issues.md IS-009 |
| OQ-004 | What is the Markdown-to-structured-data parsing strategy for the NS-003 Critic? | Determines the input format pipeline for the Critic schema validator. The existing contradiction-scanner.py extraction logic is a candidate reuse. HOW-phase decision. | unknowns.md U-004 |
| OQ-005 | What similarity ranking method (TF-IDF, BM25, or embeddings API) is used for the ACT-R Typed Buffer retrieval_buffer ranking? | Affects latency, cost, and the API-only constraint (ADR-003). HOW-phase architecture decision. | unknowns.md U-008 |

---

## 9. Assumptions in Effect

| ID | Assumption | Status | Requirements Affected |
|----|-----------|--------|----------------------|
| A-001 [amended per IS-022] | The NS-003 Critic uses a two-component design: (1) a deterministic JSON Schema validator (`jsonschema` library) for required-field and type compliance checking; (2) the Claude API (claude-sonnet-4-6) for prose-section structure assessment and confidence scoring. The schema-validator component is fully deterministic. The Claude API component introduces bounded non-determinism bounded by the ±0.05 FPCR reproducibility target. This amendment reconciles A-001 with FR-NS3A-003 per IS-022 resolution. | validated (amended) | FR-NS3A-001, FR-NS3A-002, FR-NS3A-003, NFR-REPRO-001 |
| A-002 | The Anthropic Python SDK is accessible in the script execution environment via `ANTHROPIC_API_KEY` | unvalidated | FR-NS3A-003, FR-UCA-002, FR-DEP-003 |
| A-003 | JSON Schema validation of 6 Echelon artifact categories is feasible without a false rejection rate > 5% on known-good outputs | unvalidated | FR-NS3A-005, NFR-QUAL-001 |
| A-004 (resolved by P-022) | FPCR threshold conflict (0.70 brief vs 0.80 pre-registered) is resolved by constitution amendment P-022: both thresholds are in effect simultaneously. 0.70 = PROTOTYPE_VIABLE; 0.80 = PATENT_GRADE. | validated (P-022) | FR-NS3E-004, NFR-SCOPE-002 |
| A-005 | The Echelon extension test codebase is accessible and locked to a recorded commit hash before either experiment begins | unvalidated | FR-NS3E-001, FR-UCA-001 |
| A-006 (corrected per IS-005) | The endocrine.sh Phase 3 event hooks exist in the script but are not yet wired in COMMANDER's post-dispatch protocol. Wiring requires COMMANDER.md additions and Phase 3 activation — these are outstanding deliverables for the HOW phase, not pre-existing. | partially validated — hooks exist in endocrine.sh; COMMANDER wiring is outstanding | FR-CAO-006 |
| A-007 | scipy and other scientific Python packages are installable via pip in the execution environment | low-risk | FR-DEP-001, FR-DEP-002 |
| A-008 | The U-CA-004 experiment tests overlays in the pre-registered order, starting with ACT-R Typed Buffer as Condition C in the first batch | validated | FR-UCA-001, FR-CAO-002 |
| A-009 | NS-003 Critic requires a Markdown-to-dict parsing step before JSON Schema validation | validated (pattern established in contradiction-scanner.py) | FR-NS3A-001 |
| A-010 | Sample sizes N=30 (NS-003) and N=20 per condition (U-CA-004) are fixed per pre-registered design and may not be adjusted post-hoc | validated | FR-NS3E-001, FR-UCA-001 |

---

## 10. Glossary Additions

The following terms are introduced by this spec and are not in the DISCOVER glossary:

| Term | Definition | Scope |
|------|-----------|-------|
| BANZAI Mode | Fully autonomous execution mode for the Echelon squad with no human in the loop for routine decisions. In BANZAI mode, human escalation is triggered only for BLOCKED states, constitutional violations, and CRITICAL issue resolution. BANZAI mode does not override constitutional principles (P-001 through P-022 remain in force). | Spec 017 and all downstream specs |
| PROTOTYPE_VIABLE | FPCR classification for results in [0.70, 0.80). Sufficient for continued build-phase execution of NS-003. Insufficient for patent filing (PATENT_GRADE required). Defined by P-022. | NS-003 experiment reporting |
| PATENT_GRADE | FPCR classification for results ≥ 0.80. The pre-registered PASS threshold from ns003-experiment-design.md. Required for patent filing. Defined by P-022. | NS-003 experiment reporting |
| AQS Proxy Scorer | An automated LLM judge that evaluates Echelon agent outputs on five AQS dimensions: completeness, consistency, specificity, actionability, innovation — each scored 0-5 (integer). Authorized as a substitute for human evaluators in U-CA-004 by P-021. This supersedes the four-dimension (Coherence/Completeness/Scope_Compliance/Internal_Consistency, 0-3 scale) definition in the project glossary.md which reflects the pre-P-021 human-evaluator rubric. | U-CA-004 experiment |
| Calibration Set | A set of known-good Echelon artifact outputs from prior spec runs used to measure the NS-003 Critic's false rejection rate before the full N=30 experiment proceeds. Primary source: spec runs 015-016. Fallback if runs 008-014 are unavailable. | NS-003 Phase 1 |

---

## 11. Scope Classification

### In Scope (MVP)
- NS-003-A schema validator (`scripts/ns003_critic.py`)
- NS-003-B belief revision engine (`scripts/ns003_agm.py`)
- NS-003 experiment runner (`scripts/ns003_experiment.py`)
- U-CA-004 experiment runner with AQS proxy scorer (`scripts/uca004_runner.py`)
- Dependency management (`scripts/requirements.txt`, `scripts/setup.sh`)
- Experiment result files (`experiments/ns003-results.json`, `experiments/ns003-report.md`, `experiments/uca004-results.json`)
- Negative outcome report if U-CA-004 NEGATIVE (`experiments/uca004-negative-report.md`)

### In Scope (Post-MVP, CONDITIONAL on U-CA-004 POSITIVE)
- Goal Stack overlay (`scripts/ca/goal_stack.py`)
- ACT-R Typed Buffer overlay (`scripts/ca/actr_buffer.py`)
- LIDA Broadcast overlay (`scripts/bash/lida_broadcast.sh`)
- GWT Bounded Workspace overlay (`scripts/ca/gwt_workspace.py`)
- Episodic Memory overlay (`scripts/ca/episodic_memory.py`)
- COMMANDER dispatch integration for all 5 overlays

### Explicitly Out of Scope
- Production deployment of any mechanism — spec 017 is prototype and experiment only
- Changes to endocrine.sh structure — integration is via existing command calls only
- Cross-run BeliefGraph persistence — v1 is run-scoped; Episodic Memory (overlay 5) handles cross-run if POSITIVE
- Evaluation of CA overlays 2-5 before the ACT-R Typed Buffer Condition C experiment result is known
- The 40-70% token reduction claim (P5 SPECULATION per P-005) — no measurement of this claim is in scope
- Fine-tuning, weight modification, or model parameter changes (API-only constraint per ADR-003)

---

## 12. Implementation Invariants

The following invariants apply to all components implemented in this spec. Each module SHALL satisfy these constraints in every valid execution state.

- The schema validator module SHALL produce a validation result for every artifact submitted to it.
- The AGM belief revision module SHALL maintain exactly one ACTIVE BeliefNode per field_identifier at all times.
- The NS-003 experiment service SHALL record the codebase commit hash before executing any validation call.
- The U-CA-004 experiment service SHALL log every AQS scoring call to the audit trail file before returning results.
- The setup script SHALL verify all dependency installations complete without error before returning success.
- The gate-check service SHALL block CA overlay component creation when the POSITIVE verdict is absent.
- The schema validator module SHALL report the false rejection rate on the calibration set before the full N=30 run.
- The AGM belief revision module SHALL store superseded BeliefNodes permanently in the graph without deletion.
- The NS-003 experiment service SHALL compute FPCR against both 0.70 and 0.80 thresholds in every run.
- The U-CA-004 experiment service SHALL compute Cohen's d as an effect size measure alongside the Mann-Whitney U statistic.

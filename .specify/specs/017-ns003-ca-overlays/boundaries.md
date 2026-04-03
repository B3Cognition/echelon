# System Boundaries — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03 | **Supersedes**: SCOUT boundaries.md

---

## Synthesis Note

Both NS-003 and U-CA-004 share two Python library dependencies (jsonschema required for both critics; scipy required for U-CA-004 statistics). Shared dependencies must be managed in a single `scripts/requirements.txt` — currently absent from the repo. The two sub-systems have separate internal boundary components but converge on the same external API (Anthropic) and same infrastructure tool (jq/endocrine.sh).

---

## Internal Boundaries

### Contradiction Scanner (Heuristic Baseline — existing)
- **Responsibility:** Post-hoc, upper-bound contradiction detection across adjacent pipeline stage artifact pairs. Operates on completed Markdown artifacts.
- **Interfaces:** CLI: `python3 scripts/contradiction-scanner.py --specs-dir <path> [--spec-ids ...] [--output ...]`. Output: JSON to stdout or file.
- **Data ownership:** Reads artifact files; produces contradiction-report.json. Does NOT write to state.json or endocrine state. Entirely stateless between runs.
- **Role in spec 017:** NS-003-B CCR baseline. Will remain active as a cross-validation layer even after NS-003-B is deployed.
- **Sub-system:** Shared (used by both NS-003 as baseline reference, and available to U-CA-004 for artifact quality baseline measurement).

### NS-003 Generator-Critic (to be built)
- **Responsibility:** Write-time schema compliance enforcement for all agent artifact outputs. Validates LLM-generated Markdown sections against JSON Schema Draft 2020-12 schemas per agent type.
- **Interfaces:** Function: `critic.validate(output: str, schema: dict, artifact_store: BeliefGraph) → CriticReport`. Called by COMMANDER post-agent-LLM-call, pre-artifact-commit. Retry prompt construction: returns retry_prompt string to COMMANDER.
- **Data ownership:** Reads: agent output (string), JSON Schema (static file), BeliefGraph (read-only). Writes: nothing directly — COMMANDER commits or escalates based on CriticReport.
- **Integration point with COMMANDER:** Inserts between LLM call and artifact commit. The specific hook mechanism is UNKNOWN — see U-009 in unknowns.md. This is the highest-priority architectural gap.
- **Sub-system:** NS-003.

### NS-003 Belief Graph (to be built)
- **Responsibility:** Persistent write-time belief consistency enforcement. Maintains BeliefNodes per field_identifier across the full spec run. Emits ConflictSignal on consistency violation.
- **Interfaces:** `BeliefGraph.lookup(field_identifier) → BeliefNode | None`, `BeliefGraph.commit(assertion, field_identifier, source_agent) → ConflictSignal | None`.
- **Persistence:** File-based Python dict serialized to `.specify/squad/belief-graph.json` at run end (v1 — run-scoped only). Cross-run persistence is a CA overlay 4 (Episodic Memory) dependency, not in NS-003 v1 scope.
- **Data ownership:** Owns belief graph state (BeliefNodes, supersession edges, trust scores). Shares ConflictSignal events with COMMANDER for endocrine wiring.
- **Sub-system:** NS-003.

### U-CA-004 Experiment Runner (to be built)
- **Responsibility:** Orchestrates N=20 per-condition runs (Conditions A, B, C). Records per-invocation results. Applies staged execution protocol (N=10 first, expand to N=20 on INCONCLUSIVE). Produces evaluator context bundles (run output + all prior stage artifacts).
- **Interfaces:** Script: `python3 scripts/u-ca-004-runner.py --condition [A|B|C] --n <int> --codebase <path> --output <dir>`. Reads agent prompt definitions from `.specify/extensions/echelon/agents/`. Writes: per-invocation JSON records + summary statistics + evaluator context bundles.
- **Data ownership:** Produces invocation records, AQS scores, SVR annotations, Mann-Whitney U results, POSITIVE/NEGATIVE/INCONCLUSIVE verdict.
- **Sub-system:** U-CA-004.

### ACT-R Buffer Preprocessor (to be built — conditional on POSITIVE)
- **Responsibility:** Pre-dispatch context pack construction using 4-buffer cognitive architecture model. Replaces full artifact concatenation in COMMANDER context pack.
- **Interfaces:** Python function called by COMMANDER pre-dispatch: `build_actR_context(artifact_store_path, goal, agent_type) → context_pack_str`. Operates entirely outside LLM call.
- **Dependencies:** Some form of similarity ranking (TF-IDF cosine, BM25, or embeddings API). See U-008.
- **Sub-system:** U-CA-004 (experimental), conditional CA overlay (post-POSITIVE).

### Endocrine System (existing, Phase 3 active — shared integration target)
- **Responsibility:** Hormone-modulated agent motivation. Maintained in state.json. Modified by `scripts/bash/endocrine.sh`.
- **Interfaces:** Shell commands: `endocrine.sh on_gate_pass <agent>`, `endocrine.sh on_gate_fail <agent>`, `endocrine.sh on_quality_improvement`, `endocrine.sh on_quality_regression`, `endocrine.sh propagate_downstream <from> <to>`.
- **NS-003 integration:** COMMANDER must call endocrine.sh commands based on NS-003 outcomes (ESCALATED → on_gate_fail; accepted → on_gate_pass; ConflictSignal resolved cleanly → on_quality_improvement; ESCALATED after 2 retries → on_quality_regression).
- **CA overlay integration:** ACT-R buffer quality improvements trigger on_quality_improvement system-wide; regressions trigger on_quality_regression.
- **CRITICAL GAP:** The endocrine system currently has NO hooks for NS-003 or CA overlay events. These are entirely new event sources. All wiring requires additions to commander.md — no structural changes to endocrine.sh itself.
- **Sub-system:** Shared (both NS-003 and CA overlay converge here).

---

## External Boundaries

### Anthropic Claude API
- **Type:** API (LLM inference service)
- **Dependency strength:** Hard for both sub-systems.
  - NS-003-A: Generator invocations (agent runs during NS-003 experiment)
  - U-CA-004: Agent invocations for all 60 experiment runs (N=20 per condition)
- **Data flow:** Outbound: prompt (system + context pack + agent prompt). Inbound: completion text (Markdown artifact section) + token counts.
- **CONFLICT — INTEGRATION PATTERN:** 
  - **Source A** (existing codebase): No Python script currently calls the anthropic SDK directly (confirmed via grep — zero `from anthropic` imports in scripts/). All Claude invocations go through the speckit CLI framework externally.
  - **Source B** (NS-003 design): Generator invocations require programmatic API calls with token count capture from response objects. token-logger.py anticipates `prompt_tokens` and `completion_tokens` fields from live API responses.
  - **Implication:** NS-003 must establish the FIRST Python anthropic SDK usage pattern in this codebase. If forced to use CLI subprocess instead, token logging falls back to word-count heuristic (token-logger.py fallback), violating REQ-015-003 baseline fidelity. See unknowns.md U-002.
- **Failure impact:** API unavailable → both experiments cannot run. No graceful degradation path for the experiments themselves.
- **LLM version lock requirement:** Both NS-003 and U-CA-004 require same model API string across all invocations within a batch. A version update mid-batch invalidates the experiment data.

### jsonschema Python library
- **Type:** library
- **Dependency strength:** Hard for NS-003-A Critic validation.
- **Data flow:** Inbound: agent output (parsed Markdown → dict), JSON Schema dict. Outbound: validation result (PASS/FAIL + error list).
- **SHARED DEPENDENCY:** Required by both NS-003-A (Critic) and potentially by U-CA-004 experiment runner for output structure validation.
- **Current state:** NOT in any requirements file (radar/requirements.txt only has flask, flask-cors, watchdog). No top-level scripts/requirements.txt exists. Must be created. See unknowns.md U-003.
- **Failure impact:** Without jsonschema → NS-003-A cannot function.

### scipy (Mann-Whitney U test)
- **Type:** library
- **Dependency strength:** Hard for U-CA-004 statistical verdict; soft for data collection (data can be collected, test run later).
- **Data flow:** Inbound: two arrays of AQS values (Condition B, Condition C). Outbound: U-statistic, p-value.
- **SHARED DEPENDENCY:** Required by U-CA-004. Also potentially useful for NS-003 statistical analysis of FPCR across agent types.
- **Current state:** NOT in any requirements file. Must be added to `scripts/requirements.txt` alongside jsonschema.
- **Failure impact:** Without scipy → AQS data can still be collected; Mann-Whitney U can be computed manually. p-value calculation is the gating criterion for POSITIVE verdict but is decoupled from data collection.

### jq (JSON processor)
- **Type:** infrastructure tool
- **Dependency strength:** Hard (endocrine.sh requires jq for all state.json read/write operations).
- **Shared by:** Both sub-systems via endocrine.sh. Python-based NS-003 and U-CA-004 implementations can bypass jq by using json.load/dump directly, but any endocrine event wiring through COMMANDER inherits jq.
- **Current state:** Existing hard dependency. `require_jq()` guard in endocrine.sh exits on unavailability.
- **Failure impact:** Without jq → entire endocrine system fails.

### pyyaml Python library
- **Type:** library
- **Dependency strength:** Hard for belief-parser.py YAML annotation processing.
- **Current state:** Used by belief-parser.py (explicitly stated in docstring). Not in any requirements file — presumably system-installed.
- **Failure impact:** Without pyyaml → belief-parser.py fails. NS-003 direct operation (on Markdown artifacts) does not require pyyaml, but the @belief() annotation system (NOVEL-002) depends on it.

### Echelon Extension Test Codebase
- **Type:** external data source (read-only, both experiments)
- **Path:** `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`
- **Dependency strength:** Hard for both experiments (same codebase, same version required for cross-experiment comparability).
- **SHARED DEPENDENCY — CRITICAL:** Both NS-003 and U-CA-004 use this codebase. If the codebase changes between experiments, cross-experiment comparability is compromised. Both experiments must lock to the same commit hash before running.
- **Current state:** Path referenced in both experiment specs. Must be verified accessible at experiment time. Prior spec 014 analysis documented 42 agent definitions across 7 tiers — must confirm these counts are still valid at experiment start.
- **Failure impact:** Codebase unavailable or changed → experiment reproducibility and cross-comparability compromised.

---

## Dependency Matrix: What Each Sub-System Needs

| Dependency | NS-003 | U-CA-004 | CA Overlays | Notes |
|------------|--------|----------|-------------|-------|
| anthropic SDK | Required (Generator) | Required (experiment runs) | Inherited | First SDK usage in codebase |
| jsonschema | Required (Critic) | Optional (output validation) | Not required | Must add to scripts/requirements.txt |
| scipy | Optional (FPCR statistics) | Required (Mann-Whitney U) | Not required | Must add to scripts/requirements.txt |
| pyyaml | Not required (Markdown-based) | Not required | Not required | Existing system install |
| jq | Via endocrine.sh only | Via endocrine.sh only | Via endocrine.sh | Existing hard dependency |
| Echelon extension codebase | Required (experiment target) | Required (experiment target) | Required (deployment target) | SAME version must be used |
| endocrine.sh | Integration target | Integration target | Integration target | Shared — new hooks required in COMMANDER |
| COMMANDER.md | Must add post-dispatch hook | Must add pre-dispatch preprocessor | Inherited from U-CA-004 | Two separate hooks must coexist |

---

## Trust Boundaries

### Pre-Commit Validation (NS-003)
- The Critic validates agent output BEFORE it enters the artifact store. The trust boundary is enforced by COMMANDER calling `critic.validate()` between LLM call completion and artifact write. The mechanism for this enforcement (how COMMANDER intercepts the write) is the highest-priority architectural unknown (U-009).

### Human Escalation Gate
- When NS-003 produces ESCALATED (2 failed retries), trust falls to the human. COMMANDER enters BLOCKED state. The human provides corrected artifact.

### Experiment LLM Version Lock
- Both NS-003 and U-CA-004 require LLM version lock within each experiment batch. A version update mid-batch is a trust boundary violation on the experiment — it introduces an uncontrolled confounding variable.

### Constitution P-006 Gate
- CA overlay implementation is trust-gated behind U-CA-004 POSITIVE verdict. P-006 human override (authorized 2026-04-03) permits building experiment infrastructure; it does NOT bypass the experimental gate for overlay deployments.
- Note: state.json `human_override.p006_ca_overlays = "AUTHORIZED"` is consistent with this interpretation.

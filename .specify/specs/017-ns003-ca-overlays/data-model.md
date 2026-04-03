# Data Model — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: ARCHITECT (HOW agent)
**Date**: 2026-04-03
**Spec**: 017-ns003-ca-overlays
**Constitution version**: 1.1.0

---

## 1. Python Dataclasses

### 1.1 BeliefNode

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

@dataclass
class BeliefNode:
    """
    A single assertion committed to the BeliefGraph.
    Implements the persistent node structure from FR-NS3B-001.
    
    field_identifier: normalized key (lowercase, underscores, unique in ACTIVE set)
    value:            string content of the assertion
    stage:            pipeline stage that produced this assertion
                      (one of DISCOVER / ASSESS / HOW / PLAN / BUILD / LEARN)
    confidence:       float in [0.5, 0.95] — initial confidence at insertion time
    status:           ACTIVE = in the current belief set
                      SUPERSEDED = displaced by AGM revision; never deleted
    superseded_chain: ordered list of BeliefNode instances previously ACTIVE for
                      this field_identifier, oldest first (append on revision)
    superseded_by:    field_identifier of the node that superseded this one;
                      None while status == ACTIVE
    version_counter:  monotonically increasing integer per field_identifier;
                      1 for the first assertion, +1 for each revision
    artifact_path:    source artifact file path for provenance
    """
    field_identifier: str
    value: str
    stage: Literal["DISCOVER", "ASSESS", "HOW", "PLAN", "BUILD", "LEARN"]
    confidence: float
    status: Literal["ACTIVE", "SUPERSEDED"] = "ACTIVE"
    superseded_chain: list["BeliefNode"] = field(default_factory=list)
    superseded_by: Optional[str] = None
    version_counter: int = 1
    artifact_path: Optional[str] = None
```

**Constraints (from FR-NS3B-001, §6 Key Entities):**
- `field_identifier` must be unique in the ACTIVE set at all times (Consistency postulate).
- `confidence` must be in `[0.5, 0.95]` — values outside this range are rejected as invalid.
- `superseded_chain` is append-only. Items are never removed from the chain.
- `version_counter` per `field_identifier` is monotonically increasing. It resets only if a new run begins (run-scoped graph).

---

### 1.2 ConflictSignal

```python
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class ConflictSignal:
    """
    Emitted by the contradiction classifier when a new assertion conflicts
    with an existing ACTIVE BeliefNode. Implements FR-NS3B-002 and FR-NS3B-006.
    
    field_identifier:     the shared key between the two conflicting assertions
    new_value:            content of the incoming (challenging) assertion
    new_stage:            pipeline stage of the incoming assertion
    existing_value:       content of the existing ACTIVE BeliefNode
    existing_stage:       pipeline stage of the existing ACTIVE BeliefNode
    contradiction_type:   classification of the conflict:
                          assertion_conflict — direct semantic negation or inversion
                          scope_conflict     — incompatible scope boundary terms
                          architecture_conflict — incompatible architectural component
    confidence:           float in [0.5, 0.95] — classifier confidence
    recommended_action:   accept   — low confidence (< 0.65); log only
                          revert   — medium confidence (0.65-0.79)
                          escalate — high confidence (>= 0.80)
    existing_node_ref:    reference to the existing BeliefNode (for provenance)
    artifact_path_new:    source artifact file path of the incoming assertion
    """
    field_identifier: str
    new_value: str
    new_stage: str
    existing_value: str
    existing_stage: str
    contradiction_type: Literal[
        "assertion_conflict", "scope_conflict", "architecture_conflict"
    ]
    confidence: float
    recommended_action: Literal["accept", "revert", "escalate"]
    existing_node_ref: Optional["BeliefNode"] = None
    artifact_path_new: Optional[str] = None
```

**Lifecycle**: Emitted during `check_conflict()`, consumed by the contradiction report writer, archived in the JSONL contradiction report. Not persisted independently in the BeliefGraph JSON.

---

### 1.3 AQS EvaluationRecord

```python
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class AQSEvaluationRecord:
    """
    One AQS scoring result for one invocation in U-CA-004.
    Implements FR-UCA-002, FR-UCA-003, and §6 Key Entities (AQS Evaluation Record).
    
    run_id:               UUID4 string unique to this experiment run
    condition:            BASELINE or CA-ACTIVE (FR-UCA-001)
    invocation_index:     0-based index within the condition (0-19 for N=20)
    completeness:         integer 0-5
    consistency:          integer 0-5
    specificity:          integer 0-5
    actionability:        integer 0-5
    innovation:           integer 0-5
    total_aqs:            sum of five dimensions / 25.0; float in [0.0, 1.0]
    scoring_prompt_hash:  SHA-256 hex of the exact prompt template text used
                          (must be identical across all records in a batch — P-021)
    model_identifier:     e.g. "claude-sonnet-4-6"
    codebase_commit_hash: git HEAD at experiment start (FR-NS3E-001, IS-006)
    request_timestamp:    ISO 8601 string
    response_timestamp:   ISO 8601 string
    extraction_status:    OK / OUT_OF_RANGE / SCORING_FAILED
    retry_count:          0 or 1 (per FR-UCA-ERR-001)
    """
    run_id: str
    condition: Literal["BASELINE", "CA-ACTIVE"]
    invocation_index: int
    completeness: Optional[int]
    consistency: Optional[int]
    specificity: Optional[int]
    actionability: Optional[int]
    innovation: Optional[int]
    total_aqs: Optional[float]
    scoring_prompt_hash: str
    model_identifier: str
    codebase_commit_hash: str
    request_timestamp: str
    response_timestamp: str
    extraction_status: Literal["OK", "OUT_OF_RANGE", "SCORING_FAILED"]
    retry_count: int = 0
```

**Constraint**: `scoring_prompt_hash` must be identical for all records in a single experiment run. If it differs, the run is invalid (mixed prompt versions contaminate statistical analysis).

---

## 2. BeliefGraph Class Interface

```python
class BeliefGraph:
    """
    Run-scoped persistent belief graph implementing AGM K*2 minimal revision.
    Implements FR-NS3B-001, FR-NS3B-003, FR-NS3B-005, FR-NS3B-ERR-002.
    
    Storage: JSON file at the path provided to __init__. Written atomically
    (temp file + rename) after every mutating operation.
    """

    def __init__(self, graph_path: str) -> None:
        """
        Load an existing BeliefGraph from graph_path if it exists,
        or initialize an empty graph.
        graph_path: absolute path to the JSON persistence file.
        """
        ...

    def add_belief(self, node: BeliefNode) -> None:
        """
        AGM Postulate: Success + Vacuity path.
        
        If no ACTIVE node exists for node.field_identifier:
          - Add node to ACTIVE set. (Vacuity + Success)
        
        If an ACTIVE node already exists for node.field_identifier:
          - Call check_conflict(node) to classify the contradiction.
          - Call apply_revision(node) to execute K*2 minimal contraction.
          - Return the emitted ConflictSignal for caller to record.
        
        Raises MalformedAssertionError if node.field_identifier or node.value
        is None or empty (FR-NS3B-ERR-001). BeliefGraph is not modified on error.
        """
        ...

    def check_conflict(self, incoming: BeliefNode) -> Optional[ConflictSignal]:
        """
        Test incoming against the ACTIVE node for the same field_identifier.
        Returns a ConflictSignal if a contradiction is detected, None otherwise.
        
        Contradiction type detection order:
          1. assertion_conflict (confidence 0.80)
          2. scope_conflict     (confidence 0.70)
          3. architecture_conflict (confidence 0.60)
        
        Returns None if no ACTIVE node exists for incoming.field_identifier
        (Vacuity path — no conflict possible).
        """
        ...

    def apply_revision(self, incoming: BeliefNode) -> None:
        """
        AGM K*2 Minimal Contraction + Revision.
        
        Postulate: Relevance — remove from ACTIVE only the node whose
        field_identifier matches incoming.field_identifier.
        
        Steps:
          1. Get existing ACTIVE node for incoming.field_identifier.
          2. Set existing node status = SUPERSEDED.
          3. Set existing node superseded_by = incoming.field_identifier
             (self-referential by key — the new node replaces it).
          4. Increment incoming.version_counter = existing.version_counter + 1.
          5. Set incoming.superseded_chain = existing.superseded_chain + [existing].
          6. Add incoming to ACTIVE set.
          7. Persist graph atomically (FR-NS3B-ERR-002).
        """
        ...

    def get_active(self, field_identifier: str) -> Optional[BeliefNode]:
        """
        Return the ACTIVE BeliefNode for field_identifier, or None.
        """
        ...

    def get_superseded_chain(self, field_identifier: str) -> list[BeliefNode]:
        """
        Return all SUPERSEDED BeliefNodes for field_identifier, oldest first.
        """
        ...

    def to_dict(self) -> dict:
        """
        Serialize the full graph (ACTIVE + SUPERSEDED nodes) to a dict
        suitable for JSON persistence.
        """
        ...

    @classmethod
    def from_dict(cls, data: dict, graph_path: str) -> "BeliefGraph":
        """
        Deserialize a BeliefGraph from a persisted dict.
        """
        ...
```

**Error types:**
- `MalformedAssertionError(field_identifier, reason)`: raised when required fields are missing (FR-NS3B-ERR-001).
- `BeliefGraphWriteError(path, cause)`: raised when the atomic JSON write fails (FR-NS3B-ERR-002). Caller must handle rollback (the temp file is never renamed on failure — original graph file is untouched).

---

## 3. BeliefGraph JSON Persistence Format

```json
{
  "schema_version": "1.0.0",
  "run_id": "<uuid4>",
  "spec_id": "017",
  "created_at": "<ISO 8601>",
  "last_updated_at": "<ISO 8601>",
  "active": {
    "<field_identifier>": {
      "field_identifier": "req_scope",
      "value": "auth_and_api",
      "stage": "ASSESS",
      "confidence": 0.7,
      "status": "ACTIVE",
      "version_counter": 2,
      "artifact_path": ".specify/specs/017-ns003-ca-overlays/feasibility.md",
      "superseded_by": null,
      "superseded_chain": [
        {
          "field_identifier": "req_scope",
          "value": "auth_only",
          "stage": "DISCOVER",
          "confidence": 0.7,
          "status": "SUPERSEDED",
          "version_counter": 1,
          "artifact_path": ".specify/specs/017-ns003-ca-overlays/assumptions.md",
          "superseded_by": "req_scope"
        }
      ]
    }
  },
  "conflict_signals": [
    {
      "field_identifier": "req_scope",
      "new_value": "auth_and_api",
      "new_stage": "ASSESS",
      "existing_value": "auth_only",
      "existing_stage": "DISCOVER",
      "contradiction_type": "scope_conflict",
      "confidence": 0.7,
      "recommended_action": "revert",
      "artifact_path_new": ".specify/specs/017-ns003-ca-overlays/feasibility.md"
    }
  ]
}
```

Notes:
- `active` is keyed by `field_identifier`. Lookups are O(1).
- `conflict_signals` is the append-only log of all ConflictSignals emitted during this run. Used for the contradiction report.
- The `superseded_chain` inside each active node stores the full provenance history inline (avoids secondary lookups).

---

## 4. Experiment Result Schemas

### 4.1 ns003-results.json

```json
{
  "schema_version": "1.0.0",
  "experiment_id": "NS-003",
  "spec_id": "017",
  "experiment_date": "<ISO 8601>",
  "codebase_commit_hash": "<40-char git hash>",
  "model_identifier": "claude-sonnet-4-6",
  "data_source": "live_invocations | historical_artifacts",
  "deviation_note": null,
  "n_total": 30,
  "n_pass": 0,
  "n_fail": 0,
  "n_timeout": 0,
  "n_skip": 0,
  "fpcr": 0.0,
  "fpcr_classification": "PATENT_GRADE | PROTOTYPE_VIABLE | INCONCLUSIVE",
  "contradiction_catch_rate": 0.0,
  "ccr_verdict": "PASS | FAIL",
  "false_positive_rate": 0.0,
  "fpr_verdict": "PASS | FAIL",
  "structured_to_prose_ratio": {
    "DISCOVER": 0.0,
    "ASSESS": 0.0,
    "HOW": 0.0,
    "PLAN": 0.0,
    "BUILD": 0.0,
    "LEARN": 0.0
  },
  "coverage_limitation_flag": false,
  "per_invocation_verdicts": [
    {
      "invocation_index": 0,
      "artifact_path": "<path>",
      "artifact_category": "DISCOVER | ASSESS | HOW | PLAN | BUILD | LEARN",
      "schema_verdict": "PASS | FAIL | TIMEOUT | SKIP",
      "per_field_verdicts": [
        {
          "field_name": "scope_statement",
          "verdict": "PASS | FAIL",
          "confidence": 0.95,
          "component": "deterministic | prose_assessment"
        }
      ],
      "elapsed_seconds": 0.0
    }
  ],
  "calibration_set_frr": 0.0,
  "calibration_set_size": 0,
  "calibration_set_source": "runs_015_016 | fallback_other"
}
```

**Key constraint**: `fpcr_classification` must be set by the experiment runner using both thresholds per P-022:
- `>= 0.80` → `"PATENT_GRADE"`
- `>= 0.70 and < 0.80` → `"PROTOTYPE_VIABLE"`
- `< 0.70` → `"INCONCLUSIVE"`

---

### 4.2 uca004-results.json

```json
{
  "schema_version": "1.0.0",
  "experiment_id": "U-CA-004",
  "spec_id": "017",
  "experiment_date": "<ISO 8601>",
  "codebase_commit_hash": "<40-char git hash>",
  "model_identifier": "claude-sonnet-4-6",
  "scoring_prompt_version": "1.0.0",
  "scoring_prompt_hash": "<sha256 hex>",
  "n_per_condition": 20,
  "conditions_run": ["BASELINE", "CA-ACTIVE"],
  "baseline": {
    "n_completed": 0,
    "n_timeout": 0,
    "n_scoring_failed": 0,
    "aqs_scores": [],
    "aqs_mean": 0.0,
    "aqs_std": 0.0
  },
  "ca_active": {
    "n_completed": 0,
    "n_timeout": 0,
    "n_scoring_failed": 0,
    "aqs_scores": [],
    "aqs_mean": 0.0,
    "aqs_std": 0.0
  },
  "statistics": {
    "mann_whitney_u": null,
    "p_value": null,
    "cohens_d": null,
    "test_type": "two-tailed"
  },
  "verdict": "POSITIVE | NEGATIVE | VOID",
  "void_reason": null,
  "authorized_overlays": [],
  "limitations": "AQS proxy circularity: the scoring model (claude-sonnet-4-6) is from the same model family as the model that produced the artifacts being scored. Self-evaluation introduces potential evaluator bias. This limitation is disclosed per GATEKEEPER feasibility assessment. Results should be interpreted with this constraint in mind. Independent human evaluation of a sample (n>=5 per condition) is recommended before patent filing.",
  "per_invocation_records": [
    {
      "run_id": "<uuid4>",
      "condition": "BASELINE | CA-ACTIVE",
      "invocation_index": 0,
      "completeness": 0,
      "consistency": 0,
      "specificity": 0,
      "actionability": 0,
      "innovation": 0,
      "total_aqs": 0.0,
      "extraction_status": "OK | OUT_OF_RANGE | SCORING_FAILED",
      "elapsed_seconds": 0.0
    }
  ]
}
```

**Key constraint**: `authorized_overlays` is populated only when `verdict == "POSITIVE"`. When populated, it must list all five overlay script paths:
```json
[
  "scripts/ca/goal_stack.py",
  "scripts/ca/actr_buffer.py",
  "scripts/bash/lida_broadcast.sh",
  "scripts/ca/gwt_workspace.py",
  "scripts/ca/episodic_memory.py"
]
```

---

## 5. Artifact Category JSON Schemas

Each schema lives at `scripts/schemas/<category>.json`. These are minimal schemas — IMPLEMENTER may add additional optional fields without breaking the required-field gate.

### 5.1 DISCOVER Schema (`scripts/schemas/discover.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon DISCOVER Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "scope_statement", "assumptions", "unknowns"],
  "properties": {
    "spec_id":          { "type": "string", "minLength": 1 },
    "agent":            { "type": "string", "minLength": 1 },
    "timestamp":        { "type": "string", "minLength": 1 },
    "scope_statement":  { "type": "string", "minLength": 20 },
    "assumptions":      { "type": ["string", "array"], "minLength": 1 },
    "unknowns":         { "type": ["string", "array"], "minLength": 1 }
  },
  "required_sections": [
    "scope_statement", "assumptions", "unknowns", "glossary", "boundaries"
  ]
}
```

### 5.2 ASSESS Schema (`scripts/schemas/assess.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon ASSESS Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "verdict", "risks", "effort_estimate"],
  "properties": {
    "spec_id":         { "type": "string", "minLength": 1 },
    "agent":           { "type": "string", "minLength": 1 },
    "timestamp":       { "type": "string", "minLength": 1 },
    "verdict":         { "type": "string", "enum": ["PROCEED", "PROCEED_WITH_CAVEATS", "BLOCKED", "VOID"] },
    "risks":           { "type": ["string", "array"], "minLength": 1 },
    "effort_estimate": { "type": ["string", "number"], "minLength": 1 }
  },
  "required_sections": [
    "verdict", "risks", "effort_estimate", "technical_feasibility", "kill_gate_decision"
  ]
}
```

### 5.3 HOW Schema (`scripts/schemas/how.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon HOW Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "adrs", "technology_stack", "data_model_ref"],
  "properties": {
    "spec_id":          { "type": "string", "minLength": 1 },
    "agent":            { "type": "string", "minLength": 1 },
    "timestamp":        { "type": "string", "minLength": 1 },
    "adrs":             { "type": ["string", "array"], "minLength": 1 },
    "technology_stack": { "type": ["string", "object"], "minLength": 1 },
    "data_model_ref":   { "type": "string", "minLength": 1 }
  },
  "required_sections": [
    "adrs", "technology_stack", "data_model", "api_contracts", "integration_design"
  ]
}
```

### 5.4 PLAN Schema (`scripts/schemas/plan.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon PLAN Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "tasks", "critical_path", "mvp_scope"],
  "properties": {
    "spec_id":       { "type": "string", "minLength": 1 },
    "agent":         { "type": "string", "minLength": 1 },
    "timestamp":     { "type": "string", "minLength": 1 },
    "tasks":         { "type": ["string", "array"], "minLength": 1 },
    "critical_path": { "type": ["string", "array"], "minLength": 1 },
    "mvp_scope":     { "type": ["string", "array"], "minLength": 1 }
  },
  "required_sections": [
    "tasks", "critical_path", "mvp_scope", "dependencies", "phase_breakdown"
  ]
}
```

### 5.5 BUILD Schema (`scripts/schemas/build.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon BUILD Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "implementation_notes", "test_results"],
  "properties": {
    "spec_id":               { "type": "string", "minLength": 1 },
    "agent":                 { "type": "string", "minLength": 1 },
    "timestamp":             { "type": "string", "minLength": 1 },
    "implementation_notes":  { "type": ["string", "array"], "minLength": 1 },
    "test_results":          { "type": ["string", "object"], "minLength": 1 }
  },
  "required_sections": [
    "implementation_notes", "test_results", "files_modified", "acceptance_criteria_status"
  ]
}
```

### 5.6 LEARN Schema (`scripts/schemas/learn.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Echelon LEARN Artifact Schema",
  "type": "object",
  "required": ["spec_id", "agent", "timestamp", "learnings", "pattern_updates", "quality_delta"],
  "properties": {
    "spec_id":          { "type": "string", "minLength": 1 },
    "agent":            { "type": "string", "minLength": 1 },
    "timestamp":        { "type": "string", "minLength": 1 },
    "learnings":        { "type": ["string", "array"], "minLength": 1 },
    "pattern_updates":  { "type": ["string", "array"], "minLength": 1 },
    "quality_delta":    { "type": ["string", "number"] }
  },
  "required_sections": [
    "learnings", "pattern_updates", "quality_delta", "retrospective", "next_spec_recommendations"
  ]
}
```

---

## 6. Markdown Parsing Notes for IMPLEMENTER

The JSON schemas above validate structured fields extracted from Markdown. The extraction pipeline uses the following regex patterns (reused from `contradiction-scanner.py`):

| Pattern | Target | Example |
|---------|--------|---------|
| `_BOLD_KEY_RE` | `**key**: value` | `**Spec ID**: 017` |
| `_KV_LINE_RE` | `key: value` | `Agent: ARCHITECT` |
| `_TABLE_ROW_RE` | `| col1 | col2 |` | Table rows |
| Section headers | `## Section Name` | Required sections list |

The `spec_id`, `agent`, and `timestamp` fields are expected to appear as bold-key or KV pairs near the top of the artifact. If absent, the JSON Schema validator emits FAIL with confidence=0.95 for those fields.

The `required_sections` array in each schema is used by the Claude API prose assessment component (ADR-002) to check section header presence. It is not part of the standard JSON Schema validation (`jsonschema.validate()`); it is passed to the prose-assessment prompt as `{REQUIRED_SECTIONS}`.

---

## 7. Error Dataclasses

```python
class MalformedAssertionError(Exception):
    """
    Raised when add_belief() receives a BeliefNode with null or empty
    field_identifier or value. (FR-NS3B-ERR-001)
    The BeliefGraph is NOT modified when this error is raised.
    """
    def __init__(self, field_identifier: str, reason: str):
        self.field_identifier = field_identifier
        self.reason = reason
        super().__init__(f"MalformedAssertion [{field_identifier}]: {reason}")


class BeliefGraphWriteError(Exception):
    """
    Raised when the atomic JSON write of the BeliefGraph to disk fails.
    (FR-NS3B-ERR-002)
    The caller must treat the in-memory graph as still valid;
    the on-disk file is the previous successfully persisted state.
    """
    def __init__(self, path: str, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"BeliefGraph write failed at {path}: {cause}")


class SchemaLoadError(Exception):
    """
    Raised when a required JSON schema file is missing or malformed.
    (FR-NS3A-ERR-003)
    The script exits with code 2 when this is raised.
    """
    def __init__(self, schema_path: str, reason: str):
        self.schema_path = schema_path
        self.reason = reason
        super().__init__(f"SchemaLoadError [{schema_path}]: {reason}")
```

#!/usr/bin/env python3
"""
ns003_agm.py — NS-003-B AGM Belief Revision Engine

Post-hoc contradiction detector for Echelon pipeline artifacts.
Implements AGM K*2 minimal revision logic with three-layer architecture:
  Layer 1: Assertion Extractor (T-011)
  Layer 2: BeliefGraph (T-010)
  Layer 3: Contradiction Classifier (T-012)

CLI entry point (T-013) implements contracts/ns003_interfaces.md §2.

ADR-001 (IS-003 resolution): Post-hoc mode ONLY. --mode pre-commit prints
a deprecation notice and proceeds as post-hoc.

No ANTHROPIC_API_KEY required (fully deterministic engine).

Exit codes:
    0 — processing completed
    1 — runtime error (artifact-dir not found, BeliefGraph write failure)
    2 — reserved (configuration error)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Import shared parser (T-004)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
from md_parser import extract_kv_pairs, extract_section_headers

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# Pipeline stage order (DISCOVER first, LEARN last) — T-011 AC-2.1
PIPELINE_ORDER: list[str] = ["DISCOVER", "ASSESS", "HOW", "PLAN", "BUILD", "LEARN"]

# ARTIFACT_STAGE_MAP — reused from contradiction-scanner.py
ARTIFACT_STAGE_MAP: dict[str, str] = {
    "assumptions.md": "DISCOVER",
    "glossary.md": "DISCOVER",
    "mental-model.md": "DISCOVER",
    "domain-analysis.md": "DISCOVER",
    "research.md": "DISCOVER",
    "unknowns.md": "DISCOVER",
    "boundaries.md": "DISCOVER",
    "user-intent.md": "DISCOVER",
    "feasibility.md": "ASSESS",
    "estimates.md": "ASSESS",
    "risks.md": "ASSESS",
    "risk-matrix.md": "ASSESS",
    "alternatives.md": "ASSESS",
    "assumption-review.md": "ASSESS",
    "issues.md": "ASSESS",
    "spec.md": "HOW",
    "data-model.md": "HOW",
    "test-strategy.md": "HOW",
    "test-architecture.md": "HOW",
    "tasks.md": "PLAN",
    "plan.md": "PLAN",
    "critical-path.md": "PLAN",
    "prioritization.md": "PLAN",
    "mvp-scope.md": "PLAN",
    "ground-check.md": "BUILD",
    "implementation-notes.md": "BUILD",
    "build-report.md": "BUILD",
    "learnings.md": "LEARN",
    "evolution-report.md": "LEARN",
    "retrospective.md": "LEARN",
}

# Generic stop-keys (reused from contradiction-scanner.py lines 115-142)
_GENERIC_STOP_KEYS: frozenset[str] = frozenset({
    "statement", "description", "definition", "note", "notes", "source",
    "basis", "date", "agent", "mode", "author", "version", "example",
    "rationale", "implication", "evidence", "approach", "summary",
    "detail", "details", "comment", "verdict", "text", "type", "value", "result",
})

# Contradiction detection patterns (ADR-003 Layer 3)
_NEGATION_RE = re.compile(
    r"\b(not|no |never|none|absent|missing|does not|do not|cannot|can't|"
    r"doesn't|don't|isn't|aren't|won't|hasn't|haven't)\b",
    re.IGNORECASE,
)
_STATUS_INVERSION_PAIRS: list[tuple[str, str]] = [
    ("PASS", "FAIL"), ("ENABLED", "DISABLED"), ("ACTIVE", "INACTIVE"),
    ("YES", "NO"), ("TRUE", "FALSE"), ("VALID", "INVALID"),
]
_NUMBER_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\b")

# Scope boundary terms for scope_conflict detection
_SCOPE_TERMS: frozenset[str] = frozenset({
    "only", "all", "none", "any", "within", "excluding",
})

# Architectural component terms for architecture_conflict detection
_ARCH_TERMS: frozenset[str] = frozenset({
    "database", "queue", "api", "cache", "service",
    "db", "redis", "kafka", "postgres", "mysql", "mongo",
    "elasticsearch", "rabbitmq", "pubsub", "grpc", "rest",
})

# Initial confidence for extracted assertions
INITIAL_CONFIDENCE = 0.70


# ---------------------------------------------------------------------------
# T-009: Error classes
# ---------------------------------------------------------------------------

class MalformedAssertionError(Exception):
    """
    Raised when a BeliefNode has null/empty field_identifier or value.
    Implements FR-NS3B-ERR-001.
    """
    def __init__(self, field_identifier: str, reason: str) -> None:
        self.field_identifier = field_identifier
        self.reason = reason
        super().__init__(f"MalformedAssertion[{field_identifier}]: {reason}")


class BeliefGraphWriteError(Exception):
    """
    Raised when atomic JSON write to the belief graph file fails.
    Implements FR-NS3B-ERR-002.
    """
    def __init__(self, path: str, cause: Exception) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"BeliefGraphWriteError[{path}]: {cause}")


# ---------------------------------------------------------------------------
# T-009: BeliefNode dataclass
# ---------------------------------------------------------------------------

@dataclass
class BeliefNode:
    """
    A single assertion committed to the BeliefGraph.
    Implements FR-NS3B-001 and data-model.md §1.1.

    field_identifier: normalized key (lowercase, underscores, unique in ACTIVE set)
    value:            string content of the assertion
    stage:            pipeline stage (DISCOVER/ASSESS/HOW/PLAN/BUILD/LEARN)
    confidence:       float in [0.5, 0.95]
    status:           ACTIVE or SUPERSEDED
    superseded_chain: ordered list of previously ACTIVE nodes (oldest first)
    superseded_by:    field_identifier of the node that superseded this one
    version_counter:  monotonically increasing per field_identifier (starts at 1)
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

    def __post_init__(self) -> None:
        # Constraint: confidence must be in [0.5, 0.95]
        if not (0.5 <= self.confidence <= 0.95):
            raise ValueError(
                f"BeliefNode.confidence={self.confidence} is outside [0.5, 0.95]. "
                "Per data-model.md §1.1 Constraints."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON persistence (data-model.md §3)."""
        d: dict[str, Any] = {
            "field_identifier": self.field_identifier,
            "value": self.value,
            "stage": self.stage,
            "confidence": self.confidence,
            "status": self.status,
            "version_counter": self.version_counter,
            "artifact_path": self.artifact_path,
            "superseded_by": self.superseded_by,
        }
        # Do NOT recurse superseded_chain in chain items (avoid deep nesting)
        # Chain items are serialized without their own superseded_chain
        if self.superseded_chain:
            d["superseded_chain"] = [
                {
                    "field_identifier": n.field_identifier,
                    "value": n.value,
                    "stage": n.stage,
                    "confidence": n.confidence,
                    "status": n.status,
                    "version_counter": n.version_counter,
                    "artifact_path": n.artifact_path,
                    "superseded_by": n.superseded_by,
                }
                for n in self.superseded_chain
            ]
        else:
            d["superseded_chain"] = []
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BeliefNode":
        """Deserialize from persisted dict."""
        chain_raw = d.get("superseded_chain", [])
        chain = [
            cls(
                field_identifier=c["field_identifier"],
                value=c["value"],
                stage=c["stage"],
                confidence=c["confidence"],
                status=c.get("status", "SUPERSEDED"),
                superseded_chain=[],
                superseded_by=c.get("superseded_by"),
                version_counter=c.get("version_counter", 1),
                artifact_path=c.get("artifact_path"),
            )
            for c in chain_raw
        ]
        return cls(
            field_identifier=d["field_identifier"],
            value=d["value"],
            stage=d["stage"],
            confidence=d["confidence"],
            status=d.get("status", "ACTIVE"),
            superseded_chain=chain,
            superseded_by=d.get("superseded_by"),
            version_counter=d.get("version_counter", 1),
            artifact_path=d.get("artifact_path"),
        )


# ---------------------------------------------------------------------------
# T-009: ConflictSignal dataclass
# ---------------------------------------------------------------------------

@dataclass
class ConflictSignal:
    """
    Emitted by the contradiction classifier when a new assertion conflicts
    with an existing ACTIVE BeliefNode. Implements FR-NS3B-002 and FR-NS3B-006.
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
    existing_node_ref: Optional[BeliefNode] = None
    artifact_path_new: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "field_identifier": self.field_identifier,
            "new_value": self.new_value,
            "new_stage": self.new_stage,
            "existing_value": self.existing_value,
            "existing_stage": self.existing_stage,
            "contradiction_type": self.contradiction_type,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "artifact_path_new": self.artifact_path_new,
        }


def _derive_recommended_action(confidence: float) -> Literal["accept", "revert", "escalate"]:
    """
    Derive recommended_action from confidence per ADR-003:
    >= 0.80 -> escalate; 0.65-0.79 -> revert; < 0.65 -> accept
    """
    if confidence >= 0.80:
        return "escalate"
    elif confidence >= 0.65:
        return "revert"
    else:
        return "accept"


# ---------------------------------------------------------------------------
# T-010: BeliefGraph class
# ---------------------------------------------------------------------------

class BeliefGraph:
    """
    Run-scoped persistent belief graph implementing AGM K*2 minimal revision.
    Implements FR-NS3B-001, FR-NS3B-003, FR-NS3B-005, FR-NS3B-ERR-002.

    Storage: JSON file at graph_path. Written atomically (temp file + rename)
    after every mutating operation.

    Four K*2 postulates (FR-NS3B-003, ADR-003):
      Vacuity:     No ACTIVE node for field_identifier → add without conflict.
      Success:     Incoming enters ACTIVE if field_identifier and value non-null/non-empty.
      Consistency: ACTIVE has ≤1 node per field_identifier at all times.
      Relevance:   apply_revision() moves ONLY the node with matching field_identifier to SUPERSEDED.
    """

    def __init__(
        self,
        graph_path: str,
        run_id: Optional[str] = None,
        spec_id: str = "017",
    ) -> None:
        self.graph_path = graph_path
        self._active: dict[str, BeliefNode] = {}
        self._superseded: dict[str, list[BeliefNode]] = {}  # field_id -> list
        self._conflict_signals: list[ConflictSignal] = []
        self._run_id = run_id or str(uuid.uuid4())
        self._spec_id = spec_id
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._last_updated_at = self._created_at

        # Load existing graph if file exists
        p = Path(graph_path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._load_from_dict(data)
            except (json.JSONDecodeError, KeyError):
                pass  # Start fresh if corrupt

    def _load_from_dict(self, data: dict) -> None:
        """Restore graph state from persisted dict."""
        self._run_id = data.get("run_id", self._run_id)
        self._spec_id = data.get("spec_id", self._spec_id)
        self._created_at = data.get("created_at", self._created_at)
        self._last_updated_at = data.get("last_updated_at", self._last_updated_at)

        # Restore active nodes
        for fid, node_data in data.get("active", {}).items():
            node = BeliefNode.from_dict(node_data)
            self._active[fid] = node
            # Restore superseded chain entries
            for chain_node in node.superseded_chain:
                self._superseded.setdefault(fid, []).append(chain_node)

        # Restore conflict signals
        for cs_dict in data.get("conflict_signals", []):
            # Reconstruct lightweight (no existing_node_ref)
            cs = ConflictSignal(
                field_identifier=cs_dict["field_identifier"],
                new_value=cs_dict["new_value"],
                new_stage=cs_dict["new_stage"],
                existing_value=cs_dict["existing_value"],
                existing_stage=cs_dict["existing_stage"],
                contradiction_type=cs_dict["contradiction_type"],
                confidence=cs_dict["confidence"],
                recommended_action=cs_dict["recommended_action"],
                artifact_path_new=cs_dict.get("artifact_path_new"),
            )
            self._conflict_signals.append(cs)

    def add_belief(self, node: BeliefNode) -> Optional[ConflictSignal]:
        """
        AGM Postulate: Success + Vacuity path.

        If no ACTIVE node exists for node.field_identifier:
          - Vacuity + Success: add node to ACTIVE set.

        If ACTIVE node exists:
          - Call check_conflict(node) to classify.
          - Call apply_revision(node) to execute K*2 minimal contraction.
          - Record ConflictSignal.
          - Return the ConflictSignal.

        Raises MalformedAssertionError if field_identifier or value is null/empty.
        BeliefGraph is NOT modified on error.
        """
        # Success postulate: reject self-contradictory (malformed) nodes
        if not node.field_identifier or not node.field_identifier.strip():
            raise MalformedAssertionError(
                node.field_identifier or "",
                "field_identifier is null or empty",
            )
        if not node.value or not node.value.strip():
            raise MalformedAssertionError(
                node.field_identifier,
                "value is null or empty",
            )

        existing = self._active.get(node.field_identifier)

        if existing is None:
            # Vacuity path: no existing ACTIVE node — insert directly
            self._active[node.field_identifier] = node
            self._persist()
            return None
        else:
            # Conflict path: existing ACTIVE node found
            conflict = self.check_conflict(node)
            if conflict:
                self._conflict_signals.append(conflict)
            self.apply_revision(node)
            return conflict

    def check_conflict(self, incoming: BeliefNode) -> Optional[ConflictSignal]:
        """
        T-012: Test incoming against the ACTIVE node for the same field_identifier.
        Returns a ConflictSignal if a contradiction is detected, None otherwise.

        Detectors applied in order (ADR-003 Layer 3):
          1. assertion_conflict (confidence 0.80)
          2. scope_conflict     (confidence 0.70)
          3. architecture_conflict (confidence 0.60)
        """
        existing = self._active.get(incoming.field_identifier)
        if existing is None:
            return None

        new_val = incoming.value.lower()
        ex_val = existing.value.lower()

        # --- Detector 1: assertion_conflict (confidence 0.80) ---
        if self._detect_assertion_conflict(new_val, ex_val):
            action = _derive_recommended_action(0.80)
            return ConflictSignal(
                field_identifier=incoming.field_identifier,
                new_value=incoming.value,
                new_stage=incoming.stage,
                existing_value=existing.value,
                existing_stage=existing.stage,
                contradiction_type="assertion_conflict",
                confidence=0.80,
                recommended_action=action,
                existing_node_ref=existing,
                artifact_path_new=incoming.artifact_path,
            )

        # --- Detector 2: scope_conflict (confidence 0.70) ---
        if self._detect_scope_conflict(new_val, ex_val):
            action = _derive_recommended_action(0.70)
            return ConflictSignal(
                field_identifier=incoming.field_identifier,
                new_value=incoming.value,
                new_stage=incoming.stage,
                existing_value=existing.value,
                existing_stage=existing.stage,
                contradiction_type="scope_conflict",
                confidence=0.70,
                recommended_action=action,
                existing_node_ref=existing,
                artifact_path_new=incoming.artifact_path,
            )

        # --- Detector 3: architecture_conflict (confidence 0.60) ---
        if self._detect_architecture_conflict(new_val, ex_val):
            action = _derive_recommended_action(0.60)
            return ConflictSignal(
                field_identifier=incoming.field_identifier,
                new_value=incoming.value,
                new_stage=incoming.stage,
                existing_value=existing.value,
                existing_stage=existing.stage,
                contradiction_type="architecture_conflict",
                confidence=0.60,
                recommended_action=action,
                existing_node_ref=existing,
                artifact_path_new=incoming.artifact_path,
            )

        return None

    def _detect_assertion_conflict(self, new_val: str, ex_val: str) -> bool:
        """
        Detector 1: assertion_conflict.
        Fires on: negation patterns, status-term inversions, numerical divergence > 20%.
        """
        # Negation pattern: one has negation marker, other does not
        new_negated = bool(_NEGATION_RE.search(new_val))
        ex_negated = bool(_NEGATION_RE.search(ex_val))
        if new_negated != ex_negated:
            return True

        # Status-term inversion: PASS↔FAIL, ENABLED↔DISABLED, etc.
        for term_a, term_b in _STATUS_INVERSION_PAIRS:
            has_a_new = re.search(r"\b" + term_a.lower() + r"\b", new_val)
            has_b_new = re.search(r"\b" + term_b.lower() + r"\b", new_val)
            has_a_ex = re.search(r"\b" + term_a.lower() + r"\b", ex_val)
            has_b_ex = re.search(r"\b" + term_b.lower() + r"\b", ex_val)
            if (has_a_new and has_b_ex) or (has_b_new and has_a_ex):
                return True

        # Numerical divergence > 20%
        new_nums = [float(n.replace(",", "")) for n in _NUMBER_RE.findall(new_val)]
        ex_nums = [float(n.replace(",", "")) for n in _NUMBER_RE.findall(ex_val)]
        if new_nums and ex_nums:
            new_primary = new_nums[0]
            ex_primary = ex_nums[0]
            if ex_primary != 0:
                divergence = abs(new_primary - ex_primary) / abs(ex_primary)
                if divergence > 0.20:
                    return True

        return False

    def _detect_scope_conflict(self, new_val: str, ex_val: str) -> bool:
        """
        Detector 2: scope_conflict.
        Fires when incoming contains explicit scope boundary terms incompatible
        with scope terms in the existing value.
        """
        new_words = set(re.findall(r"\b\w+\b", new_val))
        ex_words = set(re.findall(r"\b\w+\b", ex_val))
        new_scope = new_words & _SCOPE_TERMS
        ex_scope = ex_words & _SCOPE_TERMS

        # Conflict if one has scope terms and the other has incompatible ones
        if new_scope and ex_scope:
            # Pairs that are inherently contradictory
            _incompatible = [
                ({"all", "any"}, {"none", "excluding"}),
                ({"only"}, {"all", "any"}),
                ({"within"}, {"excluding"}),
            ]
            for set_a, set_b in _incompatible:
                if (new_scope & set_a and ex_scope & set_b) or \
                   (new_scope & set_b and ex_scope & set_a):
                    return True

        # Note: We do NOT fire when only the incoming has scope terms — this produces
        # excessive false positives when normal Echelon artifact text uses words like
        # "only", "all", "within" in non-contradictory contexts. Scope conflict requires
        # both sides to carry scope terms with incompatible semantics.
        return False

    def _detect_architecture_conflict(self, new_val: str, ex_val: str) -> bool:
        """
        Detector 3: architecture_conflict.
        Fires when incoming names an architectural component not present in existing.
        """
        new_words = set(re.findall(r"\b\w+\b", new_val))
        ex_words = set(re.findall(r"\b\w+\b", ex_val))
        new_arch = new_words & _ARCH_TERMS
        ex_arch = ex_words & _ARCH_TERMS

        # New assertion introduces arch components not mentioned in existing
        new_only = new_arch - ex_arch
        if new_only:
            return True

        return False

    def apply_revision(self, incoming: BeliefNode) -> None:
        """
        AGM K*2 Minimal Contraction + Revision.

        Postulate: Relevance — move ONLY the node matching incoming.field_identifier
        to SUPERSEDED. No other nodes are touched.

        Steps (data-model.md §2):
          1. Get existing ACTIVE node for incoming.field_identifier.
          2. Set existing.status = SUPERSEDED.
          3. Set existing.superseded_by = incoming.field_identifier.
          4. incoming.version_counter = existing.version_counter + 1.
          5. incoming.superseded_chain = existing.superseded_chain + [existing].
          6. Add incoming to ACTIVE.
          7. Persist atomically (FR-NS3B-ERR-002).
        """
        existing = self._active.get(incoming.field_identifier)
        if existing is None:
            # Vacuity path — just insert
            self._active[incoming.field_identifier] = incoming
            self._persist()
            return

        # Step 2-3: mark existing as superseded
        existing.status = "SUPERSEDED"
        existing.superseded_by = incoming.field_identifier

        # Step 4-5: update incoming version chain
        incoming.version_counter = existing.version_counter + 1
        incoming.superseded_chain = existing.superseded_chain + [existing]

        # Track in superseded store
        self._superseded.setdefault(incoming.field_identifier, []).append(existing)

        # Step 6: add incoming to ACTIVE (Consistency: only one per field_identifier)
        self._active[incoming.field_identifier] = incoming

        # Step 7: atomic persist
        self._persist()

    def get_active(self, field_identifier: str) -> Optional[BeliefNode]:
        """Return the ACTIVE BeliefNode for field_identifier, or None."""
        return self._active.get(field_identifier)

    def get_superseded_chain(self, field_identifier: str) -> list[BeliefNode]:
        """Return all SUPERSEDED BeliefNodes for field_identifier, oldest first."""
        return list(self._superseded.get(field_identifier, []))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full graph to a dict suitable for JSON persistence (data-model.md §3)."""
        self._last_updated_at = datetime.now(timezone.utc).isoformat()
        return {
            "schema_version": VERSION,
            "run_id": self._run_id,
            "spec_id": self._spec_id,
            "created_at": self._created_at,
            "last_updated_at": self._last_updated_at,
            "active": {
                fid: node.to_dict()
                for fid, node in self._active.items()
            },
            "conflict_signals": [cs.to_dict() for cs in self._conflict_signals],
        }

    @classmethod
    def from_dict(cls, data: dict, graph_path: str) -> "BeliefGraph":
        """Deserialize a BeliefGraph from a persisted dict."""
        g = cls.__new__(cls)
        g.graph_path = graph_path
        g._active = {}
        g._superseded = {}
        g._conflict_signals = []
        g._run_id = data.get("run_id", str(uuid.uuid4()))
        g._spec_id = data.get("spec_id", "017")
        g._created_at = data.get("created_at", datetime.now(timezone.utc).isoformat())
        g._last_updated_at = data.get("last_updated_at", g._created_at)
        g._load_from_dict(data)
        return g

    def _persist(self) -> None:
        """
        Atomically write the BeliefGraph to graph_path.
        Uses temp file + fsync + rename per FR-NS3B-ERR-002.
        On failure, raises BeliefGraphWriteError; original file is untouched.
        """
        target = Path(self.graph_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        json_bytes = json.dumps(data, indent=2).encode("utf-8")

        tmp_path = None
        try:
            # Write to temp file in same directory (for atomic rename)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(target.parent),
                prefix=".belief-graph-tmp-",
                suffix=".json",
            )
            try:
                os.write(fd, json_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            # Atomic rename
            os.replace(tmp_path, str(target))
            tmp_path = None  # rename succeeded; don't clean up
        except OSError as e:
            # Clean up temp file if rename failed
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise BeliefGraphWriteError(str(target), e)


# ---------------------------------------------------------------------------
# T-011: Assertion Extractor
# ---------------------------------------------------------------------------

def _sort_artifacts_by_stage(artifact_files: list[Path]) -> list[tuple[Path, str]]:
    """
    Sort artifact files in DISCOVER → ASSESS → HOW → PLAN → BUILD → LEARN order.
    Returns list of (path, stage) tuples. Unrecognized files are placed last.
    """
    stage_order = {stage: idx for idx, stage in enumerate(PIPELINE_ORDER)}
    result: list[tuple[Path, str]] = []
    unrecognized: list[Path] = []

    for af in artifact_files:
        stage = ARTIFACT_STAGE_MAP.get(af.name.lower())
        if stage:
            result.append((af, stage))
        else:
            unrecognized.append(af)

    # Sort by pipeline stage order
    result.sort(key=lambda x: stage_order.get(x[1], 999))
    # Append unrecognized at end (they'll be warned about separately)
    return result


def extract_assertions_from_dir(
    artifact_dir: Path,
    graph: BeliefGraph,
    verbose: bool = False,
) -> tuple[int, int]:
    """
    Layer 1: Assertion Extractor.
    Reads all .md files in artifact_dir in pipeline stage order.
    Converts each KV pair to a BeliefNode and calls graph.add_belief().
    Returns (artifacts_processed, assertions_extracted).
    """
    all_files = list(artifact_dir.glob("*.md"))
    if not all_files:
        return 0, 0

    sorted_artifacts = _sort_artifacts_by_stage(all_files)

    # Warn about unrecognized files
    recognized_names = {af.name.lower() for af in artifact_dir.glob("*.md")
                        if ARTIFACT_STAGE_MAP.get(af.name.lower())}
    for af in all_files:
        if af.name.lower() not in ARTIFACT_STAGE_MAP:
            print(f"WARNING: Unrecognized artifact filename '{af.name}' — skipping.", file=sys.stderr)

    artifacts_processed = 0
    assertions_extracted = 0

    for artifact_path, stage in sorted_artifacts:
        try:
            text = artifact_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"WARNING: Cannot read {artifact_path}: {e}", file=sys.stderr)
            continue

        kv_pairs = extract_kv_pairs(text)
        artifacts_processed += 1

        for raw_key, raw_value in kv_pairs.items():
            # Already normalized by extract_kv_pairs; double-check stop-keys
            if raw_key in _GENERIC_STOP_KEYS:
                continue

            try:
                node = BeliefNode(
                    field_identifier=raw_key,
                    value=raw_value,
                    stage=stage,
                    confidence=INITIAL_CONFIDENCE,
                    artifact_path=str(artifact_path),
                )
                graph.add_belief(node)
                assertions_extracted += 1

                if verbose:
                    active = graph.get_active(raw_key)
                    print(
                        f"  [extractor] {stage}/{artifact_path.name}: "
                        f"{raw_key} = {raw_value[:60]!r}",
                        file=sys.stderr,
                    )
            except MalformedAssertionError as e:
                if verbose:
                    print(f"  [extractor] skipped malformed: {e}", file=sys.stderr)
            except ValueError as e:
                if verbose:
                    print(f"  [extractor] skipped invalid: {e}", file=sys.stderr)

    return artifacts_processed, assertions_extracted


# ---------------------------------------------------------------------------
# T-013: CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ns003_agm.py",
        description=(
            "NS-003-B AGM Belief Revision Engine — detects post-hoc contradictions\n"
            "across Echelon pipeline artifact stages using AGM K*2 minimal revision.\n\n"
            "IMPORTANT: pre-commit mode is NOT implemented in v1 per ADR-001 (IS-003\n"
            "resolution, amendment record: experiments/adr001-amendment-record.md).\n"
            "Specifying --mode pre-commit will print a deprecation notice and proceed\n"
            "in post-hoc mode.\n\n"
            "No ANTHROPIC_API_KEY required (fully deterministic engine)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--artifact-dir",
        required=True,
        help=(
            "Path to a directory containing Echelon artifact .md files from a single "
            "spec run. Files are processed in pipeline stage order: DISCOVER → ASSESS "
            "→ HOW → PLAN → BUILD → LEARN. Unrecognized filenames are skipped with a warning."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["post-hoc", "pre-commit"],
        default="post-hoc",
        help=(
            "Operating mode. Default: post-hoc.\n"
            "pre-commit: NOT IMPLEMENTED IN V1 — prints notice and proceeds as post-hoc."
        ),
    )
    parser.add_argument(
        "--belief-graph",
        dest="belief_graph",
        default=None,
        help=(
            "Path to the BeliefGraph JSON persistence file. "
            "Default: active run dir/belief-graph-<run_id>.json"
        ),
    )
    parser.add_argument(
        "--output",
        default="experiments/ns003-contradiction-report.json",
        help="Path to write the contradiction report JSON. Default: experiments/ns003-contradiction-report.json",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Run identifier (UUID4 or human-readable). Generated as UUID4 if omitted.",
    )
    parser.add_argument(
        "--spec-id",
        dest="spec_id",
        default="017",
        help="Spec identifier. Default: 017.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-assertion extraction details to stderr.",
    )
    return parser


def _default_squad_dir(run_id: str) -> Path:
    if os.environ.get("ECHELON_SQUAD_DIR"):
        return Path(os.environ["ECHELON_SQUAD_DIR"])

    root = Path.cwd()
    for base in ("runs", "squad"):
        current = root / base / ".current"
        if current.exists():
            current_run_id = current.read_text(encoding="utf-8").strip()
            candidate = root / base / current_run_id
            if current_run_id and candidate.is_dir():
                return candidate

        candidate = root / base / run_id
        if candidate.is_dir():
            return candidate

    return root / ".specify" / "squad"


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ADR-001: --mode pre-commit notice (NOT silent — must print deprecation)
    if args.mode == "pre-commit":
        print(
            "pre-commit mode not available in v1 — IS-003 resolution descoped this.\n"
            "See experiments/adr001-amendment-record.md for the full amendment record.\n"
            "Proceeding in post-hoc mode.",
            file=sys.stderr,
        )
        # Alias to post-hoc per ADR-001 Consequences (deprecation-warning path)

    run_id = args.run_id or str(uuid.uuid4())

    # Resolve belief graph path
    belief_graph_path = args.belief_graph
    if belief_graph_path is None:
        belief_graph_path = str(_default_squad_dir(run_id) / f"belief-graph-{run_id}.json")

    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.exists():
        print(f"ERROR: artifact-dir not found: {artifact_dir}", file=sys.stderr)
        sys.exit(1)

    # Initialize BeliefGraph
    graph = BeliefGraph(
        graph_path=belief_graph_path,
        run_id=run_id,
        spec_id=args.spec_id,
    )

    # Run assertion extraction (T-011) + contradiction classification (T-012)
    processing_timestamp = datetime.now(timezone.utc).isoformat()
    try:
        artifacts_processed, assertions_extracted = extract_assertions_from_dir(
            artifact_dir, graph, verbose=args.verbose
        )
    except BeliefGraphWriteError as e:
        print(f"ERROR: BeliefGraph write failure: {e}", file=sys.stderr)
        sys.exit(1)

    # Collect conflict signals from the graph
    conflicts_detected = len(graph._conflict_signals)

    # Build contradiction report
    contradiction_report = []
    for cs in graph._conflict_signals:
        contradiction_report.append({
            "field_identifier": cs.field_identifier,
            "contradiction_type": cs.contradiction_type,
            "confidence": cs.confidence,
            "existing_value": cs.existing_value,
            "existing_stage": cs.existing_stage,
            "existing_artifact": cs.existing_node_ref.artifact_path if cs.existing_node_ref else None,
            "new_value": cs.new_value,
            "new_stage": cs.new_stage,
            "new_artifact": cs.artifact_path_new,
            "recommended_action": cs.recommended_action,
        })

    # Output JSON per ns003_interfaces.md §2
    output = {
        "schema_version": VERSION,
        "run_id": run_id,
        "mode": "post-hoc",
        "artifact_dir": str(artifact_dir),
        "belief_graph_path": belief_graph_path,
        "processing_timestamp": processing_timestamp,
        "artifacts_processed": artifacts_processed,
        "assertions_extracted": assertions_extracted,
        "conflicts_detected": conflicts_detected,
        "contradiction_report": contradiction_report,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.verbose:
        print(
            f"[ns003_agm] Processed {artifacts_processed} artifacts, "
            f"{assertions_extracted} assertions, "
            f"{conflicts_detected} conflicts. "
            f"Report: {args.output}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

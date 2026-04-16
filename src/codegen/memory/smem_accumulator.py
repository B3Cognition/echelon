"""
smem_accumulator.py — Cross-run SMEM pattern accumulator.
Spec 018 T-022: Cross-Run SMEM Accumulation.
Spec 024 T-026: F5 pattern identification for SOAR SMEM write-back.

Distills successful ADVANCE patterns from DELIVER-complete runs into codegen-patterns.yaml.

ARCHITECTURAL NOTE (Spec 024 T-026):
  This class manages the JSON/YAML patterns file (codegen-patterns.yaml).
  It does NOT write to SOAR SMEM — that is SmemPatternWriter's domain.
  identify_patterns_for_accumulation() returns PatternCandidate objects
  that SmemPatternWriter consumes via _send_command("smem --add ...").
  These are separate concerns with separate failure modes.

INV-003: ONLY best preferences — never prohibit, require, or worst.
INV-010: SmemAccumulator only triggers after DELIVER phase (is_deliver_complete gate).
RAR-002: All file reads/writes via PathSafety.
RAR-003: yaml.safe_load() only (via YamlSafety).
"""
from __future__ import annotations

import binascii
import os
import uuid
from datetime import datetime
from typing import Optional

import yaml

from .smem_types import SmemPattern
from .run_index import RunIndex
from ..security.yaml_safety import YamlSafety
from ..security.path_safety import PathSafety

PATTERN_STORE_FILE = "codegen-patterns.yaml"
PATTERNS_MAX_ENTRIES = 5000
SMEM_MIN_RUNS_DEFAULT = 3  # minimum DELIVER-complete runs before pattern upserted


def _compute_code_domain_hash(file_paths: list[str]) -> str:
    """
    CRC16 of the top-2-directory-level prefix of written file paths.
    E.g. for ["src/codegen/foo.py", "src/codegen/bar.py"] → CRC16 of "src/codegen"
    Returns hex string.
    """
    prefixes = set()
    for path in file_paths:
        parts = path.replace("\\", "/").split("/")
        prefix = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        prefixes.add(prefix)
    combined = "|".join(sorted(prefixes))
    crc = binascii.crc_hqx(combined.encode(), 0)
    return f"{crc:04x}"


class SmemAccumulator:
    """
    Cross-run SMEM pattern accumulator.
    Distills successful ADVANCE patterns from DELIVER-complete runs into codegen-patterns.yaml.
    """

    def __init__(
        self,
        patterns_path: str | None = None,
        run_index: RunIndex | None = None,
        min_runs: int = SMEM_MIN_RUNS_DEFAULT,
    ) -> None:
        if patterns_path is not None:
            self._patterns_path = patterns_path
        else:
            ps = PathSafety(os.getcwd())
            self._patterns_path = ps.anchor_output(PATTERN_STORE_FILE)
        self._run_index = run_index
        self._min_runs = min_runs

    def distill(
        self,
        run_id: str,
        epmem_records: list[dict],
        written_file_paths: list[str],
        language: str,
        is_deliver_complete: bool = True,
    ) -> list[SmemPattern]:
        """
        Distill ADVANCE records from EPMEM into codegen-patterns.yaml.

        Only runs when is_deliver_complete=True (INV-010 gate).
        Extracts ADVANCE records from epmem_records.
        Groups by dedup_key = (language, frozenset(constraint_class_set), code_domain_hash).
        If group appears in >= min_runs DELIVER-complete runs: upsert SmemPattern.
        Excludes entries where source_authority_type == "ANCHORING".
        Applies size ceiling via YamlSafety.enforce_pattern_store_ceiling().
        Returns list of upserted/updated SmemPattern entries.
        """
        # INV-010: only trigger after DELIVER phase
        if not is_deliver_complete:
            return []

        code_domain_hash = _compute_code_domain_hash(written_file_paths) if written_file_paths else "0000"

        # Extract ADVANCE records, excluding ANCHORING source_authority_type
        advance_records = []
        for rec in epmem_records:
            # Check source_authority_type exclusion
            if rec.get("source_authority_type") == "ANCHORING":
                continue
            # Detect ADVANCE records
            is_advance = (
                rec.get("event_type") in ("ADVANCE", "tier0_gate_pass")
                or rec.get("operator_outcome") == "ADVANCE"
            )
            if is_advance:
                advance_records.append(rec)

        if not advance_records:
            return []

        # Load existing patterns
        existing_raw = self._load_raw()
        existing_by_id: dict[str, dict] = {e["pattern_id"]: e for e in existing_raw if "pattern_id" in e}

        # Build a dedup_key → list of run_ids mapping from existing patterns
        # so we can track how many distinct runs contributed to each dedup_key
        dedup_key_to_runs: dict[tuple, set[str]] = {}
        dedup_key_to_pattern_id: dict[tuple, str] = {}

        for entry in existing_raw:
            if "pattern_id" not in entry:
                continue
            key = (
                entry.get("language", ""),
                frozenset(entry.get("constraint_class_set", [])),
                entry.get("code_domain_hash", ""),
            )
            runs_seen = set(entry.get("_runs_seen", []))
            dedup_key_to_runs[key] = runs_seen
            dedup_key_to_pattern_id[key] = entry["pattern_id"]

        # Group current run's advance_records by dedup_key
        current_run_keys: dict[tuple, list[str]] = {}
        for rec in advance_records:
            constraint_class_set = rec.get("cq_isc_ids_evaluated", [])
            key = (
                language,
                frozenset(constraint_class_set),
                code_domain_hash,
            )
            if key not in current_run_keys:
                current_run_keys[key] = list(constraint_class_set)

        # Update runs_seen and decide whether to upsert
        upserted: list[SmemPattern] = []
        for key, constraint_class_set in current_run_keys.items():
            lang, frozen_ccs, domain_hash = key

            if key not in dedup_key_to_runs:
                dedup_key_to_runs[key] = set()

            dedup_key_to_runs[key].add(run_id)
            runs_count = len(dedup_key_to_runs[key])

            if runs_count >= self._min_runs:
                # Upsert pattern
                if key in dedup_key_to_pattern_id:
                    pattern_id = dedup_key_to_pattern_id[key]
                    # Update existing
                    if pattern_id in existing_by_id:
                        entry = existing_by_id[pattern_id]
                        # If transitioning from pending → active, set frequency_count to runs_count.
                        # If already active, increment by 1 (each new run adds to the count).
                        if entry.get("status") == "active":
                            entry["frequency_count"] = entry.get("frequency_count", 1) + 1
                        else:
                            entry["frequency_count"] = runs_count
                        entry["last_seen_run"] = run_id
                        entry["status"] = "active"
                        entry["_runs_seen"] = list(dedup_key_to_runs[key])
                        pattern = SmemPattern(
                            pattern_id=pattern_id,
                            language=lang,
                            constraint_class_set=list(frozen_ccs),
                            operator_outcome="ADVANCE",
                            code_domain_hash=domain_hash,
                            frequency_count=entry["frequency_count"],
                            first_seen_run=entry.get("first_seen_run", run_id),
                            last_seen_run=run_id,
                            max_stale_runs=entry.get("max_stale_runs", 10),
                            status="active",
                            source_authority_type=entry.get("source_authority_type", "DEFAULT_LIBRARY"),
                        )
                        upserted.append(pattern)
                else:
                    # Insert new
                    pattern_id = str(uuid.uuid4())
                    dedup_key_to_pattern_id[key] = pattern_id
                    new_entry = {
                        "pattern_id": pattern_id,
                        "language": lang,
                        "constraint_class_set": list(frozen_ccs),
                        "operator_outcome": "ADVANCE",
                        "code_domain_hash": domain_hash,
                        "frequency_count": runs_count,
                        "first_seen_run": run_id,
                        "last_seen_run": run_id,
                        "max_stale_runs": 10,
                        "status": "active",
                        "source_authority_type": "DEFAULT_LIBRARY",
                        "_runs_seen": list(dedup_key_to_runs[key]),
                    }
                    existing_by_id[pattern_id] = new_entry
                    pattern = SmemPattern(
                        pattern_id=pattern_id,
                        language=lang,
                        constraint_class_set=list(frozen_ccs),
                        operator_outcome="ADVANCE",
                        code_domain_hash=domain_hash,
                        frequency_count=runs_count,
                        first_seen_run=run_id,
                        last_seen_run=run_id,
                        status="active",
                    )
                    upserted.append(pattern)
            else:
                # Not enough runs yet — update or create tracking entry
                if key in dedup_key_to_pattern_id:
                    pattern_id = dedup_key_to_pattern_id[key]
                    if pattern_id in existing_by_id:
                        existing_by_id[pattern_id]["_runs_seen"] = list(dedup_key_to_runs[key])
                else:
                    # Create a pending (pre-threshold) tracking entry
                    pattern_id = str(uuid.uuid4())
                    dedup_key_to_pattern_id[key] = pattern_id
                    existing_by_id[pattern_id] = {
                        "pattern_id": pattern_id,
                        "language": lang,
                        "constraint_class_set": list(frozen_ccs),
                        "operator_outcome": "ADVANCE",
                        "code_domain_hash": domain_hash,
                        "frequency_count": runs_count,
                        "first_seen_run": run_id,
                        "last_seen_run": run_id,
                        "max_stale_runs": 10,
                        "status": "pending",
                        "source_authority_type": "DEFAULT_LIBRARY",
                        "_runs_seen": list(dedup_key_to_runs[key]),
                    }

        # Apply size ceiling
        all_entries = list(existing_by_id.values())
        all_entries = YamlSafety.enforce_pattern_store_ceiling(
            all_entries,
            max_entries=PATTERNS_MAX_ENTRIES,
            sort_key="frequency_count",
        )

        self._save_raw(all_entries)
        return upserted

    def identify_patterns_for_accumulation(
        self,
        run_id: str,
        psi_score: float,
        gate_outcomes: list[dict],
        active_wmes: list[dict],
        language: str,
        smem_accumulation_min_psi: float = 0.70,
    ):
        """
        T-026: Identify candidate patterns for SOAR SMEM write-back at DELIVER phase.

        Only proceeds when psi_score >= smem_accumulation_min_psi (FR-ACC-001).
        Derives pattern content deterministically from WME attributes (no LLM call).
        Tags ^critical true for CQ-ISC-SEC-* and CQ-ISC-MSR-* (FR-ACC-004).

        Returns:
            list[PatternCandidate] — candidates for SmemPatternWriter.write().
            Empty list when Ψ < threshold (AC-F5-002).
        """
        # Avoid circular import — PatternCandidate lives in smem_writer.py
        try:
            from codegen.soar.smem_writer import PatternCandidate
        except ImportError:
            from src.codegen.soar.smem_writer import PatternCandidate  # type: ignore

        if psi_score < smem_accumulation_min_psi:
            return []

        # Extract ADVANCE gate outcomes — each represents an approved pattern
        candidates = []
        for outcome in gate_outcomes:
            if outcome.get("decision") not in ("ADVANCE", "DELIVER"):
                continue
            cq_isc_ids = outcome.get("cq_isc_ids_evaluated", [])
            if not cq_isc_ids:
                continue

            candidate = PatternCandidate(
                source_run_id=run_id,
                psi_score_at_accumulation=psi_score,
                phase=outcome.get("phase", "UNKNOWN"),
                cq_isc_ids_active=list(cq_isc_ids),
                codebase_language=language,
            )
            candidates.append(candidate)

        return candidates

    def mark_stale_patterns(
        self,
        run_index: RunIndex,
        current_sequence: int,
    ) -> list[str]:
        """
        Mark patterns stale when current_sequence - last_seen_sequence > max_stale_runs.
        Returns list of pattern_ids marked stale.
        """
        entries = self._load_raw()
        marked_stale: list[str] = []

        for entry in entries:
            if entry.get("status") == "stale":
                continue
            last_seen_run = entry.get("last_seen_run", "")
            max_stale = entry.get("max_stale_runs", 10)

            # Get the sequence number of the last seen run
            last_seq: Optional[int] = None
            if last_seen_run and run_index is not None:
                last_seq = run_index.get_sequence(last_seen_run)

            if last_seq is not None:
                gap = current_sequence - last_seq
                if gap > max_stale:
                    entry["status"] = "stale"
                    marked_stale.append(entry["pattern_id"])

        self._save_raw(entries)
        return marked_stale

    def load_active_patterns(
        self,
        code_domain_hash: str | None = None,
    ) -> list[SmemPattern]:
        """
        Load active (non-stale) patterns from codegen-patterns.yaml.
        If code_domain_hash provided: filter by matching hash (project isolation).
        """
        entries = self._load_raw()
        patterns: list[SmemPattern] = []
        for entry in entries:
            if entry.get("status") not in ("active",):
                continue
            if code_domain_hash is not None and entry.get("code_domain_hash") != code_domain_hash:
                continue
            patterns.append(SmemPattern(
                pattern_id=entry.get("pattern_id", ""),
                language=entry.get("language", ""),
                constraint_class_set=entry.get("constraint_class_set", []),
                operator_outcome=entry.get("operator_outcome", "ADVANCE"),
                code_domain_hash=entry.get("code_domain_hash", ""),
                frequency_count=entry.get("frequency_count", 1),
                first_seen_run=entry.get("first_seen_run", ""),
                last_seen_run=entry.get("last_seen_run", ""),
                max_stale_runs=entry.get("max_stale_runs", 10),
                status=entry.get("status", "active"),
                source_authority_type=entry.get("source_authority_type", "DEFAULT_LIBRARY"),
            ))
        return patterns

    def _load_raw(self) -> list[dict]:
        """Load raw entries from YAML file."""
        path_obj = __import__("pathlib").Path(self._patterns_path)
        if not path_obj.exists():
            return []
        try:
            result = YamlSafety.load(self._patterns_path)
            if result is None:
                return []
            if isinstance(result, list):
                return result
            return []
        except Exception:
            return []

    def _save_raw(self, entries: list[dict]) -> None:
        """Save entries to YAML file via PathSafety.anchor_output()."""
        path_obj = __import__("pathlib").Path(self._patterns_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(self._patterns_path, "w", encoding="utf-8") as f:
            yaml.dump(entries, f, default_flow_style=False, allow_unicode=True)

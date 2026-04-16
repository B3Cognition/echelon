"""
run_index.py — Lightweight per-project run index: run_id → {sequence_number, timestamp}
Spec 018 T-021: Cross-Run SMEM Accumulation — Run Sequence Number.

Persisted to codegen-run-index.yaml via YamlSafety + PathSafety.
RAR-002: all file writes via PathSafety.anchor_output()
RAR-003: yaml.safe_load() only (via YamlSafety)
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..security.yaml_safety import YamlSafety
from ..security.path_safety import PathSafety

RUN_INDEX_FILE = "codegen-run-index.yaml"


class RunIndex:
    """
    Lightweight per-project run index: run_id → {sequence_number, timestamp}
    Persisted to codegen-run-index.yaml via YamlSafety + PathSafety.
    """

    def __init__(self, index_path: str | None = None) -> None:
        """
        Args:
            index_path: Explicit path to the run index YAML file.
                        Defaults to PathSafety(os.getcwd()).anchor_output("codegen-run-index.yaml").
        """
        if index_path is not None:
            self._index_path = index_path
        else:
            ps = PathSafety(os.getcwd())
            self._index_path = ps.anchor_output(RUN_INDEX_FILE)

    def record(self, run_id: str, sequence_number: int, timestamp: str | None = None) -> None:
        """
        Append/update entry. timestamp defaults to datetime.utcnow().isoformat().
        YAML write via yaml.dump() to path from anchor_output().
        """
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat()

        data = self._load()
        data[run_id] = {
            "sequence_number": sequence_number,
            "timestamp": timestamp,
        }
        self._save(data)

    def get_sequence(self, run_id: str) -> Optional[int]:
        """
        Returns sequence_number for run_id, or None if not found.
        No error on missing file or missing run_id.
        """
        try:
            data = self._load()
        except Exception:
            return None
        entry = data.get(run_id)
        if entry is None:
            return None
        return entry.get("sequence_number")

    def _load(self) -> dict:
        """Load YAML index. Returns {} if file absent."""
        path = Path(self._index_path)
        if not path.exists():
            return {}
        try:
            result = YamlSafety.load(self._index_path)
            if result is None:
                return {}
            if isinstance(result, dict):
                return result
            return {}
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        """Write YAML index via PathSafety.anchor_output()."""
        path = Path(self._index_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._index_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

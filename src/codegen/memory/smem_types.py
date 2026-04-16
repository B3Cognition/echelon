"""
smem_types.py — SMEM pattern data types for Spec 018 F6 Cross-Run SMEM Accumulation.
Spec 018 T-022.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SmemPattern:
    pattern_id: str
    language: str                         # e.g. "python", "typescript"
    constraint_class_set: list[str]       # list of CQ-ISC rule IDs evaluated
    operator_outcome: str                 # "ADVANCE" | "RETRY"
    code_domain_hash: str                 # CRC16 hex of top-2-dir prefix of written file paths
    frequency_count: int = 1
    first_seen_run: str = ""              # run_id
    last_seen_run: str = ""              # run_id
    max_stale_runs: int = 10             # runs before marking stale
    status: str = "active"               # "active" | "stale"
    source_authority_type: str = "DEFAULT_LIBRARY"  # never "ANCHORING" (excluded from distill)

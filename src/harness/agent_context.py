"""Phase-aware bounded rendering for Echelon agent dispatch context."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


RENDER_MODES = {"bounded", "legacy"}


@dataclass(frozen=True)
class ContextSelector:
    path_ref: str
    filters: dict[str, str]


@dataclass(frozen=True)
class ContextPolicy:
    criticality: str
    renderer: str
    cap_bytes: int
    overflow_action: str


DEFAULT_FILE_CAP_BYTES = 96 * 1024
DEFAULT_HISTORY_CAP_BYTES = 24 * 1024
DEFAULT_DIRECTORY_CAP_BYTES = 96 * 1024
MUST_PRESERVE_CAP_BYTES = 512 * 1024


def resolve_context_render_mode(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    mode = str(source.get("ECHELON_CONTEXT_RENDER_MODE") or "bounded").strip().lower()
    return mode if mode in RENDER_MODES else "bounded"


def parse_context_pack_item(item: str) -> ContextSelector:
    raw = str(item or "").strip()
    filters: dict[str, str] = {}
    match = re.search(r"\[([^\]]+)\]", raw)
    if match:
        for part in match.group(1).split(","):
            key, separator, value = part.partition("=")
            if separator and key.strip() and value.strip():
                filters[key.strip()] = value.strip()
        raw = raw[: match.start()].strip()
    path_ref = raw.split(" ")[0].split("(")[0].rstrip()
    return ContextSelector(path_ref=path_ref, filters=filters)


def policy_for_context(
    *,
    phase_id: str,
    agent_id: str = "",
    mode: str = "",
    path_ref: str,
) -> ContextPolicy:
    ref = path_ref.strip()
    basename = Path(ref.rstrip("/")).name
    phase = phase_id.strip()

    if "reasoning-journal.jsonl" in ref:
        return ContextPolicy("history", "filtered_journal", DEFAULT_HISTORY_CAP_BYTES, "truncate_with_notice")

    if basename == "state.json":
        return ContextPolicy("important", "compact_json", DEFAULT_FILE_CAP_BYTES, "summarize_with_notice")

    if ref.endswith("/") or any(ch in ref for ch in "*?[]"):
        if "contracts" in ref:
            return ContextPolicy("must_preserve", "directory_bounded_files", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")
        if "investigation" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        if "adr/" in ref or "ADR-" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        return ContextPolicy("important", "directory_manifest", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")

    if phase == "phase1-why2" and basename in {"spec.md", "constitution.md", "assumptions.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase == "phase1-investigate" and basename in {"spec.md", "assumptions.md", "unknowns.md", "issues.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase in {"phase3-sentinel", "phase3-consensus"} and basename in {
        "spec.md",
        "plan.md",
        "data-model.md",
        "tasks.md",
        "coverage-map.md",
        "test-strategy.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    }:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if basename in {"prior-spec-context.md", "stale-memory-report.md"}:
        return ContextPolicy("advisory", "summary_pointer", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")

    return ContextPolicy("important", "full_file", DEFAULT_FILE_CAP_BYTES, "truncate_with_notice")

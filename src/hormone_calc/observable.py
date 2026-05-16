"""ObservableState — the input contract for trigger detection.

Built by build_from() at dispatch time, consumed by every triggers/*.py
detect() function. All fields are deterministically derived from
state.json + reasoning-journal.jsonl + the echelon_result YAML file.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml


@dataclass(frozen=True)
class ObservableState:
    # about the just-completed dispatch
    agent: str
    dispatch_id: str
    result: dict
    archetype: str

    # about the squad-run state
    state: dict
    iteration: int
    token_ratio: float
    autonomy_mode: str

    # about recent history (last 50 journal entries)
    recent_dispatches: list[dict]
    quality_score_series: list[float]
    prior_verdict_for_agent: Optional[str]
    upstream_agent: Optional[str]

    # about current hormone state
    current_hormones: dict[str, float]


def build_from(
    *,
    agent: str,
    dispatch_id: str,
    result_path: Path,
    state_path: Path,
    journal_path: Path,
    archetype_fn: Optional[Callable[[str], str]] = None,
    upstream_agent: Optional[str] = None,
) -> ObservableState:
    """Construct an ObservableState by reading state.json, journal, and result file.

    archetype_fn: callable(agent) -> archetype string. Defaults to
                  invoking `bash endocrine.sh get_archetype <agent>`.
    upstream_agent: passed through; if None, src/hormone_calc/upstream.derive_upstream
                    can derive it later (cli.py wires this).
    """
    state = json.loads(state_path.read_text())
    result = yaml.safe_load(result_path.read_text()) or {}
    journal = _read_journal_tail(journal_path, n=50)

    archetype = (archetype_fn or _default_archetype_fn)(agent)
    hormones = (
        state.get("endocrine_state", {})
        .get("agents", {})
        .get(agent, {})
        .get("hormones", {})
    )

    iteration = int(state.get("iteration", 0))
    token_budget_k = state.get("thresholds", {}).get("token_budget_k", 1000)
    token_budget = (token_budget_k or 0) * 1000
    total = state.get("token_ledger", {}).get("total_estimated_tokens", 0)
    token_ratio = (total / token_budget) if token_budget > 0 else 0.0

    autonomy_mode = state.get("autonomy_mode", "semi")
    quality_series = [
        float(q.get("overall", 0.0))
        for q in state.get("quality_scores", [])
        if isinstance(q, dict)
    ]
    prior_verdict = _find_prior_verdict(journal, agent)

    return ObservableState(
        agent=agent,
        dispatch_id=dispatch_id,
        result=result,
        archetype=archetype,
        state=state,
        iteration=iteration,
        token_ratio=token_ratio,
        autonomy_mode=autonomy_mode,
        recent_dispatches=journal,
        quality_score_series=quality_series,
        prior_verdict_for_agent=prior_verdict,
        upstream_agent=upstream_agent,
        current_hormones=hormones,
    )


def _read_journal_tail(path: Path, n: int) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _find_prior_verdict(journal: list[dict], agent: str) -> Optional[str]:
    """Walk journal backwards, find most recent entry where this agent had a verdict."""
    for entry in reversed(journal):
        if entry.get("agent") == agent:
            data = entry.get("data", {})
            if isinstance(data, dict) and "verdict" in data:
                return data["verdict"]
    return None


def _default_archetype_fn(agent: str) -> str:
    """Invoke `bash endocrine.sh get_archetype <agent>` to get the archetype.

    Falls back to "control" if the call fails (consistent with endocrine.sh's
    own fallback for unknown agents).
    """
    try:
        result = subprocess.run(
            ["bash", "extension/scripts/bash/endocrine.sh", "get_archetype", agent],
            capture_output=True, text=True, timeout=5,
        )
        out = result.stdout.strip()
        return out or "control"
    except Exception:
        return "control"

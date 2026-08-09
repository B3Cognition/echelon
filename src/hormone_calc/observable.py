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


def normalize_agent_name(name: str) -> str:
    """Normalize agent names from journal (echelon-foo-bar) to the
    canonical codename form (FOO_BAR) that endocrine.sh expects.

    Examples:
      "echelon-commander" → "COMMANDER"
      "echelon-spec-guard" → "SPEC_GUARD"
      "COMMANDER" → "COMMANDER"  (idempotent)
      "" → ""
    """
    if not name:
        return name
    if name.startswith("echelon-"):
        suffix = name[len("echelon-"):]
        return suffix.upper().replace("-", "_")
    return name


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


def _strip_echelon_result_fence(text: str) -> str:
    """Strip markdown fence markers from an echelon_result block.

    Tolerates three input formats:
      1. Raw YAML body — returned as-is.
      2. ```echelon_result\\n<body>\\n```  — strips both fences.
      3. ```yaml\\n<body>\\n``` or bare ```\\n<body>\\n``` — also stripped.

    The agent's response includes the fenced form (per commander.md §100
    Post-Dispatch Protocol Step A). The hook saves the agent's text to
    --result-file as-is, so the fence is present when COMMANDER's
    Post-Dispatch Protocol passes the file to hormone-calc.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    # Drop the opening fence line (```echelon_result, ```yaml, or just ```)
    lines = text.split("\n", 1)
    if len(lines) < 2:
        return text
    body = lines[1]
    # Drop trailing ``` if present
    body = body.rstrip()
    if body.endswith("```"):
        body = body[:-3].rstrip()
    return body


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
    result_text = result_path.read_text()
    result_text = _strip_echelon_result_fence(result_text)
    result = yaml.safe_load(result_text) or {}
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
        if normalize_agent_name(entry.get("agent", "")) == agent:
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

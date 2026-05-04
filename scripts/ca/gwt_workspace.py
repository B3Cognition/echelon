"""
T-024 — GWT Bounded Workspace Overlay (CA overlay, ADR-005)

Exposes:
  enrich_context(context_pack, run_id) -> dict
  add_to_workspace(item_text, run_id, config_path=None)

Token-bounded workspace with oldest-first eviction.

Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_TOKENS = 2000  # tokens
CHARS_PER_TOKEN = 4        # 4-char/token heuristic (ADR-005)
DEFAULT_MAX_CHARS = DEFAULT_MAX_TOKENS * CHARS_PER_TOKEN  # 8000 chars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workspace_path(run_id: str) -> str:
    root = _repo_root()
    return os.path.join(root, ".specify", "squad", f"gwt-workspace-{run_id}.json")


def _repo_root() -> str:
    path = os.path.dirname(os.path.abspath(__file__))
    while path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


def _max_chars(config_path: Optional[str] = None) -> int:
    """Read max_tokens from echelon-config.yml → convert to chars."""
    if config_path is None:
        config_path = os.path.join(_repo_root(), "echelon-config.yml")
    if not os.path.isfile(config_path):
        return DEFAULT_MAX_CHARS
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
        # Simple regex parse: ca_overlays.gwt.max_tokens: <N>
        import re
        m = re.search(r"max_tokens\s*:\s*(\d+)", content)
        if m:
            return int(m.group(1)) * CHARS_PER_TOKEN
    except Exception:
        pass
    return DEFAULT_MAX_CHARS


def _load_workspace(run_id: str) -> list:
    path = _workspace_path(run_id)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_workspace(items: list, run_id: str) -> None:
    path = _workspace_path(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def _total_chars(items: list) -> int:
    return sum(len(str(item.get("text", ""))) for item in items)


def _evict_to_fit(items: list, max_chars: int) -> list:
    """Evict oldest items (lowest timestamp) until total chars ≤ max_chars."""
    items = sorted(items, key=lambda x: x.get("timestamp", 0))  # oldest first
    while _total_chars(items) > max_chars and items:
        items.pop(0)  # remove oldest
    return items


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def enrich_context(context_pack: dict, run_id: str, config_path: Optional[str] = None) -> dict:
    """
    Inject the current bounded workspace into the context_pack.

    Adds context_pack["gwt_workspace"] = [list of current workspace items].
    Does NOT modify COMMANDER routing logic, quality gates, or endocrine triggers (AC-5.1).
    FR-CAO-002: workspace is token-bounded; cannot grow unboundedly.
    """
    items = _load_workspace(run_id)
    enriched = dict(context_pack)
    enriched["gwt_workspace"] = items
    return enriched


def add_to_workspace(item_text: str, run_id: str, config_path: Optional[str] = None) -> None:
    """
    Add an item to the bounded workspace. Evicts oldest items if bound exceeded.

    Called by COMMANDER post-dispatch to record workspace state.
    Eviction policy: oldest-first (lowest timestamp). Recency = higher priority.
    """
    max_chars = _max_chars(config_path)
    items = _load_workspace(run_id)

    new_item = {
        "text": item_text,
        "timestamp": time.time(),
    }
    items.append(new_item)

    # Enforce token bound
    items = _evict_to_fit(items, max_chars)
    _save_workspace(items, run_id)

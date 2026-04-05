"""
T-022 — ACT-R Typed Buffer Overlay (CA overlay, ADR-005)

Exposes:
  enrich_context(context_pack, run_id) -> dict

Restructures a flat context_pack into four typed buffers plus a read-only
retrieval_buffer (TF-IDF top-3). Standard library only — no sklearn/numpy
per ADR-005 OQ-005 resolution.

Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any


# ---------------------------------------------------------------------------
# TF-IDF helpers (stdlib only)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]{2,}", text.lower())


def _tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {w: c / total for w, c in counts.items()}


def _idf(word: str, docs: list[list[str]]) -> float:
    n = len(docs)
    df = sum(1 for d in docs if word in set(d))
    if df == 0:
        return 0.0
    return math.log((n + 1) / (df + 1))


def _tfidf_vec(tokens: list[str], docs: list[list[str]]) -> dict[str, float]:
    tf_vals = _tf(tokens)
    return {w: tf_vals[w] * _idf(w, docs) for w in tf_vals}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Token count heuristic (4 chars ≈ 1 token)
# ---------------------------------------------------------------------------

def _char_count(obj: Any) -> int:
    return len(str(obj))


def _token_estimate(obj: Any) -> int:
    return max(1, _char_count(obj) // 4)


def _token_estimate_pack(context_pack: dict) -> int:
    return sum(_token_estimate(v) for v in context_pack.values())


# ---------------------------------------------------------------------------
# Buffer classification
# ---------------------------------------------------------------------------

def _classify_key(key: str) -> str:
    """Assign a context_pack key to one of the four ACT-R buffers."""
    key_lower = key.lower()
    # Procedural: role, instruction, prompt, agent
    if any(w in key_lower for w in ("role", "instruction", "prompt", "agent", "procedure", "how")):
        return "procedural"
    # Goal: task, goal, objective, criteria, requirement
    if any(w in key_lower for w in ("task", "goal", "objective", "criteria", "requirement", "fr_", "ac_")):
        return "goal"
    # Imaginal: current, draft, artifact, in_progress
    if any(w in key_lower for w in ("current", "draft", "artifact", "in_progress", "imaginal", "wip")):
        return "imaginal"
    # Default: declarative (factual prior content)
    return "declarative"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def enrich_context(context_pack: dict, run_id: str) -> dict:  # noqa: ARG001
    """
    Restructure flat context_pack into four ACT-R typed buffers.

    Adds:
      context_pack["actr_buffers"] = {
        "declarative": [...],
        "procedural": [...],
        "goal": [...],
        "imaginal": [...],
        "retrieval_buffer": [...],  # top-3 TF-IDF, read-only
      }

    FR-CAO-002: if total token count exceeds original pack, evict from
    declarative (recency = lower priority — evict oldest entries first).
    """
    original_tokens = _token_estimate_pack(context_pack)
    max_tokens = original_tokens  # must not exceed

    # Step 1: classify keys into buffers
    buffers: dict[str, list[dict]] = {
        "declarative": [],
        "procedural": [],
        "goal": [],
        "imaginal": [],
    }

    for key, value in context_pack.items():
        buf = _classify_key(key)
        buffers[buf].append({"key": key, "value": value})

    # Step 2: TF-IDF retrieval over declarative entries
    retrieval_buffer: list[dict] = []
    declarative_texts = [str(e["value"]) for e in buffers["declarative"]]
    if len(declarative_texts) >= 2:
        tokenized_docs = [_tokenize(t) for t in declarative_texts]
        # Query = concatenation of goal + procedural content
        query_text = " ".join(
            str(e["value"]) for e in buffers["goal"] + buffers["procedural"]
        )
        query_tokens = _tokenize(query_text)
        query_vec = _tfidf_vec(query_tokens, tokenized_docs)

        scored = []
        for i, (doc_tokens, entry) in enumerate(zip(tokenized_docs, buffers["declarative"])):
            doc_vec = _tfidf_vec(doc_tokens, tokenized_docs)
            score = _cosine(query_vec, doc_vec)
            scored.append((score, i, entry))

        scored.sort(key=lambda x: -x[0])
        # Top-3 excerpts (truncate value to 500 chars for retrieval)
        for score, _, entry in scored[:3]:
            excerpt = str(entry["value"])[:500]
            retrieval_buffer.append({"key": entry["key"], "excerpt": excerpt, "score": round(score, 4)})

    # Step 3: enforce token bound — evict from declarative (oldest = first appended)
    total_new_tokens = (
        sum(_token_estimate(e) for e in buffers["declarative"])
        + sum(_token_estimate(e) for e in buffers["procedural"])
        + sum(_token_estimate(e) for e in buffers["goal"])
        + sum(_token_estimate(e) for e in buffers["imaginal"])
        + sum(_token_estimate(e) for e in retrieval_buffer)
    )

    while total_new_tokens > max_tokens and buffers["declarative"]:
        evicted = buffers["declarative"].pop(0)  # oldest first
        total_new_tokens -= _token_estimate(evicted)

    # ISS-004 / FR-SOAR-011: return only actr_buffers (no original key duplication)
    return {
        "actr_buffers": {
            "declarative": buffers["declarative"],
            "procedural": buffers["procedural"],
            "goal": buffers["goal"],
            "imaginal": buffers["imaginal"],
            "retrieval_buffer": retrieval_buffer,
        }
    }

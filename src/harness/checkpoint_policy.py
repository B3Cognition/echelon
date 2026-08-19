"""Strict runtime policy and owned-path resolution for Phase A checkpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from harness.phase_graph import PhaseGraph


class CheckpointPolicyError(RuntimeError):
    """Raised when a runtime phase has no usable checkpoint policy."""


def phase_checkpoint_policy(graph: PhaseGraph, phase: str) -> tuple[str, str]:
    """Return one phase's explicit checkpoint and rewind policy."""
    try:
        node = graph.get(phase)
    except KeyError as exc:
        raise CheckpointPolicyError(
            f"unknown phase for checkpoint policy: {phase}"
        ) from exc

    checkpoint = node.checkpoint
    rewind = node.rewind
    if checkpoint not in {"required", "none"} or rewind not in {
        "supported",
        "none",
    }:
        raise CheckpointPolicyError(
            f"missing or invalid checkpoint policy: {phase}"
        )
    if checkpoint == "none" and rewind == "supported":
        raise CheckpointPolicyError(
            f"invalid checkpoint policy combination: {phase}"
        )
    return checkpoint, rewind


def checkpoint_additional_owned_paths(
    project_root: Path,
    phase: str,
    state: Mapping[str, object],
) -> tuple[Path, ...]:
    """Return controller-owned paths outside the run-local spec directory."""
    del state
    if phase == "phase1-constitution":
        return (project_root / ".echelon" / "constitution.md",)
    return ()

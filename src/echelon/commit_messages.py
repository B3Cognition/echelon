"""Structured commit messages for Echelon-created commits."""

from __future__ import annotations

from dataclasses import dataclass


ECHELON_COAUTHOR = "Co-authored-by: Echelon <echelon@b3cognition.dev>"


@dataclass(frozen=True)
class EchelonCommitMetadata:
    origin: str
    action: str
    spec_id: str = ""
    run_id: str = ""
    phase: str = ""
    strategy: str = ""
    checkpoint_id: str = ""
    next_phase: str = ""
    completion_id: str = ""
    retarget_revision: str = ""
    baseline_run_id: str = ""
    replacement_run_id: str = ""


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def build_echelon_commit_message(subject: str, metadata: EchelonCommitMetadata) -> str:
    subject = _clean(subject)
    origin = _clean(metadata.origin)
    action = _clean(metadata.action)
    if not subject:
        raise ValueError("commit subject is required")
    if not origin:
        raise ValueError("Echelon-Origin is required")
    if not action:
        raise ValueError("Echelon-Action is required")

    trailers = [
        ECHELON_COAUTHOR,
        f"Echelon-Origin: {origin}",
        f"Echelon-Action: {action}",
    ]
    optional = (
        ("Echelon-Spec", metadata.spec_id),
        ("Echelon-Run", metadata.run_id),
        ("Echelon-Phase", metadata.phase),
        ("Echelon-Strategy", metadata.strategy),
        ("Echelon-Checkpoint", metadata.checkpoint_id),
        ("Echelon-Next-Phase", metadata.next_phase),
        ("Echelon-Completion", metadata.completion_id),
        ("Echelon-Retarget-Revision", metadata.retarget_revision),
        ("Echelon-Baseline-Run", metadata.baseline_run_id),
        ("Echelon-Replacement-Run", metadata.replacement_run_id),
    )
    for key, value in optional:
        cleaned = _clean(value)
        if cleaned:
            trailers.append(f"{key}: {cleaned}")
    return subject + "\n\n" + "\n".join(trailers)

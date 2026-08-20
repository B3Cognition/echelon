from pathlib import Path

import pytest
import yaml

from harness.checkpoint_policy import (
    CheckpointPolicyError,
    checkpoint_additional_owned_paths,
    phase_checkpoint_policy,
)
from harness.phase_graph import PhaseGraph


def _graph(tmp_path: Path, phase: dict[str, object]) -> PhaseGraph:
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump({"phases": [phase]}, sort_keys=False),
        encoding="utf-8",
    )
    return PhaseGraph(definition)


def test_policy_resolver_returns_declared_policy(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "id": "phase1-discover",
        "type": "terminal",
        "checkpoint": "required",
        "rewind": "supported",
    })

    assert phase_checkpoint_policy(graph, "phase1-discover") == (
        "required",
        "supported",
    )


@pytest.mark.parametrize(
    "phase",
    [
        {"id": "phase1-discover", "type": "terminal"},
        {
            "id": "phase1-discover",
            "type": "terminal",
            "checkpoint": "sometimes",
            "rewind": "supported",
        },
    ],
)
def test_policy_resolver_rejects_missing_or_invalid_runtime_policy(
    tmp_path: Path,
    phase: dict[str, object],
) -> None:
    graph = _graph(tmp_path, phase)

    with pytest.raises(CheckpointPolicyError, match="checkpoint policy"):
        phase_checkpoint_policy(graph, "phase1-discover")


def test_policy_resolver_rejects_unknown_phase(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "id": "phase1-discover",
        "type": "terminal",
        "checkpoint": "required",
        "rewind": "supported",
    })

    with pytest.raises(CheckpointPolicyError, match="unknown phase"):
        phase_checkpoint_policy(graph, "phase1-missing")


def test_constitution_adds_only_canonical_constitution_path(tmp_path: Path) -> None:
    assert checkpoint_additional_owned_paths(
        tmp_path,
        "phase1-constitution",
        {"spec_id": "001-demo"},
    ) == (tmp_path / ".echelon" / "constitution.md",)


def test_ordinary_phase_has_no_additional_owned_paths(tmp_path: Path) -> None:
    assert checkpoint_additional_owned_paths(
        tmp_path,
        "phase1-discover",
        {"spec_id": "001-demo"},
    ) == ()

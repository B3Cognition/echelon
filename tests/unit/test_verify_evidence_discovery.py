from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_candidate(
    path: Path,
    *,
    spec_id: str,
    completed_at: str,
    files: tuple[str, ...] = ("topology-receipt.json",),
) -> Path:
    path.mkdir(parents=True)
    (path / "state.json").write_text(
        json.dumps(
            {
                "spec_id": spec_id,
                "completed_at": completed_at,
                "status": "complete",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name in files:
        (path / name).write_text("{}\n", encoding="utf-8")
    return path


@pytest.mark.unit
def test_discovery_requires_state_identity_and_sorts_by_recorded_completion_then_path(
    tmp_path: Path,
) -> None:
    from harness.verify_evidence_discovery import discover_verify_evidence_runs

    older = _write_candidate(
        tmp_path / "runs/verify-spec-909-older",
        spec_id="909-delivery-topology",
        completed_at="2026-08-04T10:00:00+00:00",
    )
    same_time_a = _write_candidate(
        tmp_path / "runs/build-a/verify-spec/909",
        spec_id="909",
        completed_at="2026-08-04T11:00:00Z",
    )
    same_time_b = _write_candidate(
        tmp_path / "runs/build-b/verify-spec/909-delivery-topology",
        spec_id="909-delivery-topology",
        completed_at="2026-08-04T11:00:00+00:00",
    )
    _write_candidate(
        tmp_path / "runs/verify-spec-909-wrong-state",
        spec_id="910-other",
        completed_at="2026-08-04T12:00:00+00:00",
    )
    _write_candidate(
        tmp_path / "runs/verify-spec-909-missing-artifact",
        spec_id="909",
        completed_at="2026-08-04T13:00:00+00:00",
        files=(),
    )

    assert discover_verify_evidence_runs(
        tmp_path,
        "909-delivery-topology",
        required_files=("topology-receipt.json",),
    ) == (older, same_time_a, same_time_b)


@pytest.mark.unit
def test_discovery_rejects_malformed_completion_and_symlinked_candidates(
    tmp_path: Path,
) -> None:
    from harness.verify_evidence_discovery import discover_verify_evidence_runs

    malformed = _write_candidate(
        tmp_path / "runs/verify-spec-909-malformed",
        spec_id="909",
        completed_at="not-a-time",
    )
    outside = _write_candidate(
        tmp_path / "outside/verify-spec-909-linked",
        spec_id="909",
        completed_at="2026-08-04T14:00:00+00:00",
    )
    linked = tmp_path / "runs/verify-spec-909-linked"
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(outside, target_is_directory=True)

    assert discover_verify_evidence_runs(
        tmp_path,
        "909",
        required_files=("topology-receipt.json",),
    ) == ()
    assert malformed.is_dir()


@pytest.mark.unit
def test_discovery_rejects_symlinked_state_or_required_artifact(tmp_path: Path) -> None:
    from harness.verify_evidence_discovery import discover_verify_evidence_runs

    outside_state = tmp_path / "outside-state.json"
    outside_state.write_text(
        json.dumps(
            {
                "spec_id": "909",
                "completed_at": "2026-08-04T14:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    state_linked = _write_candidate(
        tmp_path / "runs/verify-spec-909-state-linked",
        spec_id="909",
        completed_at="2026-08-04T14:00:00+00:00",
    )
    (state_linked / "state.json").unlink()
    (state_linked / "state.json").symlink_to(outside_state)

    outside_receipt = tmp_path / "outside-receipt.json"
    outside_receipt.write_text("{}\n", encoding="utf-8")
    artifact_linked = _write_candidate(
        tmp_path / "runs/verify-spec-909-artifact-linked",
        spec_id="909",
        completed_at="2026-08-04T15:00:00+00:00",
    )
    (artifact_linked / "topology-receipt.json").unlink()
    (artifact_linked / "topology-receipt.json").symlink_to(outside_receipt)

    assert discover_verify_evidence_runs(
        tmp_path,
        "909",
        required_files=("topology-receipt.json",),
    ) == ()


@pytest.mark.unit
def test_discovery_requires_every_declared_file(tmp_path: Path) -> None:
    from harness.verify_evidence_discovery import discover_verify_evidence_runs

    incomplete = _write_candidate(
        tmp_path / "runs/verify-spec-909-incomplete",
        spec_id="909",
        completed_at="2026-08-04T14:00:00+00:00",
        files=("implementation-map.md",),
    )
    complete = _write_candidate(
        tmp_path / "runs/verify-spec-909-complete",
        spec_id="909",
        completed_at="2026-08-04T15:00:00+00:00",
        files=("implementation-map.md", "requirement-audit.md"),
    )

    assert discover_verify_evidence_runs(
        tmp_path,
        "909",
        required_files=("implementation-map.md", "requirement-audit.md"),
    ) == (complete,)
    assert incomplete.is_dir()

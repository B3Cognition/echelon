"""Unit tests for RequirementsMiner with MemPalaceContext."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.context import MemPalaceContext
from codegen.memory.requirements_miner import RequirementsMiner


def _make_ctx(wing="my-app", run_id="run-1", palace_path="/fake/palace"):
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path=palace_path)


def test_miner_stores_ctx(tmp_path):
    ctx = _make_ctx()
    miner = RequirementsMiner(ctx, project_dir=tmp_path)
    assert miner.ctx is ctx
    assert miner.wing == "my-app"
    assert miner.run_id == "run-1"
    assert miner.project_dir == tmp_path


def test_miner_passes_ctx_to_writer(tmp_path):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        miner = RequirementsMiner(ctx, project_dir=tmp_path)
        mock_writer = MagicMock()
        mock_writer.write.return_value = "drawer-id-1"
        miner._writer = mock_writer

        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=[]):
            result = miner.mine_file(spec)

    assert result.written == 1
    mock_writer.write.assert_called_once()


def test_miner_checks_collision_on_first_write(tmp_path):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=[]) as mock_check:
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "drawer-id-1"
            miner._writer = mock_writer
            miner.mine_file(spec)

    mock_check.assert_called_once_with(ctx.wing, tmp_path, ctx.palace_path)


def test_collision_check_runs_only_once(tmp_path):
    ctx = _make_ctx()
    spec1 = tmp_path / "spec1.md"
    spec1.write_text("FR-001: First\n")
    spec2 = tmp_path / "spec2.md"
    spec2.write_text("FR-002: Second\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision", return_value=[]) as mock_check:
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "d"
            miner._writer = mock_writer
            miner.mine_file(spec1)
            miner.mine_file(spec2)

    assert mock_check.call_count == 1


def test_miner_prints_warning_on_collision(tmp_path, capsys):
    ctx = _make_ctx()
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Do a thing\n")

    with patch("codegen.memory.requirements_miner.scrub_secrets", side_effect=lambda x: x):
        with patch("codegen.memory.requirements_miner.check_wing_collision",
                   return_value=["/other/project/spec.md"]):
            miner = RequirementsMiner(ctx, project_dir=tmp_path)
            mock_writer = MagicMock()
            mock_writer.write.return_value = "drawer-id-1"
            miner._writer = mock_writer
            miner.mine_file(spec)

    captured = capsys.readouterr()
    assert "my-app" in captured.err
    assert "/other/project/spec.md" in captured.err


def test_mine_file_passes_artifact_metadata(monkeypatch, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("FR-001: Upload.\n", encoding="utf-8")
    ctx = MemPalaceContext(wing="demo", run_id="run-1", palace_path=str(tmp_path / "palace"))
    miner = RequirementsMiner(ctx, project_dir=tmp_path)
    calls = []

    class Writer:
        def write(self, **kwargs):
            calls.append(kwargs)
            return "drawer_demo"

    monkeypatch.setattr(miner, "_get_writer", lambda: Writer())
    monkeypatch.setattr("codegen.memory.requirements_miner.check_wing_collision", lambda *args, **kwargs: [])

    miner.mine_file(spec, artifact_metadata={"artifact_hash": "sha256:" + "2" * 64, "canonical": True})

    assert calls[0]["extra_metadata"]["artifact_hash"] == "sha256:" + "2" * 64
    assert calls[0]["extra_metadata"]["canonical"] is True


def test_canonical_mining_uses_unique_stable_ids_for_same_room_requirements(
    monkeypatch,
    tmp_path: Path,
) -> None:
    text = "FR-001: First capability.\nFR-002: Second capability.\n"
    first_spec = tmp_path / "first" / "spec.md"
    second_spec = tmp_path / "moved" / "canonical.md"
    first_spec.parent.mkdir()
    second_spec.parent.mkdir()
    first_spec.write_text(text, encoding="utf-8")
    second_spec.write_text(text, encoding="utf-8")
    digest = "5" * 64

    class ExactWriter:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def write_exact(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                outcome="written",
                drawer_id=kwargs["drawer_id"],
            )

    monkeypatch.setattr(
        "codegen.memory.requirements_miner.check_wing_collision",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "codegen.memory.requirements_miner.scrub_secrets",
        lambda value: value,
    )
    first_writer = ExactWriter()
    first = RequirementsMiner(
        _make_ctx(wing="demo", run_id="run-one"),
        project_dir=tmp_path,
    )
    first._writer = first_writer
    first_result = first.mine_file(
        first_spec,
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
        },
    )
    second_writer = ExactWriter()
    second = RequirementsMiner(
        _make_ctx(wing="demo", run_id="run-two"),
        project_dir=tmp_path,
    )
    second._writer = second_writer
    second_result = second.mine_file(
        second_spec,
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
        },
    )

    assert len(first_result.drawer_ids) == 2
    assert len(set(first_result.drawer_ids)) == 2
    assert second_result.drawer_ids == first_result.drawer_ids
    assert [call["requirement_id"] for call in first_writer.calls] == [
        "FR-001",
        "FR-002",
    ]
    assert all(call["spec_sha256"] == digest for call in first_writer.calls)

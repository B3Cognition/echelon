"""Unit tests for check_wing_collision."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.collision import check_wing_collision


def _make_collection(metadatas: list[dict]):
    col = MagicMock()
    col.get.return_value = {"metadatas": metadatas, "ids": [f"id-{i}" for i in range(len(metadatas))]}
    return col


def test_no_collision_when_no_drawers(tmp_path):
    col = _make_collection([])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_no_collision_when_all_drawers_from_same_project(tmp_path):
    spec = tmp_path / "spec.md"
    col = _make_collection([{"source_file": str(spec), "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_no_collision_for_relative_canonical_spec_paths(tmp_path):
    source = "specs/003-demo/spec.md"
    (tmp_path / source).parent.mkdir(parents=True)
    (tmp_path / source).write_text("FR-001: Demo.\n", encoding="utf-8")
    col = _make_collection([{"source_file": source, "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_collision_detected_when_foreign_source_file(tmp_path):
    foreign_path = "/Users/other/other-project/spec.md"
    col = _make_collection([{"source_file": foreign_path, "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert foreign_path in result


def test_synthetic_codegen_source_files_not_flagged(tmp_path):
    col = _make_collection([{"source_file": "codegen/RE", "wing": "my-app"}])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_returns_empty_when_mempalace_not_installed(tmp_path):
    with patch("codegen.memory.collision._get_collection", side_effect=ImportError):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == []


def test_deduplicates_foreign_paths(tmp_path):
    foreign = "/other/spec.md"
    col = _make_collection([
        {"source_file": foreign, "wing": "my-app"},
        {"source_file": foreign, "wing": "my-app"},
    ])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        result = check_wing_collision("my-app", tmp_path, "/fake/palace")
    assert result == [foreign]


def test_query_uses_correct_shape(tmp_path):
    """col.get must be called with wing filter, limit=20, metadata-only include."""
    col = _make_collection([])
    with patch("codegen.memory.collision._get_collection", return_value=col):
        check_wing_collision("my-app", tmp_path, "/fake/palace")

    col.get.assert_called_once_with(
        where={"wing": {"$eq": "my-app"}},
        limit=20,
        include=["metadatas"],
    )

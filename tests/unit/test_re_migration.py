from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_migration import import_legacy_re_cache


def _write_legacy_entry(root: Path, source_id: str, fingerprint: str) -> Path:
    entry = root / ".echelon/cache/re/sources" / source_id / fingerprint
    entry.mkdir(parents=True)
    (entry / "analysis.json").write_text('{"source":"api"}\n', encoding="utf-8")
    (entry / "cache-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": source_id,
                "fingerprint": fingerprint,
                "profile_hash": "profile-hash",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return entry


def test_import_legacy_cache_is_one_way_and_does_not_publish(tmp_path: Path) -> None:
    _write_legacy_entry(tmp_path, "api", "a" * 64)

    imported = import_legacy_re_cache(tmp_path)

    destination = tmp_path / "re/.cache/sources/api" / ("a" * 64)
    assert imported == (destination,)
    assert (destination / "analysis.json").is_file()
    assert not (tmp_path / "re/index.json").exists()


def test_import_legacy_cache_never_overwrites_destination(tmp_path: Path) -> None:
    _write_legacy_entry(tmp_path, "api", "b" * 64)
    destination = tmp_path / "re/.cache/sources/api" / ("b" * 64)
    destination.mkdir(parents=True)
    (destination / "sentinel.txt").write_text("keep\n", encoding="utf-8")

    imported = import_legacy_re_cache(tmp_path)

    assert imported == ()
    assert (destination / "sentinel.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (destination / "analysis.json").exists()


def test_import_legacy_cache_skips_invalid_entries_with_warning(tmp_path: Path) -> None:
    entry = _write_legacy_entry(tmp_path, "bad source", "not-a-fingerprint")
    (entry / "cache-manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.warns(UserWarning, match="Skipping invalid legacy RE cache"):
        imported = import_legacy_re_cache(tmp_path)

    assert imported == ()
    assert not (tmp_path / "re/index.json").exists()

from __future__ import annotations

import json
from pathlib import Path

from harness.re_cache import (
    ReCacheRecord,
    ReCacheStore,
    cache_hit,
    cache_source_dir,
    copy_cached_source,
    write_cache_record,
)
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint, fingerprint_source


def _tree_fingerprint(source: Path) -> SourceFingerprint:
    return fingerprint_source(source, ReFingerprintProfile(profile="deep", depth="signatures"))


def _fingerprint(value: str = "abc123") -> SourceFingerprint:
    return SourceFingerprint(
        value=value,
        kind="git",
        dirty=False,
        profile_hash="profile-hash",
        git_head="deadbeef",
    )


def _write_source_output(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "analysis.json").write_text('{"repo_name":"app"}\n', encoding="utf-8")
    (path / "re-context.md").write_text("# RE Context\n", encoding="utf-8")
    nested = path / "nested"
    nested.mkdir()
    (nested / "codegraph-summary.json").write_text('{"nodes":1}\n', encoding="utf-8")


def test_re_cache_entry_paths_are_scoped_by_source_id_and_fingerprint(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "sources" / "app"
    source.mkdir(parents=True)
    (source / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
    fingerprint = _tree_fingerprint(source)

    entry = store.entry_path("app", fingerprint)

    assert entry == tmp_path / "re" / ".cache" / "sources" / "app" / fingerprint.value
    assert store.legacy_root == tmp_path / ".echelon" / "cache" / "re"


def test_re_cache_rejects_unsafe_source_ids(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    fingerprint = _tree_fingerprint(source)

    try:
        store.entry_path("../escape", fingerprint)
    except ValueError as exc:
        assert "unsafe source id" in str(exc)
    else:
        raise AssertionError("expected unsafe source id to fail")


def test_re_cache_store_hit_requires_manifest_and_required_artifacts(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    fingerprint = _tree_fingerprint(source)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "analysis.json").write_text('{"ok":true}\n', encoding="utf-8")

    assert store.is_hit("source", fingerprint, required_files=("analysis.json",)) is False

    store.write_entry("source", fingerprint, artifacts)

    assert store.is_hit("source", fingerprint, required_files=("analysis.json",)) is True
    assert store.is_hit("source", fingerprint, required_files=("missing.json",)) is False


def test_re_cache_write_replaces_stale_entry_contents(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    fingerprint = _tree_fingerprint(source)
    first_artifacts = tmp_path / "first"
    first_artifacts.mkdir()
    (first_artifacts / "analysis.json").write_text('{"version":1}\n', encoding="utf-8")
    (first_artifacts / "stale.json").write_text('{"stale":true}\n', encoding="utf-8")
    second_artifacts = tmp_path / "second"
    second_artifacts.mkdir()
    (second_artifacts / "analysis.json").write_text('{"version":2}\n', encoding="utf-8")

    store.write_entry("source", fingerprint, first_artifacts)
    store.write_entry("source", fingerprint, second_artifacts)

    entry = store.entry_path("source", fingerprint)
    assert (entry / "analysis.json").read_text(encoding="utf-8") == '{"version":2}\n'
    assert not (entry / "stale.json").exists()
    assert (entry / "cache-manifest.json").exists()


def test_cache_hit_requires_manifest_and_required_artifacts(tmp_path: Path) -> None:
    cache_root = tmp_path / ".echelon" / "cache" / "re"
    fingerprint = _fingerprint()
    cache_dir = cache_source_dir(cache_root, "app", fingerprint)

    assert cache_dir == cache_root / "sources" / "app" / fingerprint.value
    assert cache_hit(cache_root, "app", fingerprint) is False

    source_output = tmp_path / "source-output"
    _write_source_output(source_output)
    write_cache_record(
        source_output,
        cache_dir,
        ReCacheRecord(
            source_id="app",
            source_path="sources/app",
            fingerprint=fingerprint,
            profile={"profile": "survey", "depth": "signatures"},
        ),
    )

    assert cache_hit(cache_root, "app", fingerprint) is True
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_id"] == "app"
    assert manifest["source_path"] == "sources/app"
    assert manifest["fingerprint"]["value"] == fingerprint.value
    assert manifest["artifacts"] == [
        "analysis.json",
        "nested/codegraph-summary.json",
        "re-context.md",
    ]
    assert (cache_dir / "cache-manifest.json").is_file()


def test_copy_cached_source_copies_files_without_symlinks(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    fingerprint = _fingerprint("copy-me")
    cache_dir = cache_source_dir(cache_root, "app", fingerprint)
    source_output = tmp_path / "source-output"
    _write_source_output(source_output)
    write_cache_record(
        source_output,
        cache_dir,
        ReCacheRecord(
            source_id="app",
            source_path="sources/app",
            fingerprint=fingerprint,
            profile={"profile": "survey"},
        ),
    )

    run_source_dir = tmp_path / "runs" / "run-1" / "re" / "app"
    copied = copy_cached_source(cache_dir, run_source_dir)

    assert copied == run_source_dir
    assert (run_source_dir / "analysis.json").read_text(encoding="utf-8") == '{"repo_name":"app"}\n'
    assert (run_source_dir / "re-context.md").read_text(encoding="utf-8") == "# RE Context\n"
    assert (run_source_dir / "nested" / "codegraph-summary.json").is_file()
    assert not (run_source_dir / "analysis.json").is_symlink()
    assert not (run_source_dir / "nested" / "codegraph-summary.json").is_symlink()

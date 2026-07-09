from __future__ import annotations

from pathlib import Path

from harness.re_cache import ReCacheStore
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint, fingerprint_source


def _fingerprint(source: Path) -> SourceFingerprint:
    return fingerprint_source(source, ReFingerprintProfile(profile="deep", depth="signatures"))


def test_re_cache_entry_paths_are_scoped_by_source_id_and_fingerprint(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "sources" / "app"
    source.mkdir(parents=True)
    (source / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
    fingerprint = _fingerprint(source)

    entry = store.entry_path("app", fingerprint)

    assert entry == tmp_path / ".echelon" / "cache" / "re" / "sources" / "app" / fingerprint.value


def test_re_cache_rejects_unsafe_source_ids(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    fingerprint = _fingerprint(source)

    try:
        store.entry_path("../escape", fingerprint)
    except ValueError as exc:
        assert "unsafe source id" in str(exc)
    else:
        raise AssertionError("expected unsafe source id to fail")


def test_re_cache_hit_requires_manifest_and_required_artifacts(tmp_path: Path) -> None:
    store = ReCacheStore(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    fingerprint = _fingerprint(source)
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
    fingerprint = _fingerprint(source)
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

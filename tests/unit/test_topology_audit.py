from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_topology_registry import build_topology, _write_json


@pytest.mark.unit
def test_audit_reports_invalid_when_index_is_missing(tmp_path: Path) -> None:
    from echelon.topology_audit import audit_topology

    report = audit_topology(tmp_path)
    assert report.status == "invalid"
    assert report.exit_code == 2


@pytest.mark.unit
def test_audit_reports_current_for_matching_clean_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_topology(tmp_path)
    from harness.re_fingerprint import SourceFingerprint
    from echelon.topology_audit import audit_topology

    fingerprint = SourceFingerprint("0" * 64, "git", False, "1" * 64, "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", lambda path, profile: fingerprint)
    report = audit_topology(tmp_path)
    assert report.status == "current"
    assert report.exit_code == 0
    assert report.sources[0].source_id == "api"


@pytest.mark.unit
@pytest.mark.parametrize("case", ("dirty", "mismatch"))
def test_audit_reports_stale_for_dirty_or_changed_live_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    build_topology(tmp_path)
    from harness.re_fingerprint import SourceFingerprint
    from echelon.topology_audit import audit_topology

    fingerprint = SourceFingerprint(
        "f" * 64 if case == "mismatch" else "0" * 64,
        "git",
        case == "dirty",
        "1" * 64,
        "0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", lambda path, profile: fingerprint)
    report = audit_topology(tmp_path)
    assert report.status == "stale"
    assert report.exit_code == 1


@pytest.mark.unit
def test_audit_reports_degraded_provider_without_marking_snapshot_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = build_topology(tmp_path)
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    analysis_path = tmp_path / "re/topology/sources/api/codegraph-analysis.json"
    analysis = json.loads(analysis_path.read_text())
    analysis["provider_status"] = "partial"
    analysis["complete"] = False
    analysis_sha = _write_json(analysis_path, analysis)
    receipt["providers"]["codegraph"]["status"] = "degraded"  # type: ignore[index]
    receipt["providers"]["codegraph"]["complete"] = False  # type: ignore[index]
    receipt["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = analysis_sha  # type: ignore[index]
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    index["sources"]["api"]["providers"]["codegraph"]["status"] = "degraded"  # type: ignore[index]
    index["sources"]["api"]["providers"]["codegraph"]["complete"] = False  # type: ignore[index]
    index["sources"]["api"]["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = analysis_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from harness.re_fingerprint import SourceFingerprint
    from echelon.topology_audit import audit_topology

    fingerprint = SourceFingerprint("0" * 64, "git", False, "1" * 64, "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", lambda path, profile: fingerprint)
    report = audit_topology(tmp_path)
    assert report.status == "degraded"
    assert report.exit_code == 1


@pytest.mark.unit
@pytest.mark.parametrize("case", ("malformed", "removed", "duplicate_key", "bad_endpoint", "count_mismatch"))
def test_audit_reports_structural_contract_failures_as_invalid(
    tmp_path: Path, case: str
) -> None:
    index = build_topology(tmp_path)
    if case == "malformed":
        (tmp_path / "re/topology/index.json").write_text("{", encoding="utf-8")
    elif case == "removed":
        (tmp_path / ".echelon/config.yml").write_text("workspace:\n  sources: []\n", encoding="utf-8")
    else:
        path = tmp_path / "re/topology/sources/api/codegraph-analysis.json"
        artifact = json.loads(path.read_text())
        if case == "duplicate_key":
            artifact["symbols"].append(dict(artifact["symbols"][0]))
            artifact["counts"]["discovered_symbols"] = 2
            artifact["counts"]["emitted_symbols"] = 2
        elif case == "bad_endpoint":
            artifact["relationships"] = [{"kind": "calls", "source_key": artifact["symbols"][0]["symbol_key"], "target_key": "sha256:" + "f" * 64}]
            artifact["counts"]["discovered_relationships"] = 1
            artifact["counts"]["emitted_relationships"] = 1
        else:
            artifact["counts"]["emitted_symbols"] = 9
        artifact_sha = _write_json(path, artifact)
        index["sources"]["api"]["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = artifact_sha  # type: ignore[index]
        receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
        receipt = json.loads(receipt_path.read_text())
        receipt["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = artifact_sha
        receipt_sha = _write_json(receipt_path, receipt)
        index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
        _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_audit import audit_topology

    report = audit_topology(tmp_path)
    assert report.status == "invalid"
    assert report.exit_code == 2

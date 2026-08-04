from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_topology_registry import build_topology, _write_json


def _advance_publication_generation(root: Path) -> None:
    index_path = root / "re/topology/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    generation = int(index["generation"]) + 1
    receipt_path = root / index["sources"]["api"]["receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["generation"] = generation
    index["sources"]["api"]["receipt"]["sha256"] = _write_json(
        receipt_path, receipt
    )
    index["generation"] = generation
    _write_json(index_path, index)


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
    assert report.snapshot is not None
    assert report.snapshot.generation == 3
    assert report.snapshot.sources[0].source_id == "api"
    assert report.snapshot.sources[0].source_fingerprint == "0" * 64
    assert report.snapshot.sources[0].receipt_sha256.startswith("sha256:")


@pytest.mark.unit
def test_audit_fails_closed_when_publication_swaps_between_index_and_provider_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_topology(tmp_path)
    from harness.re_fingerprint import SourceFingerprint
    import echelon.topology_audit as topology_audit

    real_load_index = topology_audit.load_topology_index
    swapped = False

    def load_then_swap(root: Path):
        nonlocal swapped
        index = real_load_index(root)
        if not swapped:
            swapped = True
            _advance_publication_generation(root)
        return index

    fingerprint = SourceFingerprint(
        "0" * 64,
        "git",
        False,
        "1" * 64,
        "0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr(topology_audit, "load_topology_index", load_then_swap)
    monkeypatch.setattr(
        topology_audit, "resolve_re_fingerprint_profile", lambda root: object()
    )
    monkeypatch.setattr(
        topology_audit, "fingerprint_source", lambda path, profile: fingerprint
    )

    report = topology_audit.audit_topology(tmp_path, source_id="api")

    assert report.status == "invalid"
    assert report.exit_code == 2
    assert "publication changed during audit" in report.findings[0].message


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
def test_audit_reports_structurally_valid_unavailable_provider_as_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = build_topology(tmp_path)
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    unavailable = {
        "status": "unavailable",
        "complete": False,
        "artifacts": {},
        "diagnostics": [{"kind": "missing", "message": "provider output missing"}],
    }
    receipt["providers"]["codegraph"] = unavailable
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    index["sources"]["api"]["providers"]["codegraph"] = {
        "status": "unavailable", "complete": False, "artifacts": {}
    }  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from harness.re_fingerprint import SourceFingerprint
    from echelon.topology_audit import audit_topology

    fingerprint = SourceFingerprint("0" * 64, "git", False, "1" * 64, "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", lambda path, profile: fingerprint)
    report = audit_topology(tmp_path)

    assert report.status == "degraded"
    assert report.findings[0].provider == "codegraph"


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


@pytest.mark.unit
def test_audit_fingerprint_execution_failure_is_invalid_with_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_topology(tmp_path)
    from echelon.topology_audit import audit_topology

    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr(
        "echelon.topology_audit.fingerprint_source",
        lambda path, profile: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, ["git", "rev-parse"])
        ),
    )
    report = audit_topology(tmp_path, source_id="api")

    assert report.status == "invalid"
    assert report.exit_code == 2
    assert report.findings[0].source_id == "api"


@pytest.mark.unit
def test_audit_all_unsupported_completed_provider_is_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = build_topology(tmp_path)
    index["sources"]["api"]["providers"].pop("codegraph")  # type: ignore[index]
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    receipt["providers"].pop("codegraph")
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from harness.re_fingerprint import SourceFingerprint
    from echelon.topology_audit import audit_topology

    fingerprint = SourceFingerprint("0" * 64, "git", False, "1" * 64, "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr("echelon.topology_audit.resolve_re_fingerprint_profile", lambda root: object())
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", lambda path, profile: fingerprint)
    report = audit_topology(tmp_path)

    assert report.status == "current"
    assert report.exit_code == 0

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_topology_evidence import (
    _codegraph,
    _perl_unsupported,
    _summary,
    _write_json,
)


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _delivery_workspace(
    tmp_path: Path,
    *,
    status: str = "landed",
    verify_scope: str = "full",
    include_perlgraph: bool = False,
) -> tuple[Path, Path, Path, Path, str]:
    from harness.topology_evidence import write_topology_evidence_receipt

    workspace = tmp_path / "workspace"
    source = workspace / "sources/api"
    source.mkdir(parents=True)
    (workspace / ".echelon").mkdir()
    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test User")
    (source / "src").mkdir()
    (source / "src/app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    _git(source, "add", "src/app.py")
    _git(source, "commit", "-m", "feature")
    head = _git(source, "rev-parse", "HEAD")

    spec = workspace / "specs/909-delivery-topology"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        f"---\nstatus: {status}\ntargets:\n- sources/api\n---\n# Spec\n",
        encoding="utf-8",
    )
    run = workspace / "runs/verify-spec-909-20260804-120000"
    run.mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "909-delivery-topology",
                "verify_scope": verify_scope,
                "status": "complete",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    codegraph = _codegraph()
    _write_json(run / "codegraph-analysis.json", codegraph)
    _write_json(run / "codegraph-summary.json", _summary("codegraph", codegraph))
    if include_perlgraph:
        perlgraph = _perl_unsupported()
        _write_json(run / "perlgraph-analysis.json", perlgraph)
        _write_json(
            run / "perlgraph-summary.json",
            _summary("perlgraph", perlgraph),
        )
    write_topology_evidence_receipt(
        source,
        run,
        spec,
        workspace_root=workspace,
        source_id="api",
        source_root=source,
    )
    return workspace, source, spec, run, head


def _canonical_bytes(workspace: Path) -> dict[str, bytes]:
    root = workspace / "re/topology"
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "scope", "expected"),
    (
        ("ready_to_land", "full", "not landed"),
        ("landed", "scoped", "full verify scope"),
    ),
)
def test_reconciliation_rejects_unlanded_or_scoped_evidence_without_mutation(
    tmp_path: Path,
    status: str,
    scope: str,
    expected: str,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, head = _delivery_workspace(
        tmp_path,
        status=status,
        verify_scope=scope,
    )

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )

    assert result.status == "stale"
    assert expected in result.message
    assert _canonical_bytes(workspace) == {}


@pytest.mark.unit
def test_reconciliation_rejects_unknown_and_ambiguous_source_mapping(
    tmp_path: Path,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, head = _delivery_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    unknown = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        outside,
        head,
        evidence_run=run,
    )
    assert unknown.status == "unavailable"
    assert "configured source" in unknown.message
    assert _canonical_bytes(workspace) == {}

    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n"
        "    - id: api\n      path: sources/api\n"
        "    - id: duplicate\n      path: sources/api\n",
        encoding="utf-8",
    )
    ambiguous = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )
    assert ambiguous.status == "unavailable"
    assert "ambiguous" in ambiguous.message
    assert _canonical_bytes(workspace) == {}


@pytest.mark.unit
def test_exact_commit_and_full_fingerprint_promote_exact_provider_bytes(
    tmp_path: Path,
) -> None:
    from echelon.topology_registry import load_topology_index
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, head = _delivery_workspace(
        tmp_path,
        include_perlgraph=True,
    )
    analysis = (run / "codegraph-analysis.json").read_bytes()

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )

    assert result.status == "current"
    assert result.source_id == "api"
    assert result.generation == 1
    assert result.recaptured is False
    assert (
        workspace / "re/topology/sources/api/codegraph-analysis.json"
    ).read_bytes() == analysis
    index = load_topology_index(workspace)
    assert index is not None
    assert index.sources["api"].providers["perlgraph"].status == "unsupported"


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("fingerprint", "provider"))
def test_reconciliation_rejects_fingerprint_or_provider_drift_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, head = _delivery_workspace(tmp_path)
    if mutation == "fingerprint":
        (source / "src/app.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    else:
        (run / "codegraph-analysis.json").write_text("{}\n", encoding="utf-8")

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )

    assert result.status in {"stale", "unavailable"}
    assert _canonical_bytes(workspace) == {}


@pytest.mark.unit
def test_changed_landed_commit_recaptures_and_never_restamps_old_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, feature_head = _delivery_workspace(tmp_path)
    old_analysis = (run / "codegraph-analysis.json").read_bytes()
    _git(source, "commit", "--allow-empty", "-m", "no-ff merge")
    landed_head = _git(source, "rev-parse", "HEAD")
    assert landed_head != feature_head
    captured: list[Path] = []

    def recapture(project_root: Path, verify_run_dir: Path, spec_dir: Path) -> None:
        assert project_root == source
        assert _git(source, "rev-parse", "HEAD") == landed_head
        captured.append(verify_run_dir)
        document = _codegraph()
        document["generated_at"] = "land-reconciliation"
        _write_json(verify_run_dir / "codegraph-analysis.json", document)
        _write_json(
            verify_run_dir / "codegraph-summary.json",
            _summary("codegraph", document),
        )

    monkeypatch.setattr(
        "harness.topology_promotion.capture_delivery_topology_evidence",
        recapture,
    )

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        landed_head,
        evidence_run=run,
    )

    assert result.status == "current"
    assert result.recaptured is True
    assert len(captured) == 1
    published = workspace / "re/topology/sources/api/codegraph-analysis.json"
    assert published.read_bytes() != old_analysis
    assert json.loads(published.read_text())["generated_at"] == "land-reconciliation"
    canonical_receipt = json.loads(
        (workspace / "re/topology/sources/api/receipt.json").read_text()
    )
    assert canonical_receipt["analyzed_commit"] == landed_head
    assert canonical_receipt["provenance"] == {
        "kind": "land-reconciliation",
        "evidence_run": run.name,
    }


@pytest.mark.unit
def test_changed_commit_rejects_symlinked_recapture_directory_without_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, _ = _delivery_workspace(tmp_path)
    _git(source, "commit", "--allow-empty", "-m", "squash result")
    landed_head = _git(source, "rev-parse", "HEAD")
    outside = tmp_path / "outside-recapture"
    outside.mkdir()
    recapture = run / f"land-reconciliation-{landed_head[:12]}"
    recapture.symlink_to(outside, target_is_directory=True)

    def unexpected_capture(*args, **kwargs) -> None:
        pytest.fail("provider capture must not run through a symlinked owner")

    monkeypatch.setattr(
        "harness.topology_promotion.capture_delivery_topology_evidence",
        unexpected_capture,
    )

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        landed_head,
        evidence_run=run,
    )

    assert result.status == "unavailable"
    assert "recapture" in result.message
    assert list(outside.iterdir()) == []
    assert _canonical_bytes(workspace) == {}


@pytest.mark.unit
def test_generation_conflict_is_nonmutating_reconciliation_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology
    from harness.topology_publication import TopologyPublicationConflict

    workspace, source, _, run, head = _delivery_workspace(tmp_path)
    before = _canonical_bytes(workspace)

    def conflict(*args, **kwargs):
        raise TopologyPublicationConflict("expected generation 0, found 1")

    monkeypatch.setattr(
        "harness.topology_promotion.publish_topology_snapshots",
        conflict,
    )
    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )

    assert result.status == "stale"
    assert "generation" in result.message
    assert _canonical_bytes(workspace) == before


@pytest.mark.unit
def test_reconciliation_rejects_receipt_moved_from_its_recorded_run(
    tmp_path: Path,
) -> None:
    from harness.topology_promotion import reconcile_landed_topology

    workspace, source, _, run, head = _delivery_workspace(tmp_path)
    receipt_path = run / "topology-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["provenance"]["run_dir"] = "runs/verify-spec-909-another-run"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = reconcile_landed_topology(
        workspace,
        "909-delivery-topology",
        source,
        head,
        evidence_run=run,
    )

    assert result.status == "unavailable"
    assert "provenance" in result.message
    assert _canonical_bytes(workspace) == {}

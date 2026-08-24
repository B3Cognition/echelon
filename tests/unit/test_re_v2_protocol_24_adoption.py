from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from harness.re_v2.ledger import ObjectStore
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_24.adoption import (
    Protocol24AdoptionError,
    build_parent_authority_bundle,
    import_parent_acceptance_closure,
    validate_parent_for_deepening,
)
from harness.re_v2.protocol_24 import adoption as adoption_module
from harness.re_v2.protocol_24.model import (
    AdoptedArtifactAuthorityV1,
    ParentAuthorityBundleV1,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
from tests.unit.test_re_v2_protocol_22_graph import _fixture
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_controller import (
    _baseline_context,
    _inventory_context,
)


def _complete_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, object]:
    context = _inventory_context(tmp_path / "runs")
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "completed"
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption._validate_workspace_sources",
        lambda *_args: None,
    )
    return context.paths.root.parent, result


def test_complete_schema2_parent_builds_exact_authority_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_run, result = _complete_parent(tmp_path, monkeypatch)

    parent = validate_parent_for_deepening(parent_run, tmp_path)
    bundle, objects = build_parent_authority_bundle(parent)

    assert bundle.direct_parent_run_id == parent_run.name
    assert bundle.source_manifest_hash == parent.manifest.identity
    assert bundle.source_terminal_event_hash == result.events[-1].event_hash
    assert len(bundle.artifacts) == len(result.ledger.accepted_artifacts)
    assert bundle.artifacts == tuple(
        sorted(bundle.artifacts, key=lambda item: item.artifact_key_id)
    )
    assert bundle.identity not in objects
    assert bundle.source_manifest_hash in objects
    assert bundle.source_event_chain_hash in objects
    assert bundle.source_ledger_chain_hash in objects


def test_nonterminal_parent_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _inventory_context(tmp_path / "runs")
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption._validate_workspace_sources",
        lambda *_args: None,
    )

    with pytest.raises(Protocol24AdoptionError, match="completed"):
        validate_parent_for_deepening(context.paths.root.parent, tmp_path)


def test_failed_parent_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _inventory_context(tmp_path / "runs")

    class _FailingProducer:
        def produce(self, *_args: object) -> bytes:
            raise RuntimeError("deterministic producer failed")

    failing = _FailingProducer()
    context = replace(
        context,
        producers=MappingProxyType(
            {
                "evidence-pack": failing,
                "inventory": failing,
                "partition": failing,
            }
        ),
    )
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "failed"
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption._validate_workspace_sources",
        lambda *_args: None,
    )

    with pytest.raises(Protocol24AdoptionError, match="completed"):
        validate_parent_for_deepening(context.paths.root.parent, tmp_path)

def test_adoption_replays_exact_receipts_and_survives_parent_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_run, result = _complete_parent(tmp_path, monkeypatch)
    parent = validate_parent_for_deepening(parent_run, tmp_path)
    child_root = tmp_path / "child" / "v2"
    child_root.mkdir(parents=True)
    child_objects = ObjectStore(child_root / "objects")
    child_ledger = Protocol22Ledger(child_root / "ledger.jsonl", child_objects)

    report = import_parent_acceptance_closure(
        parent,
        child_objects,
        child_ledger,
    )
    shutil.rmtree(parent_run)
    replayed = child_ledger.replay()

    assert report.artifact_count == len(result.ledger.accepted_artifacts)
    assert replayed.accepted_artifacts == result.ledger.accepted_artifacts
    assert replayed.certifications == result.ledger.certifications
    assert replayed.certification_work_items == result.ledger.certification_work_items


def test_provider_candidate_assessment_closure_is_imported_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _provider = _baseline_context(tmp_path / "runs", provider_mode="cli")
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "completed"
    assert result.ledger is not None
    assert result.ledger.candidate_assessments
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption._validate_workspace_sources",
        lambda *_args: None,
    )
    parent = validate_parent_for_deepening(context.paths.root.parent, tmp_path)
    child_root = tmp_path / "candidate-child" / "v2"
    child_root.mkdir(parents=True)
    objects = ObjectStore(child_root / "objects")
    ledger = Protocol22Ledger(child_root / "ledger.jsonl", objects)

    report = import_parent_acceptance_closure(parent, objects, ledger)
    replayed = ledger.replay()

    assert report.candidate_assessment_count == len(
        result.ledger.candidate_assessments
    )
    assert replayed.candidate_assessments == result.ledger.candidate_assessments


def test_missing_parent_artifact_object_is_rejected_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_run, result = _complete_parent(tmp_path, monkeypatch)
    artifact_hash = next(iter(result.ledger.accepted_artifacts.values())).artifact_hash
    suffix = artifact_hash.removeprefix("sha256:")
    (parent_run / "v2" / "objects" / "sha256" / suffix[:2] / suffix[2:]).unlink()

    with pytest.raises(Protocol24AdoptionError, match="object"):
        validate_parent_for_deepening(parent_run, tmp_path)


def test_parent_run_must_be_a_real_direct_child_of_workspace_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_run, _result = _complete_parent(tmp_path, monkeypatch)
    link = tmp_path / "runs" / "re-linked"
    link.symlink_to(parent_run, target_is_directory=True)

    with pytest.raises(Protocol24AdoptionError, match="symlink|runs"):
        validate_parent_for_deepening(link, tmp_path)


@pytest.mark.parametrize("chain_name", ("events.jsonl", "ledger.jsonl"))
def test_corrupt_parent_chains_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_name: str,
) -> None:
    parent_run, _result = _complete_parent(tmp_path, monkeypatch)
    chain = parent_run / "v2" / chain_name
    chain.write_bytes(chain.read_bytes() + b"corrupt")

    with pytest.raises(Protocol24AdoptionError, match="authority|chain|record"):
        validate_parent_for_deepening(parent_run, tmp_path)


def test_completed_event_cannot_hide_partial_ledger_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_run, _result = _complete_parent(tmp_path, monkeypatch)
    ledger = parent_run / "v2" / "ledger.jsonl"
    lines = ledger.read_bytes().splitlines()
    assert len(lines) > 2
    ledger.write_bytes(b"\n".join(lines[:-2]) + b"\n")

    with pytest.raises(Protocol24AdoptionError, match="partial|disagree|cover"):
        validate_parent_for_deepening(parent_run, tmp_path)


def test_workspace_validation_requires_clean_exact_parent_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.email", "test@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name", "RE Test"],
        check=True,
    )
    source = workspace / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "source.py"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-qm", "initial"],
        check=True,
    )
    home = tmp_path / "echelon-home"
    home.mkdir()
    monkeypatch.setenv("ECHELON_HOME", str(home))
    snapshot = capture_workspace_snapshot(
        workspace,
        (SimpleNamespace(id="api", path=".", git_role="primary"),),
        home / "re-v2" / "snapshots",
    )
    base_manifest, _inputs = _fixture({"api": ("src",)}, goal="inventory")
    manifest = replace(base_manifest, source_snapshot_id=snapshot.snapshot_id)

    adoption_module._validate_workspace_sources(workspace, manifest)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(Protocol24AdoptionError, match="Commit|stash|revert"):
        adoption_module._validate_workspace_sources(workspace, manifest)

    subprocess.run(["git", "-C", str(workspace), "checkout", "--", "source.py"], check=True)
    source.write_text("VALUE = 3\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "source.py"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-qm", "new commit"],
        check=True,
    )
    with pytest.raises(Protocol24AdoptionError, match="commits do not match"):
        adoption_module._validate_workspace_sources(workspace, manifest)


def test_schema3_lineage_cycle_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_hash = digest("first-bundle")
    second_hash = digest("second-bundle")
    artifact = AdoptedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest("key"),
        artifact_hash=digest("artifact"),
        dependency_hashes=(),
        certification_receipt_id=digest("certification"),
        candidate_assessment_id=None,
        artifact_acceptance_receipt_id=digest("acceptance"),
        source_run_id="re-root",
        source_ledger_entry_hash=digest("ledger-entry"),
    )

    def bundle(run_id: str, ancestor: str) -> ParentAuthorityBundleV1:
        return ParentAuthorityBundleV1(
            schema_version=1,
            direct_parent_run_id=run_id,
            source_manifest_hash=digest(f"{run_id}-manifest"),
            source_event_chain_hash=digest(f"{run_id}-events"),
            source_terminal_event_hash=digest(f"{run_id}-terminal"),
            source_ledger_chain_hash=digest(f"{run_id}-ledger"),
            lineage_root_run_id="re-root",
            ancestor_bundle_hashes=(ancestor,),
            artifacts=(artifact,),
        )

    payloads = {
        first_hash: canonical_json_bytes(bundle("re-first", second_hash).to_json_dict()),
        second_hash: canonical_json_bytes(bundle("re-second", first_hash).to_json_dict()),
    }

    class _Objects:
        def __init__(self, _root: Path) -> None:
            pass

        def read_blob(self, object_hash: str) -> bytes:
            return payloads[object_hash]

    monkeypatch.setattr(adoption_module, "ObjectStore", _Objects)
    manifest = replace(
        manifest_v3(),
        parent_authority_bundle=CatalogReferenceV1(
            first_hash,
            "parent-authority.json",
        ),
    )

    with pytest.raises(Protocol24AdoptionError, match="cycle"):
        adoption_module._validate_schema3_lineage(
            SimpleNamespace(objects=tmp_path),
            manifest,
        )

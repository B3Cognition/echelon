from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_27.model import (
    PartialSourceAcceptanceV1,
    RunManifestV6,
)
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_27_fixtures import (
    digest,
    synthesis_budget_policy_v1,
)


def _completed_protocol_27_parent(tmp_path: Path) -> tuple[Path, RunManifestV6]:
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis
    from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
    from tests.unit.test_re_v2_protocol_27_publication import _completed_context

    context = _completed_context(tmp_path, run_id="re-parent")
    run_dir = context.paths.root.parent
    run_protocol_27_synthesis(
        run_dir,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    )
    return run_dir, context.inputs.manifest


@pytest.mark.unit
def test_v2_synthesis_requires_every_partial_source_explicitly(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.authority import (
        Protocol27AuthorityError,
        resolve_synthesis_parent,
    )

    parent, _manifest = _completed_protocol_27_parent(tmp_path)

    with pytest.raises(Protocol27AuthorityError, match="missing partial acceptance: web"):
        resolve_synthesis_parent(tmp_path, parent.name, ())


@pytest.mark.unit
def test_v2_synthesis_rejects_acceptance_for_complete_source(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.authority import (
        Protocol27AuthorityError,
        resolve_synthesis_parent,
    )

    parent, _manifest = _completed_protocol_27_parent(tmp_path)

    with pytest.raises(Protocol27AuthorityError, match="complete source.*api"):
        resolve_synthesis_parent(tmp_path, parent.name, ("api", "web"))


@pytest.mark.unit
def test_terminal_protocol_27_parent_reuses_embedded_source_authority(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent

    parent, manifest = _completed_protocol_27_parent(tmp_path)

    resolved = resolve_synthesis_parent(tmp_path, parent.name, ("web",))

    assert resolved.accepted_sources == manifest.accepted_sources
    assert resolved.parent_manifest_hash == manifest.run_manifest_id
    assert set(resolved.authority_objects) >= {
        source.source_root_hash for source in manifest.accepted_sources
    }


@pytest.mark.unit
def test_partial_acceptance_binds_exact_request_identity(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
    from harness.re_v2.protocol_27.lifecycle import (
        partial_acceptances_for,
        synthesis_request,
    )

    parent_path, _manifest = _completed_protocol_27_parent(tmp_path)
    parent = resolve_synthesis_parent(tmp_path, parent_path.name, ("web",))
    budget = synthesis_budget_policy_v1()
    request = synthesis_request(
        parent,
        budget,
        expected_v2_index_hash=digest("v2-index"),
        expected_compatibility_generation=3,
    )

    receipts = partial_acceptances_for(parent, request)

    assert len(receipts) == 1
    receipt = receipts[0]
    assert isinstance(receipt, PartialSourceAcceptanceV1)
    assert receipt.source_id == "web"
    assert receipt.operation_id == request.request_id
    assert receipt.debt_manifest_hash == parent.accepted_sources[1].debt_manifest_hash


@pytest.mark.unit
def test_exact_request_identity_is_stable_and_budget_sensitive(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
    from harness.re_v2.protocol_27.lifecycle import synthesis_request

    parent_path, _manifest = _completed_protocol_27_parent(tmp_path)
    parent = resolve_synthesis_parent(tmp_path, parent_path.name, ("web",))

    def request(token_limit: int):
        return synthesis_request(
            parent,
            synthesis_budget_policy_v1(token_limit=token_limit),
            expected_v2_index_hash=digest("v2-index"),
            expected_compatibility_generation=3,
        )

    first = request(400_000)

    assert request(400_000).request_id == first.request_id
    assert request(500_000).request_id != first.request_id


@pytest.mark.unit
def test_find_exact_child_ignores_wrong_request_and_rejects_collisions(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.authority import Protocol27AuthorityError
    from harness.re_v2.protocol_27.lifecycle import find_exact_protocol_27_child

    _parent, manifest = _completed_protocol_27_parent(tmp_path)
    child = tmp_path / "runs" / "re-child"
    child_paths = ReV2Paths.for_run(child)
    child_paths.root.mkdir(parents=True)
    child_request_id = digest("child-request")
    child_manifest = replace(
        manifest,
        run_id=child.name,
        request_id=child_request_id,
        partial_acceptances=tuple(
            replace(receipt, operation_id=child_request_id)
            for receipt in manifest.partial_acceptances
        ),
    )
    child_paths.manifest.write_bytes(canonical_json_bytes(child_manifest.to_json_dict()))

    assert find_exact_protocol_27_child(tmp_path, child_manifest.request_id) == child
    assert find_exact_protocol_27_child(tmp_path, digest("other-request")) is None

    duplicate = tmp_path / "runs" / "re-child-duplicate"
    duplicate_paths = ReV2Paths.for_run(duplicate)
    duplicate_paths.root.mkdir(parents=True)
    duplicate_manifest = replace(child_manifest, run_id=duplicate.name)
    duplicate_paths.manifest.write_bytes(canonical_json_bytes(duplicate_manifest.to_json_dict()))
    with pytest.raises(Protocol27AuthorityError, match="multiple protocol-2.7 children"):
        find_exact_protocol_27_child(tmp_path, child_manifest.request_id)


@pytest.mark.unit
def test_completed_protocol_26_parent_freezes_overviews_without_live_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_27.authority import (
        freeze_accepted_source_overviews,
        frozen_overview_payloads,
        resolve_synthesis_parent,
    )
    from tests.support.re_v2_layered_workspace import build_and_commit_fixture

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    with fixture.provider:
        created = CliRunner().invoke(app, ["re", "run", "--engine", "v2"])
    assert created.exit_code == 0, created.output
    parent_path = fixture.run_directories()[-1]

    # Only the frozen snapshot/run authority remains available to the resolver.
    shutil.rmtree(fixture.root / "sources")
    parent = resolve_synthesis_parent(fixture.root, parent_path.name, ())
    catalog = freeze_accepted_source_overviews(parent)
    payloads = frozen_overview_payloads(parent)

    assert tuple(item.source_id for item in catalog.projections) == ("api", "web")
    assert set(payloads) == {item.object_hash for item in catalog.projections}
    assert all(payloads[item.object_hash] for item in catalog.projections)


@pytest.mark.unit
def test_targeted_l2_parent_selects_highest_accepted_layer_per_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_27.authority import (
        freeze_accepted_source_overviews,
        resolve_synthesis_parent,
    )
    from tests.support.re_v2_layered_workspace import build_and_commit_fixture

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()
    with fixture.provider:
        l1_result = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert l1_result.exit_code == 0, l1_result.output
        l1 = fixture.run_directories()[-1]
        l2_result = runner.invoke(
            app,
            [
                "re",
                "deepen",
                "--to",
                "L2",
                "--source",
                "api",
                "--from-run",
                l1.name,
            ],
        )
    assert l2_result.exit_code == 0, l2_result.output
    l2 = fixture.run_directories()[-1]

    shutil.rmtree(fixture.root / "sources")
    parent = resolve_synthesis_parent(fixture.root, l2.name, ())
    catalog = freeze_accepted_source_overviews(parent)

    assert dict(parent.selected_layers) == {"api": "L2", "web": "L1"}
    assert {item.source_id: item.selected_layer for item in catalog.projections} == {
        "api": "L2",
        "web": "L1",
    }

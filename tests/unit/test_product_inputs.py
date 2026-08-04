"""Product-input resolution, provenance, and readiness tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

from harness.human_input import HumanInputPolicyRegistry


class _EmptyPolicyGraph:
    def human_input_policy_registry(self) -> HumanInputPolicyRegistry:
        return HumanInputPolicyRegistry(())


def test_requirement_folder_is_snapshotted_with_stable_catalog(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    product = project / "sources" / "PBS-E-45"
    product.mkdir(parents=True)
    (product / "feature.md").write_text(
        "# Connections\n\n- Show passer to receiver rows.\n",
        encoding="utf-8",
    )

    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("requirement:sources/PBS-E-45")],
    )

    manifest = json.loads(resolution.manifest_path.read_text(encoding="utf-8"))
    catalog = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))
    assert manifest["declarations"] == [{"id": "requirement-001", "role": "requirement", "location": "sources/PBS-E-45"}]
    assert [entry["status"] for entry in manifest["resources"]] == ["accepted"]
    assert (resolution.inputs_dir / "snapshots" / "requirement" / "requirement-001" / "feature.md").is_file()
    assert len(catalog["units"]) == 2
    assert all(unit["id"].startswith("IN-REQ-") for unit in catalog["units"])
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"] == [{
        "disposition": "open_question",
        "input_unit_id": catalog["units"][1]["id"],
        "rationale": "Awaiting specification analysis.",
        "spec_ids": [],
        "task_ids": [],
        "targets": [],
    }]


def test_requirement_pdf_revision_creates_page_traceability_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import (
        parse_input_declaration,
        resolve_product_input_revision,
    )

    project = tmp_path / "workspace"
    source = project / "sources" / "PBS-E-73.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-placeholder")
    base_inputs = project / "specs" / "004-demo" / "inputs"
    base_inputs.mkdir(parents=True)
    (base_inputs / "manifest.json").write_text('{"base": true}\n', encoding="utf-8")
    monkeypatch.setattr(
        "echelon.product_inputs._extract_pdf_pages",
        lambda _path: ["Requirement one", "Requirement two"],
    )

    resolution = resolve_product_input_revision(
        project,
        project / "specs" / "004-demo" / "amendments" / "001" / "inputs",
        [parse_input_declaration("requirement:sources/PBS-E-73.pdf")],
    )

    catalog = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"]
    assert [unit["statement"] for unit in catalog] == ["Requirement one", "Requirement two"]
    assert [unit["source_locator"] for unit in catalog] == [
        "sources/PBS-E-73.pdf:page:1",
        "sources/PBS-E-73.pdf:page:2",
    ]
    assert all(unit["id"].startswith("IN-REQ-") for unit in catalog)
    assert (base_inputs / "manifest.json").read_text(encoding="utf-8") == '{"base": true}\n'


def test_product_input_attachment_appends_revision_and_rebuilds_aggregate(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        attach_product_input_revision,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    base_source = project / "sources" / "base"
    added_source = project / "sources" / "DE-OPTA-SCHEMA-MAPPING"
    base_source.mkdir(parents=True)
    added_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("Initial requirement\n", encoding="utf-8")
    (added_source / "mapping.csv").write_text(
        "filter_id,table_name,column_name\nPBS-E-57,events,player_id\n",
        encoding="utf-8",
    )
    run_dir = project / "runs" / "run-1"
    base = resolve_product_inputs(
        project,
        run_dir,
        [parse_input_declaration("reference:sources/base")],
    )
    original_snapshot = (
        base.inputs_dir / "snapshots" / "reference" / "reference-001" / "brief.md"
    ).read_bytes()

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/DE-OPTA-SCHEMA-MAPPING")],
        command="echelon spec add-input",
        evidence_requests={"requests": [{"id": "ER-001", "question": "Need mapping"}]},
    )

    assert result.added
    assert result.attachment_id == "001"
    assert (base.inputs_dir / "attachments" / "001" / "manifest.json").is_file()
    assert (
        base.inputs_dir / "snapshots" / "reference" / "reference-001" / "brief.md"
    ).read_bytes() == original_snapshot
    aggregate_manifest = json.loads((base.inputs_dir / "manifest.json").read_text(encoding="utf-8"))
    accepted = [item for item in aggregate_manifest["resources"] if item.get("status") == "accepted"]
    assert any(item["source_locator"].endswith("sources/base/brief.md") for item in accepted)
    assert any(
        item["source_locator"].endswith("sources/DE-OPTA-SCHEMA-MAPPING/mapping.csv")
        for item in accepted
    )
    ledger = json.loads((base.inputs_dir / "attachment-ledger.json").read_text(encoding="utf-8"))
    assert ledger["attachments"][0]["id"] == "001"
    assert ledger["attachments"][0]["command"] == "echelon spec add-input"
    assert ledger["attachments"][0]["linked_evidence_request_ids"] == ["ER-001"]


def test_product_input_attachment_all_duplicate_source_is_idempotent(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        attach_product_input_revision,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    source = project / "sources" / "base"
    source.mkdir(parents=True)
    (source / "brief.md").write_text("Same evidence\n", encoding="utf-8")
    base = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("reference:sources/base")],
    )
    before = (base.inputs_dir / "manifest.json").read_text(encoding="utf-8")

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/base")],
        command="echelon spec add-input",
    )

    assert not result.added
    assert result.duplicates
    assert not (base.inputs_dir / "attachments" / "001").exists()
    assert (base.inputs_dir / "manifest.json").read_text(encoding="utf-8") == before


def test_product_input_attachment_duplicate_content_is_reported_without_duplicate_catalog_unit(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import (
        attach_product_input_revision,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    first = project / "sources" / "first"
    second = project / "sources" / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "a.md").write_text("Same evidence\n", encoding="utf-8")
    (second / "b.md").write_text("Same evidence\n", encoding="utf-8")
    base = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("reference:sources/first")],
    )

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/second")],
        command="echelon spec add-input",
    )

    assert not result.added
    assert result.duplicates[0]["reason"] == "duplicate content"
    catalog = json.loads((base.inputs_dir / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["units"]) == 1


def test_clone_product_input_contract_copies_complete_package_and_rebases_pointers(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import (
        attach_product_input_revision,
        clone_product_input_contract,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    baseline_run = project / "runs" / "squad-base"
    (baseline_run / "specs" / "001-demo").mkdir(parents=True)
    base_source = project / "sources" / "base"
    added_source = project / "sources" / "added"
    base_source.mkdir(parents=True)
    added_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("Original requirement\n", encoding="utf-8")
    (added_source / "diagram.svg").write_text("<svg>attachment</svg>\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        baseline_run,
        [parse_input_declaration("requirement:sources/base")],
    )
    attachment = attach_product_input_revision(
        project,
        resolution.inputs_dir,
        [parse_input_declaration("reference:sources/added")],
        command="echelon spec add-input",
    )
    product_inputs = attachment.state_product_inputs(
        project,
        resolution.state_payload(project),
    )
    source_state = {
        "spec_dir": "runs/squad-base/specs/001-demo",
        "product_inputs": product_inputs,
    }
    source_files = {
        path.relative_to(resolution.inputs_dir).as_posix(): path.read_bytes()
        for path in resolution.inputs_dir.rglob("*")
        if path.is_file()
    }

    cloned = clone_product_input_contract(
        project,
        source_state,
        project / "runs" / "squad-retarget",
    )

    destination = project / "runs" / "squad-retarget" / "inputs"
    cloned_files = {
        path.relative_to(destination).as_posix(): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert cloned_files == source_files
    assert "attachments/001/manifest.json" in cloned_files
    assert cloned["inputs_dir"] == "runs/squad-retarget/inputs"
    assert cloned["manifest"] == "runs/squad-retarget/inputs/manifest.json"
    assert cloned["traceability"] == "runs/squad-retarget/inputs/traceability.json"
    assert cloned["declarations"] == product_inputs["declarations"]


def _clone_product_input_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    baseline_run = project / "runs" / "squad-base"
    (baseline_run / "specs" / "001-demo").mkdir(parents=True)
    source = project / "requirements.md"
    source.write_text("Immutable requirement\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        baseline_run,
        [parse_input_declaration("requirement:requirements.md")],
    )
    state: dict[str, object] = {
        "spec_dir": "runs/squad-base/specs/001-demo",
        "product_inputs": resolution.state_payload(project),
    }
    return project, baseline_run, state


def test_clone_product_input_contract_rejects_wrong_in_package_pointer(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, _baseline_run, state = _clone_product_input_fixture(tmp_path)
    product_inputs = dict(state["product_inputs"])
    product_inputs["catalog"] = product_inputs["manifest"]
    state["product_inputs"] = product_inputs

    with pytest.raises(ProductInputError, match="catalog pointer"):
        clone_product_input_contract(
            project,
            state,
            project / "runs" / "squad-retarget",
        )


def test_clone_product_input_contract_rejects_symlinks_and_nonregular_files(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    package = baseline_run / "inputs"
    (package / "escape-link").symlink_to(project / "requirements.md")

    with pytest.raises(ProductInputError, match="symlink"):
        clone_product_input_contract(
            project,
            state,
            project / "runs" / "squad-retarget",
        )

    (package / "escape-link").unlink()
    fifo = package / "named-pipe"
    os.mkfifo(fifo)
    with pytest.raises(ProductInputError, match="regular file"):
        clone_product_input_contract(
            project,
            state,
            project / "runs" / "squad-retarget",
        )


def test_clone_product_input_contract_rejects_outside_baseline_package_and_pointer(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    outside = project / "outside-inputs"
    shutil.copytree(baseline_run / "inputs", outside)
    outside_state = json.loads(json.dumps(state))
    outside_inputs = outside_state["product_inputs"]
    assert isinstance(outside_inputs, dict)
    outside_inputs["inputs_dir"] = "outside-inputs"
    for key in (
        "manifest",
        "catalog",
        "input_context",
        "requirement_context",
        "reference_context",
        "traceability",
        "traceability_markdown",
    ):
        outside_inputs[key] = f"outside-inputs/{Path(str(outside_inputs[key])).name}"

    with pytest.raises(ProductInputError, match="outside the baseline run"):
        clone_product_input_contract(
            project,
            outside_state,
            project / "runs" / "squad-retarget-outside",
        )

    pointer_state = json.loads(json.dumps(state))
    pointer_inputs = pointer_state["product_inputs"]
    assert isinstance(pointer_inputs, dict)
    pointer_inputs["catalog"] = "requirements.md"
    with pytest.raises(ProductInputError, match="catalog pointer"):
        clone_product_input_contract(
            project,
            pointer_state,
            project / "runs" / "squad-retarget-pointer",
        )


def test_clone_product_input_contract_binds_source_to_verified_baseline_run(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    other_run = project / "runs" / "squad-other"
    (other_run / "specs" / "999-other").mkdir(parents=True)
    shutil.copytree(baseline_run / "inputs", other_run / "inputs")
    forged = json.loads(json.dumps(state))
    forged["spec_dir"] = "runs/squad-other/specs/999-other"
    forged_inputs = forged["product_inputs"]
    assert isinstance(forged_inputs, dict)
    for key, value in tuple(forged_inputs.items()):
        if key == "inputs_dir":
            forged_inputs[key] = "runs/squad-other/inputs"
        elif key in {
            "manifest",
            "catalog",
            "input_context",
            "requirement_context",
            "reference_context",
            "traceability",
            "traceability_markdown",
        }:
            forged_inputs[key] = f"runs/squad-other/inputs/{Path(str(value)).name}"

    with pytest.raises(ProductInputError, match="verified baseline run"):
        clone_product_input_contract(
            project,
            forged,
            project / "runs" / "squad-retarget-forged",
            baseline_run_dir=baseline_run,
        )


def test_clone_product_input_contract_rejects_manifest_and_snapshot_hash_drift(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    manifest_state = json.loads(json.dumps(state))
    manifest_inputs = manifest_state["product_inputs"]
    assert isinstance(manifest_inputs, dict)
    manifest_inputs["manifest_hash"] = "0" * 64
    with pytest.raises(ProductInputError, match="manifest hash drift"):
        clone_product_input_contract(
            project,
            manifest_state,
            project / "runs" / "squad-retarget-manifest",
        )

    manifest = json.loads((baseline_run / "inputs" / "manifest.json").read_text())
    snapshot = baseline_run / "inputs" / manifest["resources"][0]["snapshot"]
    snapshot.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ProductInputError, match="snapshot hash drift"):
        clone_product_input_contract(
            project,
            state,
            project / "runs" / "squad-retarget-snapshot",
        )


def test_clone_product_input_contract_refuses_collision_and_cleans_failed_copy_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, _baseline_run, state = _clone_product_input_fixture(tmp_path)
    collision_run = project / "runs" / "squad-retarget-collision"
    (collision_run / "inputs").mkdir(parents=True)
    with pytest.raises(ProductInputError, match="already exists"):
        clone_product_input_contract(project, state, collision_run)

    retry_run = project / "runs" / "squad-retarget-retry"
    original_copy2 = shutil.copy2
    calls = 0

    def fail_once(source: object, destination: object, *args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected copy failure")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr("echelon.product_inputs.shutil.copy2", fail_once)
    with pytest.raises(OSError, match="injected copy failure"):
        clone_product_input_contract(project, state, retry_run)
    assert not (retry_run / "inputs").exists()
    assert not list(retry_run.glob(".inputs-clone-*"))

    monkeypatch.setattr("echelon.product_inputs.shutil.copy2", original_copy2)
    cloned = clone_product_input_contract(project, state, retry_run)
    assert cloned["inputs_dir"] == "runs/squad-retarget-retry/inputs"


def test_clone_product_input_contract_rejects_symlinked_replacement_run(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, _baseline_run, state = _clone_product_input_fixture(tmp_path)
    actual_run = project / "runs" / "unexpected-run"
    actual_run.mkdir(parents=True)
    replacement_run = project / "runs" / "squad-retarget-symlink"
    replacement_run.symlink_to(actual_run, target_is_directory=True)

    with pytest.raises(ProductInputError, match="replacement run directory"):
        clone_product_input_contract(project, state, replacement_run)

    assert not (actual_run / "inputs").exists()


def test_cloned_product_input_contract_authenticates_every_package_byte(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import (
        ProductInputError,
        clone_product_input_contract,
        validate_immutable_product_input_package,
    )

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    (baseline_run / "inputs" / "unindexed.bin").write_bytes(b"unindexed baseline bytes")
    attachment = baseline_run / "inputs/attachments/001/manifest.json"
    attachment.parent.mkdir(parents=True)
    attachment.write_text('{"attachment": true}\n', encoding="utf-8")
    replacement_run = project / "runs/squad-retarget-tree"
    cloned = clone_product_input_contract(project, state, replacement_run)
    assert cloned["tree_hash"].startswith("sha256:")

    for relative in (
        "catalog.json",
        "traceability.json",
        "unindexed.bin",
        "attachments/001/manifest.json",
    ):
        path = replacement_run / "inputs" / relative
        original = path.read_bytes()
        path.write_bytes(original + b"tamper")
        with pytest.raises(ProductInputError, match="tree hash drift"):
            validate_immutable_product_input_package(replacement_run / "inputs", cloned)
        path.write_bytes(original)

    manifest = replacement_run / "inputs/manifest.json"
    original_mode = manifest.stat().st_mode
    manifest.chmod(original_mode ^ 0o100)
    with pytest.raises(ProductInputError, match="tree hash drift"):
        validate_immutable_product_input_package(replacement_run / "inputs", cloned)


def test_clone_product_input_contract_rejects_hardlinked_file(tmp_path: Path) -> None:
    from echelon.product_inputs import ProductInputError, clone_product_input_contract

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    source = baseline_run / "inputs/manifest.json"
    os.link(source, baseline_run / "inputs/hardlink.json")
    with pytest.raises(ProductInputError, match="hardlink"):
        clone_product_input_contract(project, state, project / "runs/squad-retarget-hardlink")


@pytest.mark.parametrize("mutation", ["bytes", "path_swap"])
def test_clone_product_input_contract_rejects_source_mutation_during_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    import echelon.product_inputs as product_inputs

    project, baseline_run, state = _clone_product_input_fixture(tmp_path)
    victim = baseline_run / "inputs/unindexed.bin"
    victim.write_bytes(b"baseline")
    outside = project / "outside.bin"
    outside.write_bytes(b"outside")
    original_copy = shutil.copy2
    mutated = False

    def mutate_after_copy(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ):
        nonlocal mutated
        result = original_copy(source, destination, *args, **kwargs)
        if not mutated:
            mutated = True
            if mutation == "bytes":
                victim.write_bytes(b"changed during copy")
            else:
                victim.unlink()
                victim.symlink_to(outside)
        return result

    monkeypatch.setattr(product_inputs.shutil, "copy2", mutate_after_copy)
    replacement = project / f"runs/squad-retarget-mutation-{mutation}"
    with pytest.raises(product_inputs.ProductInputError, match="mutated|symlink"):
        product_inputs.clone_product_input_contract(project, state, replacement)

    assert not (replacement / "inputs").exists()


def test_product_input_revision_refuses_to_replace_existing_evidence(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        ProductInputError,
        parse_input_declaration,
        resolve_product_input_revision,
    )

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("Requirement\n", encoding="utf-8")
    destination = project / "specs" / "004-demo" / "amendments" / "001" / "inputs"
    destination.mkdir(parents=True)

    with pytest.raises(ProductInputError, match="already exists"):
        resolve_product_input_revision(
            project,
            destination,
            [parse_input_declaration("requirement:requirements.md")],
        )


def test_requirement_pdf_without_extractable_text_blocks_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import (
        ProductInputError,
        parse_input_declaration,
        resolve_product_input_revision,
    )

    project = tmp_path / "workspace"
    source = project / "requirements.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr("echelon.product_inputs._extract_pdf_pages", lambda _path: [])

    with pytest.raises(ProductInputError, match="no extractable text"):
        resolve_product_input_revision(
            project,
            project / "revision-inputs",
            [parse_input_declaration("requirement:requirements.pdf")],
        )


def test_requirement_pdf_uses_pypdf_when_poppler_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import _extract_pdf_pages

    source = tmp_path / "requirements.pdf"
    source.write_bytes(b"%PDF-placeholder")

    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _Reader:
        def __init__(self, _path: Path) -> None:
            self.pages = [_Page("Requirement one"), _Page("Requirement two")]

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = _Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    def _missing_poppler(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr("echelon.product_inputs.subprocess.run", _missing_poppler)

    assert _extract_pdf_pages(source) == ["Requirement one", "Requirement two"]


def test_requirement_pdf_prefers_pypdf_over_poppler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import _extract_pdf_pages

    source = tmp_path / "requirements.pdf"
    source.write_bytes(b"%PDF-placeholder")

    class _Page:
        def extract_text(self) -> str:
            return "pypdf requirement"

    class _Reader:
        def __init__(self, _path: Path) -> None:
            self.pages = [_Page()]

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = _Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    def _poppler_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pypdf must be attempted before pdftotext")

    monkeypatch.setattr("echelon.product_inputs.subprocess.run", _poppler_must_not_run)

    assert _extract_pdf_pages(source) == ["pypdf requirement"]


def test_requirement_pdf_falls_back_to_poppler_when_pypdf_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.product_inputs import _extract_pdf_pages

    source = tmp_path / "requirements.pdf"
    source.write_bytes(b"%PDF-placeholder")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    monkeypatch.setattr(
        "echelon.product_inputs.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Poppler requirement\f", stderr=""
        ),
    )

    assert _extract_pdf_pages(source) == ["Poppler requirement"]


def test_requirement_catalog_keeps_markdown_scaffolding_as_context_only(tmp_path: Path) -> None:
    """Headings and table syntax inform agents but must not require traceability."""
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Transform reference\n\n"
        "**Available transforms**\n\n"
        "| Transform | Meaning |\n"
        "| --- | --- |\n"
        "| Standard | Raw total |\n",
        encoding="utf-8",
    )

    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("requirement:requirements.md")],
    )

    catalog = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"]
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))

    assert len(catalog) == 5
    assert [unit["traceability_required"] for unit in catalog] == [False, False, False, False, True]
    assert [entry["input_unit_id"] for entry in ledger["requirements"]] == [catalog[-1]["id"]]
    requirement_context = resolution.requirement_context_path.read_text(encoding="utf-8")
    assert all(unit["id"] not in requirement_context for unit in catalog[:-1])
    assert catalog[-1]["id"] in requirement_context


def test_structural_input_repair_updates_legacy_traceability_ledger(tmp_path: Path) -> None:
    from echelon.product_inputs import repair_product_input_structural_units

    catalog_path = tmp_path / "catalog.json"
    traceability_path = tmp_path / "traceability.json"
    catalog_path.write_text(json.dumps({"units": [
        {"id": "IN-REQ-1", "role": "requirement", "statement": "# Reference"},
        {"id": "IN-REQ-2", "role": "requirement", "statement": "| Name | Meaning |"},
        {"id": "IN-REQ-3", "role": "requirement", "statement": "| --- | --- |"},
        {"id": "IN-REQ-4", "role": "requirement", "statement": "| Standard | Raw total |"},
    ]}), encoding="utf-8")
    traceability_path.write_text(json.dumps({"requirements": [
        {"input_unit_id": f"IN-REQ-{index}", "disposition": "open_question", "rationale": "old", "spec_ids": [], "task_ids": [], "targets": []}
        for index in range(1, 5)
    ]}), encoding="utf-8")

    repaired = repair_product_input_structural_units(traceability_path, catalog_path, apply=True)
    ledger = json.loads(traceability_path.read_text(encoding="utf-8"))

    assert repaired == ("IN-REQ-1", "IN-REQ-2", "IN-REQ-3")
    assert [entry["disposition"] for entry in ledger["requirements"]] == ["excluded", "excluded", "excluded", "open_question"]


def test_context_only_catalog_unit_cannot_carry_a_requirement_mapping(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        ProductInputError,
        normalize_context_only_product_input_updates,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Context only\n\nA normative requirement.\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("requirement:requirements.md")],
    )
    context_only_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]

    with pytest.raises(ProductInputError, match="context-only catalog unit is not traceable"):
        normalize_context_only_product_input_updates(
            [{
                "input_unit_id": context_only_id,
                "disposition": "included",
                "rationale": "Incorrectly treated as a requirement.",
                "spec_ids": ["FR-001"],
                "task_ids": [],
                "targets": [],
            }],
            resolution.catalog_path,
        )


def test_secret_and_hidden_files_are_recorded_but_never_snapshotted(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    product = project / "sources" / "provision"
    product.mkdir(parents=True)
    (product / "spec.md").write_text("# Reference\n", encoding="utf-8")
    (product / "provision.env").write_text("PASSWORD=do-not-copy\n", encoding="utf-8")
    (product / ".DS_Store").write_bytes(b"metadata")

    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("reference:sources/provision")],
    )

    manifest_text = resolution.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    excluded = {entry["source_locator"]: entry for entry in manifest["resources"] if entry["status"] == "excluded"}
    assert excluded["sources/provision/provision.env"]["reason"] == "secret-like filename"
    assert excluded["sources/provision/.DS_Store"]["reason"] == "hidden OS metadata"
    assert "do-not-copy" not in manifest_text
    assert not (resolution.inputs_dir / "snapshots" / "reference" / "reference-001" / "provision.env").exists()


def test_unsupported_file_and_escaping_symlink_block_preflight(tmp_path: Path) -> None:
    from echelon.product_inputs import ProductInputError, parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    product = project / "input"
    product.mkdir(parents=True)
    (product / "recording.mov").write_bytes(b"not supported")

    with pytest.raises(ProductInputError, match="unsupported input file.*recording.mov"):
        resolve_product_inputs(project, project / "runs/run-1", [parse_input_declaration("requirement:input")])

    (product / "recording.mov").unlink()
    external = tmp_path / "external.md"
    external.write_text("outside", encoding="utf-8")
    (product / "escape.md").symlink_to(external)
    with pytest.raises(ProductInputError, match="escapes declared input root"):
        resolve_product_inputs(project, project / "runs/run-1", [parse_input_declaration("requirement:input")])


def test_figma_bundle_is_accepted_and_url_requires_connector(tmp_path: Path) -> None:
    from echelon.product_inputs import ProductInputError, parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    bundle = project / "design"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"format":"figma-export"}\n', encoding="utf-8")
    (bundle / "design.json").write_text('{"document":{"id":"0:1"}}\n', encoding="utf-8")
    (bundle / "frame.png").write_bytes(b"png")

    result = resolve_product_inputs(project, project / "runs/run-1", [parse_input_declaration("requirement:design")])
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert {entry["media_type"] for entry in manifest["resources"] if entry["status"] == "accepted"} == {
        "application/json", "image/png"
    }
    with pytest.raises(ProductInputError, match="offline Figma evidence bundle"):
        resolve_product_inputs(project, project / "runs/run-2", [parse_input_declaration("requirement:https://www.figma.com/file/abc")])


def test_figma_url_uses_environment_token_without_publishing_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"document":{"id":"0:1"}}'

    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout: int):
        captured["token"] = request.get_header("X-figma-token")
        assert timeout == 30
        return Response()

    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "figma-secret-token")
    monkeypatch.setattr("echelon.product_inputs.urlopen", fake_urlopen)
    result = resolve_product_inputs(
        tmp_path,
        tmp_path / "runs/run-1",
        [parse_input_declaration("requirement:https://www.figma.com/design/abc/Player-connections")],
    )

    assert captured["token"] == "figma-secret-token"
    assert "figma-secret-token" not in result.manifest_path.read_text(encoding="utf-8")
    assert any("figma.com/design/abc" in unit["source_locator"] for unit in json.loads(result.catalog_path.read_text())["units"])


def test_traceability_requires_target_owned_tasks(tmp_path: Path) -> None:
    from echelon.product_inputs import validate_product_input_traceability

    spec = tmp_path / "specs" / "001-demo"
    inputs = spec / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "traceability.json").write_text(
        json.dumps(
            {"requirements": [{"input_unit_id": "IN-REQ-1", "disposition": "included", "spec_ids": ["FR-1"], "task_ids": ["T-001"], "targets": ["sources/web"]}]}
        ),
        encoding="utf-8",
    )
    (spec / "tasks.md").write_text("- [ ] T-001 [target=sources/web] [req=FR-1] Build it\n", encoding="utf-8")

    assert validate_product_input_traceability(spec, ["sources/web"]) == []
    (spec / "tasks.md").write_text("- [ ] T-001 [req=FR-1] Build it\n", encoding="utf-8")
    assert validate_product_input_traceability(spec, ["sources/web"]) == [
        "IN-REQ-1: task T-001 is not target-owned by a declared implementation target"
    ]


def test_traceability_uses_canonical_task_rows_for_csv_requirements(tmp_path: Path) -> None:
    """Examples and later prose must not overwrite a canonical task's metadata."""
    from echelon.product_inputs import validate_product_input_traceability

    spec = tmp_path / "specs" / "001-demo"
    inputs = spec / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "traceability.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "input_unit_id": "IN-REQ-1",
                        "disposition": "included",
                        "spec_ids": ["FR-140", "FR-141"],
                        "task_ids": ["T-057"],
                        "targets": ["sources/web"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (spec / "tasks.md").write_text(
        """```markdown
- [ ] T-057 complexity=standard phase=download req=FR-140,FR-141 depends=none target=sources/web
```

- [ ] T-057 complexity=standard phase=download req=FR-140,FR-141 depends=none target=sources/web

T-057 is described above and must not be parsed as another task row.
""",
        encoding="utf-8",
    )

    assert validate_product_input_traceability(spec, ["sources/web"]) == []


def test_traceability_repair_prunes_contextual_task_ids_only_when_direct_mappings_remain(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import repair_product_input_traceability

    spec = tmp_path / "specs" / "001-demo"
    inputs = spec / "inputs"
    inputs.mkdir(parents=True)
    traceability_path = inputs / "traceability.json"
    traceability_path.write_text(
        json.dumps(
            {
                "requirements": [
                    {
                        "input_unit_id": "IN-REQ-1",
                        "disposition": "included",
                        "spec_ids": ["FR-1"],
                        "task_ids": ["T-001", "T-S01"],
                        "targets": ["sources/web"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tasks_path = spec / "tasks.md"
    tasks_path.write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-1 depends=none target=sources/web\n"
        "- [ ] T-S01 complexity=standard phase=foundation req=INFRA depends=none target=sources/web\n",
        encoding="utf-8",
    )

    preview = repair_product_input_traceability(
        traceability_path, tasks_path, ["sources/web"], apply=False
    )

    assert preview.removed == (("IN-REQ-1", "T-S01"),)
    assert preview.blockers == ()
    assert json.loads(traceability_path.read_text(encoding="utf-8"))["requirements"][0]["task_ids"] == [
        "T-001",
        "T-S01",
    ]

    applied = repair_product_input_traceability(
        traceability_path, tasks_path, ["sources/web"], apply=True
    )

    assert applied.removed == (("IN-REQ-1", "T-S01"),)
    assert json.loads(traceability_path.read_text(encoding="utf-8"))["requirements"][0]["task_ids"] == [
        "T-001"
    ]


def test_controller_applies_structured_traceability_updates(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        apply_product_input_updates,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("A normative requirement.\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("requirement:requirements.md")],
    )
    unit_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]

    apply_product_input_updates(
        resolution.traceability_path,
        [{
            "input_unit_id": unit_id,
            "disposition": "included",
            "rationale": "Captured by the product specification.",
            "spec_ids": ["FR-1"],
            "task_ids": ["T-001"],
            "targets": ["sources/web"],
        }],
    )

    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["disposition"] == "included"
    assert ledger["requirements"][0]["task_ids"] == ["T-001"]


def test_controller_ignores_empty_exclusions_for_context_only_catalog_units(tmp_path: Path) -> None:
    """A legacy prompt can name scaffolding, but it must not block the real mapping."""
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Context only\n\nA normative requirement.\n", encoding="utf-8")
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project,
        run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    catalog = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"]
    context_only_id = catalog[0]["id"]
    requirement_id = catalog[1]["id"]
    store = SquadStateStore(run_dir)
    store.initialize(
        "run-1",
        "greenfield",
        "demo",
        0,
        "phase1-what",
        product_inputs=resolution.state_payload(project),
    )
    controller = SquadController(
        object(),
        store,
        _EmptyPolicyGraph(),
        project / "ext",
        project,
        squad_dir=run_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        raw_output="",
        duration_ms=0,
        timed_out=False,
        echelon_result={
            "product_input_updates": [
                {
                    "input_unit_id": context_only_id,
                    "disposition": "excluded",
                    "rationale": "Markdown heading only.",
                    "spec_ids": [],
                    "task_ids": [],
                    "targets": [],
                },
                {
                    "input_unit_id": requirement_id,
                    "disposition": "included",
                    "rationale": "Captured by the feature specification.",
                    "spec_ids": ["FR-001"],
                    "task_ids": [],
                    "targets": [],
                },
            ]
        },
    )

    assert controller._apply_product_input_updates(
        result,
        "phase1-what",
        store.load(),
    ) is None
    refreshed_context = resolution.requirement_context_path.read_text(encoding="utf-8")
    assert context_only_id not in refreshed_context
    assert requirement_id in refreshed_context
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"] == [{
        "input_unit_id": requirement_id,
        "disposition": "included",
        "rationale": "Captured by the feature specification.",
        "spec_ids": ["FR-001"],
        "task_ids": [],
        "targets": [],
    }]


def test_discover_ignores_reference_traceability_updates(tmp_path: Path) -> None:
    """Discovery may use references as evidence but cannot mutate the requirement ledger."""
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    project = tmp_path / "workspace"
    source = project / "sources" / "docs.md"
    source.parent.mkdir(parents=True)
    source.write_text("https://api.example.test/openapi.json\n", encoding="utf-8")
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project,
        run_dir,
        [parse_input_declaration("reference:sources/docs.md")],
    )
    reference_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
    store = SquadStateStore(run_dir)
    store.initialize(
        "run-1",
        "greenfield",
        "demo",
        0,
        "phase1-discover",
        product_inputs=resolution.state_payload(project),
    )
    controller = SquadController(
        object(),
        store,
        _EmptyPolicyGraph(),
        project / "ext",
        project,
        squad_dir=run_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        raw_output="",
        duration_ms=0,
        timed_out=False,
        echelon_result={
            "product_input_updates": [{
                "input_unit_id": reference_id,
                "disposition": "included",
                "rationale": "Used as API documentation evidence during discovery.",
                "spec_ids": [],
                "task_ids": [],
                "targets": [],
            }],
        },
    )

    assert controller._apply_product_input_updates(result, "phase1-discover") is None
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"] == []
    assert ledger["references"] == [{
        "input_unit_id": reference_id,
        "state": "reviewed_unused",
        "rationale": "Awaiting analysis.",
    }]


def test_plan_updates_reject_contextual_task_ids_without_mutating_ledger(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        ProductInputError,
        apply_product_input_updates,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("A normative requirement.\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("requirement:requirements.md")],
    )
    unit_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
    tasks_path = project / "specs" / "001-demo" / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-1 depends=none target=sources/web\n"
        "- [ ] T-S01 complexity=standard phase=foundation req=INFRA depends=none target=sources/web\n",
        encoding="utf-8",
    )

    with pytest.raises(ProductInputError, match=rf"{unit_id}: task T-S01 does not reference"):
        apply_product_input_updates(
            resolution.traceability_path,
            [{
                "input_unit_id": unit_id,
                "disposition": "included",
                "rationale": "Mapped during planning.",
                "spec_ids": ["FR-1"],
                "task_ids": ["T-001", "T-S01"],
                "targets": ["sources/web"],
            }],
            tasks_path=tasks_path,
            declared_targets=["sources/web"],
        )

    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["disposition"] == "open_question"
    assert ledger["requirements"][0]["task_ids"] == []


def test_phase_plan_controller_rejects_bad_traceability_before_consensus(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("A normative requirement.\n", encoding="utf-8")
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project, run_dir, [parse_input_declaration("requirement:requirements.md")]
    )
    unit_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
    store = SquadStateStore(run_dir)
    store.initialize(
        "run-1", "greenfield", "demo", 0, "phase3-plan",
        implementation_targets=["sources/web"],
        product_inputs=resolution.state_payload(project),
    )
    spec = run_dir / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-1 depends=none target=sources/web\n"
        "- [ ] T-S01 complexity=standard phase=foundation req=INFRA depends=none target=sources/web\n",
        encoding="utf-8",
    )
    state = store.load()
    state["spec_dir"] = str(spec.relative_to(project))
    store.save(state)
    controller = SquadController(
        object(),
        store,
        _EmptyPolicyGraph(),
        project / "ext",
        project,
        squad_dir=run_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        raw_output="",
        duration_ms=0,
        timed_out=False,
        echelon_result={
            "product_input_updates": [{
                "input_unit_id": unit_id,
                "disposition": "included",
                "rationale": "Mapped during planning.",
                "spec_ids": ["FR-1"],
                "task_ids": ["T-001", "T-S01"],
                "targets": ["sources/web"],
            }]
        },
    )

    error = controller._apply_product_input_updates(
        result,
        "phase3-plan",
        store.load(),
    )

    assert error == f"invalid product input updates: {unit_id}: task T-S01 does not reference the mapped specification IDs"
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["disposition"] == "open_question"


def test_consensus_controller_validates_run_local_traceability_without_requiring_publication(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import (
        apply_product_input_updates,
        parse_input_declaration,
        resolve_product_inputs,
    )
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("A normative requirement.\n", encoding="utf-8")
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project, run_dir, [parse_input_declaration("requirement:requirements.md")]
    )
    unit_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
    spec = run_dir / "specs" / "001-demo"
    spec.mkdir(parents=True)
    tasks_path = spec / "tasks.md"
    tasks_path.write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-1 depends=none target=sources/web\n",
        encoding="utf-8",
    )
    apply_product_input_updates(
        resolution.traceability_path,
        [{
            "input_unit_id": unit_id,
            "disposition": "included",
            "rationale": "Mapped during planning.",
            "spec_ids": ["FR-1"],
            "task_ids": ["T-001"],
            "targets": ["sources/web"],
        }],
        tasks_path=tasks_path,
        declared_targets=["sources/web"],
    )
    store = SquadStateStore(run_dir)
    store.initialize(
        "run-1", "greenfield", "demo", 0, "phase3-consensus",
        implementation_targets=["sources/web"],
        product_inputs=resolution.state_payload(project),
    )
    state = store.load()
    state["spec_dir"] = str(spec.relative_to(project))
    store.save(state)
    controller = SquadController(
        object(),
        store,
        _EmptyPolicyGraph(),
        project / "ext",
        project,
        squad_dir=run_dir,
    )
    result = SquadAgentResult(
        exit_code=0, raw_output="", duration_ms=0, timed_out=False,
        echelon_result={"verdict": "PASS"},
    )

    assert controller._apply_product_input_updates(
        result,
        "phase3-consensus",
        store.load(),
    ) is None


def test_prompt_contract_uses_snapshot_paths_and_structured_updates() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/one/inputs/manifest.json",
            "catalog": "runs/one/inputs/catalog.json",
            "traceability": "runs/one/inputs/traceability.json",
            "requirement_context": "runs/one/inputs/requirement-context.md",
            "reference_context": "runs/one/inputs/reference-context.md",
        }
    })

    assert "PRODUCT_INPUT_MANIFEST=runs/one/inputs/manifest.json" in prompt
    assert "Requirement inputs are normative" in prompt
    assert "immutable snapshot paths" in prompt
    assert "product_input_updates" in prompt
    assert "input_unit_id: <traceable IN-REQ-* ID from PRODUCT_INPUT_TRACEABILITY>" in prompt
    assert "Catalog units absent from PRODUCT_INPUT_TRACEABILITY are context-only" in prompt
    assert "disposition: <included|excluded|duplicate|open_question|conflict>" in prompt
    assert "spec_ids: [FR-001, AC-001]" in prompt
    assert "task_ids: []" in prompt
    assert "targets: []" in prompt


def test_product_input_context_includes_controller_mapping_repair() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/one/inputs/manifest.json",
            "catalog": "runs/one/inputs/catalog.json",
            "traceability": "runs/one/inputs/traceability.json",
            "requirement_context": "runs/one/inputs/requirement-context.md",
            "reference_context": "runs/one/inputs/reference-context.md",
        },
        "product_input_mapping_repair": {
            "attempt": 1,
            "blockers": ["IN-REQ-1: unresolved disposition open_question"],
        },
    })

    assert "Product Input Mapping Repair" in prompt
    assert "IN-REQ-1: unresolved disposition open_question" in prompt
    assert "Do not return COMPLETE" in prompt


def test_product_input_context_renders_added_reference_material() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/run-1/inputs/manifest.json",
            "catalog": "runs/run-1/inputs/catalog.json",
            "traceability": "runs/run-1/inputs/traceability.json",
            "requirement_context": "runs/run-1/inputs/requirement-context.md",
            "reference_context": "runs/run-1/inputs/reference-context.md",
        },
        "product_input_attachments": [
            {
                "id": "001",
                "declarations": [
                    {
                        "role": "reference",
                        "location": "sources/DE-OPTA-SCHEMA-MAPPING",
                    }
                ],
                "resources": [
                    {
                        "snapshot": (
                            "attachments/001/snapshots/reference/"
                            "reference-001/mapping.csv"
                        )
                    }
                ],
                "linked_evidence_request_ids": ["ER-001"],
            }
        ],
        "evidence_requests": {
            "requests": [{"id": "ER-001", "question": "Need mapping"}]
        },
    })

    assert "## Added Reference Material" in prompt
    assert "sources/DE-OPTA-SCHEMA-MAPPING" in prompt
    assert "ER-001" in prompt
    assert "Preserve and extend prior investigation artifacts" in prompt


def test_product_input_context_makes_phase_one_id_repair_allowlist_explicit() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/one/inputs/manifest.json",
            "catalog": "runs/one/inputs/catalog.json",
            "traceability": "runs/one/inputs/traceability.json",
            "requirement_context": "runs/one/inputs/requirement-context.md",
            "reference_context": "runs/one/inputs/reference-context.md",
        },
        "product_input_mapping_repair": {
            "attempt": 1,
            "phase": "phase1-what",
            "blockers": ["product input update references unknown requirement unit 'IN-REQ-FILTER-GROUPS'"],
            "invalid_input_unit_ids": ["IN-REQ-FILTER-GROUPS"],
            "valid_requirement_ids": ["IN-REQ-CANONICAL"],
        },
    })

    assert "Invalid IDs from the prior result: IN-REQ-FILTER-GROUPS" in prompt
    assert "Only these canonical IDs may be used: IN-REQ-CANONICAL" in prompt
    assert "Never derive an ID from a requirement label" in prompt


def test_product_input_context_exposes_deterministic_mapping_worksheet() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/one/inputs/manifest.json",
            "catalog": "runs/one/inputs/catalog.json",
            "traceability": "runs/one/inputs/traceability.json",
            "requirement_context": "runs/one/inputs/requirement-context.md",
            "reference_context": "runs/one/inputs/reference-context.md",
        },
        "product_input_mapping_repair": {
            "attempt": 1,
            "blockers": ["IN-REQ-1: task T-002 does not reference the mapped specification IDs"],
            "candidates": [{
                "input_unit_id": "IN-REQ-1",
                "spec_ids": ["FR-001"],
                "direct_task_ids": ["T-001"],
                "invalid_task_ids": ["T-002"],
            }],
            "task_requirement_matrix": [
                {"task_id": "T-001", "requirements": ["FR-001"], "target": "sources/web"},
            ],
        },
    })

    assert "Deterministic Mapping Worksheet" in prompt
    assert "Direct task IDs=[T-001]" in prompt
    assert "Invalid task IDs=[T-002]" in prompt
    assert "T-001: req=[FR-001]; target=sources/web" in prompt


def test_product_input_mapping_repair_shows_candidate_direct_task_options(tmp_path: Path) -> None:
    from echelon.product_inputs import build_product_input_mapping_repair_hints

    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none target=sources/web\n"
        "- [ ] T-002 complexity=standard phase=build req=INFRA depends=none target=sources/web\n",
        encoding="utf-8",
    )

    hints = build_product_input_mapping_repair_hints(
        [
            {
                "input_unit_id": "IN-REQ-1",
                "spec_ids": ["FR-001"],
                "task_ids": ["T-001", "T-002"],
            }
        ],
        tasks_path,
        ["sources/web"],
    )

    assert hints["candidates"] == [{
        "input_unit_id": "IN-REQ-1",
        "spec_ids": ["FR-001"],
        "direct_task_ids": ["T-001"],
        "invalid_task_ids": ["T-002"],
    }]
    assert hints["task_requirement_matrix"] == [
        {"task_id": "T-001", "requirements": ["FR-001"], "target": "sources/web"},
        {"task_id": "T-002", "requirements": ["INFRA"], "target": "sources/web"},
    ]


def test_product_input_context_requires_tasks_lexicon_repair_before_completion() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/one/inputs/manifest.json",
            "catalog": "runs/one/inputs/catalog.json",
            "traceability": "runs/one/inputs/traceability.json",
            "requirement_context": "runs/one/inputs/requirement-context.md",
            "reference_context": "runs/one/inputs/reference-context.md",
        },
        "tasks_lexicon_pass": False,
        "tasks_lexicon_attempts": 1,
    })

    assert "Tasks Lexicon Repair" in prompt
    assert "controller-owned tasks validator" in prompt
    assert "Do not report tasks_lexicon_pass yourself" in prompt
    assert "tasks-lexicon-report.json" in prompt


def test_plan_phase_requires_direct_product_input_task_mappings() -> None:
    phase = (
        Path(__file__).parents[2]
        / "extension/workflow/phases/phase3-plan.md"
    ).read_text(encoding="utf-8")

    assert "directly intersect that unit's `spec_ids`" in phase
    assert "Do not mark a contextual or illustrative unit `included` with empty" in phase


def test_phase_a_publication_copies_evidence_only_after_traceability_is_ready(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        apply_product_input_updates,
        parse_input_declaration,
        resolve_product_inputs,
    )
    from harness.squad import SquadController
    from harness.squad_state import SquadStateStore

    class TerminalGraph(_EmptyPolicyGraph):
        def entry_phase(self) -> str:
            return "DONE"

        def all_phase_ids(self) -> set[str]:
            return {"DONE"}

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text("A normative requirement.\n", encoding="utf-8")
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project, run_dir, [parse_input_declaration("requirement:requirements.md")]
    )
    unit_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
    store = SquadStateStore(run_dir)
    store.initialize("run-1", "greenfield", "demo", 0, "DONE", implementation_targets=["sources/web"], product_inputs=resolution.state_payload(project))
    controller = SquadController(object(), store, TerminalGraph(), project / "ext", project, squad_dir=run_dir)
    spec = project / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [ ] T-001 [target=sources/web] [req=FR-1] Build it\n", encoding="utf-8")

    assert controller._publish_product_input_evidence(spec, store.load()) == [
        f"{unit_id}: unresolved disposition open_question"
    ]
    apply_product_input_updates(resolution.traceability_path, [{
        "input_unit_id": unit_id,
        "disposition": "included",
        "rationale": "Mapped during planning.",
        "spec_ids": ["FR-1"],
        "task_ids": ["T-001"],
        "targets": ["sources/web"],
    }])

    assert controller._publish_product_input_evidence(spec, store.load()) == []
    assert (spec / "inputs" / "manifest.json").is_file()


def _product_effect_staging_fixture(
    tmp_path: Path,
):
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore

    project = tmp_path / "workspace"
    source = project / "requirements.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Product heading\n\nA normative requirement.\n",
        encoding="utf-8",
    )
    run_dir = project / "runs" / "run-1"
    resolution = resolve_product_inputs(
        project,
        run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    catalog = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))
    structural_unit, normative_unit = catalog["units"]
    ledger = json.loads(resolution.traceability_path.read_text(encoding="utf-8"))
    ledger["requirements"].insert(
        0,
        {
            "input_unit_id": structural_unit["id"],
            "disposition": "open_question",
            "rationale": "Legacy structural entry.",
            "spec_ids": [],
            "task_ids": [],
            "targets": [],
        },
    )
    resolution.traceability_path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resolution.traceability_markdown_path.write_text(
        "# Product Input Traceability\n\nlegacy\n",
        encoding="utf-8",
    )
    resolution.requirement_context_path.write_text(
        "# stale requirement context\n",
        encoding="utf-8",
    )

    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001 "
        "depends=none target=sources/web\n",
        encoding="utf-8",
    )
    store = SquadStateStore(run_dir)
    store.initialize(
        "run-1",
        "greenfield",
        "demo",
        0,
        "phase3-plan",
        implementation_targets=["sources/web"],
        product_inputs=resolution.state_payload(project),
    )
    state = store.load()
    state["spec_dir"] = str(spec_dir.relative_to(project))
    store.save(state)
    controller = SquadController(
        object(),
        store,
        _EmptyPolicyGraph(),
        project / "ext",
        project,
        squad_dir=run_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        raw_output="",
        duration_ms=0,
        timed_out=False,
        echelon_result={
            "verdict": "DONE",
            "product_input_updates": [
                {
                    "input_unit_id": normative_unit["id"],
                    "disposition": "included",
                    "rationale": "Mapped during planning.",
                    "spec_ids": ["FR-001"],
                    "task_ids": ["T-001"],
                    "targets": ["sources/web"],
                }
            ],
        },
    )
    visible = (
        resolution.traceability_path,
        resolution.traceability_markdown_path,
        resolution.requirement_context_path,
    )
    return controller, store, result, visible


@pytest.mark.parametrize(
    ("fault_point", "fault_occurrence"),
    [
        ("json", 1),
        ("markdown", 1),
        ("requirement_context", 1),
        ("json", 2),
        ("markdown", 2),
        ("task_validation", 1),
    ],
    ids=[
        "structural-json",
        "structural-markdown",
        "requirement-context",
        "candidate-json",
        "candidate-markdown",
        "final-task-validation",
    ],
)
def test_product_effect_staging_failure_keeps_visible_inputs_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_point: str,
    fault_occurrence: int,
) -> None:
    import echelon.product_inputs as product_inputs
    from harness.squad import _ProductInputCommitError

    controller, store, result, visible = _product_effect_staging_fixture(tmp_path)
    before = {path: path.read_bytes() for path in visible}
    calls = 0

    if fault_point == "json":
        original = product_inputs._write_json

        def faulting_write_json(path, payload):
            nonlocal calls
            original(path, payload)
            if path.name == "traceability.json":
                calls += 1
                if calls == fault_occurrence:
                    raise OSError("injected staged JSON failure")

        monkeypatch.setattr(product_inputs, "_write_json", faulting_write_json)
    elif fault_point == "markdown":
        original = product_inputs._write_traceability_markdown

        def faulting_write_markdown(path, payload):
            nonlocal calls
            original(path, payload)
            calls += 1
            if calls == fault_occurrence:
                raise OSError("injected staged Markdown failure")

        monkeypatch.setattr(
            product_inputs,
            "_write_traceability_markdown",
            faulting_write_markdown,
        )
    elif fault_point == "requirement_context":
        original = product_inputs.refresh_requirement_context_from_catalog

        def faulting_context(catalog_path, requirement_context_path):
            original(catalog_path, requirement_context_path)
            raise OSError("injected staged requirement-context failure")

        monkeypatch.setattr(
            product_inputs,
            "refresh_requirement_context_from_catalog",
            faulting_context,
        )
    else:
        original = product_inputs.apply_product_input_updates

        def faulting_final_validation(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected final task validation failure")

        monkeypatch.setattr(
            product_inputs,
            "apply_product_input_updates",
            faulting_final_validation,
        )

    with pytest.raises(_ProductInputCommitError):
        controller._prepare_external_phase_effects(
            result,
            "phase3-plan",
            store.load(),
            manual_phase_run=False,
        )

    assert {path: path.read_bytes() for path in visible} == before
    assert "pending_external_publication" not in store.load()


def test_product_effect_staging_changes_only_sealed_copies_until_publish(
    tmp_path: Path,
) -> None:
    controller, store, result, visible = _product_effect_staging_fixture(tmp_path)
    before = {path: path.read_bytes() for path in visible}

    prepared = controller._prepare_external_phase_effects(
        result,
        "phase3-plan",
        store.load(),
        manual_phase_run=False,
    )

    assert prepared is not None
    assert {path: path.read_bytes() for path in visible} == before
    manifest = json.loads(
        next(
            (
                controller._squad_dir
                / ".publication-outbox"
                / prepared.marker.transaction_id
            ).glob("manifest.json")
        ).read_text(encoding="utf-8")
    )
    assert [operation["target"] for operation in manifest["operations"]] == sorted(
        str(path.relative_to(controller._project_root)).replace("\\", "/")
        for path in visible
    )

    prepared.publish()

    assert {path: path.read_bytes() for path in visible} != before

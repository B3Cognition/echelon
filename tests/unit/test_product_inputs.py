"""Product-input resolution, provenance, and readiness tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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
    controller = SquadController(object(), store, object(), project / "ext", project, squad_dir=run_dir)
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

    assert controller._apply_product_input_updates(result, "phase1-what") is None
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
    controller = SquadController(object(), store, object(), project / "ext", project, squad_dir=run_dir)
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

    error = controller._apply_product_input_updates(result, "phase3-plan")

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
    controller = SquadController(object(), store, object(), project / "ext", project, squad_dir=run_dir)
    result = SquadAgentResult(
        exit_code=0, raw_output="", duration_ms=0, timed_out=False,
        echelon_result={"verdict": "PASS"},
    )

    assert controller._apply_product_input_updates(result, "phase3-consensus") is None


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
    assert "must return ok=true" in prompt


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

    class TerminalGraph:
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

"""Pure logical graph views over explicitly selected captured source trees."""

from __future__ import annotations

import builtins
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3

import pytest

from echelon.spec_graph import GraphEdge, SpecGraphError, render_spec_graph
from echelon.spec_graph_captured import CapturedGraphMemory, build_captured_identity_graph
from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource
from echelon.spec_memory_miner import plan_canonical_requirement_drawers
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_store import IdentityStore
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_publication_snapshot import PublicationImageDescriptor
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import ProjectedPublicationSources, project_publication_source_images
from harness.squad_source_snapshot import ProjectDirectorySnapshot, ProjectFileSnapshot
from tests.unit.test_spec_graph_captured import (
    _args as _captured_args,
    _history,
    _native_retained_args,
    _sources,
    _three_domains,
)
from tests.unit.test_spec_graph_structure import _tree
from tests.unit.test_squad_source_projection_images import secure_posix


pytestmark = pytest.mark.unit


SPEC = "specs/demo/spec.md"
EVIDENCE = "specs/demo/evidence/verify.md"
ACTIVE_ROOT = "runs/spec-test/specs/demo"
ACTIVE_SPEC = f"{ACTIVE_ROOT}/spec.md"
BEFORE = b"- **FR-000001**: Move using WASD.\n"
AFTER = b"- **FR-000001**: Move using arrow keys.\n"
EVIDENCE_BYTES = b"See FR-000001.\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _audit() -> GraphMemoryAudit:
    return GraphMemoryAudit(
        "returned", 1, "active-view-test-wing", "pass", 1, 1, 1,
        (), (), (), (), (), (), (), (),
    )


def _zero_operation_projection(project: Path, squad: Path, *roots: str):
    squad.mkdir(parents=True, exist_ok=True)
    prepared = SquadPublicationTransaction.begin(
        project, squad, hashlib.sha256("|".join(roots).encode()).hexdigest()[:32],
    ).seal()
    with prepared.inspect_sources(tree_paths=roots) as observed:
        return project_publication_source_images(observed)


def _memory(content: bytes) -> tuple[CapturedGraphMemory, ...]:
    rows = tuple(plan_canonical_requirement_drawers(
        content,
        source=SPEC,
        wing="active-view-test-wing",
        artifact_metadata={
            "canonical": True,
            "artifact_hash": "sha256:" + _sha(content),
        },
    ))
    return (CapturedGraphMemory(
        "canonical-spec",
        (GraphMemorySource(SPEC, content, "requirement", ""),),
        rows,
        _audit(),
    ),)


def _reject(arguments: dict) -> None:
    with pytest.raises(SpecGraphError) as caught:
        build_captured_identity_graph(**arguments)
    assert str(caught.value) == "invalid captured identity graph assembly"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def _active_sources(active_files=None, *, canonical_files=None, exists=True):
    trees = (
        _tree(canonical_files or {}, root="specs/demo"),
        _tree(active_files or {}, root=ACTIVE_ROOT, exists=exists),
    )
    return _sources(tuple(sorted(trees, key=lambda tree: tree.path)))


def test_run_local_view_matches_canonical_graph_and_retains_history(tmp_path, secure_posix):
    # Catch physical-path leakage, stale canonical blending and history rebinding.
    project = tmp_path.resolve()
    store = IdentityStore.initialize(project)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000001"
    old_declaration, = parse_identity_artifact(
        path=SPEC, role="requirements", text=BEFORE.decode(),
    ).declarations
    new_declaration, = parse_identity_artifact(
        path=SPEC, role="requirements", text=AFTER.decode(),
    ).declarations
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Movement", old_declaration.content, "reserve"),
    ))
    reference, = parse_identity_artifact(
        path=EVIDENCE, role="evidence", text=EVIDENCE_BYTES.decode(),
    ).references
    assert (reference.target_id, reference.span.start, reference.span.end, reference.relation) == (
        label, 4, 13, "evidence",
    )
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim(EVIDENCE, _sha(EVIDENCE_BYTES), "span:4:13", label, "1", reference.relation),
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Movement", new_declaration.content),
    ))
    history = store.identity_history(spec_id="demo")

    canonical = project / "specs/demo"
    active = project / ACTIVE_ROOT
    (canonical / "evidence").mkdir(parents=True)
    (active / "evidence").mkdir(parents=True)
    (active / "empty").mkdir()
    (canonical / "spec.md").write_bytes(BEFORE)
    (canonical / "evidence/verify.md").write_bytes(EVIDENCE_BYTES)
    (active / "spec.md").write_bytes(AFTER)
    (active / "evidence/verify.md").write_bytes(EVIDENCE_BYTES)
    (active / ".hidden.bin").write_bytes(b"\x00\xffactive")
    retained_physical_sources = _zero_operation_projection(
        project, project / "runs/spec-test", "specs/demo", ACTIVE_ROOT,
    )

    comparison = project / "comparison"
    comparison_spec = comparison / "specs/demo"
    (comparison_spec / "evidence").mkdir(parents=True)
    (comparison_spec / "empty").mkdir()
    (comparison_spec / "spec.md").write_bytes(AFTER)
    (comparison_spec / "evidence/verify.md").write_bytes(EVIDENCE_BYTES)
    (comparison_spec / ".hidden.bin").write_bytes(b"\x00\xffactive")
    canonical_sources = _zero_operation_projection(
        comparison, comparison / "runs/spec-comparison", "specs/demo",
    )

    canonical_arguments = dict(
        spec_id="demo", lifecycle="phase_a", generator_version="active-view-test",
        sources=canonical_sources, policy_paths=(EVIDENCE,), memory=_memory(AFTER),
        re_artifacts=(), re_sources=(), history=history,
    )
    active_arguments = canonical_arguments | {"sources": retained_physical_sources}
    expected = build_captured_identity_graph(**canonical_arguments)
    requirement = next(node for node in expected.nodes if node.id == "req:demo:FR-000001")
    old_revision = next(
        node for node in expected.nodes
        if node.type == "ElementRevision" and node.properties["revision"] == "1"
    )
    claim, = (node for node in expected.nodes if node.type == "ReferenceClaim")
    assert requirement.id == "req:demo:FR-000001"
    assert requirement.properties["identity"]["revision"] == "2"
    assert GraphEdge(claim.id, "ASSESSES_REVISION", old_revision.id, {}) in expected.edges

    actual = build_captured_identity_graph(
        **active_arguments, spec_source_path=ACTIVE_ROOT,
    )
    assert render_spec_graph(actual) == render_spec_graph(expected)
    assert active_arguments["sources"] == retained_physical_sources


def test_none_explicit_canonical_and_run_local_selectors_have_exact_wire_parity():
    # Catch a changed legacy default, a special canonical branch, or physical graph paths.
    content = b"- FR-000001: Active requirement.\n"
    canonical_sources = _sources((_tree({"spec.md": content}),))
    arguments = _captured_args(
        sources=canonical_sources, memory=_memory(content),
        history=_history(("FR-000001",)),
    )
    legacy = build_captured_identity_graph(**arguments)
    explicit_none = build_captured_identity_graph(**arguments, spec_source_path=None)
    explicit_canonical = build_captured_identity_graph(
        **arguments, spec_source_path="specs/demo",
    )
    active_sources = _active_sources(
        {"spec.md": content}, canonical_files={"spec.md": b"- FR-999999: Stale.\n"},
    )
    active = build_captured_identity_graph(
        **(arguments | {"sources": active_sources}), spec_source_path=ACTIVE_ROOT,
    )
    expected = render_spec_graph(legacy)
    assert render_spec_graph(explicit_none) == expected
    assert render_spec_graph(explicit_canonical) == expected
    assert render_spec_graph(active) == expected
    assert b"runs/spec-test" not in expected


@pytest.mark.parametrize("path", [
    "runs/spec-test/specs/other",
    "runs/spec-test/specs",
    "runs/spec-test/specs/demo/extra",
    "runs/spec-test/demo",
    "drafts/spec-test/specs/demo",
    "runs/spec-test/spec/demo",
    "other",
    "/runs/spec-test/specs/demo",
    "runs/../spec-test/specs/demo",
    "runs/spec-test//specs/demo",
    "runs/spec-test/specs/demo/",
    "./runs/spec-test/specs/demo",
    "runs\\spec-test\\specs\\demo",
    "runs/spec-test/specs/demo\ud800",
    1,
    b"runs/spec-test/specs/demo",
])
def test_selector_rejects_every_non_contract_value(path):
    # Catch normalization, basename inference, broad roots and non-wire scalar coercion.
    _reject(_captured_args(
        sources=_active_sources({"spec.md": b"- FR-000001: Active.\n"}),
    ) | {"spec_source_path": path})


def test_selector_rejects_str_subclasses_and_absent_exact_tree():
    # Catch isinstance acceptance and fallback to canonical or another run.
    class Text(str):
        pass

    sources = _sources(tuple(sorted((
        _tree({"spec.md": b"canonical"}),
        _tree({"spec.md": b"other"}, root="runs/spec-other/specs/demo"),
    ), key=lambda tree: tree.path)))
    _reject(_captured_args(sources=sources) | {
        "spec_source_path": Text(ACTIVE_ROOT),
    })
    _reject(_captured_args(sources=sources) | {"spec_source_path": ACTIVE_ROOT})


@pytest.mark.parametrize("exists", [False, True])
def test_selected_missing_and_empty_tree_exclusively_owns_empty_logical_view(exists):
    # Catch fallback to stale canonical files or merging canonical-only policy inputs.
    stale = {"spec.md": b"- FR-999999: Stale.\n", "plan.md": b"stale policy"}
    sources = _active_sources({}, canonical_files=stale, exists=exists)
    retained = deepcopy(sources)
    arguments = _captured_args(sources=sources)
    actual = build_captured_identity_graph(**arguments, spec_source_path=ACTIVE_ROOT)
    expected = build_captured_identity_graph(**_captured_args(
        sources=_sources((_tree(exists=exists),)),
    ))
    assert render_spec_graph(actual) == render_spec_graph(expected)
    assert not any(node.type == "Requirement" for node in actual.nodes)
    assert not any(item.path == "specs/demo/plan.md" for item in actual.inputs)
    assert sources == retained

    _reject(arguments | {
        "policy_paths": ("specs/demo/plan.md",), "spec_source_path": ACTIVE_ROOT,
    })
    stale_memory = (CapturedGraphMemory(
        "canonical-spec",
        (GraphMemorySource(SPEC, stale["spec.md"], "requirement", ""),),
        (), _audit(),
    ),)
    _reject(arguments | {"memory": stale_memory, "spec_source_path": ACTIVE_ROOT})


def test_selected_missing_and_empty_physical_manifests_remain_distinct():
    # Catch collapsing physical absence into an invented present directory.
    missing = _active_sources({}, canonical_files={"spec.md": b"stale"}, exists=False)
    empty = _active_sources({}, canonical_files={"spec.md": b"stale"}, exists=True)
    arguments = _captured_args()
    missing_graph = build_captured_identity_graph(
        **(arguments | {"sources": missing}), spec_source_path=ACTIVE_ROOT,
    )
    empty_graph = build_captured_identity_graph(
        **(arguments | {"sources": empty}), spec_source_path=ACTIVE_ROOT,
    )
    assert missing.manifest != empty.manifest
    missing_tree = next(tree for tree in missing.trees if tree.path == ACTIVE_ROOT)
    empty_tree = next(tree for tree in empty.trees if tree.path == ACTIVE_ROOT)
    assert missing_tree.exists is False and empty_tree.exists is True
    assert render_spec_graph(missing_graph) == render_spec_graph(empty_graph)


def test_selected_tree_owns_policy_and_memory_bytes_without_blending():
    # Catch canonical-only artifacts, old content, or physical spellings entering the logical view.
    active_spec = b"- FR-000001: Active.\n"
    active_plan = b"- FR-000002: Active plan.\n"
    active_evidence = b"FR-000001 active evidence\n"
    sources = _active_sources(
        {
            "spec.md": active_spec,
            "plan.md": active_plan,
            "evidence/verify.md": active_evidence,
        },
        canonical_files={
            "spec.md": b"- FR-999999: Old.\n",
            "plan.md": b"- FR-999998: Old plan.\n",
            "tasks.md": b"- [ ] T-999999 complexity=standard phase=build req=FR-999999 depends=none\n",
            "canonical-only.md": b"old only",
        },
    )
    arguments = _captured_args(
        sources=sources,
        policy_paths=("specs/demo/plan.md", "specs/demo/evidence/verify.md"),
        memory=(*_memory(active_spec), CapturedGraphMemory(
            "spec-evidence",
            (GraphMemorySource(
                "specs/demo/evidence/verify.md", active_evidence, "spec-evidence", "",
            ),),
            (), _audit(),
        )),
        history=_history(("FR-000001", "FR-000002")),
    )
    result = build_captured_identity_graph(**arguments, spec_source_path=ACTIVE_ROOT)
    assert {node.id for node in result.nodes if node.type == "Requirement"} == {
        "req:demo:FR-000001", "req:demo:FR-000002",
    }
    assert not any(node.type == "Task" for node in result.nodes)
    plan = next(item for item in result.inputs if item.path == "specs/demo/plan.md")
    assert plan.hash == "sha256:" + _sha(active_plan)
    assert all(ACTIVE_ROOT not in item.path for item in result.inputs)

    _reject(arguments | {
        "policy_paths": ("specs/demo/canonical-only.md",),
        "spec_source_path": ACTIVE_ROOT,
    })
    _reject(arguments | {
        "memory": _memory(b"- FR-999999: Old.\n"),
        "spec_source_path": ACTIVE_ROOT,
    })
    old_evidence = replace(
        arguments["memory"][1],
        sources=(GraphMemorySource(
            "specs/demo/evidence/verify.md", b"old evidence", "spec-evidence", "",
        ),),
    )
    _reject(arguments | {
        "memory": (arguments["memory"][0], old_evidence),
        "spec_source_path": ACTIVE_ROOT,
    })
    _reject(arguments | {
        "policy_paths": (f"{ACTIVE_ROOT}/plan.md",),
        "spec_source_path": ACTIVE_ROOT,
    })
    physical_memory = (CapturedGraphMemory(
        "canonical-spec",
        (GraphMemorySource(ACTIVE_SPEC, active_spec, "requirement", ""),),
        (), _audit(),
    ),)
    _reject(arguments | {"memory": physical_memory, "spec_source_path": ACTIVE_ROOT})


def test_canonical_prefix_sibling_never_substitutes_for_selected_tree():
    # Catch string-prefix ancestry that treats specs/demo-other as specs/demo.
    sources = _sources(tuple(sorted((
        _tree({"spec.md": b"- FR-999999: Canonical.\n"}),
        _tree({}, root=ACTIVE_ROOT),
        _tree({"spec.md": b"- FR-888888: Sibling.\n"}, root="specs/demo-other"),
    ), key=lambda tree: tree.path)))
    result = build_captured_identity_graph(
        **_captured_args(sources=sources), spec_source_path=ACTIVE_ROOT,
    )
    assert not any(node.type == "Requirement" for node in result.nodes)


def test_run_local_view_preserves_native_all_domain_and_re_graph(tmp_path):
    # Catch dropped RE contributions or physical naming in local, memory and evidence records.
    arguments = _native_retained_args(tmp_path)
    expected = build_captured_identity_graph(**arguments)
    re_tree = next(tree for tree in arguments["sources"].trees if tree.path == "re")
    canonical_tree = next(
        tree for tree in arguments["sources"].trees if tree.path == "specs/demo"
    )
    root_length = len(Path(canonical_tree.path).parts)
    active_files = {
        Path(*Path(item.path).parts[root_length:]).as_posix(): item.content
        for item in canonical_tree.files
    }
    stale_canonical = _tree({
        "spec.md": b"FR-999999: Stale canonical.\n",
        "plan.md": b"stale",
        "evidence/verify.md": b"stale",
    })
    active_tree = _tree(active_files, root=ACTIVE_ROOT)
    sources = _sources(tuple(sorted(
        (re_tree, active_tree, stale_canonical), key=lambda tree: tree.path,
    )))
    retained = deepcopy(sources)
    actual = build_captured_identity_graph(
        **(arguments | {"sources": sources}), spec_source_path=ACTIVE_ROOT,
    )
    assert render_spec_graph(actual) == render_spec_graph(expected)
    ids = {node.id for node in actual.nodes}
    assert "artifact:demo:specs/demo/spec.md" in ids
    assert "req:demo:FR-000001" in ids
    assert "drawer:demo:row-0" in ids
    assert "source:api" in ids
    assert "decision:api:decisions/a.md" in ids
    assert sources == retained


def test_selected_graph_self_file_is_validated_but_excluded_from_derived_bytes():
    # Catch graph recursion or treating the excluded output as an unvalidated side channel.
    content = b"- FR-000001: Active.\n"
    history = _history(("FR-000001",))
    without_self = _active_sources({"spec.md": content})
    with_self_a = _active_sources({
        "spec.md": content, "spec-artifact-graph.json": b"old graph A",
    })
    with_self_b = _active_sources({
        "spec.md": content, "spec-artifact-graph.json": b"old graph B",
    })
    base = _captured_args(memory=_memory(content), history=history)
    rendered = {
        render_spec_graph(build_captured_identity_graph(
            **(base | {"sources": sources}), spec_source_path=ACTIVE_ROOT,
        ))
        for sources in (without_self, with_self_a, with_self_b)
    }
    assert len(rendered) == 1
    assert len({without_self.manifest, with_self_a.manifest, with_self_b.manifest}) == 3


@pytest.mark.parametrize("damage", [
    "ignored-bytes", "ignored-hash", "ignored-mode", "ignored-layout",
    "ignored-hidden-binary", "stale-manifest", "mismatched-manifest",
])
def test_every_original_physical_observation_is_validated_before_filtering(damage):
    # Catch filtering that hides damaged inactive canonical observations.
    sources = _sources(tuple(sorted((
        _tree({"spec.md": b"# old\n", ".hidden.bin": b"\x00\xffold"}),
        _tree({"spec.md": b"# active\n"}, root=ACTIVE_ROOT),
        _tree({".hidden.bin": b"\x00\xffother"}, root="runs/spec-other/specs/demo"),
    ), key=lambda tree: tree.path)))
    canonical = next(tree for tree in sources.trees if tree.path == "specs/demo")
    visible = next(item for item in canonical.files if item.path.endswith("spec.md"))
    other = next(
        tree for tree in sources.trees if tree.path == "runs/spec-other/specs/demo"
    )
    hidden = other.files[0]
    if damage == "ignored-bytes":
        object.__setattr__(visible, "content", b"changed without hash")
    elif damage == "ignored-hash":
        object.__setattr__(visible.image, "sha256", "0" * 64)
    elif damage == "ignored-mode":
        object.__setattr__(visible.image, "mode", True)
    elif damage == "ignored-layout":
        object.__setattr__(canonical, "directories", ())
    elif damage == "ignored-hidden-binary":
        object.__setattr__(hidden.image, "sha256", "f" * 64)
    elif damage == "stale-manifest":
        sources = replace(sources, manifest=replace(sources.manifest, sha256="0" * 64))
    else:
        sources = replace(sources, manifest=replace(sources.manifest, payload="{}"))
    _reject(_captured_args(sources=sources) | {"spec_source_path": ACTIVE_ROOT})


def test_self_consistent_inactive_canonical_changes_are_coherent_not_authoritative():
    # Catch accidental authority assigned to valid but inactive canonical observations.
    active = {"spec.md": b"# active\n"}
    first = _active_sources(
        active, canonical_files={"spec.md": b"# old A\n", ".hidden.bin": b"\x00A"},
    )
    second = _active_sources(
        active, canonical_files={"spec.md": b"# old B\n", ".hidden.bin": b"\x00B"},
    )
    arguments = _captured_args()
    one = build_captured_identity_graph(
        **(arguments | {"sources": first}), spec_source_path=ACTIVE_ROOT,
    )
    two = build_captured_identity_graph(
        **(arguments | {"sources": second}), spec_source_path=ACTIVE_ROOT,
    )
    assert first.manifest != second.manifest
    assert render_spec_graph(one) == render_spec_graph(two)


def test_run_local_view_detaches_outputs_from_every_caller_owned_input():
    # Catch retained references from the private remap or identity projection.
    sources = _active_sources({"spec.md": b"# active\n"})
    arguments = _captured_args(sources=sources)
    retained_sources = deepcopy(sources)
    retained_memory = deepcopy(arguments["memory"])
    retained_history = deepcopy(arguments["history"])
    result = build_captured_identity_graph(**arguments, spec_source_path=ACTIVE_ROOT)
    rendered = render_spec_graph(result)
    assert sources == retained_sources
    assert arguments["memory"] == retained_memory
    assert arguments["history"] == retained_history

    selected = next(tree for tree in sources.trees if tree.path == ACTIVE_ROOT)
    object.__setattr__(selected.directories[0], "path", "damaged")
    object.__setattr__(sources.manifest, "payload", "damaged")
    object.__setattr__(arguments["memory"][0].audit, "status", "damaged")
    object.__setattr__(arguments["history"], "payload", "damaged")
    assert render_spec_graph(result) == rendered


def test_run_local_graph_call_has_no_external_acquisition_or_io(tmp_path, monkeypatch):
    # Catch any runtime activation hidden behind the opt-in pure selector.
    from echelon import mempalace_audit, mempalace_requirements, spec_memory_miner
    from harness import llm_provider

    arguments = _captured_args(sources=_active_sources({"spec.md": b"# active\n"}))
    expected = render_spec_graph(build_captured_identity_graph(
        **arguments, spec_source_path=ACTIVE_ROOT,
    ))

    def forbidden(*args, **kwargs):
        raise AssertionError("external acquisition")

    targets = (
        (builtins, "open"),
        (Path, "open"), (Path, "read_bytes"), (Path, "read_text"),
        (Path, "write_bytes"), (Path, "write_text"), (Path, "stat"),
        (Path, "exists"), (Path, "iterdir"), (Path, "resolve"),
        (sqlite3, "connect"),
        (IdentityStore, "initialize"), (IdentityStore, "open"),
        (llm_provider.AICodingCliProvider, "__init__"),
        (mempalace_requirements, "create_requirement_memory_adapter"),
        (mempalace_audit, "audit_spec_memory"),
        (spec_memory_miner, "plan_canonical_requirement_drawers"),
        (spec_memory_miner, "plan_canonical_support_drawers"),
    )
    with monkeypatch.context() as guard:
        for owner, name in targets:
            guard.setattr(owner, name, forbidden)
        actual = build_captured_identity_graph(
            **arguments, spec_source_path=ACTIVE_ROOT,
        )
    assert render_spec_graph(actual) == expected


def test_run_local_view_preserves_bounded_errors_and_baseexception(monkeypatch):
    # Catch accidental process-control normalization or source-bearing exception chains.
    import echelon.spec_graph_captured as captured

    arguments = _captured_args(sources=_active_sources({"spec.md": b"# active\n"}))
    _reject(arguments | {"spec_source_path": "runs/spec-test/specs/other"})

    def interrupt(**kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(captured, "build_spec_graph_structure", interrupt)
    with pytest.raises(KeyboardInterrupt, match="stop"):
        build_captured_identity_graph(**arguments, spec_source_path=ACTIVE_ROOT)


def test_guarded_run_local_publication_matches_projected_logical_graph(tmp_path, secure_posix):
    # Catch a view that cannot compose with the existing physical publication guard.
    project = tmp_path.resolve()
    canonical = project / "specs/demo"
    active = project / ACTIVE_ROOT
    canonical.mkdir(parents=True)
    active.mkdir(parents=True)
    (canonical / "spec.md").write_bytes(BEFORE)
    (active / "spec.md").write_bytes(BEFORE)

    transaction = SquadPublicationTransaction.begin(
        project, project / "runs/spec-test", "9" * 32,
    )
    stage = transaction.build_path("active-after.md")
    stage.write_bytes(AFTER)
    transaction.add_write(Path(ACTIVE_SPEC), stage, owned_paths={Path(ACTIVE_SPEC)})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo", ACTIVE_ROOT)) as initial:
        projected = project_publication_source_images(initial)

    history = _history(("FR-000001",))
    expected_arguments = _captured_args(
        sources=_sources((_tree({"spec.md": AFTER}),)),
        memory=_memory(AFTER), history=history,
    )
    expected = render_spec_graph(build_captured_identity_graph(**expected_arguments))
    active_arguments = expected_arguments | {"sources": projected}
    assert render_spec_graph(build_captured_identity_graph(
        **active_arguments, spec_source_path=ACTIVE_ROOT,
    )) == expected

    final = prepared.publish_sources(initial)
    final_manifest = snapshot_source_manifest(trees=final.trees, files=final.files)
    assert final_manifest == projected.manifest
    final_sources = ProjectedPublicationSources(final.trees, final.files, final_manifest)
    assert render_spec_graph(build_captured_identity_graph(
        **(active_arguments | {"sources": final_sources}),
        spec_source_path=ACTIVE_ROOT,
    )) == expected
    assert (canonical / "spec.md").read_bytes() == BEFORE
    assert (active / "spec.md").read_bytes() == AFTER

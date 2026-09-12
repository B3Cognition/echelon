import builtins
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, replace
import hashlib
import io
import os
from pathlib import Path
import random
import socket
import sqlite3
import time
import traceback

import pytest

import harness.squad_publication as publication


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def _transaction(project, operations, transaction_id="2" * 32):
    from harness.squad_publication import SquadPublicationTransaction

    squad = project / "runs/spec-test"
    squad.mkdir(parents=True, exist_ok=True)
    transaction = SquadPublicationTransaction.begin(project, squad, transaction_id)
    for index, (action, target, after, mode) in enumerate(operations):
        relative = Path(target)
        if action == "delete":
            transaction.add_delete(relative, owned_paths={relative})
            continue
        stage = transaction.build_path(f"stage-{index}")
        stage.write_bytes(after)
        if mode is not None:
            stage.chmod(mode)
        transaction.add_write(relative, stage, owned_paths={relative})
    return transaction.seal()


def _simple_snapshot(tmp_path):
    project = tmp_path.resolve()
    (project / "source.md").write_bytes(b"before\r\n")
    prepared = _transaction(project, (("write", "source.md", b"after\r\n", None),))
    with prepared.inspect_sources(file_paths=("source.md",)) as snapshot:
        return snapshot


def _byte_inventory(snapshot):
    return (
        tuple((operation.target, operation.current_bytes, operation.postimage_bytes)
              for operation in snapshot.publication.operations),
        tuple((tree.path, tuple((item.path, item.content) for item in tree.files))
              for tree in snapshot.trees),
        tuple((item.path, item.content) for item in snapshot.files),
    )


def test_sealed_original_and_proposed_bytes_supply_candidate_images(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    target = Path("specs/demo/unknowns.md")
    (project / target).parent.mkdir(parents=True)
    before = b"### U-001: Lighting\r\nOriginal.\r\n"
    after = b"### U-001: Lighting\r\nRevised.\r\n"
    (project / target).write_bytes(before)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(after)
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=()) as snapshot:
        assert snapshot.publication.operations[0].current_bytes == before
        assert snapshot.publication.operations[0].postimage_bytes == after
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    result = assemble_candidate_sources(snapshot,
        (CandidateSourceBinding(target.as_posix(), "unknowns.md", "unknowns"),),
        writable_paths=(target.as_posix(),))
    assert not result.diagnostics
    artifact, = result.artifacts
    assert (artifact.path, artifact.role, artifact.before_text, artifact.after_text) == (
        "unknowns.md", "unknowns", before.decode(), after.decode())
    assert (project / target).read_bytes() == before


def test_explicit_mapping_preserves_every_role_and_exact_text_without_parsing(tmp_path):
    from harness.element_identity_candidate import IDENTITY_SUPPORTED_ROLES
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    project = tmp_path.resolve()
    root = project / "captured"
    root.mkdir()
    bindings = []
    expected = {}
    for index, role in enumerate(sorted(IDENTITY_SUPPORTED_ROLES)):
        source_path = f"captured/source-{index}"
        artifact_path = f"logical/{index}-{role}.md"
        text = f"\ufeffwide FR-000000000000000000000001 legacy AC-1.{index}\r\n{role} ⚡\r\n"
        (project / source_path).write_bytes(text.encode("utf-8"))
        bindings.append(CandidateSourceBinding(source_path, artifact_path, role))
        expected[artifact_path] = (role, text)
    prepared = _transaction(project, ())
    with prepared.inspect_sources(tree_paths=("captured",)) as snapshot:
        result = assemble_candidate_sources(snapshot, list(reversed(bindings)), writable_paths=[])

    assert not result.diagnostics
    assert [artifact.path for artifact in result.artifacts] == sorted(expected)
    assert {
        artifact.path: (artifact.role, artifact.before_text, artifact.after_text)
        for artifact in result.artifacts
    } == {path: (role, text, text) for path, (role, text) in expected.items()}


def test_absent_selected_tree_root_and_members_remain_absent(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    project = tmp_path.resolve()
    prepared = _transaction(project, ())
    with prepared.inspect_sources(tree_paths=("missing/tree",)) as snapshot:
        result = assemble_candidate_sources(snapshot, (
            CandidateSourceBinding("missing/tree", "root.md", "references"),
            CandidateSourceBinding("missing/tree/member.md", "member.md", "references"),
        ), writable_paths=())
    assert result.artifacts == ()
    assert result.diagnostics == ()


def test_tree_external_and_operation_resolution_distinguishes_absent_empty_and_prefixes(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    project = tmp_path.resolve()
    (project / "spec/a/nested").mkdir(parents=True)
    (project / "spec/a/nested/source.md").write_bytes("Café\r\n".encode())
    (project / "spec/a/empty.md").write_bytes(b"")
    (project / "spec/a/.hidden").write_bytes(b"\xff\x00")
    (project / "spec/ab").mkdir(parents=True)
    (project / "spec/ab/sibling.md").write_bytes(b"not selected")
    (project / "external.md").write_bytes(b"external\n")
    (project / "delete.md").write_bytes(b"delete me\n")
    prepared = _transaction(project, (
        ("write", "created.md", "created ⚡\r\n".encode(), None),
        ("delete", "delete.md", None, None),
        ("delete", "missing-delete.md", None, None),
    ))
    with prepared.inspect_sources(
        tree_paths=("spec/a",), file_paths=("external.md", "missing-external.md"),
    ) as snapshot:
        original_hidden = snapshot.trees[0].files[0].content
        bindings = (
            CandidateSourceBinding("spec/a/nested/source.md", "z.md", "references"),
            CandidateSourceBinding("spec/a/empty.md", "empty.md", "evidence"),
            CandidateSourceBinding("spec/a/absent.md", "absent.md", "unknowns"),
            CandidateSourceBinding("external.md", "external.md", "assumptions"),
            CandidateSourceBinding("missing-external.md", "missing.md", "tasks"),
            CandidateSourceBinding("created.md", "created.md", "requirements"),
            CandidateSourceBinding("delete.md", "deleted.md", "references"),
            CandidateSourceBinding("missing-delete.md", "missing-delete.md", "issues"),
        )
        result = assemble_candidate_sources(
            snapshot, bindings,
            writable_paths=("created.md", "delete.md", "missing-delete.md"),
        )

    assert not result.diagnostics
    assert original_hidden == b"\xff\x00"
    by_path = {artifact.path: artifact for artifact in result.artifacts}
    assert set(by_path) == {"z.md", "empty.md", "external.md", "created.md", "deleted.md"}
    assert (by_path["z.md"].before_text, by_path["z.md"].after_text) == ("Café\r\n", "Café\r\n")
    assert (by_path["empty.md"].before_text, by_path["empty.md"].after_text) == ("", "")
    assert (by_path["created.md"].before_text, by_path["created.md"].after_text) == (None, "created ⚡\r\n")
    assert (by_path["deleted.md"].before_text, by_path["deleted.md"].after_text) == ("delete me\n", None)

    for bad_path in ("spec/a/nested", "spec/a/nested/source.md/child", "spec/ab/sibling.md"):
        with pytest.raises(ValueError, match="^invalid captured candidate source request$"):
            assemble_candidate_sources(
                snapshot, (CandidateSourceBinding(bad_path, "bad.md", "references"),),
                writable_paths=("created.md", "delete.md", "missing-delete.md"),
            )


def test_all_sealed_operations_need_exact_write_and_typed_or_opaque_permission(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    project = tmp_path.resolve()
    for path, content, mode in (
        ("typed.md", b"old\n", 0o644),
        ("mode.md", b"mode\n", 0o600),
        ("noop.md", b"same\n", 0o644),
        ("opaque.bin", b"\xff\x00", 0o600),
    ):
        (project / path).write_bytes(content)
        (project / path).chmod(mode)
    prepared = _transaction(project, (
        ("write", "typed.md", b"new\n", None),
        ("write", "mode.md", b"mode\n", 0o640),
        ("write", "noop.md", b"same\n", 0o644),
        ("delete", "noop-delete.md", None, None),
        ("write", "opaque.bin", b"\x00\xff", None),
        ("write", "unbound.md", b"unbound\n", None),
    ))
    with prepared.inspect_sources() as snapshot:
        bindings = tuple(
            CandidateSourceBinding(path, f"logical/{path}", "references")
            for path in ("typed.md", "mode.md", "noop.md", "noop-delete.md")
        )
        result = assemble_candidate_sources(snapshot, bindings, writable_paths=("parent",))
        assert [(d.path, d.code) for d in result.diagnostics] == [
            ("mode.md", "artifact_out_of_scope"),
            ("noop-delete.md", "artifact_out_of_scope"),
            ("noop.md", "artifact_out_of_scope"),
            ("opaque.bin", "artifact_out_of_scope"),
            ("opaque.bin", "publication_target_unbound"),
            ("typed.md", "artifact_out_of_scope"),
            ("unbound.md", "artifact_out_of_scope"),
            ("unbound.md", "publication_target_unbound"),
        ]

        clean = assemble_candidate_sources(
            snapshot, bindings,
            writable_paths=tuple(operation.target for operation in snapshot.publication.operations),
            opaque_write_paths=("opaque.bin", "unbound.md"),
        )
    assert not clean.diagnostics
    assert {artifact.path for artifact in clean.artifacts} == {
        "logical/typed.md", "logical/mode.md", "logical/noop.md",
    }


def test_typed_binary_rules_distinguish_bad_baseline_from_bad_proposal(tmp_path):
    from harness.element_identity_candidate import CandidateDiagnostic
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    project = tmp_path.resolve()
    (project / "bad-after.md").write_bytes(b"valid before\n")
    (project / "bad-before.md").write_bytes(b"\xff")
    (project / "nul-before.md").write_bytes(b"bad\x00baseline")
    (project / "nul-after.md").write_bytes(b"valid before nul\n")
    (project / "unbound.bin").write_bytes(b"\xff\x00")
    prepared = _transaction(project, (
        ("write", "bad-after.md", b"\xff", None),
        ("write", "nul-after.md", b"bad\x00proposal", None),
    ))
    with prepared.inspect_sources(
        tree_paths=(), file_paths=(
            "bad-after.md", "bad-before.md", "nul-after.md", "nul-before.md", "unbound.bin",
        ),
    ) as snapshot:
        proposed = assemble_candidate_sources(
            snapshot, (
                CandidateSourceBinding("bad-after.md", "bad-after.md", "references"),
                CandidateSourceBinding("nul-after.md", "nul-after.md", "references"),
            ),
            writable_paths=("bad-after.md", "nul-after.md"),
        )
        assert proposed.artifacts == ()
        assert proposed.diagnostics == tuple(sorted((
            CandidateDiagnostic(
                "candidate_source_not_text", "bad-after.md", None,
                "typed proposed source must contain valid UTF-8 text without NUL",
            ),
            CandidateDiagnostic(
                "candidate_source_not_text", "nul-after.md", None,
                "typed proposed source must contain valid UTF-8 text without NUL",
            ),
        ), key=lambda row: (row.path or "", row.element_id or "", row.code, row.detail)))
        for source in ("bad-before.md", "nul-before.md", "unbound.bin"):
            with pytest.raises(
                ValueError,
                match="^typed source baseline must contain valid UTF-8 text without NUL$",
            ):
                assemble_candidate_sources(
                    snapshot, (CandidateSourceBinding(source, "typed.md", "references"),),
                    writable_paths=("bad-after.md", "nul-after.md"),
                )


@pytest.mark.parametrize("field,value", [
    ("bindings", None), ("bindings", "source.md"), ("bindings", b"source.md"),
    ("bindings", iter(())), ("bindings", ({"source_path": "source.md"},)),
    ("writable_paths", None), ("writable_paths", "source.md"),
    ("writable_paths", iter(("source.md",))),
    ("opaque_write_paths", b"source.md"), ("opaque_write_paths", iter(())),
])
def test_sequence_and_exact_binding_types_are_strict(tmp_path, field, value):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    snapshot = _simple_snapshot(tmp_path)
    arguments = {
        "bindings": (CandidateSourceBinding("source.md", "source.md", "references"),),
        "writable_paths": ("source.md",),
        "opaque_write_paths": (),
    }
    arguments[field] = value
    with pytest.raises(ValueError, match="^invalid captured candidate source request$"):
        assemble_candidate_sources(snapshot, **arguments)


@pytest.mark.parametrize("case", [
    "duplicate_source", "duplicate_artifact", "duplicate_writable", "duplicate_opaque",
    "opaque_not_writable", "opaque_typed_overlap", "unknown_role", "role_subclass",
    "damaged_source", "damaged_artifact", "damaged_role", "source_path", "artifact_path",
    "writable_path", "opaque_path",
])
def test_binding_and_scope_values_are_revalidated_without_coercion(tmp_path, case):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    snapshot = _simple_snapshot(tmp_path)
    first = CandidateSourceBinding("source.md", "source.md", "references")
    bindings, writable, opaque = (first,), ("source.md",), ()
    if case == "duplicate_source":
        bindings = (first, CandidateSourceBinding("source.md", "other.md", "evidence"))
    elif case == "duplicate_artifact":
        bindings = (first, CandidateSourceBinding("other.md", "source.md", "evidence"))
    elif case == "duplicate_writable":
        writable = ("source.md", "source.md")
    elif case == "duplicate_opaque":
        writable, opaque = ("other",), ("other", "other")
    elif case == "opaque_not_writable":
        opaque = ("other",)
    elif case == "opaque_typed_overlap":
        opaque = ("source.md",)
    elif case == "unknown_role":
        bindings = (replace(first, role="unknown"),)
    elif case == "role_subclass":
        class StringSubclass(str):
            pass
        bindings = (replace(first, role=StringSubclass("references")),)
    elif case.startswith("damaged_"):
        field = {"damaged_source": "source_path", "damaged_artifact": "artifact_path",
                 "damaged_role": "role"}[case]
        object.__setattr__(first, field, None)
    elif case == "source_path":
        bindings = (replace(first, source_path="bad/../path"),)
    elif case == "artifact_path":
        bindings = (replace(first, artifact_path="bad\\path"),)
    elif case == "writable_path":
        writable = ("bad/./path",)
    elif case == "opaque_path":
        writable = opaque = ("bad\udcff",)
    with pytest.raises(ValueError, match="^invalid captured candidate source request$"):
        assemble_candidate_sources(
            snapshot, bindings, writable_paths=writable, opaque_write_paths=opaque,
        )


def test_snapshot_errors_remain_publication_errors_and_input_tracebacks_are_bounded(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    from harness.squad_publication import PublicationError

    snapshot = _simple_snapshot(tmp_path)
    damaged = replace(snapshot, publication=replace(snapshot.publication, promoted_prefix=1))
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        assemble_candidate_sources(damaged, (), writable_paths=())

    class RecursiveSequence(Sequence):
        def __len__(self):
            raise RecursionError("UNTRUSTED-" * 10000)

        def __getitem__(self, index):
            raise AssertionError(index)

    with pytest.raises(ValueError, match="^invalid captured candidate source request$") as caught:
        assemble_candidate_sources(snapshot, RecursiveSequence(), writable_paths=())
    rendered = "".join(traceback.format_exception(caught.value))
    assert "UNTRUSTED-" not in rendered
    assert caught.value.__cause__ is None


def test_inputs_are_snapshotted_and_results_are_frozen_owned_tuples(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources

    snapshot = _simple_snapshot(tmp_path)
    bindings = [CandidateSourceBinding("source.md", "source.md", "references")]
    writable = ["source.md"]
    opaque = []
    result = assemble_candidate_sources(
        snapshot, bindings, writable_paths=writable, opaque_write_paths=opaque,
    )
    bindings.clear()
    writable.clear()
    opaque.append("other")
    assert isinstance(result.artifacts, tuple) and isinstance(result.diagnostics, tuple)
    assert result.artifacts[0].before_text == "before\r\n"
    with pytest.raises(FrozenInstanceError):
        result.artifacts = ()


def test_assembly_is_io_free_after_real_capture_and_leaves_snapshot_exact(tmp_path, monkeypatch):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    snapshot = _simple_snapshot(tmp_path)
    baseline = encode_initial_publication_sources(snapshot)
    byte_inventory = _byte_inventory(snapshot)

    def forbidden(*args, **kwargs):
        raise AssertionError("external access during pure assembly")

    for owner, name in (
        (builtins, "open"), (io, "open"), (Path, "open"),
        (os, "open"), (os, "listdir"), (os, "scandir"), (os, "stat"),
        (sqlite3, "connect"), (socket, "socket"), (time, "time"), (random, "random"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    result = assemble_candidate_sources(
        snapshot, (CandidateSourceBinding("source.md", "source.md", "references"),),
        writable_paths=("source.md",),
    )
    assert result.artifacts[0].after_text == "after\r\n"
    assert encode_initial_publication_sources(snapshot) == baseline
    assert _byte_inventory(snapshot) == byte_inventory


def test_real_store_and_reference_checks_consume_assembled_exact_images_without_effects(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import DiscoveryEditScope
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_reference_sources import validate_reference_claim_sources
    from harness.element_identity_store import IdentityStore

    fixture = Path(__file__).parents[1] / "fixtures/element_identity/discovery"
    before = (fixture / "before/unknowns.md").read_text()
    after = (fixture / "after/unknowns.md").read_text()
    project = (tmp_path / "project").resolve()
    project.mkdir()
    target = "specs/demo/unknowns.md"
    evidence_path = "specs/demo/evidence.md"
    (project / target).parent.mkdir(parents=True)
    (project / target).write_text(before)
    evidence = "Evidence for U-001.\r\n"
    (project / evidence_path).write_bytes(evidence.encode())
    prepared = _transaction(project, (("write", target, after.encode(), None),), "3" * 32)
    with prepared.inspect_sources(tree_paths=("specs/demo",)) as snapshot:
        assembled = assemble_candidate_sources(snapshot, (
            CandidateSourceBinding(target, "unknowns.md", "unknowns"),
            CandidateSourceBinding(evidence_path, "evidence.md", "evidence"),
        ), writable_paths=(target,))
    assert not assembled.diagnostics

    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    store = IdentityStore.initialize(registry_root)
    declarations = parse_identity_artifact(path="unknowns.md", role="unknowns", text=before).declarations
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple(
        (entry.element_id, entry.caption) for entry in declarations
    ))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(
        ElementAdopt(entry.element_id, entry.caption, entry.content) for entry in declarations
    ))
    with sqlite3.connect(registry_root / ".echelon/identity/registry.sqlite3") as connection:
        original_registry = tuple(connection.iterdump())
    result = store.check_discovery_candidate(
        spec_id="demo", artifacts=assembled.artifacts,
        scope=DiscoveryEditScope(("unknowns.md",), tuple(entry.element_id for entry in declarations)),
    )
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {"subject_changed", "definition_removed"}
    with sqlite3.connect(registry_root / ".echelon/identity/registry.sqlite3") as connection:
        assert tuple(connection.iterdump()) == original_registry
    assert (project / target).read_text() == before

    evidence_artifact = next(artifact for artifact in assembled.artifacts if artifact.path == "evidence.md")
    parsed = parse_identity_artifact(path="evidence.md", role="evidence", text=evidence)
    reference, = parsed.references
    exact = ReferenceClaim(
        "evidence.md", parsed.content_sha256,
        f"span:{reference.span.start}:{reference.span.end}", "U-001", "1", "evidence",
    )
    assert validate_reference_claim_sources((evidence_artifact,), (exact,)) == ()
    stale = replace(exact, source_sha256=hashlib.sha256(b"stale-before").hexdigest())
    assert {item.code for item in validate_reference_claim_sources((evidence_artifact,), (stale,))} == {
        "reference_source_hash_mismatch",
    }


def test_retained_initial_assembly_survives_real_partial_fault_and_retry(tmp_path):
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    from harness.squad_publication import PublicationError

    project = tmp_path.resolve()
    expected = {"a.md": (b"old-a\n", b"new-a\n"), "b.md": (b"old-b\n", b"new-b\n")}
    for target, (before, _) in expected.items():
        (project / target).write_bytes(before)
    prepared = _transaction(project, tuple(
        ("write", target, after, None) for target, (_, after) in expected.items()
    ), "4" * 32)
    with prepared.inspect_sources(file_paths=tuple(expected)) as retained:
        pass
    bindings = tuple(
        CandidateSourceBinding(target, f"logical/{target}", "references") for target in expected
    )

    def interrupt(position):
        if position == 1:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(PublicationError, match="^publish_io$"):
        prepared.publish(fault_hook=interrupt)
    with prepared.inspect_sources(file_paths=tuple(expected)) as partial:
        with pytest.raises(PublicationError, match="^manifest_invalid$"):
            assemble_candidate_sources(partial, bindings, writable_paths=tuple(expected))
    retained_result = assemble_candidate_sources(retained, bindings, writable_paths=tuple(expected))
    assert {
        artifact.path: (artifact.before_text, artifact.after_text)
        for artifact in retained_result.artifacts
    } == {
        "logical/a.md": ("old-a\n", "new-a\n"),
        "logical/b.md": ("old-b\n", "new-b\n"),
    }

    prepared.publish()
    with prepared.inspect_sources(file_paths=tuple(expected)) as completed:
        with pytest.raises(PublicationError, match="^manifest_invalid$"):
            assemble_candidate_sources(completed, bindings, writable_paths=tuple(expected))
    after_retry = assemble_candidate_sources(retained, bindings, writable_paths=tuple(expected))
    assert after_retry == retained_result

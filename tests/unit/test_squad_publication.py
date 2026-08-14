from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import harness.squad_publication as publication_module
from harness.squad import SquadController
from harness.controller_state_contracts import ControllerStateContractViolation
from harness.squad_publication import (
    PublicationError,
    PublicationMarker,
    SquadPublicationTransaction,
    add_verified_quality_debt_publication,
    load_prepared_publication,
)


TRANSACTION_ID = "a" * 32


def test_verified_quality_debt_is_an_explicit_exact_publication_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    active = project_root / "runs/spec-1/specs/001-demo"
    published = project_root / "specs/001-demo"
    active.mkdir(parents=True)
    published.mkdir(parents=True)
    debt_bytes = (
        b'{"failed_gates":[],"qualitative_debt":['
        b'{"issue_id":"ISS-QUALITY-0","route":"spec_repair",'
        b'"title":"Residual quality debt"}],"resolved_by":"COMMANDER",'
        b'"status":"accepted_with_debt"}\n'
    )
    (active / "quality-debt.json").write_bytes(debt_bytes)
    digest = hashlib.sha256(debt_bytes).hexdigest()
    state = {
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": (
                "runs/spec-1/specs/001-demo/quality-debt.json"
            ),
            "debt_artifact_sha256": digest,
        }
    }
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = transaction.build_path("staged/001-demo")
    staged.mkdir(parents=True)
    (staged / "quality-debt.json").write_bytes(debt_bytes)

    count = add_verified_quality_debt_publication(
        transaction,
        project_root=project_root,
        state=state,
        active_spec_dir=active,
        published_spec_dir=published,
        staged_spec_dir=staged,
    )
    prepared = transaction.seal()
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert count == 1
    assert manifest["operations"] == [
        {
            "action": "write",
            "postimage": {
                "kind": "file",
                "sha256": digest,
                "mode": stat.S_IMODE(
                    (staged / "quality-debt.json").stat().st_mode
                ),
            },
            "preimage": {"kind": "missing"},
            "staged": "staged/001-demo/quality-debt.json",
            "target": "specs/001-demo/quality-debt.json",
        }
    ]
    prepared.publish()
    assert (published / "quality-debt.json").read_bytes() == debt_bytes


def test_quality_debt_publication_fails_closed_when_authority_is_not_current(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    active = project_root / "runs/spec-1/specs/001-demo"
    published = project_root / "specs/001-demo"
    for root in (active, published):
        root.mkdir(parents=True)
    (active / "quality-debt.json").write_text("{}\n", encoding="utf-8")
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = transaction.build_path("staged/001-demo")
    staged.mkdir(parents=True)
    (staged / "quality-debt.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(PublicationError, match="manifest_invalid"):
        add_verified_quality_debt_publication(
            transaction,
            project_root=project_root,
            state={
                "spec_quality_debt_authorization": {
                    "status": "accepted_with_debt"
                }
            },
            active_spec_dir=active,
            published_spec_dir=published,
            staged_spec_dir=staged,
        )


def test_quality_debt_publication_rejects_staged_swap_before_manifest_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    active = project_root / "runs/spec-1/specs/001-demo"
    published = project_root / "specs/001-demo"
    active.mkdir(parents=True)
    published.mkdir(parents=True)
    debt_bytes = b'{"status":"accepted_with_debt"}\n'
    (active / "quality-debt.json").write_bytes(debt_bytes)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = transaction.build_path("staged/001-demo")
    staged.mkdir(parents=True)
    staged_debt = staged / "quality-debt.json"
    staged_debt.write_bytes(debt_bytes)
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )
    original_add_write = transaction.add_write

    def swap_then_add(*args, **kwargs):
        staged_debt.write_bytes(b'{"status":"tampered"}\n')
        return original_add_write(*args, **kwargs)

    monkeypatch.setattr(transaction, "add_write", swap_then_add)

    with pytest.raises(PublicationError, match="manifest_invalid"):
        add_verified_quality_debt_publication(
            transaction,
            project_root=project_root,
            state={
                "spec_quality_debt_authorization": {
                    "status": "accepted_with_debt",
                    "debt_artifact": (
                        "runs/spec-1/specs/001-demo/quality-debt.json"
                    ),
                    "debt_artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
                }
            },
            active_spec_dir=active,
            published_spec_dir=published,
            staged_spec_dir=staged,
        )


def test_downstream_planning_context_receives_exact_verified_debt_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    spec_dir = project_root / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    debt = {
        "schema_version": 1,
        "status": "accepted_with_debt",
        "resolved_by": "user",
        "failed_gates": [
            {"name": "overall", "score": 0.7, "threshold": 0.8, "margin": -0.1}
        ],
        "qualitative_debt": [
            {
                "issue_id": "ISS-QUALITY-0",
                "route": "spec_repair",
                "title": "Residual quality debt",
            }
        ],
    }
    debt_bytes = (json.dumps(debt, sort_keys=True) + "\n").encode("utf-8")
    (spec_dir / "quality-debt.json").write_bytes(debt_bytes)
    state = {
        "spec_dir": "specs/001-demo",
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": "specs/001-demo/quality-debt.json",
            "debt_artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
            "resolved_by": "user",
            "failed_gates": debt["failed_gates"],
            "qualitative_debt": debt["qualitative_debt"],
        },
    }
    saved: list[dict[str, object]] = []
    controller = object.__new__(SquadController)
    controller._project_root = project_root
    controller._state_store = SimpleNamespace(
        load=lambda: dict(state),
        save=lambda value: saved.append(dict(value)),
    )
    node = SimpleNamespace(
        id="phase3-plan",
        type="agent",
        lexicon_artifact=None,
        context_pack=[],
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )

    dispatched = controller._materialize_controller_phase_inputs(node)

    assert dispatched is not node
    assert node.context_pack == []
    assert dispatched.context_pack == []
    assert json.dumps(debt, sort_keys=True) in dispatched.controller_context
    assert "accepted_with_debt" in dispatched.controller_context
    assert saved[-1]["spec_quality_status"] == "accepted_with_debt"
    assert saved[-1]["spec_quality_debt_context"] == {
        "status": "accepted_with_debt",
        "artifact": "specs/001-demo/quality-debt.json",
        "artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
        "resolved_by": "user",
        "failed_gates": debt["failed_gates"],
        "qualitative_debt": debt["qualitative_debt"],
    }


def test_staged_verification_agents_each_receive_verified_debt_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    spec_dir = project_root / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    debt = {"status": "accepted_with_debt", "failed_gates": []}
    debt_bytes = (json.dumps(debt) + "\n").encode("utf-8")
    (spec_dir / "quality-debt.json").write_bytes(debt_bytes)
    state = {
        "spec_dir": "specs/001-demo",
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": "specs/001-demo/quality-debt.json",
            "debt_artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
            "resolved_by": "COMMANDER",
            "failed_gates": [],
        },
    }
    controller = object.__new__(SquadController)
    controller._project_root = project_root
    controller._state_store = SimpleNamespace(
        load=lambda: dict(state),
        save=lambda _value: None,
    )
    node = SimpleNamespace(
        id="phase3-consensus",
        type="staged_parallel",
        lexicon_artifact=None,
        context_pack=[],
        agents=[
            {"id": "echelon.sage", "context_pack": ["{spec_dir}/spec.md"]},
            {"id": "echelon.gatekeeper", "context_pack": []},
        ],
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )

    dispatched = controller._materialize_controller_phase_inputs(node)

    assert dispatched is not node
    assert node.agents[0]["context_pack"] == ["{spec_dir}/spec.md"]
    assert node.agents[1]["context_pack"] == []
    assert dispatched.agents == node.agents
    assert json.dumps(debt) in dispatched.controller_context


def test_downstream_dispatch_rejects_invalid_debt_instead_of_silently_continuing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    spec_dir = project_root / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    debt_bytes = b'{"status":"accepted_with_debt"}\n'
    (spec_dir / "quality-debt.json").write_bytes(debt_bytes)
    state = {
        "spec_dir": "specs/001-demo",
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": "specs/001-demo/quality-debt.json",
            "debt_artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
        },
    }
    controller = object.__new__(SquadController)
    controller._project_root = project_root
    controller._state_store = SimpleNamespace(load=lambda: dict(state))
    node = SimpleNamespace(
        id="phase3-plan",
        type="agent",
        lexicon_artifact=None,
        context_pack=[],
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(
        ControllerStateContractViolation,
        match="quality-debt authorization is stale",
    ):
        controller._materialize_controller_phase_inputs(node)


def test_dispatch_context_pins_verified_debt_bytes_against_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    spec_dir = project_root / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    debt = {
        "status": "accepted_with_debt",
        "resolved_by": "user",
        "failed_gates": [{"name": "overall", "score": 0.7, "threshold": 0.8}],
    }
    debt_bytes = (json.dumps(debt, sort_keys=True) + "\n").encode("utf-8")
    debt_path = spec_dir / "quality-debt.json"
    debt_path.write_bytes(debt_bytes)
    state = {
        "spec_dir": "specs/001-demo",
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": "specs/001-demo/quality-debt.json",
            "debt_artifact_sha256": hashlib.sha256(debt_bytes).hexdigest(),
            "resolved_by": "user",
            "failed_gates": debt["failed_gates"],
        },
    }
    controller = object.__new__(SquadController)
    controller._project_root = project_root
    controller._state_store = SimpleNamespace(load=lambda: dict(state), save=lambda _value: None)
    node = SimpleNamespace(
        id="phase3-specialists",
        type="conditional_sequential",
        lexicon_artifact=None,
        context_pack=[],
        agents=[{"id": "echelon.guardian", "context_pack": []}],
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )

    first = controller._materialize_controller_phase_inputs(node)
    debt_path.write_text('{"status":"tampered"}\n', encoding="utf-8")

    assert debt_bytes.decode("utf-8") in first.controller_context
    assert "tampered" not in first.controller_context
    assert not hasattr(node, "controller_context")


def test_phase_a_publication_state_preserves_accepted_with_debt_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    active = tmp_path / "runs/spec-1/specs/001-demo"
    published = tmp_path / "specs/001-demo"
    controller._active_phase_a_spec_dir = lambda _state: active
    controller._published_phase_a_spec_dir = lambda _state, _active: published
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )

    updates = controller._planned_phase_a_publication_updates(
        "phase4-document",
        {
            "spec_quality_debt_authorization": {
                "status": "accepted_with_debt"
            }
        },
    )

    assert updates == {
        "published_spec_dir": "specs/001-demo",
        "spec_status": "accepted_with_debt",
    }


def test_phase_a_publication_status_does_not_trust_authorization_shape(
    tmp_path: Path,
) -> None:
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    active = tmp_path / "runs/spec-1/specs/001-demo"
    published = tmp_path / "specs/001-demo"
    controller._active_phase_a_spec_dir = lambda _state: active
    controller._published_phase_a_spec_dir = lambda _state, _active: published

    updates = controller._planned_phase_a_publication_updates(
        "phase4-document",
        {"spec_quality_debt_authorization": {"status": "accepted_with_debt"}},
    )

    assert updates == {"published_spec_dir": "specs/001-demo"}


def test_stale_quality_debt_guard_removes_presentation_and_publication_status(
    tmp_path: Path,
) -> None:
    state = {
        "phase": "checkpoint-assess",
        "completed_phases": ["phase1-why2", "phase1-lexicon"],
        "spec_quality_debt_authorization": {"status": "accepted_with_debt"},
        "spec_status": "accepted_with_debt",
        "spec_quality_status": "accepted_with_debt",
        "spec_quality_debt_context": {"status": "accepted_with_debt"},
    }
    saved: list[dict[str, object]] = []
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    controller._state_store = SimpleNamespace(
        load=lambda: dict(state),
        save=lambda value: saved.append(dict(value)),
    )

    routed = controller._guard_phase1_quality_evidence("checkpoint-assess")

    assert routed == "phase1-understanding"
    assert "spec_quality_debt_authorization" not in saved[-1]
    assert "spec_status" not in saved[-1]
    assert "spec_quality_status" not in saved[-1]
    assert "spec_quality_debt_context" not in saved[-1]


@pytest.mark.parametrize(
    "code",
    [
        "manifest_invalid",
        "manifest_mismatch",
        "publish_io",
        "stage_corrupt",
        "stage_missing",
        "state_finalize",
        "target_drift",
    ],
)
def test_publication_error_preserves_only_bounded_diagnostic_codes(
    code: str,
) -> None:
    error = PublicationError(code)

    assert error.code == code
    assert str(error) == code


def test_publication_error_sanitizes_an_unbounded_diagnostic() -> None:
    error = PublicationError("/secret/path and content")

    assert error.code == "publish_io"
    assert str(error) == "publish_io"


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    squad_dir = project_root / ".echelon" / "squad"
    project_root.mkdir()
    squad_dir.mkdir(parents=True)
    return project_root, squad_dir


def _staged_file(
    transaction: SquadPublicationTransaction,
    name: str,
    content: bytes,
) -> Path:
    staged = transaction.build_path(name)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(content)
    return staged


def _assert_error_code(code: str, action) -> None:
    with pytest.raises(PublicationError) as raised:
        action()
    assert raised.value.code == code
    assert str(raised.value) == code


def _sealed_write(
    tmp_path: Path,
    *,
    target_name: str = "published/result.txt",
    old_content: bytes | None = None,
    new_content: bytes = b"new bytes\n",
) -> tuple[
    Path,
    Path,
    SquadPublicationTransaction,
    Path,
    object,
]:
    project_root, squad_dir = _roots(tmp_path)
    target = project_root / target_name
    if old_content is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old_content)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/result.txt", new_content)
    transaction.add_write(
        Path(target_name),
        staged,
        owned_paths={Path(target_name)},
    )
    prepared = transaction.seal()
    return project_root, squad_dir, transaction, staged, prepared


def test_seal_writes_a_canonical_sorted_exact_image_manifest(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    (project_root / "z.txt").write_bytes(b"old z")
    (project_root / "middle.txt").write_bytes(b"remove me")
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged_z = _staged_file(transaction, "build/z.txt", b"new z")
    staged_a = _staged_file(transaction, "build/a.txt", b"new a")
    owned = {Path("a.txt"), Path("middle.txt"), Path("z.txt")}

    transaction.add_write(Path("z.txt"), staged_z, owned_paths=owned)
    transaction.add_delete(Path("middle.txt"), owned_paths=owned)
    transaction.add_write(Path("a.txt"), staged_a, owned_paths=owned)

    prepared = transaction.seal()
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)

    assert manifest_bytes == (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    assert list(manifest) == ["operations", "schema_version", "transaction_id"]
    assert manifest["schema_version"] == 1
    assert manifest["transaction_id"] == TRANSACTION_ID
    assert [operation["target"] for operation in manifest["operations"]] == [
        "a.txt",
        "middle.txt",
        "z.txt",
    ]
    assert manifest["operations"] == [
        {
            "action": "write",
            "postimage": {
                "kind": "file",
                "sha256": hashlib.sha256(b"new a").hexdigest(),
                "mode": stat.S_IMODE(staged_a.stat().st_mode),
            },
            "preimage": {"kind": "missing"},
            "staged": "build/a.txt",
            "target": "a.txt",
        },
        {
            "action": "delete",
            "postimage": {"kind": "missing"},
            "preimage": {
                "kind": "file",
                "sha256": hashlib.sha256(b"remove me").hexdigest(),
                "mode": stat.S_IMODE((project_root / "middle.txt").stat().st_mode),
            },
            "target": "middle.txt",
        },
        {
            "action": "write",
            "postimage": {
                "kind": "file",
                "sha256": hashlib.sha256(b"new z").hexdigest(),
                "mode": stat.S_IMODE(staged_z.stat().st_mode),
            },
            "preimage": {
                "kind": "file",
                "sha256": hashlib.sha256(b"old z").hexdigest(),
                "mode": stat.S_IMODE((project_root / "z.txt").stat().st_mode),
            },
            "staged": "build/z.txt",
            "target": "z.txt",
        },
    ]
    expected_digest = hashlib.sha256(manifest_bytes).hexdigest()
    assert prepared.marker == PublicationMarker(
        schema_version=1,
        transaction_id=TRANSACTION_ID,
        manifest_sha256=expected_digest,
    )
    assert prepared.marker.to_dict() == {
        "schema_version": 1,
        "transaction_id": TRANSACTION_ID,
        "manifest_sha256": expected_digest,
    }
    assert (project_root / "z.txt").read_bytes() == b"old z"
    assert not (project_root / "a.txt").exists()
    assert (project_root / "middle.txt").read_bytes() == b"remove me"


def test_publish_creates_canonical_parent_modes_under_restrictive_umask(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/result.txt", b"payload")
    staged.chmod(0o751)
    transaction.add_write(
        Path("created/parents/result.txt"),
        staged,
        owned_paths={Path("created/parents/result.txt")},
    )
    prepared = transaction.seal()

    previous_umask = os.umask(0o077)
    try:
        prepared.publish()
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE((project_root / "created").stat().st_mode) == 0o755
    assert stat.S_IMODE((project_root / "created/parents").stat().st_mode) == 0o755
    assert stat.S_IMODE((project_root / "created/parents/result.txt").stat().st_mode) == 0o751


def test_publication_control_directories_ignore_restrictive_umask(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    previous_umask = os.umask(0o077)
    try:
        transaction = SquadPublicationTransaction.begin(
            project_root,
            squad_dir,
            TRANSACTION_ID,
        )
        staged = _staged_file(transaction, "build/result.txt", b"payload")
        transaction.add_write(
            Path("result.txt"),
            staged,
            owned_paths={Path("result.txt")},
        )
        prepared = transaction.seal()
        prepared.publish()
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE((squad_dir / ".publication-outbox").stat().st_mode) == 0o755
    assert stat.S_IMODE(
        (squad_dir / ".publication-outbox" / TRANSACTION_ID).stat().st_mode
    ) == 0o755
    assert stat.S_IMODE((project_root / ".echelon/runtime").stat().st_mode) == 0o755


def test_publish_rejects_later_postimage_before_earlier_preimage_without_writes(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    owned = {Path("a.txt"), Path("b.txt"), Path("c.txt")}
    staged: dict[str, Path] = {}
    for name in ("a", "b", "c"):
        target = project_root / f"{name}.txt"
        target.write_bytes(f"old-{name}".encode())
        stage = _staged_file(
            transaction,
            f"build/{name}.txt",
            f"new-{name}".encode(),
        )
        staged[name] = stage
        transaction.add_write(
            Path(f"{name}.txt"),
            stage,
            owned_paths=owned,
        )
    prepared = transaction.seal()
    (project_root / "c.txt").write_bytes(b"new-c")
    (project_root / "c.txt").chmod(stat.S_IMODE(staged["c"].stat().st_mode))
    before = {
        path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in project_root.glob("*.txt")
    }

    _assert_error_code("target_drift", prepared.publish)

    assert {
        path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in project_root.glob("*.txt")
    } == before


def test_seal_flushes_stages_and_manifest_and_syncs_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "nested/staged.txt", b"durable")
    transaction.add_write(
        Path("target.txt"),
        staged,
        owned_paths={Path("target.txt")},
    )
    real_fsync = publication_module.os.fsync
    fsynced: list[int] = []

    def recording_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(publication_module.os, "fsync", recording_fsync)

    transaction.seal()

    assert len(fsynced) >= 4


def test_seal_rereads_staged_file_and_rejects_preseal_mutation(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"expected")
    transaction.add_write(
        Path("value.txt"),
        staged,
        owned_paths={Path("value.txt")},
    )
    staged.write_bytes(b"mutated")

    _assert_error_code("stage_corrupt", transaction.seal)


def test_seal_rereads_manifest_after_the_durable_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"expected")
    transaction.add_write(
        Path("value.txt"),
        staged,
        owned_paths={Path("value.txt")},
    )
    durable_write = publication_module._durable_write_bytes_at

    def corrupting_write(
        parent_fd: int,
        name: str,
        content: bytes,
    ) -> None:
        durable_write(parent_fd, name, content)
        if name == "manifest.json":
            fd = os.open(
                name,
                os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                os.write(fd, b" ")
                os.fsync(fd)
            finally:
                os.close(fd)

    monkeypatch.setattr(
        publication_module,
        "_durable_write_bytes_at",
        corrupting_write,
    )

    _assert_error_code("manifest_mismatch", transaction.seal)


@pytest.mark.parametrize(
    "targets",
    [
        (Path("same.txt"), Path("same.txt")),
        (Path("tree"), Path("tree/child.txt")),
        (Path("tree/child.txt"), Path("tree")),
    ],
)
def test_duplicate_or_ancestor_overlapping_targets_are_rejected(
    tmp_path: Path,
    targets: tuple[Path, Path],
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    first = _staged_file(transaction, "build/first.txt", b"first")
    second = _staged_file(transaction, "build/second.txt", b"second")
    owned = set(targets)
    transaction.add_write(targets[0], first, owned_paths=owned)

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            targets[1],
            second,
            owned_paths=owned,
        ),
    )


@pytest.mark.parametrize(
    "target",
    [
        Path("/absolute.txt"),
        Path("../escape.txt"),
        Path("nested/../../escape.txt"),
        Path("."),
        Path(""),
    ],
)
def test_unsafe_workspace_target_is_rejected(
    tmp_path: Path,
    target: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"value")

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            target,
            staged,
            owned_paths={target},
        ),
    )


def test_target_not_in_exact_owned_path_set_is_rejected(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"value")

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            Path("not-owned.txt"),
            staged,
            owned_paths={Path("owned.txt")},
        ),
    )


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_non_regular_target_is_rejected(
    tmp_path: Path,
    kind: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    target = project_root / "unsafe"
    if kind == "symlink":
        target.symlink_to(project_root / "elsewhere")
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_delete(
            Path("unsafe"),
            owned_paths={Path("unsafe")},
        ),
    )


def test_symlinked_target_ancestor_is_rejected(tmp_path: Path) -> None:
    project_root, squad_dir = _roots(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_root / "linked").symlink_to(outside, target_is_directory=True)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"value")

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            Path("linked/value.txt"),
            staged,
            owned_paths={Path("linked/value.txt")},
        ),
    )


@pytest.mark.parametrize("kind", ["outside", "symlink", "fifo"])
def test_unsafe_staged_file_is_rejected(
    tmp_path: Path,
    kind: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    if kind == "outside":
        staged = tmp_path / "outside.txt"
        staged.write_bytes(b"value")
    elif kind == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"value")
        staged = transaction.build_path("build/link.txt")
        staged.parent.mkdir(parents=True)
        staged.symlink_to(outside)
    else:
        staged = transaction.build_path("build/fifo")
        staged.parent.mkdir(parents=True)
        os.mkfifo(staged)

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            Path("value.txt"),
            staged,
            owned_paths={Path("value.txt")},
        ),
    )


@pytest.mark.parametrize(
    "transaction_id",
    [
        "A" * 32,
        "a" * 31,
        "a" * 33,
        "../" + "a" * 29,
        "g" * 32,
    ],
)
def test_invalid_transaction_id_is_rejected(
    tmp_path: Path,
    transaction_id: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)

    _assert_error_code(
        "manifest_invalid",
        lambda: SquadPublicationTransaction.begin(
            project_root,
            squad_dir,
            transaction_id,
        ),
    )


@pytest.mark.parametrize(
    "name",
    ["../outside", "/absolute", "nested/../../outside", "", "."],
)
def test_build_path_rejects_unsafe_names(
    tmp_path: Path,
    name: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.build_path(name),
    )


def test_loading_rejects_a_mutated_staged_file(tmp_path: Path) -> None:
    project_root, squad_dir, _, staged, prepared = _sealed_write(tmp_path)
    staged.write_bytes(b"corrupt")

    _assert_error_code(
        "stage_corrupt",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


def test_loading_rejects_a_missing_staged_file(tmp_path: Path) -> None:
    project_root, squad_dir, _, staged, prepared = _sealed_write(tmp_path)
    staged.unlink()

    _assert_error_code(
        "stage_missing",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


def test_loading_rejects_a_missing_transaction_stage(tmp_path: Path) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(tmp_path)
    manifest_path = next(squad_dir.rglob("manifest.json"))
    transaction_root = manifest_path.parent
    for path in sorted(
        transaction_root.rglob("*"),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    transaction_root.rmdir()

    _assert_error_code(
        "stage_missing",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


def test_loading_rejects_manifest_bytes_that_do_not_match_marker(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(tmp_path)
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    _assert_error_code(
        "manifest_mismatch",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


@pytest.mark.parametrize(
    "marker",
    [
        {},
        {
            "schema_version": True,
            "transaction_id": TRANSACTION_ID,
            "manifest_sha256": "b" * 64,
        },
        {
            "schema_version": 1,
            "transaction_id": "A" * 32,
            "manifest_sha256": "b" * 64,
        },
        {
            "schema_version": 1,
            "transaction_id": TRANSACTION_ID,
            "manifest_sha256": "B" * 64,
        },
        {
            "schema_version": 1,
            "transaction_id": TRANSACTION_ID,
            "manifest_sha256": "b" * 64,
            "extra": 1,
        },
    ],
)
def test_loading_rejects_non_exact_marker(
    tmp_path: Path,
    marker: object,
) -> None:
    project_root, squad_dir = _roots(tmp_path)

    _assert_error_code(
        "manifest_invalid",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            marker,
        ),
    )


def _sealed_mixed_publication(
    tmp_path: Path,
) -> tuple[Path, Path, object, list[Path]]:
    project_root, squad_dir = _roots(tmp_path)
    (project_root / "b.txt").write_bytes(b"old b")
    (project_root / "c.txt").write_bytes(b"remove c")
    (project_root / "unrelated.txt").write_bytes(b"leave alone")
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged_a = _staged_file(transaction, "build/a.txt", b"new a")
    staged_b = _staged_file(transaction, "build/b.txt", b"new b")
    owned = {Path("a.txt"), Path("b.txt"), Path("c.txt")}
    transaction.add_delete(Path("c.txt"), owned_paths=owned)
    transaction.add_write(Path("b.txt"), staged_b, owned_paths=owned)
    transaction.add_write(Path("a.txt"), staged_a, owned_paths=owned)
    return (
        project_root,
        squad_dir,
        transaction.seal(),
        [staged_a, staged_b],
    )


def test_publish_installs_writes_and_deletes_only_exact_owned_files(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, staged = (
        _sealed_mixed_publication(tmp_path)
    )
    transaction_root = next(squad_dir.rglob("manifest.json")).parent

    prepared.publish()

    assert (project_root / "a.txt").read_bytes() == b"new a"
    assert (project_root / "b.txt").read_bytes() == b"new b"
    assert not (project_root / "c.txt").exists()
    assert (project_root / "unrelated.txt").read_bytes() == b"leave alone"
    assert transaction_root.is_dir()
    assert [path.read_bytes() for path in staged] == [b"new a", b"new b"]


def test_publish_creates_missing_target_directories_durably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/new.txt", b"new")
    transaction.add_write(
        Path("new/deep/value.txt"),
        staged,
        owned_paths={Path("new/deep/value.txt")},
    )
    prepared = transaction.seal()
    real_fsync = publication_module.os.fsync
    fsynced: list[int] = []

    def recording_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(publication_module.os, "fsync", recording_fsync)

    prepared.publish()

    assert (project_root / "new/deep/value.txt").read_bytes() == b"new"
    assert len(fsynced) >= 5


@pytest.mark.parametrize("fault_position", [0, 1, 2, 3])
def test_retry_after_each_operation_position_is_idempotent(
    tmp_path: Path,
    fault_position: int,
) -> None:
    project_root, squad_dir, prepared, _ = _sealed_mixed_publication(
        tmp_path
    )

    def fault_hook(position: int) -> None:
        if position == fault_position:
            raise RuntimeError(f"fault at {position}")

    _assert_error_code(
        "publish_io",
        lambda: prepared.publish(fault_hook=fault_hook),
    )
    assert (project_root / "unrelated.txt").read_bytes() == b"leave alone"
    assert next(squad_dir.rglob("manifest.json")).is_file()

    recovered = load_prepared_publication(
        project_root,
        squad_dir,
        prepared.marker.to_dict(),
    )
    recovered.publish()

    assert (project_root / "a.txt").read_bytes() == b"new a"
    assert (project_root / "b.txt").read_bytes() == b"new b"
    assert not (project_root / "c.txt").exists()
    assert (project_root / "unrelated.txt").read_bytes() == b"leave alone"


def test_retry_redurably_accepts_write_after_parent_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _, _, prepared = _sealed_write(
        tmp_path,
        old_content=b"old",
        new_content=b"new",
    )
    target = project_root / "published/result.txt"
    parent_inode = os.stat(target.parent).st_ino
    fsync_call = publication_module.os.fsync
    fstat_call = publication_module.os.fstat
    failed = False
    retrying = False
    retry_synced_inodes: list[int] = []

    def fail_once_then_record(fd: int) -> None:
        nonlocal failed
        metadata = fstat_call(fd)
        if retrying:
            retry_synced_inodes.append(metadata.st_ino)
        if (
            not failed
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_ino == parent_inode
            and target.read_bytes() == b"new"
        ):
            failed = True
            raise OSError("parent sync fault")
        fsync_call(fd)

    monkeypatch.setattr(
        publication_module.os,
        "fsync",
        fail_once_then_record,
    )

    _assert_error_code("publish_io", prepared.publish)
    assert target.read_bytes() == b"new"

    retrying = True
    prepared.publish()

    assert os.stat(target).st_ino in retry_synced_inodes
    assert parent_inode in retry_synced_inodes


def test_retry_redurably_accepts_delete_after_parent_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    target = project_root / "remove.txt"
    target.write_bytes(b"remove")
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    transaction.add_delete(
        Path("remove.txt"),
        owned_paths={Path("remove.txt")},
    )
    prepared = transaction.seal()
    parent_inode = os.stat(project_root).st_ino
    fsync_call = publication_module.os.fsync
    fstat_call = publication_module.os.fstat
    failed = False
    retrying = False
    retry_synced_inodes: list[int] = []

    def fail_once_then_record(fd: int) -> None:
        nonlocal failed
        metadata = fstat_call(fd)
        if retrying:
            retry_synced_inodes.append(metadata.st_ino)
        if (
            not failed
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_ino == parent_inode
            and not target.exists()
        ):
            failed = True
            raise OSError("parent sync fault")
        fsync_call(fd)

    monkeypatch.setattr(
        publication_module.os,
        "fsync",
        fail_once_then_record,
    )

    _assert_error_code("publish_io", prepared.publish)
    assert not target.exists()

    retrying = True
    prepared.publish()

    assert parent_inode in retry_synced_inodes
    assert not target.exists()


def test_missing_to_missing_delete_does_not_create_parent_directory(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    transaction.add_delete(
        Path("never/existed.txt"),
        owned_paths={Path("never/existed.txt")},
    )
    prepared = transaction.seal()

    prepared.publish()

    assert not (project_root / "never").exists()


def test_retry_syncs_full_target_chain_after_created_parent_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _, _, prepared = _sealed_write(
        tmp_path,
        target_name="new/deep/value.txt",
    )
    target = project_root / "new/deep/value.txt"
    root_inode = os.stat(project_root).st_ino
    fsync_call = publication_module.os.fsync
    fstat_call = publication_module.os.fstat
    failed = False
    retrying = False
    retry_synced_inodes: list[int] = []

    def fail_once_then_record(fd: int) -> None:
        nonlocal failed
        metadata = fstat_call(fd)
        if retrying:
            retry_synced_inodes.append(metadata.st_ino)
        if (
            not failed
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_ino == root_inode
            and (project_root / "new").is_dir()
        ):
            failed = True
            raise OSError("created parent sync fault")
        fsync_call(fd)

    monkeypatch.setattr(
        publication_module.os,
        "fsync",
        fail_once_then_record,
    )

    _assert_error_code("publish_io", prepared.publish)
    assert (project_root / "new").is_dir()
    assert not target.exists()

    retrying = True
    prepared.publish()

    assert root_inode in retry_synced_inodes
    assert os.stat(project_root / "new").st_ino in retry_synced_inodes
    assert os.stat(project_root / "new/deep").st_ino in (
        retry_synced_inodes
    )
    assert target.read_bytes() == b"new bytes\n"


@pytest.mark.parametrize(
    ("drift", "old_content"),
    [
        ("unexpected_creation", None),
        ("unexpected_deletion", b"old"),
        ("content", b"old"),
        ("directory", b"old"),
        ("symlink", b"old"),
        ("fifo", b"old"),
    ],
)
def test_publish_rejects_every_unexpected_target_drift(
    tmp_path: Path,
    drift: str,
    old_content: bytes | None,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    target = project_root / "target.txt"
    if old_content is not None:
        target.write_bytes(old_content)
    (project_root / "unrelated.txt").write_bytes(b"unchanged")
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/new.txt", b"new")
    transaction.add_write(
        Path("target.txt"),
        staged,
        owned_paths={Path("target.txt")},
    )
    prepared = transaction.seal()
    if drift == "unexpected_creation":
        target.write_bytes(b"intruder")
    elif drift == "unexpected_deletion":
        target.unlink()
    elif drift == "content":
        target.write_bytes(b"changed")
    elif drift == "directory":
        target.unlink()
        target.mkdir()
    elif drift == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "outside")
    else:
        target.unlink()
        os.mkfifo(target)

    _assert_error_code("target_drift", prepared.publish)

    assert (project_root / "unrelated.txt").read_bytes() == b"unchanged"
    assert staged.read_bytes() == b"new"
    assert next(squad_dir.rglob("manifest.json")).is_file()


@pytest.mark.parametrize("damage", ["missing", "corrupt", "special"])
def test_stage_preflight_failure_never_touches_an_earlier_target(
    tmp_path: Path,
    damage: str,
) -> None:
    project_root, squad_dir, prepared, staged = (
        _sealed_mixed_publication(tmp_path)
    )
    damaged = staged[1]
    if damage == "missing":
        damaged.unlink()
        expected_code = "stage_missing"
    elif damage == "corrupt":
        damaged.write_bytes(b"corrupt")
        expected_code = "stage_corrupt"
    else:
        damaged.unlink()
        os.mkfifo(damaged)
        expected_code = "stage_corrupt"

    _assert_error_code(expected_code, prepared.publish)

    assert not (project_root / "a.txt").exists()
    assert (project_root / "b.txt").read_bytes() == b"old b"
    assert (project_root / "c.txt").read_bytes() == b"remove c"
    assert (project_root / "unrelated.txt").read_bytes() == b"leave alone"
    assert next(squad_dir.rglob("manifest.json")).is_file()


def test_manifest_mismatch_at_publish_entry_never_touches_targets(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, _ = _sealed_mixed_publication(
        tmp_path
    )
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    _assert_error_code("manifest_mismatch", prepared.publish)

    assert not (project_root / "a.txt").exists()
    assert (project_root / "b.txt").read_bytes() == b"old b"
    assert (project_root / "c.txt").read_bytes() == b"remove c"


def test_stage_changed_after_entry_check_is_rejected_before_install(
    tmp_path: Path,
) -> None:
    project_root, _, prepared, staged = _sealed_mixed_publication(tmp_path)

    def mutate_stage(position: int) -> None:
        if position == 0:
            staged[0].write_bytes(b"changed after preflight")

    _assert_error_code(
        "stage_corrupt",
        lambda: prepared.publish(fault_hook=mutate_stage),
    )

    assert not (project_root / "a.txt").exists()
    assert (project_root / "b.txt").read_bytes() == b"old b"
    assert (project_root / "c.txt").read_bytes() == b"remove c"


def test_postimage_verification_failure_retains_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, _, staged, prepared = _sealed_write(
        tmp_path,
        old_content=b"old",
    )
    target = project_root / "published/result.txt"
    expected_digest = hashlib.sha256(b"new bytes\n").hexdigest()
    target_image = publication_module._target_image

    def incorrect_postimage(
        root: Path,
        relative: Path,
        *,
        invalid_code: str,
    ) -> dict[str, str]:
        image = target_image(root, relative, invalid_code=invalid_code)
        if image.get("sha256") == expected_digest:
            return {"kind": "file", "sha256": "0" * 64}
        return image

    monkeypatch.setattr(
        publication_module,
        "_target_image",
        incorrect_postimage,
    )

    _assert_error_code("target_drift", prepared.publish)

    assert staged.is_file()
    assert next(squad_dir.rglob("manifest.json")).is_file()


def test_publish_error_never_exposes_fault_text_or_paths(
    tmp_path: Path,
) -> None:
    project_root, _, prepared, _ = _sealed_mixed_publication(tmp_path)
    secret_path = project_root / "secret-name.txt"

    def fault_hook(position: int) -> None:
        raise OSError(f"do not expose {secret_path} at {position}")

    with pytest.raises(PublicationError) as raised:
        prepared.publish(fault_hook=fault_hook)

    assert raised.value.code == "publish_io"
    assert str(raised.value) == "publish_io"
    assert str(secret_path) not in str(raised.value)


def test_discard_removes_only_this_transaction_stage(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared, _ = _sealed_mixed_publication(tmp_path)
    transaction_root = next(squad_dir.rglob("manifest.json")).parent
    unrelated = transaction_root.parent / "keep"
    unrelated.mkdir()
    (unrelated / "value.txt").write_bytes(b"keep")

    prepared.discard()

    assert not transaction_root.exists()
    assert (unrelated / "value.txt").read_bytes() == b"keep"
    prepared.discard()


def test_discard_rechecks_pinned_transaction_before_final_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, squad_dir, prepared, _ = _sealed_mixed_publication(tmp_path)
    transaction_root = next(squad_dir.rglob("manifest.json")).parent
    moved_transaction = tmp_path / "moved-original-transaction"
    replacement_keep = transaction_root / "keep.txt"
    transaction_inode = os.stat(transaction_root).st_ino
    fstat_call = publication_module.os.fstat
    transaction_pinned = threading.Event()
    replacement_ready = threading.Event()
    injected = False

    def pausing_fstat(fd: int) -> os.stat_result:
        nonlocal injected
        metadata = fstat_call(fd)
        if (
            stat.S_ISDIR(metadata.st_mode)
            and metadata.st_ino == transaction_inode
            and not injected
        ):
            injected = True
            transaction_pinned.set()
            assert replacement_ready.wait(timeout=2)
        return metadata

    def substitute_transaction() -> None:
        assert transaction_pinned.wait(timeout=2)
        transaction_root.rename(moved_transaction)
        transaction_root.mkdir()
        replacement_keep.write_bytes(b"replacement")
        replacement_ready.set()

    substituter = threading.Thread(target=substitute_transaction)

    monkeypatch.setattr(
        publication_module.os, "fstat", pausing_fstat
    )
    substituter.start()

    _assert_error_code("stage_corrupt", prepared.discard)

    substituter.join(timeout=2)
    assert not substituter.is_alive()
    assert replacement_keep.read_bytes() == b"replacement"


def test_loading_rejects_manifest_symlink_swap_between_check_and_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(tmp_path)
    manifest_path = next(squad_dir.rglob("manifest.json"))
    original_manifest = manifest_path.read_bytes()
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_bytes(original_manifest)
    backup_manifest = tmp_path / "original-manifest.json"
    open_regular_at = publication_module._open_regular_at
    swapped = False

    def swapping_open_regular_at(*args, **kwargs) -> int:
        nonlocal swapped
        opened = open_regular_at(*args, **kwargs)
        if args[1] == Path("manifest.json") and not swapped:
            swapped = True
            manifest_path.rename(backup_manifest)
            manifest_path.symlink_to(outside_manifest)
        return opened

    monkeypatch.setattr(
        publication_module,
        "_open_regular_at",
        swapping_open_regular_at,
    )

    _assert_error_code(
        "manifest_invalid",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


def test_discard_rejects_replaced_outbox_ancestor_without_deleting_stage(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared, _ = _sealed_mixed_publication(tmp_path)
    outbox = next(squad_dir.rglob("manifest.json")).parent.parent
    moved_outbox = tmp_path / "moved-outbox"
    outbox.rename(moved_outbox)
    outbox.symlink_to(moved_outbox, target_is_directory=True)
    moved_transaction = moved_outbox / TRANSACTION_ID

    _assert_error_code("stage_corrupt", prepared.discard)

    assert (moved_transaction / "manifest.json").is_file()


def test_loading_empty_manifest_rejects_symlinked_outbox_ancestor(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    prepared = transaction.seal()
    outbox = next(squad_dir.rglob("manifest.json")).parent.parent
    moved_outbox = tmp_path / "moved-empty-outbox"
    outbox.rename(moved_outbox)
    outbox.symlink_to(moved_outbox, target_is_directory=True)

    _assert_error_code(
        "stage_corrupt",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


def test_stage_metadata_io_error_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _, _, prepared = _sealed_write(tmp_path)

    def failing_fstat(fd: int) -> os.stat_result:
        raise OSError(f"do not expose {project_root}")

    monkeypatch.setattr(publication_module.os, "fstat", failing_fstat)

    _assert_error_code("publish_io", prepared.publish)


def test_stage_copy_metadata_io_error_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _, _, prepared = _sealed_write(tmp_path)
    real_fstat = publication_module.os.fstat
    copy_stage = publication_module._copy_pinned_stage_to_temporary

    def copy_with_failing_fstat(
        pinned,
        parent_fd: int,
        expected_digest: str,
        expected_mode: int,
    ) -> str:
        def failing_fstat(fd: int) -> os.stat_result:
            if fd == pinned.fd:
                raise OSError(f"do not expose {project_root}")
            return real_fstat(fd)

        publication_module.os.fstat = failing_fstat
        try:
            return copy_stage(pinned, parent_fd, expected_digest, expected_mode)
        finally:
            publication_module.os.fstat = real_fstat

    monkeypatch.setattr(
        publication_module,
        "_copy_pinned_stage_to_temporary",
        copy_with_failing_fstat,
    )

    _assert_error_code("stage_corrupt", prepared.publish)


def test_prepared_publication_capability_is_immutable(
    tmp_path: Path,
) -> None:
    _, _, _, _, prepared = _sealed_write(tmp_path)

    with pytest.raises(FrozenInstanceError):
        prepared.marker = PublicationMarker(  # type: ignore[misc]
            schema_version=1,
            transaction_id="b" * 32,
            manifest_sha256="c" * 64,
        )


@pytest.mark.parametrize("hostile_id", ["absolute", "parent"])
def test_discard_revalidates_hostile_mutated_marker_before_deletion(
    tmp_path: Path,
    hostile_id: str,
) -> None:
    _, squad_dir, _, _, prepared = _sealed_write(tmp_path)
    if hostile_id == "absolute":
        victim = tmp_path / "absolute-victim"
        transaction_id = str(victim)
    else:
        victim = squad_dir / "parent-victim"
        transaction_id = "../parent-victim"
    victim.mkdir()
    (victim / "keep.txt").write_bytes(b"keep")
    object.__setattr__(
        prepared,
        "marker",
        PublicationMarker(
            schema_version=1,
            transaction_id=transaction_id,
            manifest_sha256="c" * 64,
        ),
    )

    _assert_error_code("manifest_invalid", prepared.discard)

    assert (victim / "keep.txt").read_bytes() == b"keep"


@pytest.mark.parametrize("action", [[], {}])
def test_loading_bounds_unhashable_manifest_action(
    tmp_path: Path,
    action: object,
) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(tmp_path)
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    manifest["operations"][0]["action"] = action
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    marker = PublicationMarker(
        schema_version=1,
        transaction_id=prepared.marker.transaction_id,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )

    _assert_error_code(
        "manifest_invalid",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            marker,
        ),
    )


@pytest.mark.parametrize("protected_kind", ["outbox", "control"])
def test_builder_rejects_publication_control_namespace_targets(
    tmp_path: Path,
    protected_kind: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    staged = _staged_file(transaction, "build/value.txt", b"value")
    if protected_kind == "outbox":
        target = staged.relative_to(project_root)
    else:
        target = Path(".echelon/runtime/publication.lock")

    _assert_error_code(
        "manifest_invalid",
        lambda: transaction.add_write(
            target,
            staged,
            owned_paths={target},
        ),
    )


def test_loading_rejects_manifest_targeting_its_own_transaction(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(
        project_root,
        squad_dir,
        TRANSACTION_ID,
    )
    prepared = transaction.seal()
    manifest_path = next(squad_dir.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    manifest["operations"] = [
        {
            "action": "delete",
            "target": manifest_path.relative_to(project_root).as_posix(),
            "preimage": {"kind": "file", "sha256": "0" * 64},
            "postimage": {"kind": "missing"},
        }
    ]
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    marker = PublicationMarker(
        schema_version=1,
        transaction_id=prepared.marker.transaction_id,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )

    _assert_error_code(
        "manifest_invalid",
        lambda: load_prepared_publication(
            project_root,
            squad_dir,
            marker,
        ),
    )


def test_intermediate_stage_symlink_swap_fails_before_target_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(
        tmp_path,
        target_name="new/deep/value.txt",
        new_content=b"expected",
    )
    transaction_root = next(squad_dir.rglob("manifest.json")).parent
    staged_parent = transaction_root / "build"
    moved_stage = tmp_path / "moved-stage"
    outside_stage = tmp_path / "outside-stage"
    outside_stage.mkdir()
    (outside_stage / "result.txt").write_bytes(b"expected")
    open_directory = publication_module._open_directory
    swapped = False

    def swapping_open_directory(*args, **kwargs) -> int:
        nonlocal swapped
        opened = open_directory(*args, **kwargs)
        if args[0] == "build" and not swapped:
            swapped = True
            staged_parent.rename(moved_stage)
            staged_parent.symlink_to(
                outside_stage,
                target_is_directory=True,
            )
        return opened

    monkeypatch.setattr(
        publication_module,
        "_open_directory",
        swapping_open_directory,
    )

    _assert_error_code("stage_corrupt", prepared.publish)

    assert not (project_root / "new").exists()


def test_outbox_swap_after_descriptor_open_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, _, _, prepared = _sealed_write(
        tmp_path,
        target_name="new/deep/value.txt",
    )
    outbox = next(squad_dir.rglob("manifest.json")).parent.parent
    outbox_inode = os.stat(outbox).st_ino
    moved_outbox = tmp_path / "moved-open-outbox"
    fstat_call = publication_module.os.fstat
    outbox_pinned = threading.Event()
    replacement_ready = threading.Event()
    injected = False

    def pausing_fstat(fd: int) -> os.stat_result:
        nonlocal injected
        metadata = fstat_call(fd)
        if (
            stat.S_ISDIR(metadata.st_mode)
            and metadata.st_ino == outbox_inode
            and not injected
        ):
            injected = True
            outbox_pinned.set()
            assert replacement_ready.wait(timeout=2)
        return metadata

    def substitute_outbox() -> None:
        assert outbox_pinned.wait(timeout=2)
        outbox.rename(moved_outbox)
        outbox.mkdir()
        replacement_ready.set()

    substituter = threading.Thread(target=substitute_outbox)
    monkeypatch.setattr(
        publication_module.os,
        "fstat",
        pausing_fstat,
    )
    substituter.start()

    _assert_error_code("stage_corrupt", prepared.publish)

    substituter.join(timeout=2)
    assert not substituter.is_alive()
    assert not (project_root / "new").exists()
    assert (moved_outbox / TRANSACTION_ID / "manifest.json").is_file()


def test_missing_stage_preflight_creates_no_target_directories(
    tmp_path: Path,
) -> None:
    project_root, _, _, staged, prepared = _sealed_write(
        tmp_path,
        target_name="new/deep/value.txt",
    )
    staged.unlink()

    _assert_error_code("stage_missing", prepared.publish)

    assert not (project_root / "new").exists()


def test_missing_secure_posix_capability_fails_closed_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _, _, prepared = _sealed_write(
        tmp_path,
        target_name="new/deep/value.txt",
    )
    monkeypatch.setattr(
        publication_module,
        "_secure_posix_capabilities_available",
        lambda: False,
        raising=False,
    )

    _assert_error_code("publish_io", prepared.publish)

    assert not (project_root / "new").exists()


def test_cooperating_publishers_serialize_precheck_and_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    squad_dirs = (
        project_root / ".echelon" / "runs" / "run-a",
        project_root / ".echelon" / "runs" / "run-b",
    )
    for squad_dir in squad_dirs:
        squad_dir.mkdir(parents=True)
    prepared = []
    for squad_dir, transaction_id, content in (
        (squad_dirs[0], "a" * 32, b"first"),
        (squad_dirs[1], "b" * 32, b"second"),
    ):
        transaction = SquadPublicationTransaction.begin(
            project_root,
            squad_dir,
            transaction_id,
        )
        staged = _staged_file(
            transaction,
            "build/value.txt",
            content,
        )
        transaction.add_write(
            Path("value.txt"),
            staged,
            owned_paths={Path("value.txt")},
        )
        prepared.append(transaction.seal())

    first_at_preimage = threading.Event()
    first_completed = threading.Event()
    preimage_barrier = threading.Barrier(2)
    target_image_at = publication_module._target_image_at
    replace = publication_module.os.replace

    def coordinated_target_image_at(
        parent_fd: int,
        name: str,
    ) -> dict[str, str]:
        image = target_image_at(parent_fd, name)
        if image == {"kind": "missing"}:
            if threading.current_thread().name == "first-publisher":
                first_at_preimage.set()
            try:
                preimage_barrier.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
        return image

    def coordinated_replace(src, dst, *args, **kwargs) -> None:
        if (
            threading.current_thread().name == "second-publisher"
            and str(src).startswith(".echelon-publish-")
        ):
            first_completed.wait(timeout=2)
        replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(
        publication_module,
        "_target_image_at",
        coordinated_target_image_at,
    )
    monkeypatch.setattr(
        publication_module.os,
        "replace",
        coordinated_replace,
    )
    results: dict[str, str | None] = {}

    def run_publication(name: str, publication) -> None:
        try:
            publication.publish()
        except PublicationError as error:
            results[name] = error.code
        else:
            results[name] = None
        finally:
            if name == "first":
                first_completed.set()

    first = threading.Thread(
        target=run_publication,
        args=("first", prepared[0]),
        name="first-publisher",
    )
    second = threading.Thread(
        target=run_publication,
        args=("second", prepared[1]),
        name="second-publisher",
    )
    first.start()
    assert first_at_preimage.wait(timeout=2)
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(
        results.values(),
        key=lambda value: "" if value is None else value,
    ) == [None, "target_drift"]
    assert (project_root / "value.txt").read_bytes() in {
        b"first",
        b"second",
    }

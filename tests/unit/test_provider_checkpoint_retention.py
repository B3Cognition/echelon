"""A revisit may retain bytes proven by completed, authorized owner phases."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import harness.squad as squad
from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    PhaseCheckpointError,
    accepted_checkpoint_outputs,
    record_phase_checkpoint,
)
from harness.provider_dispatch_finalizer import (
    ProviderDispatchContext,
    ProviderDispatchFailure,
    ProviderDispatchFinalizer,
)
from harness.provider_output_publication import (
    compile_provider_artifact_contract,
    resolve_provider_artifact_contract,
)
from harness.squad import _required_active_spec_output_proofs
from harness.squad_state import StateAdvanceError, _validated_provider_output_proofs
from harness.squad_provider import SquadAgentResult


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_completion_proof_keeps_only_published_required_spec_outputs() -> None:
    digest = "a" * 64
    execution = SimpleNamespace(receipts=({
        "outcome": "published",
        "outputs": [
            {"root": "active_spec", "path": "glossary.md", "kind": "file",
             "requirement": "required", "sha256": digest},
            {"root": "active_spec", "path": "optional.md", "kind": "file",
             "requirement": "optional", "sha256": digest},
            {"root": "squad", "path": "notes.md", "kind": "file",
             "requirement": "required", "sha256": digest},
        ],
    }, {
        "outcome": "domain_blocked",
        "outputs": [{"root": "active_spec", "path": "blocked.md", "kind": "file",
                     "requirement": "required", "sha256": digest}],
    }))
    proofs = _required_active_spec_output_proofs(execution)
    assert proofs == ({"path": "glossary.md", "kind": "file", "sha256": digest},)
    assert _validated_provider_output_proofs(proofs) == list(proofs)
    with pytest.raises(StateAdvanceError, match="provider output proof is invalid"):
        _validated_provider_output_proofs(({
            "path": "../outside.md", "kind": "file", "sha256": digest,
        },))


def test_optional_completion_proof_keeps_only_published_spec_outputs() -> None:
    digest = "a" * 64
    execution = SimpleNamespace(receipts=({
        "outcome": "published",
        "outputs": [
            {"root": "active_spec", "path": "reference-architectures.md", "kind": "file",
             "requirement": "optional", "sha256": digest},
            {"root": "active_spec", "path": "glossary.md", "kind": "file",
             "requirement": "required", "sha256": digest},
            {"root": "squad", "path": "notes.md", "kind": "file",
             "requirement": "optional", "sha256": digest},
        ],
    }, {
        "outcome": "domain_blocked",
        "outputs": [{"root": "active_spec", "path": "blocked.md", "kind": "file",
                     "requirement": "optional", "sha256": digest}],
    }))
    assert squad._optional_active_spec_output_proofs(execution) == (
        {"path": "reference-architectures.md", "kind": "file", "sha256": digest},
    )


def test_completion_proof_uses_final_sealed_write_after_consensus_revalidation() -> None:
    initial = "a" * 64
    final = "b" * 64
    execution = SimpleNamespace(receipts=({
        "outcome": "published",
        "outputs": [
            {"root": "active_spec", "path": "issues.md", "kind": "file",
             "requirement": "required", "sha256": initial},
            {"root": "active_spec", "path": "quality-gates.md", "kind": "file",
             "requirement": "required", "sha256": initial},
        ],
    }, {
        "outcome": "published",
        "outputs": [
            {"root": "active_spec", "path": "issues.md", "kind": "file",
             "requirement": "required", "sha256": final},
            {"root": "active_spec", "path": "quality-gates.md", "kind": "file",
             "requirement": "required", "sha256": final},
        ],
    }))

    proofs = _required_active_spec_output_proofs(execution)
    assert proofs == (
        {"path": "issues.md", "kind": "file", "sha256": final},
        {"path": "quality-gates.md", "kind": "file", "sha256": final},
    )
    assert _validated_provider_output_proofs(proofs) == list(proofs)


def test_completion_proof_preserves_required_obligation_after_optional_rewrite() -> None:
    initial = "a" * 64
    final = "b" * 64
    execution = SimpleNamespace(receipts=({
        "outcome": "published",
        "outputs": [{"root": "active_spec", "path": "report.md", "kind": "file",
                     "requirement": "required", "sha256": initial}],
    }, {
        "outcome": "published",
        "outputs": [{"root": "active_spec", "path": "report.md", "kind": "file",
                     "requirement": "optional", "sha256": final}],
    }))

    assert _required_active_spec_output_proofs(execution) == (
        {"path": "report.md", "kind": "file", "sha256": final},
    )
    assert squad._optional_active_spec_output_proofs(execution) == ()


def test_revisit_retains_only_receipt_proven_optional_output(
    tmp_path: Path,
) -> None:
    root = tmp_path
    spec = root / "specs/game"
    spec.mkdir(parents=True)
    target = spec / "reference-architectures.md"
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "commit", "--allow-empty", "-qm", "initial")
    target.write_text("accepted architecture\n", encoding="utf-8")
    digest = hashlib.sha256(b"accepted architecture\n").hexdigest()
    completion_id = "a" * 32
    message = build_echelon_commit_message(
        "echelon-checkpoint: game phase1-discover",
        EchelonCommitMetadata(
            origin="phase-a", action="checkpoint", spec_id="game", run_id="run-1",
            phase="phase1-discover", next_phase="phase1-synthesizer",
            checkpoint_id="phase1-discover", completion_id=completion_id,
            checkpoint_source="auto",
        ),
    )
    _git(root, "add", "--", "specs/game/reference-architectures.md")
    _git(root, "commit", "-qm", message)
    record_phase_checkpoint(
        spec,
        PhaseCheckpoint(
            id="phase1-discover", spec_id="game", phase="phase1-discover",
            next_phase="phase1-synthesizer", commit=_git(root, "rev-parse", "HEAD"),
            metadata_commit="", source="auto", run_id="run-1",
            created_at="2026-09-28T00:00:00+00:00",
            completion_id=completion_id, boundary_completion_id=completion_id,
        ),
    )
    outcome = {
        "phase": "phase1-discover", "next_phase": "phase1-synthesizer",
        "completion_id": completion_id, "outcome": "executed", "checkpoint": "required",
        "optional_provider_outputs": [{"path": target.name, "kind": "file", "sha256": digest}],
    }
    state = {"run_id": "run-1", "spec_id": "game", "phase_completion_outcomes": [outcome]}
    artifacts = ((target.name, "file", "optional"),)

    assert accepted_checkpoint_outputs(root, spec, state, "phase1-discover", artifacts) == (
        ("active_spec", target.name, digest),
    )

    contract = compile_provider_artifact_contract(
        {"mode": "publish", "artifacts": [
            {"root": "active_spec", "path": target.name, "kind": "file", "requirement": "optional"},
        ]},
        assignment_id="phase1-discover",
    )
    context = ProviderDispatchContext(
        phase_id="phase1-discover", assignment_id="phase1-discover",
        occurrence_id="revisit", state_revision=7,
        contract=resolve_provider_artifact_contract(
            contract, assignment_id="phase1-discover",
            roots={"active_spec": spec, "project": root, "squad": root / "runs/run-1"},
        ),
        prompt_sha256="a" * 64, prompt_metadata_sha256="b" * 64,
        previously_accepted_outputs=accepted_checkpoint_outputs(
            root, spec, state, "phase1-discover", artifacts,
        ),
    )

    def result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS", "state_updates": {}, "journal_entries": [],
                "output_files": [str(target)],
            },
            raw_output="", duration_ms=0, timed_out=False,
        )

    finalized = ProviderDispatchFinalizer().dispatch(
        context, execute=lambda _permissions: result(),
        validate_result=lambda value: value, classify_outcome=lambda _value: "published",
    )
    assert finalized.receipt.outputs[0]["evidence_kind"] == "retained"

    del outcome["optional_provider_outputs"]
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-discover", artifacts) == ()
    with pytest.raises(ProviderDispatchFailure, match="stale claimed output"):
        ProviderDispatchFinalizer().dispatch(
            replace(context, previously_accepted_outputs=()),
            execute=lambda _permissions: result(),
            validate_result=lambda value: value, classify_outcome=lambda _value: "published",
        )

    outcome["optional_provider_outputs"] = [
        {"path": target.name, "kind": "file", "sha256": digest},
    ]
    target.write_text("unaccepted retry\n", encoding="utf-8")
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-discover", artifacts) == (
        ("active_spec", target.name, digest),
    )
    with pytest.raises(ProviderDispatchFailure, match="stale claimed output"):
        ProviderDispatchFinalizer().dispatch(
            context, execute=lambda _permissions: result(),
            validate_result=lambda value: value, classify_outcome=lambda _value: "published",
        )

    outcome["optional_provider_outputs"][0]["sha256"] = "b" * 64
    with pytest.raises(PhaseCheckpointError, match="proof digest drift"):
        accepted_checkpoint_outputs(root, spec, state, "phase1-discover", artifacts)


def test_only_matching_completed_phase_checkpoint_supplies_prior_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path
    spec = root / "specs/game"
    spec.mkdir(parents=True)
    target = spec / "issues.md"
    target.write_text("accepted\n", encoding="utf-8")
    directory = spec / "reports"
    directory.mkdir()
    (directory / "report.md").write_text("report\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (spec / "optional.md").write_text("inherited\n", encoding="utf-8")
    _git(root, "add", "--", "specs/game/optional.md")
    _git(root, "commit", "--allow-empty", "-qm", "initial")
    _git(root, "add", "--", "specs/game/issues.md", "specs/game/reports/report.md")
    completion_id = "a" * 32
    message = build_echelon_commit_message(
        "echelon-checkpoint: game phase1-why2",
        EchelonCommitMetadata(
            origin="phase-a", action="checkpoint", spec_id="game", run_id="run-1",
            phase="phase1-why2", next_phase="phase1-why3",
            checkpoint_id="phase1-why2", completion_id=completion_id,
            checkpoint_source="auto",
        ),
    )
    _git(root, "commit", "-qm", message)
    commit = _git(root, "rev-parse", "HEAD")
    record_phase_checkpoint(
        spec,
        PhaseCheckpoint(
            id="phase1-why2", spec_id="game", phase="phase1-why2",
            next_phase="phase1-why3", commit=commit, metadata_commit="",
            source="auto", run_id="run-1", created_at="2026-09-28T00:00:00+00:00",
            completion_id=completion_id, boundary_completion_id=completion_id,
        ),
    )
    state = {
        "run_id": "run-1", "spec_id": "game",
        "phase_completion_outcomes": [
            {"phase": "phase1-why2", "next_phase": "phase1-why3",
             "completion_id": completion_id, "outcome": "executed", "checkpoint": "required"}
        ],
    }
    artifacts = (
        ("issues.md", "file", "required"),
        ("reports", "directory", "required"),
        ("optional.md", "file", "optional"),
    )
    report_digest = hashlib.sha256(b"report\n").hexdigest()
    directory_digest = hashlib.sha256(
        json.dumps([["report.md", report_digest]], separators=(",", ":")).encode()
    ).hexdigest()

    assert accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts) == (
        ("active_spec", "issues.md", hashlib.sha256(b"accepted\n").hexdigest()),
        ("active_spec", "reports", directory_digest),
    )
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-why1", artifacts) == ()

    contract = compile_provider_artifact_contract(
        {"mode": "publish", "artifacts": [
            {"root": "active_spec", "path": path, "kind": kind, "requirement": requirement}
            for path, kind, requirement in artifacts
        ]},
        assignment_id="phase1-why2",
    )
    resolved = resolve_provider_artifact_contract(
        contract, assignment_id="phase1-why2",
        roots={"active_spec": spec, "project": root, "squad": root / "runs/run-1"},
    )
    context = ProviderDispatchContext(
        phase_id="phase1-why2", assignment_id="phase1-why2", occurrence_id="ordinary",
        state_revision=7, contract=resolved, prompt_sha256="a" * 64,
        prompt_metadata_sha256="b" * 64,
        previously_accepted_outputs=accepted_checkpoint_outputs(
            root, spec, state, "phase1-why2", artifacts,
        ),
    )

    def result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0, echelon_result={
                "verdict": "PASS", "state_updates": {}, "journal_entries": [],
                "output_files": [str(target), str(directory / "report.md")],
            }, raw_output="", duration_ms=0, timed_out=False,
        )

    finalized = ProviderDispatchFinalizer().dispatch(
        context, execute=lambda _permissions: result(),
        validate_result=lambda value: value, classify_outcome=lambda _value: "published",
    )
    assert [row["evidence_kind"] for row in finalized.receipt.outputs] == [
        "retained", "retained",
    ]

    target.write_text("unaccepted retry\n", encoding="utf-8")
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts) == (
        ("active_spec", "issues.md", hashlib.sha256(b"accepted\n").hexdigest()),
        ("active_spec", "reports", directory_digest),
    )
    with pytest.raises(ProviderDispatchFailure, match="stale claimed output"):
        ProviderDispatchFinalizer().dispatch(
            context, execute=lambda _permissions: result(),
            validate_result=lambda value: value, classify_outcome=lambda _value: "published",
        )

    # A no-change completion has no new checkpoint row; keep the last proof.
    state["phase_completion_outcomes"].append({
        "phase": "phase1-why2", "next_phase": "phase1-why3",
        "completion_id": "b" * 32, "outcome": "executed", "checkpoint": "required",
    })
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts) == (
        ("active_spec", "issues.md", hashlib.sha256(b"accepted\n").hexdigest()),
        ("active_spec", "reports", directory_digest),
    )

    # The state marker alone is not enough to authorize stale output.
    state["phase_completion_outcomes"][0]["completion_id"] = "b" * 32
    assert accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts) == ()

    state["phase_completion_outcomes"][0]["completion_id"] = completion_id
    state["run_id"] = "other-run"
    with pytest.raises(PhaseCheckpointError, match="identity drift"):
        accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts)

    # A real committed completion with a missing ledger row is not no-change.
    state["run_id"] = "run-1"
    missing_completion_id = "c" * 32
    state["phase_completion_outcomes"][-1]["completion_id"] = missing_completion_id
    _git(root, "add", "--", "specs/game/issues.md")
    missing_message = build_echelon_commit_message(
        "echelon-checkpoint: game phase1-why2",
        EchelonCommitMetadata(
            origin="phase-a", action="checkpoint", spec_id="game", run_id="run-1",
            phase="phase1-why2", next_phase="phase1-why3",
            checkpoint_id="phase1-why2", completion_id=missing_completion_id,
            checkpoint_source="auto",
        ),
    )
    _git(root, "commit", "-qm", missing_message)
    with pytest.raises(PhaseCheckpointError, match="row is missing"):
        accepted_checkpoint_outputs(root, spec, state, "phase1-why2", artifacts)


@pytest.mark.parametrize(
    ("revisited_requirement", "own_phase_published"),
    [("required", True), ("optional", True), ("optional", False)],
)
def test_revisit_retains_artifact_from_later_completed_required_owner(
    tmp_path: Path,
    revisited_requirement: str,
    own_phase_published: bool,
) -> None:
    root = tmp_path
    spec = root / "specs/game"
    spec.mkdir(parents=True)
    target = spec / "glossary.md"
    target.write_text("scout version\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "commit", "--allow-empty", "-qm", "initial")

    outcomes = []
    for phase, next_phase, completion_id, text in (
        ("phase1-discover", "phase1-synthesizer", "a" * 32, "scout version\n"),
        ("phase1-synthesizer", "phase1-modeler", "b" * 32, "synth version\n"),
    ):
        target.write_text(text, encoding="utf-8")
        _git(root, "add", "--", "specs/game/glossary.md")
        message = build_echelon_commit_message(
            f"echelon-checkpoint: game {phase}",
            EchelonCommitMetadata(
                origin="phase-a", action="checkpoint", spec_id="game", run_id="run-1",
                phase=phase, next_phase=next_phase, checkpoint_id=phase,
                completion_id=completion_id, checkpoint_source="auto",
            ),
        )
        _git(root, "commit", "-qm", message)
        record_phase_checkpoint(
            spec,
            PhaseCheckpoint(
                id=phase, spec_id="game", phase=phase, next_phase=next_phase,
                commit=_git(root, "rev-parse", "HEAD"), metadata_commit="",
                source="auto", run_id="run-1", created_at="2026-09-28T00:00:00+00:00",
                completion_id=completion_id, boundary_completion_id=completion_id,
            ),
        )
        outcomes.append({
            "phase": phase, "next_phase": next_phase, "completion_id": completion_id,
            "outcome": "executed", "checkpoint": "required",
        })

    if revisited_requirement == "optional" and own_phase_published:
        outcomes[0]["optional_provider_outputs"] = [{
            "path": "glossary.md", "kind": "file",
            "sha256": hashlib.sha256(b"scout version\n").hexdigest(),
        }]
    outcomes[1]["required_provider_outputs"] = [{
        "path": "glossary.md", "kind": "file",
        "sha256": hashlib.sha256(b"synth version\n").hexdigest(),
    }]
    state = {"run_id": "run-1", "spec_id": "game", "phase_completion_outcomes": outcomes}
    artifacts = (("glossary.md", "file", revisited_requirement),)
    assert accepted_checkpoint_outputs(
        root, spec, state, "phase1-discover", artifacts,
    ) == (("active_spec", "glossary.md", hashlib.sha256(b"synth version\n").hexdigest()),)

    contract = compile_provider_artifact_contract(
        {"mode": "publish", "artifacts": [
            {"root": "active_spec", "path": "glossary.md", "kind": "file",
             "requirement": revisited_requirement},
        ]},
        assignment_id="phase1-discover",
    )
    resolved = resolve_provider_artifact_contract(
        contract, assignment_id="phase1-discover",
        roots={"active_spec": spec, "project": root, "squad": root / "runs/run-1"},
    )
    context = ProviderDispatchContext(
        phase_id="phase1-discover", assignment_id="phase1-discover",
        occurrence_id="revisit", state_revision=7, contract=resolved,
        prompt_sha256="a" * 64, prompt_metadata_sha256="b" * 64,
        previously_accepted_outputs=accepted_checkpoint_outputs(
            root, spec, state, "phase1-discover", artifacts,
        ),
    )

    def result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS", "state_updates": {}, "journal_entries": [],
                "output_files": [str(target)],
            },
            raw_output="", duration_ms=0, timed_out=False,
        )

    finalized = ProviderDispatchFinalizer().dispatch(
        context, execute=lambda _permissions: result(),
        validate_result=lambda value: value, classify_outcome=lambda _value: "published",
    )
    assert finalized.receipt.outputs[0]["evidence_kind"] == "retained"

    # Merely having the newer bytes in the workspace does not authorize a retry.
    target.write_text("unaccepted retry\n", encoding="utf-8")
    assert accepted_checkpoint_outputs(
        root, spec, state, "phase1-discover", artifacts,
    ) == (("active_spec", "glossary.md", hashlib.sha256(b"synth version\n").hexdigest()),)
    with pytest.raises(ProviderDispatchFailure, match="stale claimed output"):
        ProviderDispatchFinalizer().dispatch(
            context, execute=lambda _permissions: result(),
            validate_result=lambda value: value, classify_outcome=lambda _value: "published",
        )

    # A later checkpoint without its original accepted-output proof cannot
    # retroactively become an owner after a workflow contract change.
    del outcomes[1]["required_provider_outputs"]
    assert accepted_checkpoint_outputs(
        root, spec, state, "phase1-discover", artifacts,
    ) == (
        (("active_spec", "glossary.md", hashlib.sha256(b"scout version\n").hexdigest()),)
        if own_phase_published else ()
    )

"""Checkpoint metadata is an authenticated projection, never an ignored tree."""
import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_discovery_normal_entry import (
    case, enrolled, turn_prepared, prepared, controller, selection, FullDiscoveryExecutor, Interrupted,
)


@pytest.fixture
def checkpoint_case(prepared):
    root, store, _, _ = prepared
    for command in (["git", "init", "-q"], ["git", "config", "user.name", "Test"],
                    ["git", "config", "user.email", "test@example.invalid"],
                    ["git", "commit", "--allow-empty", "-m", "Initial"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    state = store.load()
    state.update(spec_dir="specs/game", checkpoint_policy_version=2, phase_completion_outcomes=[])
    store.save(state)
    return prepared


def interrupt_checkpoint(case, executor, monkeypatch, point):
    from harness import squad, phase_checkpoints
    ctrl = controller(case, executor)
    with monkeypatch.context() as patch:
        if point in {"before_checkpoint", "after_commit", "after_ledger"}:
            original = phase_checkpoints.create_or_recover_completion_checkpoint
            def apply(*args, **kwargs):
                if point == "before_checkpoint":
                    raise Interrupted()
                def fault(observed):
                    if observed == point:
                        raise Interrupted()
                kwargs["fault_hook"] = fault
                return original(*args, **kwargs)
            patch.setattr(phase_checkpoints, "create_or_recover_completion_checkpoint", apply)
        else:
            original = squad.persist_completion_effect_receipt
            def persist(completion, effect, receipt):
                if effect == "checkpoint" and point == "before_receipt":
                    raise Interrupted()
                result = original(completion, effect, receipt)
                if effect == "checkpoint" and point == "after_receipt":
                    raise Interrupted()
                return result
            patch.setattr(squad, "persist_completion_effect_receipt", persist)
        with pytest.raises(Interrupted):
            ctrl.run(managed_discovery=selection(case), create_managed_discovery=True)


@pytest.mark.parametrize("point", ["before_checkpoint", "after_commit", "after_ledger", "before_receipt", "after_receipt"])
def test_checkpoint_restart_keeps_one_commit_and_releases_identity(checkpoint_case, monkeypatch, point):
    executor = FullDiscoveryExecutor()
    interrupt_checkpoint(checkpoint_case, executor, monkeypatch, point)
    result = controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case))
    state = checkpoint_case[1].load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True, result
    assert state["token_usage"] == 21 and len(executor.calls) == 3
    ledger = json.loads((checkpoint_case[0] / "specs/game/.echelon/checkpoints.json").read_bytes())
    assert len(ledger["checkpoints"]) == 1
    commits = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=checkpoint_case[0],
        check=True, capture_output=True, text=True).stdout.strip()
    assert commits == "2"
    assert checkpoint_case[2].pending_identity_publication(spec_id="game") is None


@pytest.mark.parametrize("damage", ["ledger_missing", "lock_missing", "ledger_row", "extra_row", "unknown_field",
    "ledger_mode", "lock_content", "directory_mode", "extra_file", "artifact", "symlink"])
def test_checkpoint_receipt_does_not_authorize_tampering(checkpoint_case, monkeypatch, damage):
    executor = FullDiscoveryExecutor()
    interrupt_checkpoint(checkpoint_case, executor, monkeypatch, "after_receipt")
    spec = checkpoint_case[0] / "specs/game"
    ledger = spec / ".echelon/checkpoints.json"
    lock = spec / ".echelon/checkpoints.lock"
    if damage == "ledger_missing": ledger.unlink()
    elif damage == "lock_missing": lock.unlink()
    elif damage == "ledger_mode": ledger.chmod(0o644)
    elif damage == "directory_mode": ledger.parent.chmod(0o755)
    elif damage == "lock_content": lock.write_bytes(b"arbitrary metadata")
    elif damage == "extra_file": (ledger.parent / "surprise.md").write_text("U-999999")
    elif damage == "artifact": (spec / "unknowns.md").write_text("### U-999999: Changed subject")
    elif damage == "symlink":
        content = ledger.read_bytes()
        other = checkpoint_case[0] / "other-ledger.json"
        other.write_bytes(content)
        ledger.unlink()
        ledger.symlink_to(other)
    else:
        value = json.loads(ledger.read_bytes())
        if damage == "ledger_row": value["checkpoints"][0]["phase"] = "phase1-what"
        elif damage == "extra_row": value["checkpoints"].append(value["checkpoints"][0])
        else: value["extra"] = "not authorized"
        ledger.write_text(json.dumps(value, indent=2) + "\n")
    result = controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case))
    assert result.status == "blocked"
    state = checkpoint_case[1].load()
    assert state["last_dispatch"]["post_dispatch_complete"] is False, result
    assert checkpoint_case[2].pending_identity_publication(spec_id="game")["state"] == "applied"
    assert len(executor.calls) == 3


def test_released_checkpoint_projection_survives_outbox_cleanup(checkpoint_case):
    from harness import discovery_completion
    from harness.squad_source_snapshot import inspect_project_tree
    from harness.squad_source_manifest import snapshot_source_manifest
    executor = FullDiscoveryExecutor()
    controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    root, store, identity, _ = checkpoint_case
    state = store.load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert not list((store.squad_dir / ".completion-outbox").iterdir())
    project = discovery_completion.released_checkpoint_projector(root, store.squad_dir, state)
    with inspect_project_tree(root, "specs/game") as sources:
        assert any(item.path.endswith("/checkpoints.json") for item in sources.files)
        artifacts = project(sources)
    assert all("/.echelon/" not in item.path for item in artifacts.files)
    manifest = snapshot_source_manifest(trees=(artifacts,), files=())
    observed = identity.check_managed_context(spec_id="game", run_id="first", record=state["managed_identity"])
    assert observed["source_context"]["manifest"]["payload"] == manifest.payload
    (root / "specs/game/.echelon/checkpoints.json").write_text("{}")
    with pytest.raises(ValueError):
        with inspect_project_tree(root, "specs/game") as changed:
            project(changed)


def test_checkpoint_target_cannot_be_selected_from_foreign_state(checkpoint_case):
    root, store, _, _ = checkpoint_case
    (root / "specs/foreign").mkdir()
    state = store.load()
    state["spec_dir"] = "specs/foreign"
    store.save(state)
    before = store.load()
    executor = FullDiscoveryExecutor()
    result = controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    assert result.status == "blocked"
    assert len(executor.calls) == 0
    assert store.load() == before


def test_matching_commit_trailers_cannot_certify_wrong_artifact_bytes(checkpoint_case, monkeypatch):
    from harness import phase_checkpoints
    original = phase_checkpoints._commit_spec_changes
    path = checkpoint_case[0] / "specs/game/unknowns.md"
    def changed_commit(*args, **kwargs):
        content = path.read_bytes()
        try:
            path.write_bytes(b"### U-000001: Wrong checkpoint body\n")
            return original(*args, **kwargs)
        finally:
            path.write_bytes(content)
    monkeypatch.setattr(phase_checkpoints, "_commit_spec_changes", changed_commit)
    executor = FullDiscoveryExecutor()
    result = controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    assert result.status == "blocked"
    assert checkpoint_case[1].load()["last_dispatch"]["post_dispatch_complete"] is False
    assert checkpoint_case[2].pending_identity_publication(spec_id="game")["state"] == "applied"
    assert len(executor.calls) == 3


def test_retained_checkpoint_proof_outlives_recent_git_history(checkpoint_case):
    from harness.discovery_completion import released_checkpoint_projector
    from harness.squad_source_snapshot import inspect_project_tree
    executor = FullDiscoveryExecutor()
    controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    root, store, _, _ = checkpoint_case
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    parent, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    for number in range(256):
        parent = git("commit-tree", tree, "-p", parent, "-m", f"Later unrelated work {number}")
    git("update-ref", "HEAD", parent)
    project = released_checkpoint_projector(root, store.squad_dir, store.load())
    with inspect_project_tree(root, "specs/game") as captured:
        assert len(project(captured).files) == 7


@pytest.mark.parametrize("point", ["after_commit", "after_ledger"])
def test_committed_checkpoint_requires_its_preexisting_lock_before_receipt(checkpoint_case, monkeypatch, point):
    executor = FullDiscoveryExecutor()
    interrupt_checkpoint(checkpoint_case, executor, monkeypatch, point)
    (checkpoint_case[0] / "specs/game/.echelon/checkpoints.lock").unlink()
    result = controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case))
    assert result.status == "blocked"
    assert checkpoint_case[1].load()["last_dispatch"]["post_dispatch_complete"] is False
    assert len(executor.calls) == 3


def test_retained_completion_proof_rejects_changed_intent_receipts_or_marker(checkpoint_case):
    from copy import deepcopy
    from harness.squad_completion import CompletionError, validate_retained_completion_proof
    executor = FullDiscoveryExecutor()
    controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    state = checkpoint_case[1].load()
    row = checkpoint_case[2].identity_publication(spec_id="game",
        operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
    saved = json.loads(row["completion_payload"])
    assert saved["version"] == 3
    for damage in ("parent", "route", "receipt", "missing_effect", "marker", "extra"):
        proof = deepcopy(saved)
        checkpoint = proof["proof"]
        if damage == "parent": checkpoint["intent"]["checkpoint_prestate"]["head"] = "a" * 40
        elif damage == "route": checkpoint["intent"]["route"]["to_phase"] = "phase1-what"
        elif damage == "receipt": checkpoint["receipts"]["effects"]["checkpoint"]["commit"] = "a" * 40
        elif damage == "missing_effect": del checkpoint["receipts"]["effects"]["checkpoint"]
        elif damage == "marker": proof["completion"]["receipts_sha256"] = "a" * 64
        else: checkpoint["intent"]["unexpected"] = True
        with pytest.raises(CompletionError):
            validate_retained_completion_proof(proof["completion"], checkpoint["intent"], checkpoint["receipts"])


@pytest.mark.parametrize("point", ["completed", "released", "publication_disposed"])
def test_checkpoint_release_recovery_retains_projection_proof(checkpoint_case, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import PreparedSquadPublication
    from harness.discovery_completion import released_checkpoint_projector
    from harness.squad_source_snapshot import inspect_project_tree
    executor = FullDiscoveryExecutor()
    target, method = {"completed": (checkpoint_case[1], "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
        "publication_disposed": (PreparedSquadPublication, "discard")}[point]
    original = getattr(target, method)
    def stop_after(*args, **kwargs):
        result = original(*args, **kwargs)
        if point != "publication_disposed" or (checkpoint_case[1].load().get("last_dispatch") or {}).get("post_dispatch_complete"):
            raise Interrupted()
        return result
    with monkeypatch.context() as patch:
        patch.setattr(target, method, stop_after)
        with pytest.raises(Interrupted):
            controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case))
    root, store, identity, _ = checkpoint_case
    state = store.load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert identity.pending_identity_publication(spec_id="game") is None
    assert len(executor.calls) == 3 and state["token_usage"] == 21
    project = released_checkpoint_projector(root, store.squad_dir, state)
    with inspect_project_tree(root, "specs/game") as captured:
        assert len(project(captured).files) == 7

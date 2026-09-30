"""Run real Ralph selection, journals, reviews and accounting across browser repair."""
import json
from pathlib import Path

import pytest

from harness.delivery_slice_journal import DeliverySliceJournal
from harness.product_inventory import product_evidence_fingerprint
from harness.visual_ralph import VisualRalphController
from tests.unit.test_browser_capture_failures import _capture
from tests.unit.test_delivery_browser_checkpoints import _passing_capture
from tests.unit.test_delivery_repair_ownership import _project, _verify
from tests.unit.test_delivery_controller_integration import _reconstruct
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


def _handoff_project(fixture, tmp_path, monkeypatch, *, recheck="pass"):
    controller, store, _ = _project(fixture, tmp_path)
    captures = []
    source_bytes = {}
    candidate_at_capture = None

    def script(assignment, payload, root):
        if len(executor.calls) == 1:
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need current screenshots",
                           browser_evidence_request={"purpose": "baseline_capture"})
        elif assignment["task_id"] == "T-011" and assignment["step"] == "implementer":
            # The scripted external agent accepts the current proposal without
            # changing the candidate. Production harness still controls every gate.
            (root / "app.py").write_bytes(candidate_at_capture)

    executor = ScriptedExecutor(script)
    controller._llm_provider = executor

    def capture(visual, worktree):
        nonlocal candidate_at_capture
        candidate_at_capture = (Path(worktree) / "app.py").read_bytes()
        operation = store.read()["delivery_slice_operation"]
        captures.append(operation.get("repair_task_id") or "T-011")
        if (len(captures) == 1 or (operation.get("continuation") or {}).get("kind") == "refresh"
                or len(captures) == 2 and recheck != "pass"):
            title = "[echelon:E2E-START-002] startup" if len(captures) == 2 and recheck == "third" else "[echelon:CT-NET-001] network"
            return _capture(product_evidence_fingerprint(Path(worktree)), title=title)
        return _passing_capture(worktree)

    original = DeliverySliceJournal.save
    def save(journal, data):
        original(journal, data)
        if (data["task_id"] == "T-011" and len(data["records"]) == 1
                and data["records"][0].get("browser_evidence") is not None):
            source_bytes.setdefault(journal.path, journal.path.read_bytes())
    monkeypatch.setattr(VisualRalphController, "capture_baselines", capture)
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    return controller, store, executor, captures, source_bytes


def _drive(controller, fixture):
    return controller._exec_feedback(None, _verify(), "echelon build", "", worktree_path=str(fixture[0]))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("crash_after_install", [False, True])
def test_return_installs_exact_proposals_then_reviews_and_replays(
    slice_project, tmp_path, monkeypatch, existing, crash_after_install,
):
    """Receipt-backed installation is not an arbitrary post-capture edit."""
    root, spec, _ = slice_project
    baseline = root / "tests/e2e/degradation.spec.ts-snapshots/pitch-chromium.png"
    if existing:
        baseline.parent.mkdir(parents=True)
        baseline.write_bytes(b"previous baseline")
    controller, store, executor, captures, retained = _handoff_project(slice_project, tmp_path, monkeypatch)
    original_script = executor.script

    def install(assignment, payload, candidate):
        original_script(assignment, payload, candidate)
        if len(executor.calls) > 1 and assignment["task_id"] == "T-011" and assignment["step"] == "implementer":
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(b"proposal")

    executor.script = install
    if crash_after_install:
        from tests.unit.test_delivery_slice_recovery import ProcessLost
        save = DeliverySliceJournal.save
        crashed = False

        def save_then_crash(journal, data):
            nonlocal crashed
            save(journal, data)
            if (not crashed and (data.get("continuation") or {}).get("kind") == "return"
                    and data["records"] and data["records"][-1]["result"] is not None):
                crashed = True
                raise ProcessLost()

        monkeypatch.setattr(DeliverySliceJournal, "save", save_then_crash)
        with pytest.raises(ProcessLost):
            _drive(controller, slice_project)
        assert len(executor.calls) == 6
        controller = _reconstruct(controller, store, executor)
    result = _drive(controller, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert baseline.read_bytes() == b"proposal"
    assert [a["step"] for a, _, _ in executor.calls[-4:]] == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert len(executor.calls) == 9
    # Replaying the durable acceptance must not reinstall, recapture, or dispatch.
    calls_before = len(executor.calls)
    captures_before = list(captures)
    replay = _drive(controller, slice_project)
    assert replay["passed"], replay
    assert len(executor.calls) == calls_before
    assert captures == captures_before
    assert retained and all(path.read_bytes() == content for path, content in retained.items())
    assert not store.read()["delivery_slice_operation"]["progress_applied"]


@pytest.mark.parametrize("damage", ["missing_intent", "wrong_checkpoint", "invalid_digest", "extra_field"])
def test_return_installation_replay_requires_retained_valid_intent(slice_project, tmp_path, monkeypatch, damage):
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    original_script = executor.script

    def install(assignment, payload, root):
        original_script(assignment, payload, root)
        if len(executor.calls) > 1 and assignment["task_id"] == "T-011" and assignment["step"] == "implementer":
            baseline = root / "tests/e2e/degradation.spec.ts-snapshots/pitch-chromium.png"
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(b"proposal")

    executor.script = install
    save = DeliverySliceJournal.save
    def stop_after_install(journal, data):
        save(journal, data)
        if ((data.get("continuation") or {}).get("kind") == "return"
                and data["records"] and data["records"][-1]["result"] is not None):
            raise ProcessLost()
    monkeypatch.setattr(DeliverySliceJournal, "save", stop_after_install)
    with pytest.raises(ProcessLost):
        _drive(controller, slice_project)
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    operation = store.read()["delivery_slice_operation"]
    journal = DeliverySliceJournal(controller._delivery_operation_evidence_root(), operation["id"])
    data = journal.load(required=True)
    record = data["records"][0]
    if damage == "missing_intent":
        record.pop("baseline_installation")
    elif damage == "wrong_checkpoint":
        record["baseline_installation"]["checkpoint_id"] = "unrelated-checkpoint"
    elif damage == "invalid_digest":
        record["baseline_installation"]["candidate_fingerprint"] = None
    else:
        record["baseline_installation"]["authorize_all_pngs"] = True
    journal.path.write_text(json.dumps(data))
    before = journal.path.read_bytes()
    result = _drive(_reconstruct(controller, store, executor), slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 6  # No review or implementer redispatch.
    assert journal.path.read_bytes() == before


@pytest.mark.parametrize("damage", ["wrong_bytes", "source", "unlisted_image", "executable", "symlink"])
def test_return_proposal_installation_does_not_authorize_other_changes(slice_project, tmp_path, monkeypatch, damage):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    original_script = executor.script

    def install(assignment, payload, root):
        original_script(assignment, payload, root)
        if len(executor.calls) > 1 and assignment["task_id"] == "T-011" and assignment["step"] == "implementer":
            baseline = root / "tests/e2e/degradation.spec.ts-snapshots/pitch-chromium.png"
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(b"wrong" if damage == "wrong_bytes" else b"proposal")
            if damage == "source":
                (root / "app.py").write_text("unreviewed source change\n")
            elif damage == "unlisted_image":
                (baseline.parent / "unlisted.png").write_bytes(b"proposal")
            elif damage == "executable":
                baseline.chmod(0o755)
            elif damage == "symlink":
                baseline.unlink()
                baseline.symlink_to(root / "app.py")

    executor.script = install
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert "recapture_required" in result["build_reason"], result
    assert executor.calls[-1][0]["step"] == "implementer"
    assert not store.read()["delivery_slice_operation"]["progress_applied"]


@pytest.mark.parametrize("recheck,rounds", [("pass", 1), ("retry", 2)])
def test_ralph_repairs_owner_then_returns_to_source_with_normal_reviews(slice_project, tmp_path, monkeypatch, recheck, rounds):
    controller, store, executor, captures, retained = _handoff_project(slice_project, tmp_path, monkeypatch, recheck=recheck)
    before = store.read()
    task_bytes = (slice_project[1] / "tasks.md").read_bytes()
    result = _drive(controller, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    roles = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert [(a["task_id"], a["step"]) for a, _, _ in executor.calls] == (
        [("T-011", "implementer")] + [("T-012", role) for role in roles] * rounds
        + [("T-011", role) for role in roles])
    assert captures == ["T-011"] + ["T-012"] * rounds + ["T-011"]
    assert store.read()["tokens_used"] == result["tokens"] == (63 if rounds == 1 else 91)
    assert retained and all(path.read_bytes() == content for path, content in retained.items())
    assert (slice_project[1] / "tasks.md").read_bytes() == task_bytes
    for key in ("outer_iter", "inner_iter"):
        assert store.read().get(key) == before.get(key)
    operation = store.read()["delivery_slice_operation"]
    assert operation["browser_handoff"]["phase"] == "return"
    assert operation["accepted_task_id"] == "T-011"
    controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    assert store.read()["delivery_slice_operation"]["progress_applied"] is True
    receipts = [json.loads(path.read_text()) for path in controller._delivery_operation_evidence_root().rglob("receipt.json")]
    assert [row["task_id"] for row in receipts].count("T-011") == 2
    assert [row["task_id"] for row in receipts].count("T-012") == rounds


def test_owner_recheck_never_opens_a_nested_foreign_repair(slice_project, tmp_path, monkeypatch):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch, recheck="third")
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"]
    assert "third_owner" in result["build_reason"], result
    assert len(executor.calls) == 5 and captures == ["T-011", "T-012"]
    assert store.read()["delivery_slice_operation"]["browser_handoff"]["phase"] == "owner"
    assert not store.read()["delivery_slice_operation"].get("accepted_task_id")


@pytest.mark.parametrize("damage", ["spec", "scope", "role"])
def test_owner_resume_rejects_changed_context_before_dispatch(slice_project, tmp_path, monkeypatch, damage):
    from harness.state import StateStore
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    from tests.unit.test_delivery_controller_integration import _reconstruct
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    original = StateStore.write
    crashed = False
    def write(current_store, state):
        nonlocal crashed
        original(current_store, state)
        if state.get("delivery_slice_operation", {}).get("browser_handoff", {}).get("phase") == "owner" and not crashed:
            crashed = True
            raise ProcessLost()
    monkeypatch.setattr(StateStore, "write", write)
    with pytest.raises(ProcessLost):
        _drive(controller, slice_project)
    assert len(executor.calls) == 1
    if damage == "spec":
        (slice_project[1] / "spec.md").write_text("Changed requirement\n")
    elif damage == "role":
        path = slice_project[0] / ".echelon/prosaic/subagents/echelon.delivery-implementer.md"
        path.write_text(path.read_text() + "\nChanged instructions\n")
    else:
        state = store.read()
        state["target_task_ids"] = ["T-011"]
        store.write(state)
    resumed = _reconstruct(controller, store, executor)
    result = _drive(resumed, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 1


@pytest.mark.parametrize("damage", ["scope", "role"])
def test_selection_authenticates_source_context_again(slice_project, tmp_path, monkeypatch, damage):
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    select = controller._select_browser_repair_operation
    def changed(request, **kwargs):
        if damage == "scope":
            state = store.read()
            state["target_task_ids"] = ["T-012"]
            store.write(state)
        else:
            path = slice_project[0] / ".echelon/prosaic/subagents/echelon.delivery-implementer.md"
            path.write_text(path.read_text() + "\nChanged instructions\n")
        return select(request, **kwargs)
    monkeypatch.setattr(controller, "_select_browser_repair_operation", changed)
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 1


@pytest.mark.parametrize("budget,expected_calls", [(7, 1), (10, 2), (14, 2), (35, 5), (42, 6)])
def test_handoff_never_renews_token_allowance(slice_project, tmp_path, monkeypatch, budget, expected_calls):
    controller, store, executor, _, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    controller._controlled_slice_budget = budget
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert "budget_exhausted" in result["build_reason"], result
    assert len(executor.calls) == expected_calls
    assert store.read()["tokens_used"] == 7 * expected_calls
    again = _drive(controller, slice_project)
    assert not again["passed"] and "budget_exhausted" in again["build_reason"], again
    assert len(executor.calls) == expected_calls
    assert store.read()["tokens_used"] == 7 * expected_calls


@pytest.mark.parametrize("boundary", [
    "before_owner_selection", "after_owner_selection", "after_owner_provider_receipt",
    "after_owner_accounting", "after_recheck_intent", "after_recheck_receipt",
    "before_return_selection", "after_return_selection", "after_return_capture_receipt",
    "after_source_acceptance",
])
def test_handoff_reconstructs_at_durable_boundaries(slice_project, tmp_path, monkeypatch, boundary):
    from harness.state import StateStore
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    from tests.unit.test_delivery_controller_integration import _reconstruct
    controller, store, executor, captures, retained = _handoff_project(slice_project, tmp_path, monkeypatch)
    saved = DeliverySliceJournal.save
    written = StateStore.write
    crashed = False
    def interrupt():
        nonlocal crashed
        crashed = True
        raise ProcessLost()
    def write(current_store, state):
        operation = state.get("delivery_slice_operation", {})
        phase = operation.get("browser_handoff", {}).get("phase")
        selecting = phase and current_store.read().get("delivery_slice_operation", {}).get("id") != operation.get("id")
        if not crashed and selecting and boundary == f"before_{phase}_selection":
            interrupt()
        written(current_store, state)
        if not crashed and (
                selecting and boundary == f"after_{phase}_selection"
                or phase == "owner" and boundary == "after_owner_accounting" and operation["accounted_tokens"] > 0
                or phase == "return" and boundary == "after_source_acceptance" and operation.get("accepted_task_id")):
            interrupt()
    def save(journal, data):
        saved(journal, data)
        kind = (data.get("continuation") or {}).get("kind")
        checks = data.get("browser_checks", [])
        if not crashed and (
                kind == "owner_retry" and boundary == "after_owner_provider_receipt"
                and data["records"] and data["records"][-1]["result"] is not None
                or kind == "owner_retry" and checks and checks[-1]["purpose"] == "owner_recheck"
                and ((boundary == "after_recheck_intent" and checks[-1]["receipt"] is None)
                     or (boundary == "after_recheck_receipt" and checks[-1]["receipt"] is not None))
                or kind == "return" and boundary == "after_return_capture_receipt"
                and checks and checks[-1]["receipt"] is not None):
            interrupt()
    monkeypatch.setattr(StateStore, "write", write)
    monkeypatch.setattr(DeliverySliceJournal, "save", save)
    with pytest.raises(ProcessLost):
        _drive(controller, slice_project)
    resumed = _reconstruct(controller, store, executor)
    result = _drive(resumed, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert len(executor.calls) == 9 and store.read()["tokens_used"] == 63
    assert [a["task_id"] for a, _, _ in executor.calls] == ["T-011"] + ["T-012"] * 4 + ["T-011"] * 4
    assert captures == ["T-011", "T-012", "T-011"]
    assert all(path.read_bytes() == content for path, content in retained.items())
    operation = store.read()["delivery_slice_operation"]
    owner_id = operation["browser_handoff"]["owner_journal"]["operation_id"]
    owner = DeliverySliceJournal(controller._delivery_operation_evidence_root(), owner_id).load(required=True)
    assert [row["request_ordinal"] for row in owner["browser_checks"]] == (
        [1, 2] if boundary == "after_recheck_intent" else [1])


def _stopped_v2(controller, store, fixture, monkeypatch):
    from copy import deepcopy
    from harness.browser_baseline_evidence import BrowserBaselineEvidenceRef
    from tests.unit.test_browser_capture_failures import _rewrite_receipt
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    def stop(*args, **kwargs):
        raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(controller, "_select_browser_repair_operation", stop)
        with pytest.raises(ProcessLost):
            _drive(controller, fixture)
    operation = store.read()["delivery_slice_operation"]
    journal = DeliverySliceJournal(controller._delivery_operation_evidence_root(), operation["id"])
    data = journal.load(required=True)
    reference = data["records"][-1]["browser_evidence"]
    payload = json.loads(Path(reference["path"]).read_text())
    payload.pop("verification_failures")
    payload["schema_version"] = 2
    ref = _rewrite_receipt(BrowserBaselineEvidenceRef(Path(reference["path"]), reference["receipt_sha256"]), payload)
    reference["receipt_sha256"] = ref.receipt_sha256
    duplicate = deepcopy(data["records"][-1])
    duplicate.pop("browser_evidence")
    duplicate["assignment"]["dispatch_id"] = "completed-v2-duplicate"
    duplicate["assignment"]["candidate_fingerprint"] = duplicate["candidate_after"]
    duplicate["result"].update(duplicate["assignment"])
    duplicate["raw_result"] = json.dumps(duplicate["result"])
    data["records"].append(duplicate)
    data["schema_version"] = 2
    for key in ("continuation", "browser_checks", "require_browser_recheck"):
        data.pop(key)
    journal.save(data)
    return journal, data, ref


@pytest.mark.parametrize("damage", [None, "candidate", "input", "tokens"])
def test_native_ralph_refreshes_stopped_v2_boundary_without_rewriting(slice_project, tmp_path, monkeypatch, damage):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    journal, data, ref = _stopped_v2(controller, store, slice_project, monkeypatch)
    if damage == "candidate":
        (slice_project[0] / "app.py").write_text("changed outside delivery\n")
    elif damage == "input":
        (slice_project[1] / "spec.md").write_text("changed contract\n")
    elif damage == "tokens":
        data["budget_limit"] = 14
        journal.save(data)
    before = journal.path.read_bytes(), ref.path.read_bytes()
    result = _drive(controller, slice_project)
    assert (journal.path.read_bytes(), ref.path.read_bytes()) == before
    if damage:
        assert not result["passed"] and len(executor.calls) == 1 and captures == ["T-011"], result
        return
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert len(executor.calls) == 9 and store.read()["tokens_used"] == 70
    assert captures == ["T-011", "T-011", "T-012", "T-011"]
    journals = [json.loads(path.read_text()) for path in controller._delivery_operation_evidence_root().rglob("journal.json")]
    refreshed = next(row for row in journals if (row.get("continuation") or {}).get("kind") == "refresh")
    returned = next(row for row in journals if (row.get("continuation") or {}).get("kind") == "return")
    assert refreshed["browser_checks"][0]["request_ordinal"] == 3
    assert returned["browser_checks"][0]["request_ordinal"] == 4


@pytest.mark.parametrize("task", ["T-011", "T-012"])
def test_unknown_provider_usage_blocks_finite_handoff_budget(slice_project, tmp_path, monkeypatch, task):
    from harness.ai_cli_backend import CliRunResult
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    controller._controlled_slice_budget = 100
    script = executor.script
    def unknown(assignment, payload, root):
        script(assignment, payload, root)
        if assignment["task_id"] == task:
            return CliRunResult(0, json.dumps(payload), "", token_usage=None)
    executor.script = unknown
    result = _drive(controller, slice_project)
    assert not result["passed"] and "usage_unknown" in result["build_reason"], result
    assert len(executor.calls) == (1 if task == "T-011" else 2)
    assert captures == ([] if task == "T-011" else ["T-011"])


def test_explicit_existing_budget_extension_can_resume_owner_without_rewriting_parent(slice_project, tmp_path, monkeypatch):
    controller, store, executor, _, retained = _handoff_project(slice_project, tmp_path, monkeypatch)
    controller._controlled_slice_budget = 14
    blocked = _drive(controller, slice_project)
    assert not blocked["passed"] and len(executor.calls) == 2
    state = store.read()
    state["token_budget"] = 100
    state["delivery_slice_operation"]["budget_extension_limit"] = 95
    store.write(state)
    controller._controlled_slice_budget = 95 - state["tokens_used"]
    result = _drive(controller, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert store.read()["tokens_used"] == 63 and len(executor.calls) == 9
    assert all(path.read_bytes() == content for path, content in retained.items())


@pytest.mark.parametrize("purpose", ["requested", "owner_recheck", "return_capture"])
def test_replay_rejects_redirected_checkpoint_ancestry(slice_project, tmp_path, monkeypatch, purpose):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    assert _drive(controller, slice_project)["passed"]
    root = controller._delivery_operation_evidence_root()
    journals = [json.loads(path.read_text()) for path in root.rglob("journal.json")]
    check = next(check for data in journals for check in data.get("browser_checks", [])
                 if check["purpose"] == purpose and check["receipt"] is not None)
    directory = Path(check["receipt"]["path"]).parent.parent
    moved = tmp_path / "redirected-evidence"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    result = _drive(controller, slice_project)
    assert not result["passed"] and not result["task_ids"], result
    assert len(executor.calls) == 9 and store.read()["tokens_used"] == 63
    assert captures == ["T-011", "T-012", "T-011"]


@pytest.mark.parametrize("after_write", [False, True])
def test_pending_source_progress_replays_across_state_write(slice_project, tmp_path, monkeypatch, after_write):
    from harness.state import StateStore
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    from tests.unit.test_delivery_controller_integration import _reconstruct
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    tasks = slice_project[1] / "tasks.md"
    tasks.write_text(tasks.read_text().replace("[x] T-011", "[ ] T-011")
                     .replace("**Status:** DONE", "**Status:** PENDING", 1)
                     .replace("[x] Implement `E2E", "[ ] Implement `E2E")
                     .replace("depends=T-011", "depends=none"))
    result = controller._exec_controlled_slice(str(slice_project[0]), "", repair=False)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    written = StateStore.write
    def write(current_store, state):
        if after_write:
            written(current_store, state)
        raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(StateStore, "write", write)
        with pytest.raises(ProcessLost):
            controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    assert "[x] T-011" in tasks.read_text()
    resumed = _reconstruct(controller, store, executor)
    result = resumed._exec_controlled_slice(str(slice_project[0]), "", repair=False)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    resumed._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    assert store.read()["delivery_slice_operation"]["progress_applied"] is True
    assert len(executor.calls) == 9 and store.read()["tokens_used"] == 63
    assert captures == ["T-011", "T-012", "T-011"]


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("checkpoint,failed_call,total_calls", [
    ("return_capture", 7, 10), ("requested", 4, 11), ("owner_recheck", 7, 14),
])
def test_provider_recovery_retains_browser_checkpoint_authority(
    slice_project, tmp_path, monkeypatch, unknown, checkpoint, failed_call, total_calls,
):
    from harness.ai_cli_backend import CliRunResult
    from tests.unit.test_delivery_slice_recovery import ProcessLost
    from tests.unit.test_delivery_controller_integration import _reconstruct
    controller, store, executor, captures, _ = _handoff_project(
        slice_project, tmp_path, monkeypatch, recheck="retry" if checkpoint == "owner_recheck" else "pass")
    script = executor.script
    requested_candidate = None
    def fail(assignment, payload, root):
        nonlocal requested_candidate
        script(assignment, payload, root)
        if checkpoint == "requested" and len(executor.calls) == 2:
            requested_candidate = (root / "app.py").read_bytes()
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need owner screenshots",
                           browser_evidence_request={"purpose": "baseline_capture"})
        elif checkpoint == "requested" and len(executor.calls) == 3:
            (root / "app.py").write_bytes(requested_candidate)
        if len(executor.calls) == failed_call:
            assert assignment["step"] == "spec_guard"
            if unknown:
                raise ProcessLost()
            return CliRunResult(1, "", "transient provider failure", token_usage=7)
    executor.script = fail
    if unknown:
        with pytest.raises(ProcessLost):
            _drive(controller, slice_project)
    else:
        blocked = _drive(controller, slice_project)
        assert blocked["build_reason"] == "delivery_provider_failed", blocked
    operation = store.read()["delivery_slice_operation"]
    evidence = controller._delivery_operation_evidence_root()
    parent = DeliverySliceJournal(evidence, operation["id"]).load(required=True)
    checks = parent["browser_checks"]
    assert any(check["purpose"] == checkpoint for check in checks)
    receipt_bytes = {Path(check["receipt"]["path"]): Path(check["receipt"]["path"]).read_bytes()
                     for check in checks if check["receipt"] is not None}
    resumed = _reconstruct(controller, store, executor)
    resumed._retry_failed_dispatch = not unknown
    resumed._reconcile_unknown_dispatch = unknown
    result = _drive(resumed, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert len(executor.calls) == total_calls
    assert store.read()["tokens_used"] == 7 * (total_calls - int(unknown))
    assert all(path.read_bytes() == content for path, content in receipt_bytes.items())
    again = _drive(resumed, slice_project)
    assert again["passed"] and len(executor.calls) == total_calls, again


@pytest.mark.parametrize("extend", [False, True])
def test_stopped_v2_refresh_preserves_only_explicit_budget_extension(slice_project, tmp_path, monkeypatch, extend):
    controller, store, executor, captures, _ = _handoff_project(slice_project, tmp_path, monkeypatch)
    journal, data, ref = _stopped_v2(controller, store, slice_project, monkeypatch)
    data["budget_limit"] = 14
    journal.save(data)
    before = journal.path.read_bytes(), ref.path.read_bytes()
    state = store.read()
    state["token_budget"] = 100
    if extend:
        state["delivery_slice_operation"]["budget_extension_limit"] = 95
    store.write(state)
    controller._controlled_slice_budget = 95 - state["tokens_used"]
    result = _drive(controller, slice_project)
    assert (journal.path.read_bytes(), ref.path.read_bytes()) == before
    if not extend:
        assert not result["passed"] and "budget_exhausted" in result["build_reason"], result
        assert len(executor.calls) == 1 and captures == ["T-011"]
        return
    assert result["passed"] and result["task_ids"] == ["T-011"], result
    assert len(executor.calls) == 9 and store.read()["tokens_used"] == 70
    assert captures == ["T-011", "T-011", "T-012", "T-011"]

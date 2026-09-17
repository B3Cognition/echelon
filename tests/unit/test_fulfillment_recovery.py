"""Recover exact fulfillment work without resetting calls, usage or publication."""
import json
from dataclasses import replace

import pytest

from tests.unit.test_controlled_fulfillment import (
    preparation_context, scripted_graph_tools, installed_roles, SemanticExecutor, run,
)


@pytest.mark.parametrize("via_context", [False, True])
@pytest.mark.parametrize("change", ["changed", "missing"])
def test_selected_observation_is_bound_on_resume(preparation_context, tmp_path, monkeypatch, via_context, change):
    import hashlib
    from tests.unit import test_coverage_observation as observations
    context = preparation_context
    coverage_map = context.spec_dir / "coverage-map.md"
    coverage_map.write_text("# Coverage\n")
    monkeypatch.setattr(observations, "_MAP_HASH", hashlib.sha256(coverage_map.read_bytes()).hexdigest())
    observation = observations._write_observation(tmp_path / "receipts")
    if via_context:
        (context.verify_run_dir / "coverage-observation-context.json").write_text(json.dumps({
            "schema_version": 1, "observer_required": True,
            "coverage_observation": observation.ref.as_mapping(),
        }))
    else:
        context = replace(context, observer_required=True, observation_path=observation.ref.path)
    executor = SemanticExecutor()
    first = run(context, executor)
    assert first.exit_code == 0, first.reason
    if change == "changed":
        observation.ref.path.write_text("{}")
    else:
        observation.ref.path.unlink()
    result = run(context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == first.dispatch_count
    assert result.token_usage == first.token_usage


def test_completed_stage_replays_without_model_or_preparation(preparation_context, monkeypatch):
    executor = SemanticExecutor()
    first = run(preparation_context, executor)
    assert first.exit_code == 0, first.reason
    before = first.report_path.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("accepted preparation was repeated")
    monkeypatch.setattr("harness.controlled_fulfillment.prepare_fulfillment_inputs", forbidden)
    second = run(preparation_context, executor, token_budget=0)
    assert second.exit_code == 0, second.reason
    assert executor.dispatch_count == 1
    assert second.token_usage == first.token_usage == 7
    assert second.report_path.read_bytes() == before


def test_completed_model_turn_survives_host_step_failure(preparation_context, monkeypatch):
    import harness.controlled_fulfillment as controlled
    executor = SemanticExecutor()
    original = controlled.write_judgment_prepass
    def interrupted(**kwargs):
        raise OSError("interrupted before prepass")
    monkeypatch.setattr(controlled, "write_judgment_prepass", interrupted)
    first = run(preparation_context, executor)
    assert first.exit_code != 0
    assert first.token_usage == 7
    monkeypatch.setattr(controlled, "write_judgment_prepass", original)
    second = run(preparation_context, executor)
    assert second.exit_code == 0, second.reason
    assert executor.dispatch_count == 1
    assert second.token_usage == 7


def test_unknown_external_completion_is_not_redispatched(preparation_context):
    class Crash(BaseException):
        pass
    class Interrupted(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            self.dispatches.append("started")
            raise Crash()
    crashed = Interrupted()
    with pytest.raises(Crash):
        run(preparation_context, crashed)
    executor = SemanticExecutor()
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert "unknown" in result.reason
    assert executor.dispatch_count == 0
    assert result.token_usage is None


@pytest.mark.parametrize("change", ["source", "role", "scope", "stage", "missing_journal", "corrupt_journal", "provider"])
def test_changed_or_lost_recovery_inputs_never_restart(preparation_context, change):
    context = preparation_context
    executor = SemanticExecutor()
    first = run(context, executor)
    assert first.exit_code == 0, first.reason
    if change == "source":
        (context.source_root / "app.py").write_text("changed source")
    elif change == "role":
        path = context.workspace_root / ".echelon/prosaic/subagents/echelon.fulfillment-mapper.md"
        path.write_text(path.read_text() + "\nChanged semantic instructions\n")
    elif change == "scope":
        path = context.verify_run_dir / "state.json"
        state = json.loads(path.read_text())
        state["scoped_ids"] = ["FR-1000000"]
        path.write_text(json.dumps(state))
    elif change == "stage":
        first.report_path.write_text("externally replaced")
    elif change == "provider":
        executor.cli = "claude"
    else:
        path = context.verify_run_dir / "controlled-fulfillment.json"
        if change == "missing_journal":
            path.unlink()
        else:
            path.write_text("{")
    result = run(context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == 1
    assert not (context.spec_dir / "fulfillment-report.md").exists()


def test_failed_provider_usage_survives_reentry_without_retry(preparation_context):
    executor = SemanticExecutor(bad="provider")
    first = run(preparation_context, executor)
    second = run(preparation_context, executor)
    assert first.exit_code == second.exit_code == 2
    assert first.token_usage == second.token_usage == 7
    assert executor.dispatch_count == 1


def test_pending_publication_replays_exact_bytes(preparation_context, monkeypatch):
    import harness.fulfillment_recovery as recovery
    context = preparation_context
    report = context.spec_dir / "fulfillment-report.md"
    gaps = context.spec_dir / "fulfillment-gaps.md"
    report.write_text("old report")
    gaps.write_text("old gaps")
    outputs = {"fulfillment-report.md": "new report", "fulfillment-gaps.md": "new gaps"}
    original = recovery.write_text_atomic
    def interrupted(path, text, **kwargs):
        if path == gaps:
            raise OSError("publication interrupted")
        return original(path, text, **kwargs)
    monkeypatch.setattr(recovery, "write_text_atomic", interrupted)
    with pytest.raises(OSError):
        recovery.publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir, outputs)
    assert report.read_text() == "new report"
    assert gaps.read_text() == "old gaps"
    monkeypatch.setattr(recovery, "write_text_atomic", original)
    recovery.publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir, outputs)
    assert report.read_text() == "new report"
    assert gaps.read_text() == "new gaps"


@pytest.mark.parametrize("conflict", ["destination", "intent", "output_scope"])
def test_publication_conflicts_are_not_overwritten(preparation_context, monkeypatch, conflict):
    import harness.fulfillment_recovery as recovery
    context = preparation_context
    report = context.spec_dir / "fulfillment-report.md"
    report.write_text("old report")
    outputs = {"fulfillment-report.md": "new report", "fulfillment-gaps.md": "new gaps"}
    original = recovery.write_text_atomic
    def interrupted(*args, **kwargs):
        raise OSError("before publication")
    monkeypatch.setattr(recovery, "write_text_atomic", interrupted)
    with pytest.raises(OSError):
        recovery.publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir, outputs)
    monkeypatch.setattr(recovery, "write_text_atomic", original)
    if conflict == "destination":
        report.write_text("external edit")
    elif conflict == "intent":
        outputs["fulfillment-report.md"] = "different report"
    else:
        outputs["spec.md"] = "unauthorized"
    with pytest.raises((ValueError, OSError)):
        recovery.publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir, outputs)
    assert report.read_text() == ("external edit" if conflict == "destination" else "old report")


def test_concurrent_recovery_is_rejected_without_dispatch(preparation_context):
    from harness.fulfillment_recovery import FulfillmentRecovery
    executor = SemanticExecutor()
    with FulfillmentRecovery(preparation_context.verify_run_dir):
        result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == 0


def test_failed_preparation_is_not_silently_repeated(preparation_context, monkeypatch):
    import harness.controlled_fulfillment as controlled
    original = controlled.prepare_fulfillment_inputs
    def interrupted(*args):
        raise OSError("preparation interrupted")
    monkeypatch.setattr(controlled, "prepare_fulfillment_inputs", interrupted)
    first = run(preparation_context, SemanticExecutor())
    assert first.exit_code != 0
    monkeypatch.setattr(controlled, "prepare_fulfillment_inputs", original)
    executor = SemanticExecutor()
    second = run(preparation_context, executor)
    assert second.exit_code != 0
    assert "preparation completion unknown" in second.reason
    assert executor.dispatch_count == 0


def test_reentry_does_not_replenish_exhausted_budget(preparation_context):
    executor = SemanticExecutor(inspect_source=True)
    first = run(preparation_context, executor, token_budget=7)
    second = run(preparation_context, executor, token_budget=1000)
    assert first.exit_code == second.exit_code == 2
    assert first.token_usage == second.token_usage == 7
    assert executor.dispatch_count == 1
    assert "budget" in second.reason


def test_saved_read_deadline_does_not_restart_on_resume(preparation_context, monkeypatch):
    import harness.controlled_fulfillment as controlled
    from harness.fulfillment_recovery import FulfillmentRecovery
    class Crash(BaseException):
        pass
    now = [1000.0]
    monkeypatch.setattr(controlled.time, "time", lambda: now[0])
    original = FulfillmentRecovery.save
    def interrupted(journal):
        original(journal)
        records = journal.data["steps"].get("mapper", {}).get("records", [])
        if records and records[-1]["read"] is not None:
            raise Crash()
    monkeypatch.setattr(FulfillmentRecovery, "save", interrupted)
    executor = SemanticExecutor(inspect_source=True)
    with pytest.raises(Crash):
        run(preparation_context, executor)
    monkeypatch.setattr(FulfillmentRecovery, "save", original)
    now[0] = 1400.0
    second = run(preparation_context, executor)
    assert second.exit_code != 0
    assert "deadline" in second.reason
    assert executor.dispatch_count == 1
    assert second.token_usage == 7


@pytest.mark.parametrize("name", ["controlled-fulfillment.json", "controlled-fulfillment.lock", "fulfillment-publication.json"])
def test_unsafe_recovery_paths_do_not_touch_external_files(preparation_context, tmp_path, name):
    from harness.fulfillment_recovery import publish_fulfillment_outputs
    target = tmp_path / "outside"
    target.write_text("private original")
    (preparation_context.verify_run_dir / name).symlink_to(target)
    if name == "fulfillment-publication.json":
        with pytest.raises((ValueError, OSError)):
            publish_fulfillment_outputs(preparation_context.verify_run_dir, preparation_context.spec_dir,
                {"fulfillment-report.md": "new", "fulfillment-gaps.md": "new"})
    else:
        result = run(preparation_context, SemanticExecutor())
        assert result.exit_code != 0
    assert target.read_text() == "private original"


def test_publication_receipt_corruption_does_not_publish(preparation_context):
    from harness.fulfillment_recovery import publish_fulfillment_outputs
    context = preparation_context
    outputs = {"fulfillment-report.md": "new", "fulfillment-gaps.md": "new"}
    (context.verify_run_dir / "fulfillment-publication.json").write_text('{"payload":{},"sha256":"wrong"}')
    with pytest.raises(ValueError):
        publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir, outputs)
    assert not (context.spec_dir / "fulfillment-report.md").exists()


@pytest.mark.parametrize("failure", ["missing_role", "unsupported"])
def test_early_admission_failure_retains_prior_usage(preparation_context, failure):
    executor = SemanticExecutor()
    assert run(preparation_context, executor).token_usage == 7
    if failure == "missing_role":
        (preparation_context.workspace_root / ".echelon/prosaic/subagents/echelon.fulfillment-mapper.md").unlink()
    else:
        executor.supports_inspection_turn = False
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert result.token_usage == 7
    assert executor.dispatch_count == 1


def test_publication_preserves_exact_original_newlines(preparation_context):
    from harness.fulfillment_recovery import publish_fulfillment_outputs
    context = preparation_context
    (context.spec_dir / "fulfillment-report.md").write_bytes(b"original\r\nreport\r\n")
    (context.spec_dir / "fulfillment-gaps.md").write_bytes(b"original\r\ngaps\r\n")
    publish_fulfillment_outputs(context.verify_run_dir, context.spec_dir,
        {"fulfillment-report.md": "new\nreport\n", "fulfillment-gaps.md": "new\ngaps\n"})
    assert (context.spec_dir / "fulfillment-report.md").read_bytes() == b"new\nreport\n"
    assert (context.spec_dir / "fulfillment-gaps.md").read_bytes() == b"new\ngaps\n"

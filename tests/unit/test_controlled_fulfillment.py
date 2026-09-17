"""The real host sequence stages exact reports without model write authority."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from harness.ai_cli_backend import CliRunResult
from tests.unit.test_fulfillment_preparation import preparation_context, scripted_graph_tools, _snapshot


@pytest.fixture(autouse=True)
def installed_roles(preparation_context, monkeypatch):
    """Script only external Prosaic inspect; parse the actual authored artifacts."""
    context = preparation_context
    bundle = context.workspace_root / ".echelon/prosaic/subagents"
    bundle.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    for name in ("mapper", "judge"):
        filename = f"echelon.fulfillment-{name}.md"
        (bundle / filename).write_bytes((repo / "prosaic/subagents" / filename).read_bytes())
    real_run = subprocess.run
    def inspect(command, **kwargs):
        if command[:2] != ["prosaic", "inspect"]:
            return real_run(command, **kwargs)
        path = Path(command[4]) / command[2]
        if not path.exists():
            return subprocess.CompletedProcess(command, 1, "", "missing role")
        _, metadata, body = path.read_text().split("---", 2)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "type": "subagent", "frontmatter": yaml.safe_load(metadata), "body": body}), "")
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)


class SemanticExecutor:
    supports_inspection_turn = True
    cli = "codex"

    def __init__(self, *, inspect_source=False, bad=None, usage=7):
        self.inspect_source, self.bad, self.usage = inspect_source, bad, usage
        self.dispatches = []

    @property
    def dispatch_count(self):
        return len(self.dispatches)

    def run_inspection_turn(self, private_cwd, prompt, *, frontmatter, timeout_ms):
        assert not list(Path(private_cwd).iterdir())
        assert set(frontmatter) == {"model_tier", "effort"}
        assert 0 < timeout_ms <= 300000
        data = json.loads(prompt.split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment = data["assignment"]
        self.dispatches.append(data)
        if self.bad == "provider":
            return CliRunResult(125, "", "scripted native tool rejection", token_usage=self.usage)
        if self.bad == "malformed":
            return CliRunResult(0, "[]", "", token_usage=self.usage)
        if self.bad == "read_forever" or (self.inspect_source and assignment["step"] == "mapper" and not data["reads"]):
            value = {**assignment, "action": "read", "request": {
                "op": "read_file", "root": "worktree", "path": "app.py", "start_line": 1, "line_count": 2}}
        else:
            rows = []
            for item in assignment["assigned_ids"]:
                if assignment["step"] == "mapper":
                    evidence = "worktree:app.py:1" if self.inspect_source and item == "FR-000001" else ""
                    rows.append({"id": item, "verified_implementation_evidence": evidence,
                        "verified_test_evidence": "", "codegraph_candidates": "",
                        "candidate_disposition": "none", "evidence_kind": "missing", "evidence_strength": "none",
                        "runtime_threshold": False, "confidence": "low" if evidence else "none",
                        "notes": "No test evidence"})
                else:
                    rows.append({"id": item, "status": "UNVERIFIED", "evidence": "worktree:app.py:1; no test evidence"})
            if self.bad == "extra_id":
                rows[0]["id"] = "FR-999999"
            if self.bad == "unread_citation":
                rows[0]["verified_implementation_evidence"] = "worktree:app.py:1"
            value = {**assignment, "action": "final", "rows": rows, "unmapped_candidates": []}
        return CliRunResult(0, json.dumps(value), "", token_usage=self.usage)


def run(context, executor, **kwargs):
    from harness.controlled_fulfillment import ControlledFulfillment
    return ControlledFulfillment(executor, context.workspace_root).run(context, **kwargs)


def test_mechanical_missing_report_skips_judge_and_stays_staged(preparation_context):
    context = preparation_context
    before = _snapshot(context.spec_dir)
    executor = SemanticExecutor()
    result = run(context, executor)
    assert result.exit_code == 0, result.reason
    assert result.token_usage == 7
    assert executor.dispatch_count == 1
    assert result.report_path.parent == context.verify_run_dir
    assert result.report_path.read_text().splitlines()[4:7] == [
        "| FR-000001 | MISSING | no coverage-map row |",
        "| FR-002 | MISSING | no coverage-map row |",
        "| FR-1000000 | MISSING | no coverage-map row |"]
    assert _snapshot(context.spec_dir) == before
    assert not (context.spec_dir / "fulfillment-report.md").exists()
    assert "T-000001" in result.gaps_path.read_text()
    assert json.loads((context.verify_run_dir / "state.json").read_text())["status"] == "in_progress"


def test_real_host_read_and_prepass_select_only_unresolved_ids(preparation_context):
    (preparation_context.spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-000001 | TC-000001 | unit | automated | automated | tests/test_app.py | none |\n")
    executor = SemanticExecutor(inspect_source=True)
    result = run(preparation_context, executor)
    assert result.exit_code == 0, result.reason
    assert result.token_usage == 21
    assert executor.dispatch_count == 3
    assert executor.dispatches[1]["reads"][0]["response"]["text"] == "def hello(): return 'hello'\n"
    assert executor.dispatches[2]["assignment"]["assigned_ids"] == ["FR-000001"]
    assert "| FR-000001 | UNVERIFIED |" in result.report_path.read_text()
    assert "| FR-002 | MISSING |" in result.report_path.read_text()
    assert "TC-000001" in result.gaps_path.read_text()


@pytest.mark.parametrize("bad", ["provider", "malformed", "extra_id", "unread_citation"])
def test_failed_semantics_never_publish_and_keep_usage(preparation_context, bad):
    (preparation_context.spec_dir / "fulfillment-report.md").write_text("previous accepted report")
    before = _snapshot(preparation_context.spec_dir)
    result = run(preparation_context, SemanticExecutor(bad=bad))
    assert result.exit_code != 0
    assert result.token_usage == 7
    assert result.report_path is None
    assert _snapshot(preparation_context.spec_dir) == before


def test_denied_source_read_stops_before_another_turn(preparation_context):
    executor = SemanticExecutor(inspect_source=True)
    result = run(preparation_context, executor, forbidden_paths=(preparation_context.source_root / "app.py",))
    assert result.exit_code != 0
    assert "denied" in result.reason
    assert executor.dispatch_count == 1
    assert result.token_usage == 7


@pytest.mark.parametrize("budget,usage,count", [(0, 7, 0), (6, 7, 1), (100, None, 1)])
def test_finite_budget_blocks_next_dispatch(preparation_context, budget, usage, count):
    executor = SemanticExecutor(inspect_source=True, usage=usage)
    result = run(preparation_context, executor, token_budget=budget)
    assert result.exit_code != 0
    assert "budget" in result.reason or "usage" in result.reason
    assert executor.dispatch_count == count


def test_read_limit_is_enforced_without_semantic_repair(preparation_context):
    executor = SemanticExecutor(bad="read_forever")
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert "read limit" in result.reason
    assert executor.dispatch_count == 33


def test_missing_role_and_unsupported_provider_do_not_prepare_or_dispatch(preparation_context):
    executor = SemanticExecutor()
    executor.supports_inspection_turn = False
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == 0
    assert not (preparation_context.verify_run_dir / "canonical-requirements.json").exists()
    executor.supports_inspection_turn = True
    (preparation_context.workspace_root / ".echelon/prosaic/subagents/echelon.fulfillment-judge.md").unlink()
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == 0
    assert not (preparation_context.verify_run_dir / "canonical-requirements.json").exists()


def test_scoped_stage_preserves_full_inventory_without_out_of_scope_judgments(preparation_context):
    context = replace(preparation_context, scope="scoped", scoped_ids=("FR-1000000",))
    state_path = context.verify_run_dir / "state.json"
    state = json.loads(state_path.read_text())
    state.update(verify_scope="scoped", scoped_ids=["FR-1000000"])
    state_path.write_text(json.dumps(state))
    executor = SemanticExecutor()
    result = run(context, executor)
    assert result.exit_code == 0, result.reason
    assert executor.dispatches[0]["assignment"]["assigned_ids"] == ["FR-1000000"]
    assert result.report_path.read_text().splitlines()[4:] == ["| FR-1000000 | MISSING | no coverage-map row |"]
    assert len(json.loads((context.verify_run_dir / "canonical-requirements.json").read_text())["requirements"]) == 3


@pytest.mark.parametrize("name", ["judgment-prepass.md", "progress-integrity.json", "fulfillment-report.staged.md",
                                  "fulfillment-gaps.staged.md"])
@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_unsafe_stage_destinations_block_before_dispatch(preparation_context, tmp_path, name, alias):
    import os
    target = tmp_path / "protected.txt"
    target.write_text("outside must remain unchanged")
    destination = preparation_context.verify_run_dir / name
    if alias == "symlink":
        destination.symlink_to(target)
    else:
        os.link(target, destination)
    executor = SemanticExecutor()
    result = run(preparation_context, executor)
    assert result.exit_code != 0
    assert executor.dispatch_count == 0
    assert target.read_text() == "outside must remain unchanged"


def test_read_evidence_mutation_during_final_turn_is_rejected(preparation_context):
    measured = preparation_context.source_root / "test-results/run.json"
    measured.parent.mkdir()
    measured.write_text("original measurement\n")
    class MutatingExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            value = json.loads(result.stdout)
            if value["action"] == "read":
                value["request"]["path"] = "test-results/run.json"
            else:
                measured.write_text("changed measurement\n")
                value["rows"][0]["verified_implementation_evidence"] = "worktree:test-results/run.json:1"
            result.stdout = json.dumps(value)
            return result
    result = run(preparation_context, MutatingExecutor(inspect_source=True))
    assert result.exit_code != 0
    assert "changed" in result.reason
    assert result.token_usage == 14
    assert not (preparation_context.verify_run_dir / "fulfillment-report.staged.md").exists()


def test_provider_exception_is_unknown_usage(preparation_context):
    class Crashed(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            raise OSError("lost process response")
    result = run(preparation_context, Crashed())
    assert result.exit_code != 0
    assert result.token_usage is None
    assert result.dispatch_count == 1


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("fault", [None, "tool", "extra_id"])
def test_actual_provider_adapter_stages_or_blocks_semantic_result(preparation_context, monkeypatch, cli, fault):
    import sys
    from harness.llm_provider import AICodingCliProvider
    from tests.unit.test_review_triage_provider import _config, _codex_wire, _claude_wire
    from tests.unit.test_inspection_turn import assert_no_tools_command
    monkeypatch.setattr("harness.ai_cli_backends.claude.host_workspace_synthesis_boundary_available", lambda: True)
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage._sandbox_exec_path", lambda: "/usr/bin/sandbox-exec")
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage.sys.platform", "darwin")
    if fault == "tool":
        wire = (_codex_wire(item_type="command_execution") if cli == "codex" else
                b'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n' + _claude_wire())
        script = f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})"
    else:
        wire = (_codex_wire("__RESULT__") if cli == "codex" else _claude_wire("__RESULT__")).decode()
        script = '''import json, sys
data = json.loads(sys.stdin.read().split("\\nHOST_INPUT_JSON\\n", 1)[1])
rows = [{"id": item, "verified_implementation_evidence": "", "verified_test_evidence": "",
         "codegraph_candidates": "", "candidate_disposition": "none", "evidence_kind": "missing",
         "evidence_strength": "none", "runtime_threshold": False, "confidence": "none", "notes": "No evidence"}
        for item in data["assignment"]["assigned_ids"]]
'''
        if fault == "extra_id":
            script += 'rows[0]["id"] = "FR-999999"\n'
        script += '''answer = json.dumps({**data["assignment"], "action": "final", "rows": rows, "unmapped_candidates": []})
'''
        script += f"sys.stdout.write({wire!r}.replace(json.dumps('__RESULT__'), json.dumps(answer)))\n"
    real_popen = subprocess.Popen
    commands = []
    def launch(command, **kwargs):
        if Path(command[0]).name not in {"codex", "sandbox-exec"}:
            return real_popen(command, **kwargs)
        commands.append(command)
        return real_popen([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(subprocess, "Popen", launch)
    result = run(preparation_context, AICodingCliProvider(_config(cli, unsafe=True)))
    assert result.token_usage == (11 if cli == "codex" else 13)
    assert len(commands) == 1
    assert_no_tools_command(cli, commands[0])
    if fault:
        assert result.exit_code != 0
        assert result.report_path is None
    else:
        assert result.exit_code == 0, result.reason
        assert "| FR-1000000 | MISSING |" in result.report_path.read_text()
    assert not (preparation_context.spec_dir / "fulfillment-report.md").exists()


@pytest.mark.parametrize("field,value", [("status", "blocked"), ("spec_id", "other-spec"),
                                       ("verify_scope", "scoped"), ("scoped_ids", ["FR-1000000"]),
                                       ("build", {"completed_tasks": 99})])
def test_selected_run_binding_cannot_change_during_model_call(preparation_context, field, value):
    class MutatingState(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            path = preparation_context.verify_run_dir / "state.json"
            state = json.loads(path.read_text())
            state[field] = value
            path.write_text(json.dumps(state))
            return result
    result = run(preparation_context, MutatingState())
    assert result.exit_code != 0
    assert "changed" in result.reason
    assert result.token_usage == 7
    assert not (preparation_context.verify_run_dir / "fulfillment-report.staged.md").exists()


@pytest.mark.parametrize("evidence", ["worktree:nonexistent.py:999; claimed verified",
                                     "Everything works; all tests passed"])
def test_judge_cannot_publish_implemented_from_unread_or_absent_citations(preparation_context, evidence):
    (preparation_context.spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-000001 | TC-000001 | unit | automated | automated | tests/test_app.py | none |\n")
    class FabricatingJudge(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            payload = json.loads(result.stdout)
            if payload["step"] == "judge":
                payload["rows"][0].update(status="IMPLEMENTED", evidence=evidence)
                result.stdout = json.dumps(payload)
            return result
    result = run(preparation_context, FabricatingJudge(inspect_source=True))
    assert result.exit_code != 0
    assert "citat" in result.reason or "unread" in result.reason
    assert result.token_usage == 21
    assert not (preparation_context.verify_run_dir / "fulfillment-report.staged.md").exists()


def test_host_staging_does_not_invalidate_immutable_evidence_listing(preparation_context):
    class ListingExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            payload = json.loads(result.stdout)
            if payload["action"] == "read":
                payload["request"] = {"op": "list_directory", "root": "evidence", "path": "."}
            else:
                payload["rows"][0]["verified_implementation_evidence"] = ""
            result.stdout = json.dumps(payload)
            return result
    result = run(preparation_context, ListingExecutor(inspect_source=True))
    assert result.exit_code == 0, result.reason
    assert result.token_usage == 14


def test_degraded_graph_cannot_erase_runtime_threshold(preparation_context, scripted_graph_tools):
    context = preparation_context
    (context.spec_dir / "spec.md").write_text("# Spec\nNFR-000001: Response latency must remain below 50ms.\n")
    (context.spec_dir / "tasks.md").write_text(
        "- [ ] T-000001 complexity=standard phase=build req=NFR-000001 depends=none\n")
    (context.spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| NFR-000001 | TC-000001 | unit | automated | automated | tests/test_app.py | none |\n")
    scripted_graph_tools[0].write_text('process.stderr.write("graph unavailable"); process.exit(1);')
    class ThresholdExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            value = json.loads(result.stdout)
            if value["step"] == "mapper" and value["action"] == "final":
                value["rows"][0].update(verified_implementation_evidence="worktree:app.py:1",
                    evidence_kind="assertion_only", evidence_strength="weak", runtime_threshold=False, confidence="high")
                result.stdout = json.dumps(value)
            return result
    executor = ThresholdExecutor(inspect_source=True)
    result = run(context, executor)
    assert result.exit_code == 0, result.reason
    assert executor.dispatch_count == 2
    assert "| NFR-000001 | UNVERIFIED | prepass:threshold_assertion_only |" in result.report_path.read_text()


def test_owner_deferred_ids_never_enter_semantic_assignment(preparation_context):
    from harness.deferred_scope import apply_defer
    apply_defer(preparation_context.spec_dir, ["FR-000001"], reason="owner decision")
    executor = SemanticExecutor()
    result = run(preparation_context, executor)
    assert result.exit_code == 0, result.reason
    assert executor.dispatches[0]["assignment"]["assigned_ids"] == ["FR-002", "FR-1000000"]
    assert "| FR-000001 | DEFERRED_SCOPE | defer:defer-001: owner decision |" in result.report_path.read_text()


def test_required_observation_cannot_be_replaced_by_semantics(preparation_context):
    executor = SemanticExecutor()
    result = run(replace(preparation_context, observer_required=True), executor)
    assert result.exit_code != 0
    assert "observation" in result.reason
    assert executor.dispatch_count == 0
    assert result.token_usage == 0


def test_literal_markdown_separator_in_requirement_does_not_drop_threshold_input(preparation_context):
    (preparation_context.spec_dir / "spec.md").write_text(
        "# Spec\nFR-000001: Preserve the --- YAML document separator.\n")
    result = run(preparation_context, SemanticExecutor())
    assert result.exit_code == 0, result.reason
    assert "| FR-000001 | MISSING |" in result.report_path.read_text()

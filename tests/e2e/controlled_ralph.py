"""Test-only controlled delivery fixtures; never use legacy shell-like LLM dispatch."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from harness.ai_cli_backend import CliRunResult
from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM
from harness.verification_stack_runtime import apply_verification_stacks


CHAIN = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
FINDING = "app.py:1 FR-001 division is incorrect"
VERIFY_COMMAND = "python -B -m unittest discover -s tests -v"
OBSERVER_COMMAND = 'python -B tests/emit_coverage_json.py "$ECHELON_COVERAGE_REPORT"'
ROLES = [f"echelon.delivery-{role}.md" for role in (
    "implementer", "spec-guard", "code-reviewer", "test-guardian", "tech-writer", "docs-verifier"
)] + [f"echelon.fulfillment-{role}.md" for role in ("mapper", "judge")]


def install_roles(root):
    agents = root / ".echelon/prosaic/subagents"
    agents.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[2] / "prosaic/subagents"
    for name in ROLES:
        shutil.copyfile(source / name, agents / name)


def install_test_stack(root):
    """Select a fixture-owned observer; the production capability gate stays real."""
    stack = root / ".echelon/stacks/controlled-unit"
    stack.mkdir(parents=True)
    (stack / "stack.yml").write_text(yaml.safe_dump({
        "schema_version": "1.4",
        "stack": {"id": "controlled-unit", "name": "Controlled unit test",
                  "version": "1", "kind": "capability"},
        "applies_to": {"archetypes": ["custom"]},
        "provides": {"x.test.observer": "controlled-unit"},
        "context": {"files": ["context.md"]},
        "runnability": {"classification": "non_runnable", "policy": "not_applicable"},
        "coverage_observers": [{
            "id": "controlled-unit", "test_types": ["unit"],
            "command": OBSERVER_COMMAND,
            "report_path": ".echelon/coverage-reports/unit.json",
            "adapter": "vitest-json", "mode": "isolated", "required": True,
        }],
    }))
    (stack / "context.md").write_text("# Controlled unit-test observer\n")


class ControlledGitOps(MockGitOps):
    def __init__(self, root):
        super().__init__(root)
        self.source = root / "sources/app"
        self.source.mkdir(parents=True)
        self._write_project(self.source)
        self._git(self.source, "init", "-b", "main")
        self._git(self.source, "config", "user.email", "test@example.invalid")
        self._git(self.source, "config", "user.name", "Fixture")
        self._git(self.source, "add", "-A")
        self._git(self.source, "commit", "-m", "baseline")
        self.mirror = root / "runs/build-test/mirror.git"
        self.mirror.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "--mirror", str(self.source), str(self.mirror)],
                       check=True, capture_output=True)
        self._git(self.mirror, "config", "user.email", "test@example.invalid")
        self._git(self.mirror, "config", "user.name", "Fixture")

    @staticmethod
    def _git(root, *args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

    @staticmethod
    def _write_project(root):
        spec = root / "specs/test-spec"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text("# Spec\nFR-001: Divide two numbers correctly.\n")
        (spec / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
            "  **Files:**\n  - `app.py` - Division implementation.\n"
            "  **Named Test Ownership:** TC-001\n"
            "  **Acceptance Criteria:**\n  - [ ] divide(10, 2) returns 5.\n"
        )
        (root / "app.py").write_text("def divide(a, b): return a * b\n")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text(
            "import unittest\nfrom app import divide\n"
            "class DivisionTest(unittest.TestCase):\n"
            "    # test_divide [echelon:TC-001]\n"
            "    def test_divide(self):\n"
            "        \"\"\"[echelon:TC-001] divides numbers\"\"\"\n"
            "        self.assertEqual(divide(10, 2), 5)\n"
        )
        (tests / "emit_coverage_json.py").write_text(
            "import json\nimport sys\nimport unittest\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "class RecordingResult(unittest.TextTestResult):\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        super().__init__(*args, **kwargs)\n"
            "        self.passed_ids = []\n"
            "    def addSuccess(self, test):\n"
            "        super().addSuccess(test)\n"
            "        self.passed_ids.append(test.id())\n"
            "suite = unittest.defaultTestLoader.discover('tests')\n"
            "result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, "
            "resultclass=RecordingResult).run(suite)\n"
            "passed = (result.wasSuccessful() and result.testsRun == 1 and "
            "result.passed_ids == ['test_app.DivisionTest.test_divide'])\n"
            "report = {'testResults': [{'name': 'tests/test_app.py', 'assertionResults': ["
            "{'title': 'test_divide [echelon:TC-001]', "
            "'status': 'passed' if passed else 'failed', "
            "'failureMessages': [str(error) for _, error in result.failures + result.errors] "
            "or ([] if passed else ['TC-001 was not executed'])}]}]}\n"
            "path = Path(sys.argv[1])\npath.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text(json.dumps(report))\n"
            "raise SystemExit(0 if passed else 1)\n"
        )
        (spec / "coverage-map.md").write_text(
            "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
            "|---|---|---|---|---|---|---|\n"
            "| FR-001 | TC-001 | unit | automated | automated | tests/test_app.py | none |\n"
        )
        for name, content in {
            "00-overview.md": "# Division fixture\nA single division correction.\n",
            "requirements-overview.md": "# Requirements\nFR-001 requires correct division.\n",
            "plan.md": "# Plan\nImplement T-001 and verify TC-001.\n",
            "plan-conformance.md": "# Plan conformance\nThe plan covers FR-001.\n",
            "research.md": "# Research\nPython unittest supplies the unit assertion.\n",
            "data-model.md": "# Data model\nNo persisted data model.\n",
            "constitution.md": "# Constitution\nP1: Verify the division result.\n",
            "test-strategy.md": "# Test strategy\nRun TC-001 with the controlled unit observer.\n",
            "test-architecture.md": "# Test architecture\nOne unit test binds TC-001 to FR-001.\n",
        }.items():
            (spec / name).write_text(content)
        (spec / "plan-conformance.json").write_text(json.dumps({
            "status": "pass", "findings": [], "sources": ["spec.md", "tasks.md"],
        }))
        (root / "README.md").write_text("# Division fixture\nInternal test fixture.\n")

    def create_worktree(self, spec_id, outer_iter, *, build_id, **kwargs):
        root = self._tmp_dir / "runs" / build_id / "worktrees" / f"iter-{outer_iter}"
        root.parent.mkdir(parents=True, exist_ok=True)
        self._git(self.mirror, "worktree", "add", "-b", f"delivery-{outer_iter}", str(root), "main")
        self.worktrees_created.append(str(root))
        self._latest_worktrees[(spec_id, build_id)] = str(root)
        return str(root)

    def commit(self, worktree_path, message, *, exclude_paths=()):
        self.commits.append({"path": worktree_path, "message": message})
        self._git(worktree_path, "add", "-A", "--", ".", *[f":(exclude){path}" for path in exclude_paths])
        self._git(worktree_path, "commit", "--allow-empty", "-m", message)
        return self._git(worktree_path, "rev-parse", "HEAD")

    def local_merge(self, branch, spec_id, spec_name=""):
        self._git(self.source, "fetch", str(self.mirror), branch)
        self._git(self.source, "merge", "--ff-only", "FETCH_HEAD")
        super().local_merge(branch, spec_id, spec_name)


class ControlledExecutor:
    supports_read_only_review = True
    supports_inspection_turn = True
    cli = "codex"

    def __init__(self, *, tokens=50, reject_reviews=False, wrong_builds=0):
        self.tokens = tokens
        self.reject_reviews = reject_reviews
        self.wrong_builds = wrong_builds
        self.build_count = 0
        self.calls = []
        self.inspections = []

    def run_agent_result(self, cwd, prompt, *, request_metadata, **kwargs):
        assignment = dict(request_metadata["delivery_assignment"])
        self.calls.append((assignment, prompt))
        step = assignment["step"]
        verdict = {"implementer": "DONE", "spec_guard": "PASS",
                   "code_reviewer": "APPROVED", "test_guardian": "PASS",
                   "tech_writer": "DONE", "docs_verifier": "PASS"}[step]
        findings = []
        if step == "implementer":
            self.build_count += 1
            wrong = self.reject_reviews or self.build_count <= self.wrong_builds
            Path(cwd, "app.py").write_text(
                f"# Candidate {len(self.calls)}\ndef divide(a, b): return a {'*' if wrong else '/'} b\n"
            )
        elif step == "spec_guard" and self.reject_reviews:
            verdict, findings = "FAIL", [FINDING]
        payload = {**assignment, "verdict": verdict,
                   "summary": "Reviewed the assigned division task", "findings": findings}
        if step in {"spec_guard", "test_guardian"}:
            assert "self.assertEqual(divide(10, 2), 5)" in Path(cwd, "tests/test_app.py").read_text()
            payload["reviewed_test_paths"] = ["tests/test_app.py"]
        if step == "tech_writer":
            payload["report_markdown"] = """---
schema_version: 2
docs_required: false
readme_updated: false
changelog_updated: false
changelog_format: not_required
not_applicable_reason: Internal division bug fix; no user-facing interface change.
delivery_change_ids: [T-001]
documented_changes:
  - change_id: T-001
    disposition: not_applicable
    reason: Internal division bug fix.
    evidence_paths: [app.py]
---
# Documentation Impact Report
The division correction is internal; app.py is the evidence.
"""
        elif step == "docs_verifier":
            for path in ("app.py", "tests/test_app.py", "README.md", "specs/test-spec/spec.md"):
                assert Path(cwd, path).read_text()
            metadata = dict(schema_version=2, reviewed_change_ids=["T-001"], uncovered_change_ids=[],
                unsupported_claims=[], verdict="PASS", readme_first_run_manual=True,
                changelog_valid=True, impact_report_valid=True, project_evidence_checked=True,
                evidence_items_checked=4, blocking_findings=0,
                runnability_evidence_sha256="", runnability_commands_current=False)
            payload["report_markdown"] = "---\n" + yaml.safe_dump(metadata) + "---\n# Docs Verification Report\nPASS\n"
        return CliRunResult(0, json.dumps(payload),
            "", token_usage=self.tokens)

    def run_inspection_turn(self, private_cwd, prompt, **kwargs):
        assert not list(Path(private_cwd).iterdir())
        data = json.loads(prompt.split("\nHOST_INPUT_JSON\n", 1)[1])
        self.inspections.append(data)
        binding = data["reply_contract"]["binding"]
        reads = data["reads"]
        if len(reads) < 2:
            path = "app.py" if not reads else "tests/test_app.py"
            value = {**binding, "action": "read", "request": {
                "op": "read_file", "root": "worktree", "path": path,
                "start_line": 1, "line_count": 10}}
        else:
            rows = []
            for item in data["assignment"]["assigned_ids"]:
                if binding["step"] == "mapper":
                    rows.append(dict(id=item, verified_implementation_evidence="worktree:app.py:2",
                        verified_test_evidence="worktree:tests/test_app.py:5", codegraph_candidates="",
                        candidate_disposition="none", evidence_kind="source_and_test", evidence_strength="strong",
                        runtime_threshold=False, confidence="high", notes="Division assertion exercises the implementation."))
                else:
                    rows.append(dict(id=item, status="IMPLEMENTED",
                        evidence="worktree:app.py:2; worktree:tests/test_app.py:5"))
            value = {**binding, "action": "final", "rows": rows, "unmapped_candidates": []}
        return CliRunResult(0, json.dumps(value), "", token_usage=self.tokens)


class VerificationSandbox:
    """Test surrogate for a container: run only the fixture's registered verifier.

    This is not a security sandbox. No model-supplied command is executed here.
    CandidateEvidenceRunner still owns the actual output parsing and receipts.
    """
    def __init__(self):
        self.created, self.destroyed, self.executions = {}, [], []
        self.observer_executions = []
        self.reports = {}

    def create(self, spec):
        from harness.provider import SandboxHandle
        handle = SandboxHandle(f"verify-{len(self.created)}", "fixture-session")
        self.created[handle.id] = Path(spec.worktree_mount)
        return handle

    def exec(self, handle, cmd, **kwargs):
        from harness.exec_result import ExecResult
        assert handle.id not in self.destroyed
        assert cmd in {VERIFY_COMMAND, OBSERVER_COMMAND}, f"Unregistered fixture command: {cmd}"
        root = self.created[handle.id]
        started = time.monotonic()
        if cmd == OBSERVER_COMMAND:
            sandbox_path = kwargs["env"]["ECHELON_COVERAGE_REPORT"]
            report = root.parent / "observer-reports" / handle.id / Path(sandbox_path).name
            self.reports[(handle.id, sandbox_path)] = report
            command = [sys.executable, "-B", "tests/emit_coverage_json.py", str(report)]
        else:
            command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
        calls = self.observer_executions if cmd == OBSERVER_COMMAND else self.executions
        calls.append((root, result.returncode, result.stdout, result.stderr))
        return ExecResult(result.returncode, result.stdout, result.stderr,
                          int((time.monotonic() - started) * 1000), None)

    def read_file(self, handle, path):
        assert handle.id not in self.destroyed
        return self.reports[(handle.id, path)].read_bytes()

    def destroy(self, handle):
        self.destroyed.append(handle.id)


class ControlledRun:
    def __init__(self, root, config, *, tokens=50, reject_reviews=False, wrong_builds=0, mode="banzai"):
        self.root = Path(root)
        install_roles(self.root)
        install_test_stack(self.root)
        (self.root / ".echelon/config.yml").write_text(
            "workspace:\n  sources:\n    - id: app\n      path: sources/app\n"
            "stacks:\n  selected:\n    - controlled-unit\n"
        )
        apply_verification_stacks(config, project_root=self.root,
                                  target_root=self.root / "sources/app")
        config.verify_command = VERIFY_COMMAND
        self.executor = ControlledExecutor(tokens=tokens, reject_reviews=reject_reviews, wrong_builds=wrong_builds)
        self.legacy_stub = StubLLM()
        self.provider = VerificationSandbox()
        self.controller, self.store, self.gitops, self.provider, self.escalation = make_ralph_controller(
            stub_llm=self.legacy_stub, tmp_dir=self.root, harness_config=config, mode=mode,
            mock_gitops=ControlledGitOps(self.root), llm_provider=self.executor,
            sandbox_provider=self.provider,
        )
        shutil.copytree(self.gitops.source / "specs", self.root / "specs")
        (self.root / ".gitignore").write_text("/sources/\n/runs/\n")
        self.gitops._git(self.root, "init", "-b", "main")
        self.gitops._git(self.root, "config", "user.email", "test@example.invalid")
        self.gitops._git(self.root, "config", "user.name", "Fixture")
        self.gitops._git(self.root, "add", ".echelon", "specs", ".gitignore")
        self.gitops._git(self.root, "commit", "-m", "workspace baseline")
        self.store.acquire_lock("test-run")
        self.mode = mode

    def initialize(self, *, budget=5000, max_outer=3, max_inner=5):
        self.store.initialize(run_id="test-run", mode=self.mode, max_outer=max_outer,
                              max_inner=max_inner, token_budget=budget or 0,
                              workspace_root=str(self.root), source_id="app",
                              source_root=str(self.gitops.source), target_repo="app",
                              spec_dir=str(self.root / "specs/test-spec"), target_task_ids=["T-001"])

    def run(self, *, budget=5000, max_outer=3, max_inner=5):
        return self.controller.run_loop(token_budget=budget, max_outer=max_outer, max_inner=max_inner)

    def delivery(self, monkeypatch):
        """Use the real phase owner for human resume and final state transitions."""
        from harness.delivery_controller import DeliveryController
        config = self.controller._config
        config.llm.enabled = True
        monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda _: self.executor)
        for key, value in dict(ECHELON_SOURCE_ROOT=str(self.gitops.source),
                               ECHELON_SOURCE_ID="app", ECHELON_TARGET_REPO_NAME="app",
                               ECHELON_TARGET_REPO_PATH=str(self.gitops.source),
                               ECHELON_TARGET_TASK_IDS="T-001").items():
            monkeypatch.setenv(key, value)
        return DeliveryController(self.provider, self.gitops, config, base_dir=str(self.root),
                                  build_id="build-test", orchestration_root=self.root)

    def journals(self):
        return [json.loads(path.read_text()) for path in self.store.state_dir.rglob("journal.json")]

    @property
    def steps(self):
        return [assignment["step"] for assignment, _ in self.executor.calls]

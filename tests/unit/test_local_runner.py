"""Lifecycle tests for the explicit macOS local runner."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from harness.local_runner_candidate import EffectiveLocalCandidate, LocalCandidateRequest
from harness.local_runner_engine import LocalResourceSet
from harness.local_runner_journal import ResourceJournalEntry
from harness.product_inventory import product_evidence_fingerprint
from harness.local_runner import (
    LocalRunnerOptions,
    LocalRunnabilityRunner,
    LocalVerificationRequest,
)
from harness.runnability_contract import load_runnability_contract, runnability_contract_sha256


_CONTRACT = """\
schema_version: 2
enabled: true
install_commands: []
bootstrap_commands: []
start_commands: ["node server.mjs"]
readiness:
  url: http://127.0.0.1:${ECHELON_PORT}/health
  timeout_ms: 1000
primary_journey:
  kind: browser
  url: ${ECHELON_BASE_URL}/
  requirements: [FR-001]
  real_services_required: [web, postgres]
  steps:
    - action: goto
      path: /
  observations:
    - id: scene-visible
      kind: browser_dom
      selector: "#scene"
      expectation: visible
    - id: marker-persisted
      kind: postgres_query
      statement: "select marker from markers where marker = $1"
      parameters: ["${ECHELON_MARKER}"]
      expectation: one_row_exact
persistence_probe:
  restart_commands: ["node server.mjs"]
  observations: [scene-visible, marker-persisted]
stop_commands: ["node stop.mjs"]
local_journey:
  prerequisites: [Docker Desktop]
  provision_commands: ["docker compose up -d postgres"]
  readiness_commands: ["docker compose exec postgres pg_isready"]
  prepare_commands: ["pnpm migrate"]
  verify_commands: ["pnpm verify"]
  start_commands: ["node server.mjs"]
  session_commands: ["pnpm issue-session"]
  open_urls: ["http://127.0.0.1:4173"]
  boundary_probes:
    - id: web-boundary
      service: web
      command: "curl -fsS http://127.0.0.1:4173/health"
    - id: postgres-boundary
      service: postgres
      command: "pnpm db:probe"
  stop_commands: ["node stop.mjs"]
  cleanup_commands: ["docker compose down"]
  execution:
    profile: macos-compose-v1
    compose:
      file: docker-compose.yml
      services: [postgres]
    lifecycle:
      start:
        - [node, server.mjs]
      stop:
        - [node, stop.mjs]
    manual_equivalents:
      start:
        - field: local_journey.start_commands
          index: 0
          transform: same_argv
      stop:
        - field: local_journey.stop_commands
          index: 0
          transform: same_argv
"""


class _FakeProcess:
    returncode = None

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


class _FakeAdapter:
    def __init__(self) -> None:
        self.down_resource_ids: tuple[str, ...] = ()
        self.global_prune_called = False
        self.up_calls = 0

    def probe(self):
        return SimpleNamespace(profile_id="docker-desktop-macos-v1")

    def render_plan(self, plan, run_id: str, generated_root: Path):
        generated_root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            project_name=f"echelon-local-{run_id}",
            generated_override_path=generated_root / f"compose-{run_id}.json",
        )

    def up(self, rendered):
        self.up_calls += 1
        return LocalResourceSet(
            run_id=rendered.project_name.removeprefix("echelon-local-"),
            resources=(
                ResourceJournalEntry(
                    engine="docker",
                    resource_kind="container",
                    resource_id="journalled-container",
                    labels=(
                        ("io.echelon.local-managed", "true"),
                        ("io.echelon.local-run-id", rendered.project_name.removeprefix("echelon-local-")),
                    ),
                ),
            ),
        )

    def inspect(self, rendered, resources):
        return LocalResourceSet(
            run_id=resources.run_id,
            resources=resources.resources,
            bindings=(
                ("DATABASE_URL", "postgresql://generated"),
                ("TEST_DATABASE_URL", "postgresql://generated"),
            ),
        )

    def down(self, rendered, resources):
        self.down_resource_ids = tuple(item.resource_id for item in resources.resources)
        return LocalResourceSet(run_id=resources.run_id, resources=())

    def cleanup(self, generated_override_path: Path, resources):
        self.down_resource_ids = tuple(item.resource_id for item in resources.resources)
        return LocalResourceSet(run_id=resources.run_id, resources=())


@dataclass
class _Fixture:
    workspace: Path
    target: Path
    managed_worktree: Path
    candidate: EffectiveLocalCandidate
    adapter: _FakeAdapter
    candidate_command_calls: list[SimpleNamespace]
    target_git_status_calls: list[str]

    def request(self) -> LocalVerificationRequest:
        return LocalVerificationRequest(
            workspace_root=self.workspace,
            target_root=self.target,
            spec_id="003-local-demo",
            target_id="browser-3d-game",
            candidate_request=LocalCandidateRequest(
                workspace_root=self.workspace,
                target_root=self.target,
                spec_id="003-local-demo",
                target_id="browser-3d-game",
            ),
            local_run_root=self.workspace / "runs" / "build-local-demo" / "local-runs",
        )


def _runner_with_fakes(
    tmp_path: Path,
    *,
    browser_result: str = "passed",
    mutate_candidate_during_start: bool = False,
):
    workspace = tmp_path / "workspace"
    target = workspace / "sources" / "browser-3d-game"
    target.mkdir(parents=True)
    managed = tmp_path / "managed-template"
    (managed / ".echelon").mkdir(parents=True)
    (managed / ".echelon" / "runnability.yml").write_text(_CONTRACT, encoding="utf-8")
    (managed / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:17-alpine\n", encoding="utf-8"
    )
    mirror = workspace / "runs" / "mirror.git"
    mirror.mkdir(parents=True)
    contract = load_runnability_contract(managed)
    assert contract is not None
    candidate = EffectiveLocalCandidate(
        build_id="build-local-demo",
        sandbox_candidate_commit="a" * 40,
        effective_candidate_commit="b" * 40,
        product_fingerprint=product_evidence_fingerprint(managed),
        contract_hash=runnability_contract_sha256(contract),
        stack_hash="d" * 64,
        observer_plan_hash="e" * 64,
        sandbox_receipt_sha256="f" * 64,
        mirror_path=mirror,
        stack_snapshot={
            "schema_version": 1,
            "resolved": {
                "runnability": {
                    "local_runner": {
                        "profiles": ["macos-compose-v1"],
                        "allowed_services": ["postgres"],
                        "environment_bindings": {
                            "DATABASE_URL": "postgres_url",
                            "TEST_DATABASE_URL": "postgres_url",
                        },
                    }
                }
            },
        },
    )
    adapter = _FakeAdapter()
    calls: list[SimpleNamespace] = []
    target_status_calls: list[str] = []

    def materialize(_candidate, destination: Path) -> Path:
        destination.mkdir(parents=True)
        for source in managed.rglob("*"):
            relative = source.relative_to(managed)
            output = destination / relative
            if source.is_dir():
                output.mkdir(exist_ok=True)
            else:
                output.write_bytes(source.read_bytes())
        return destination

    def execute(argv, *, cwd: Path, env, background: bool):
        calls.append(SimpleNamespace(argv=argv, cwd=cwd, env=env, background=background))
        if background and mutate_candidate_during_start:
            (cwd / "unexpected-local-change.txt").write_text("changed\n", encoding="utf-8")
        return _FakeProcess() if background else 0

    def baseline(path: Path) -> str:
        if path == target:
            target_status_calls.append("before" if len(target_status_calls) == 0 else "after")
        return ""

    fixture = _Fixture(workspace, target, managed, candidate, adapter, calls, target_status_calls)
    runner = LocalRunnabilityRunner(
        candidate_resolver=lambda _request: candidate,
        candidate_materializer=materialize,
        candidate_remover=lambda _candidate, path: None,
        adapters={"docker": adapter},
        command_executor=execute,
        readiness_probe=lambda *_args, **_kwargs: True,
        observation_runner=lambda *_args, **_kwargs: browser_result == "passed",
        git_baseline=baseline,
    )
    return runner, fixture


@pytest.mark.unit
def test_runner_uses_managed_worktree_and_preserves_user_checkout(tmp_path: Path) -> None:
    runner, fixture = _runner_with_fakes(tmp_path)

    result = runner.verify(
        fixture.request(),
        LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
    )

    assert result.status == "passed"
    assert fixture.target_git_status_calls == ["before", "after"]
    assert all(call.cwd != fixture.target for call in fixture.candidate_command_calls)
    assert all(call.cwd != fixture.workspace for call in fixture.candidate_command_calls)


@pytest.mark.unit
def test_runner_cleans_only_journalled_resources_after_journey_failure(tmp_path: Path) -> None:
    runner, fixture = _runner_with_fakes(tmp_path, browser_result="failed")

    result = runner.verify(
        fixture.request(),
        LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
    )

    assert result.status == "candidate_lifecycle_failed"
    assert fixture.adapter.down_resource_ids == ("journalled-container",)
    assert fixture.adapter.global_prune_called is False


@pytest.mark.unit
def test_runner_rejects_post_build_contract_change_before_creating_resources(
    tmp_path: Path,
) -> None:
    runner, fixture = _runner_with_fakes(tmp_path)
    runner._candidate_resolver = lambda _request: replace(
        fixture.candidate, contract_hash="0" * 64
    )

    result = runner.verify(
        fixture.request(),
        LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
    )

    assert result.status == "candidate_lifecycle_failed"
    assert fixture.adapter.up_calls == 0


@pytest.mark.unit
def test_runner_rejects_lifecycle_that_changes_the_verified_candidate(
    tmp_path: Path,
) -> None:
    """A local run cannot pass after changing product contents outside Echelon."""
    runner, fixture = _runner_with_fakes(
        tmp_path,
        mutate_candidate_during_start=True,
    )

    result = runner.verify(
        fixture.request(),
        LocalRunnerOptions(engine="docker", action_confirmed=True, keep_on_failure=False),
    )

    assert result.status == "candidate_lifecycle_failed"
    assert "verified product contents" in result.summary


@pytest.mark.unit
def test_interrupted_run_cleanup_uses_only_journalled_resources_and_managed_candidate(
    tmp_path: Path,
) -> None:
    """A recovery command must never broaden cleanup beyond its run journal."""
    runner, fixture = _runner_with_fakes(tmp_path)
    run_id = "local-" + "a" * 32
    run_root = fixture.request().local_run_root / run_id
    candidate = run_root / "candidate"
    candidate.mkdir(parents=True)
    fixture.candidate.mirror_path.mkdir(parents=True, exist_ok=True)
    from harness.local_runner_journal import LocalRunJournal, write_local_run_journal

    write_local_run_journal(
        run_root,
        LocalRunJournal(
            local_run_id=run_id,
            status="running",
            target_git_baseline="",
            workspace_git_baseline="",
            workspace_root=str(fixture.workspace),
            target_root=str(fixture.target),
            mirror_path=str(fixture.candidate.mirror_path),
            resources=(
                ResourceJournalEntry(
                    engine="docker",
                    resource_kind="container",
                    resource_id="journalled-container",
                    labels=(
                        ("io.echelon.local-managed", "true"),
                        ("io.echelon.local-run-id", run_id),
                    ),
                ),
            ),
        ),
    )

    recovered = LocalRunnabilityRunner(
        adapters={"docker": fixture.adapter},
        git_baseline=lambda _path: "",
        recovery_workspace_root=fixture.workspace,
        recovery_candidate_remover=lambda _mirror, path: shutil.rmtree(path),
    ).cleanup(run_id)

    assert recovered.status == "cleanup_complete"
    assert recovered.cleanup_complete is True
    assert fixture.adapter.down_resource_ids == ("journalled-container",)
    assert not candidate.exists()

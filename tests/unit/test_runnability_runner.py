from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.exec_result import ExecResult
from harness.provider import (
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxSpec,
)
from harness.runnability_contract import (
    JourneyStep,
    Observation,
    PersistenceProbe,
    PrimaryJourney,
    RunnabilityContract,
    RunnabilityIdentity,
    RunnabilityReadiness,
)
from harness.runnability_evidence import validate_runnability_report
from harness.runnability_runner import RunnabilityRunner
from harness.stacks.resolver import ResolvedRunnability, ResolvedStacks
from harness.verification_plan import SandboxServiceSpec


def _ok(stdout: str = "") -> ExecResult:
    return ExecResult(
        exit_code=0,
        stdout=stdout,
        stderr="",
        duration_ms=5,
        resource_stats=None,
    )


def _failed(message: str) -> ExecResult:
    return ExecResult(
        exit_code=1,
        stdout="",
        stderr=message,
        duration_ms=5,
        resource_stats=None,
    )


class RecordingProvider:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.created: list[SandboxHandle] = []
        self.destroyed: list[SandboxHandle] = []
        self.commands: list[str] = []
        self.service_commands: list[tuple[str, tuple[str, ...]]] = []
        self.files: dict[str, bytes] = {}
        self.services_started = 0

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        handle = SandboxHandle(
            id=f"sandbox-{len(self.created) + 1}",
            session_id=f"session-{len(self.created) + 1}",
        )
        self.created.append(handle)
        return handle

    def start_services(
        self,
        handle: SandboxHandle,
        services: tuple[SandboxServiceSpec, ...],
    ) -> tuple[str, ...]:
        self.services_started += 1
        if self.fail_at == "provision":
            raise RuntimeError("sidecar failed")
        return tuple(f"service-{index}" for index, _ in enumerate(services))

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        self.commands.append(cmd)
        stage = ""
        if cmd == "install-dependencies":
            stage = "install"
        elif cmd == "migrate-database":
            stage = "bootstrap"
        elif cmd == "issue-session":
            stage = "identity"
        elif "echelon-runnability-start" in cmd:
            stage = "start"
        elif "echelon-runnability-readiness" in cmd:
            stage = "readiness"
        elif "echelon-runnability-app-logs" in cmd:
            return _ok("application process log: API failed to bind")
        elif "user-runnability-browser.mjs" in cmd:
            stage = "primary_journey"
        elif cmd == "restart-application":
            stage = "restart"
        elif cmd == "stop-application" or "echelon-runnability-stop" in cmd:
            stage = "stop"
        if self.fail_at == stage:
            return _failed(f"{stage} failed")
        if stage == "identity":
            return _ok(json.dumps({"token": "sandbox-session-token"}))
        if stage == "primary_journey":
            return _ok(
                json.dumps(
                    {
                        "status": "passed",
                        "observations": {
                            "checkpoint-visible": {
                                "passed": True,
                                "actual": "present",
                            }
                        },
                    }
                )
            )
        return _ok("ready")

    def exec_service(
        self,
        handle: SandboxHandle,
        service_name: str,
        argv: tuple[str, ...],
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        self.service_commands.append((service_name, argv))
        if self.fail_at == "persistence":
            return _ok("")
        marker_argument = next(item for item in argv if item.startswith("echelon_p1="))
        return _ok(marker_argument.split("=", 1)[1] + "\n")

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        self.files[path] = content

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return self.files[path]

    def destroy(self, handle: SandboxHandle) -> None:
        self.destroyed.append(handle)


def _sandbox_spec(worktree: Path) -> SandboxSpec:
    return SandboxSpec(
        image="mcr.microsoft.com/playwright:v1.62.1-noble",
        image_source="runnability",
        worktree_mount=str(worktree),
        container_mount="/workspace",
        resource_limits=ResourceLimits(),
        network_policy=NetworkPolicy(),
        env={},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
        ephemeral_volumes=["node_modules"],
    )


def _contract() -> RunnabilityContract:
    observations = (
        Observation(
            id="checkpoint-visible",
            kind="browser_dom",
            expectation="present",
            selector='[data-checkpoint-state="owned"]',
        ),
        Observation(
            id="checkpoint-persisted",
            kind="postgres_query",
            expectation="one_row_exact",
            statement="SELECT player_id FROM checkpoints WHERE player_id = $1",
            parameters=("${ECHELON_MARKER}",),
        ),
    )
    return RunnabilityContract(
        schema_version=1,
        enabled=True,
        install_commands=("install-dependencies",),
        bootstrap_commands=("migrate-database",),
        start_commands=("start-application",),
        readiness=RunnabilityReadiness(
            url="http://127.0.0.1:${ECHELON_PORT}/health",
            timeout_ms=30_000,
        ),
        identity=RunnabilityIdentity(
            command="issue-session",
            stdout_json=(("token", "ECHELON_SESSION_TOKEN"),),
        ),
        primary_journey=PrimaryJourney(
            kind="browser",
            url="${ECHELON_BASE_URL}",
            requirements=("FR-001",),
            real_services_required=("web", "postgres"),
            session_storage=(("session-token", "${ECHELON_SESSION_TOKEN}"),),
            steps=(JourneyStep(action="goto", path="/"),),
            observations=observations,
        ),
        persistence_probe=PersistenceProbe(
            restart_commands=("restart-application",),
            observation_ids=("checkpoint-visible", "checkpoint-persisted"),
        ),
        stop_commands=("stop-application",),
    )


def _resolved() -> ResolvedStacks:
    return ResolvedStacks(
        selected_ids=["browser", "postgres"],
        resolved_ids=["browser", "postgres"],
        implied_by={},
        capabilities={},
        tools={},
        required_commands=["pnpm"],
        required_registries=[],
        context_files=[],
        services=[
            SandboxServiceSpec(
                service_name="postgres",
                image="postgres:16.4-alpine",
                environment_names=("DATABASE_URL", "TEST_DATABASE_URL"),
            )
        ],
        runnability=ResolvedRunnability(
            classification="user_facing",
            policy="required",
            runner="linux_container",
            capabilities=("install", "provision", "start", "readiness", "primary_journey", "stop"),
            required_observations=("browser_dom", "postgres_query"),
            sources=("browser", "postgres"),
        ),
    )


def _runner(provider: RecordingProvider) -> RunnabilityRunner:
    return RunnabilityRunner(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        spec_id="003-browser-game",
        target_id="browser-game",
        strategy_id="default",
        build_id="build-1",
    )


def _worktree(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    return target


@pytest.mark.unit
def test_runner_proves_journey_and_persistence_in_one_fresh_sandbox(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    result = _runner(provider).run(
        worktree=_worktree(tmp_path),
        contract=_contract(),
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )

    assert result.status == "runnable"
    assert [stage.name for stage in result.stages] == [
        "sandbox_prerequisites",
        "install",
        "provision",
        "bootstrap",
        "identity",
        "start",
        "readiness",
        "primary_journey",
        "persistence_before_restart",
        "restart",
        "persistence_after_restart",
        "stop",
        "teardown",
    ]
    assert provider.commands.index("corepack enable") < provider.commands.index(
        "install-dependencies"
    )
    assert len(provider.created) == 1
    assert provider.destroyed == provider.created
    assert provider.services_started == 1
    assert [name for name, _ in provider.service_commands] == ["postgres", "postgres"]
    for _name, argv in provider.service_commands:
        assert "--username" in argv
        assert argv[argv.index("--username") + 1] == "echelon_session1"
        assert "--dbname" in argv
        assert argv[argv.index("--dbname") + 1] == "echelon_verify"
    assert validate_runnability_report(
        result.evidence,
        candidate_commit="b" * 40,
        candidate_fingerprint=result.candidate_fingerprint,
        contract_hash=result.contract_hash,
        stack_hash=result.stack_hash,
    ).valid


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    ["install", "provision", "start", "readiness", "primary_journey", "persistence"],
)
def test_runner_always_stops_and_destroys_after_failure(
    tmp_path: Path,
    failure: str,
) -> None:
    provider = RecordingProvider(fail_at=failure)

    result = _runner(provider).run(
        worktree=_worktree(tmp_path),
        contract=_contract(),
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )

    assert result.status == "not_runnable"
    assert result.failed_stage is not None
    assert provider.destroyed == provider.created
    assert any(stage.name == "teardown" for stage in result.stages)


@pytest.mark.unit
def test_runner_creates_a_new_sandbox_for_every_attempt(tmp_path: Path) -> None:
    provider = RecordingProvider()
    runner = _runner(provider)
    worktree = _worktree(tmp_path)

    runner.run(
        worktree=worktree,
        contract=_contract(),
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )
    runner.run(
        worktree=worktree,
        contract=_contract(),
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=2,
    )

    assert [item.session_id for item in provider.created] == ["session-1", "session-2"]
    assert provider.destroyed == provider.created


@pytest.mark.unit
def test_runner_rejects_missing_required_service_boundary_observation(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    contract = _contract()
    contract = replace(
        contract,
        primary_journey=replace(
            contract.primary_journey,
            real_services_required=("web", "api", "postgres"),
        ),
    )

    result = _runner(provider).run(
        worktree=_worktree(tmp_path),
        contract=contract,
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )

    assert result.status == "not_runnable"
    assert result.failure_class == "mocked_dependency_detected"
    assert result.failed_stage == "primary_journey"


@pytest.mark.unit
def test_runner_rejects_omitting_stack_required_observation(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    resolved = _resolved()
    resolved = replace(
        resolved,
        runnability=replace(
            resolved.runnability,
            required_observations=("browser_dom", "http", "postgres_query"),
        ),
    )

    result = _runner(provider).run(
        worktree=_worktree(tmp_path),
        contract=_contract(),
        resolved=resolved,
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )

    assert result.status == "not_runnable"
    assert result.failure_class == "mocked_dependency_detected"
    assert "stack-required observation 'http'" in result.summary
    assert provider.created == []


@pytest.mark.unit
def test_readiness_failure_includes_background_application_logs(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(fail_at="readiness")

    result = _runner(provider).run(
        worktree=_worktree(tmp_path),
        contract=_contract(),
        resolved=_resolved(),
        candidate_commit="a" * 40,
        evidence_dir=tmp_path / "evidence",
        attempt_sequence=1,
    )

    assert result.status == "not_runnable"
    assert result.failure_class == "readiness_failed"
    assert "application process log: API failed to bind" in result.summary
    assert any("echelon-runnability-app-logs" in command for command in provider.commands)

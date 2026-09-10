"""Tests for Ralph-owned structured coverage observers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.config import HarnessConfig
from harness.coverage_observer_runner import run_coverage_observers
from harness.exec_result import ExecResult
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.product_inventory import product_evidence_fingerprint
from harness.stacks.resolver import ResolvedCoverageObserver
from harness.stacks.schema import StackCoverageObserver
from harness.verification_evidence import VerificationStage, write_verification_receipt
from harness.verification_plan import SandboxServiceSpec, materialize_services


class _CoverageProvider(SandboxProvider):
    """Records sandbox-only observer execution without a host executor."""

    def __init__(
        self,
        worktree: Path,
        *,
        mutate_candidate: bool = False,
        absolute_report_paths: bool = False,
        transient_browser_failures: int = 0,
    ) -> None:
        self.worktree = worktree
        self.mutate_candidate = mutate_candidate
        self.absolute_report_paths = absolute_report_paths
        self.transient_browser_failures = transient_browser_failures
        self.created_session_ids: list[str] = []
        self.destroyed_session_ids: list[str] = []
        self.service_environments: list[dict[str, str]] = []
        self.exec_calls: list[tuple[str, str, dict[str, str]]] = []
        self.host_exec_calls: list[str] = []
        self.remote_files: dict[str, bytes] = {}
        self.observer_attempts = 0

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        del spec
        session_id = (
            "standard"
            if not self.created_session_ids
            else f"observer-vitest-{len(self.created_session_ids)}"
        )
        self.created_session_ids.append(session_id)
        return SandboxHandle(id=session_id, session_id=session_id)

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        del timeout_ms
        self.exec_calls.append((handle.session_id, cmd, dict(env or {})))
        if cmd == "run-vitest-observer":
            self.observer_attempts += 1
            if self.observer_attempts <= self.transient_browser_failures:
                return ExecResult(
                    1,
                    "",
                    "browserContext.newPage: Target crashed; session closed",
                    15,
                    None,
                )
            if self.mutate_candidate:
                (self.worktree / "candidate-mutation.txt").write_text(
                    "observer must not change product files\n", encoding="utf-8"
                )
            report_path = str((env or {})["ECHELON_COVERAGE_REPORT"])
            self.remote_files[report_path] = json.dumps(
                {
                    "testResults": [
                        {
                            "name": (
                                "/workspace/tests/feature.test.ts"
                                if self.absolute_report_paths
                                else "tests/feature.test.ts"
                            ),
                            "projectName": "default",
                            "assertionResults": [
                                {
                                    "title": "persists checkpoint [echelon:UT-PERSIST-001]",
                                    "status": "passed",
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        assert cwd == "/workspace"
        return ExecResult(0, "ok", "", 15, None)

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        del handle, path, content

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        del handle
        return self.remote_files[path]

    def destroy(self, handle: SandboxHandle) -> None:
        self.destroyed_session_ids.append(handle.session_id)

    def start_services(self, handle: SandboxHandle, services: tuple[Any, ...]) -> tuple[str, ...]:
        del handle
        self.service_environments.append(dict(services[0].environment))
        return ("postgres",)


def _observer(*, mode: str) -> ResolvedCoverageObserver:
    return ResolvedCoverageObserver(
        owner_stack_id="browser-game",
        observer=StackCoverageObserver(
            id="vitest",
            test_types=("unit",),
            command="run-vitest-observer",
            report_path=".echelon/coverage-reports/vitest.json",
            adapter="vitest-json",
            mode=mode,
            required=True,
        ),
    )


def _standard_receipt(root: Path, fingerprint: str) -> object:
    return write_verification_receipt(
        evidence_dir=root / "verification",
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        candidate_commit="a" * 40,
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="sandbox",
        stages=(
            VerificationStage(
                name="verify",
                command=("pnpm", "verify"),
                exit_code=0,
                duration_ms=1,
                stdout=b"ok",
                stderr=b"",
            ),
        ),
        attempt_sequence=1,
        sensitive_environment={},
    )


def _sandbox_spec(worktree: Path) -> SandboxSpec:
    return SandboxSpec(
        image="node:20-slim",
        image_source="fingerprint",
        worktree_mount=str(worktree),
        container_mount="/workspace",
        resource_limits=HarnessConfig().resource_limits,
        network_policy=HarnessConfig().network,
        env={},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
    )


def _config() -> HarnessConfig:
    config = HarnessConfig()
    config.verification_services = [
        SandboxServiceSpec(
            service_name="postgres",
            image="postgres:16.4-alpine",
            environment_names=("TEST_DATABASE_URL",),
        )
    ]
    return config


def test_isolated_observer_uses_fresh_sandbox_services_and_never_host(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "feature.test.ts").write_text(
        'it("persists checkpoint [echelon:UT-PERSIST-001]", () => {});\n',
        encoding="utf-8",
    )
    provider = _CoverageProvider(tmp_path)
    standard_handle = provider.create(_sandbox_spec(tmp_path))
    standard_services = materialize_services(
        tuple(_config().verification_services), session_id=standard_handle.session_id
    )
    provider.start_services(standard_handle, standard_services.services)
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"

    bundle = run_coverage_observers(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="isolated"),),
        standard_receipt=_standard_receipt(evidence_dir, fingerprint),
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    assert provider.created_session_ids == ["standard", "observer-vitest-1"]
    assert provider.destroyed_session_ids == ["observer-vitest-1"]
    assert len(provider.service_environments) == 2
    assert provider.service_environments[0]["POSTGRES_USER"] != (
        provider.service_environments[1]["POSTGRES_USER"]
    )
    assert provider.service_environments[0]["POSTGRES_PASSWORD"] != (
        provider.service_environments[1]["POSTGRES_PASSWORD"]
    )
    assert provider.host_exec_calls == []
    assert bundle.observer_runs[0].status == "passed"
    assert bundle.observer_runs[0].executions[0].test_type == "unit"
    assert bundle.observer_runs[0].receipt is not None
    assert bundle.observer_runs[0].receipt.passed is True
    assert not (tmp_path / ".echelon" / "coverage-reports").exists()
    assert product_evidence_fingerprint(tmp_path) == fingerprint
    assert list(
        (evidence_dir / "coverage-observers" / "vitest" / "reports").glob(
            "attempt-0001-vitest.json"
        )
    )


def test_isolated_observer_normalizes_report_paths_under_its_sandbox_mount(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "feature.test.ts").write_text(
        'it("persists checkpoint [echelon:UT-PERSIST-001]", () => {});\n',
        encoding="utf-8",
    )
    provider = _CoverageProvider(tmp_path, absolute_report_paths=True)
    standard_handle = provider.create(_sandbox_spec(tmp_path))
    standard_services = materialize_services(
        tuple(_config().verification_services), session_id=standard_handle.session_id
    )
    provider.start_services(standard_handle, standard_services.services)
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"

    bundle = run_coverage_observers(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="isolated"),),
        standard_receipt=_standard_receipt(evidence_dir, fingerprint),
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    assert bundle.observer_runs[0].status == "passed"
    assert bundle.observer_runs[0].executions[0].file == "tests/feature.test.ts"


def test_isolated_observer_retries_transient_browser_loss_in_fresh_sandbox(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "feature.test.ts").write_text(
        'it("persists checkpoint [echelon:UT-PERSIST-001]", () => {});\n',
        encoding="utf-8",
    )
    provider = _CoverageProvider(tmp_path, transient_browser_failures=1)
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"

    bundle = run_coverage_observers(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="isolated"),),
        standard_receipt=_standard_receipt(evidence_dir, fingerprint),
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    assert provider.created_session_ids == ["standard", "observer-vitest-1"]
    assert provider.destroyed_session_ids == ["standard", "observer-vitest-1"]
    assert bundle.observer_runs[0].status == "passed"
    assert len(list((evidence_dir / "coverage-observers" / "vitest").glob("attempt-*.json"))) == 2


def test_isolated_observer_classifies_repeated_browser_loss_as_infrastructure(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    provider = _CoverageProvider(tmp_path, transient_browser_failures=2)
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"

    bundle = run_coverage_observers(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="isolated"),),
        standard_receipt=_standard_receipt(evidence_dir, fingerprint),
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    run = bundle.observer_runs[0]
    assert run.status == "failed"
    assert run.failure_kind == "browser_runtime_unavailable"
    assert "fresh-sandbox" in run.reason


def test_captured_observer_reuses_passing_standard_receipt_without_session(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "feature.test.ts").write_text(
        'it("persists checkpoint [echelon:UT-PERSIST-001]", () => {});\n',
        encoding="utf-8",
    )
    report = tmp_path / ".echelon" / "coverage-reports" / "vitest.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "tests/feature.test.ts",
                        "assertionResults": [
                            {
                                "title": "persists checkpoint [echelon:UT-PERSIST-001]",
                                "status": "passed",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = _CoverageProvider(tmp_path)
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"

    standard_receipt = _standard_receipt(evidence_dir, fingerprint)
    bundle = run_coverage_observers(
        provider=provider,
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="captured"),),
        standard_receipt=standard_receipt,
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    assert provider.created_session_ids == []
    assert provider.exec_calls == []
    assert bundle.observer_runs[0].status == "passed"
    assert bundle.observer_runs[0].receipt == standard_receipt


def test_isolated_observer_rejects_a_candidate_mutation_in_its_receipt(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "feature.test.ts").write_text(
        'it("persists checkpoint [echelon:UT-PERSIST-001]", () => {});\n',
        encoding="utf-8",
    )
    fingerprint = product_evidence_fingerprint(tmp_path)
    evidence_dir = tmp_path.parent / f"{tmp_path.name}-evidence"
    bundle = run_coverage_observers(
        provider=_CoverageProvider(tmp_path, mutate_candidate=True),
        sandbox_spec_factory=_sandbox_spec,
        worktree=tmp_path,
        config=_config(),
        observers=(_observer(mode="isolated"),),
        standard_receipt=_standard_receipt(evidence_dir, fingerprint),
        candidate_commit="a" * 40,
        candidate_fingerprint=fingerprint,
        evidence_dir=evidence_dir,
        spec_id="spec-001",
        target_id="game",
        strategy_id="default",
        build_id="build-001",
        sensitive_environment={},
    )

    assert bundle.observer_runs[0].status == "failed"
    assert bundle.observer_runs[0].receipt is not None
    assert bundle.observer_runs[0].receipt.passed is False

"""One explicit, isolated macOS local-verification lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import platform
import re
import signal
import shlex
import shutil
import socket
import subprocess
import time
from typing import Callable, Mapping, MutableMapping
from urllib.parse import urlsplit
from urllib.request import urlopen
import uuid

from harness.local_runner_candidate import (
    EffectiveLocalCandidate,
    LocalCandidateRequest,
    materialize_local_candidate,
    resolve_effective_local_candidate,
)
from harness.local_runner_compose import parse_canonical_compose_plan
from harness.local_runner_engine import (
    DockerDesktopMacOSAdapter,
    LocalEngineAdapter,
    LocalEngineError,
    LocalResourceSet,
    PodmanMacOSAdapter,
)
from harness.local_runner_evidence import (
    LocalRunnabilityAttestationInput,
    local_runner_profile_digest,
    write_local_runnability_attestation,
)
from harness.local_runner_journal import (
    LocalRunJournal,
    LocalRunRecoveryRequired,
    LocalRunSideEffectError,
    acquire_workspace_local_run_lock,
    assert_git_baseline_unchanged,
    assert_no_recovery_journal,
    build_host_execution_environment,
    filter_git_porcelain_baseline,
    git_porcelain_baseline,
    load_local_run_journal,
    write_local_run_journal,
)
from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_contract import (
    LocalExecution,
    RunnabilityContract,
    RunnabilityContractError,
    load_runnability_contract,
    runnability_contract_sha256,
)


class LocalActionConfirmationRequired(RuntimeError):
    """Raised when host-local execution was not explicitly confirmed."""


@dataclass(frozen=True)
class LocalVerificationRequest:
    workspace_root: Path
    target_root: Path
    spec_id: str
    target_id: str
    candidate_request: LocalCandidateRequest
    local_run_root: Path


@dataclass(frozen=True)
class LocalRunnerOptions:
    engine: str
    action_confirmed: bool
    keep_on_failure: bool


@dataclass(frozen=True)
class LocalRunnerResult:
    status: str
    local_run_id: str
    attestation_path: Path | None
    cleanup_complete: bool
    summary: str = ""


@dataclass(frozen=True)
class LocalObservationResult:
    passed: bool
    summary: str


CommandExecutor = Callable[..., object]
ObservationRunner = Callable[..., bool | LocalObservationResult]
BrowserInstaller = Callable[[Path, Mapping[str, str]], None]


class LocalRunnabilityRunner:
    """Own the complete lifecycle; it has no repair or landing authority."""

    def __init__(
        self,
        *,
        candidate_resolver: Callable[[LocalCandidateRequest], EffectiveLocalCandidate] = resolve_effective_local_candidate,
        candidate_materializer: Callable[[EffectiveLocalCandidate, Path], Path] = materialize_local_candidate,
        candidate_remover: Callable[[EffectiveLocalCandidate, Path], None] | None = None,
        adapters: Mapping[str, LocalEngineAdapter] | None = None,
        command_executor: CommandExecutor | None = None,
        readiness_probe: Callable[..., bool] | None = None,
        observation_runner: ObservationRunner | None = None,
        git_baseline: Callable[[Path], str] = git_porcelain_baseline,
        browser_helper: Path | None = None,
        browser_installer: BrowserInstaller | None = None,
        recovery_workspace_root: Path | None = None,
        recovery_candidate_remover: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self._candidate_resolver = candidate_resolver
        self._candidate_materializer = candidate_materializer
        self._candidate_remover = candidate_remover or _remove_candidate_worktree
        self._adapters = dict(adapters or {
            "docker": DockerDesktopMacOSAdapter(),
            "podman": PodmanMacOSAdapter(),
        })
        self._command_executor = command_executor or _run_command
        self._readiness_probe = readiness_probe or _wait_for_readiness
        self._browser_helper = browser_helper
        self._browser_installer = browser_installer or _install_playwright_chromium
        self._observation_runner = observation_runner or (
            lambda worktree, contract, environment, adapter, resources, after_restart:
            _run_independent_observations(
                worktree,
                contract,
                environment,
                adapter,
                resources,
                after_restart,
                browser_helper=self._browser_helper,
            )
        )
        self._git_baseline = git_baseline
        self._recovery_workspace_root = (
            Path(recovery_workspace_root) if recovery_workspace_root is not None else None
        )
        self._recovery_candidate_remover = (
            recovery_candidate_remover or _remove_candidate_at_path
        )

    def verify(
        self,
        request: LocalVerificationRequest,
        options: LocalRunnerOptions,
    ) -> LocalRunnerResult:
        if not options.action_confirmed:
            raise LocalActionConfirmationRequired(
                "local verification requires explicit confirmation"
            )
        adapter = self._adapters.get(options.engine)
        if adapter is None:
            raise LocalEngineError("local engine must be docker or podman")
        with acquire_workspace_local_run_lock(request.workspace_root):
            candidate = self._candidate_resolver(request.candidate_request)
            root = _local_runs_root(request.local_run_root, candidate)
            assert_no_recovery_journal(root)
            return self._verify_locked(candidate, request, options, adapter, root)

    def cleanup(self, local_run_id: str) -> LocalRunnerResult:
        """Recover one interrupted run, using no resource beyond its journal."""
        if not re.fullmatch(r"local-[a-f0-9]{32}", local_run_id):
            raise LocalRunRecoveryRequired("local cleanup requires a valid local run ID")
        if self._recovery_workspace_root is None:
            raise LocalRunRecoveryRequired(
                "local cleanup requires an explicit workspace root"
            )
        workspace = _existing_regular_directory(
            self._recovery_workspace_root, "workspace root"
        )
        with acquire_workspace_local_run_lock(workspace):
            run_root = _find_local_run_root(workspace, local_run_id)
            journal = load_local_run_journal(run_root / "journal.json", run_root.parent)
            if journal.local_run_id != local_run_id:
                raise LocalRunRecoveryRequired("local-run journal identity does not match")
            _validate_recovery_journal(journal, workspace, run_root)
            target = _existing_regular_directory(Path(journal.target_root), "target root")
            resources = LocalResourceSet(
                run_id=local_run_id,
                resources=journal.resources,
            )
            try:
                if resources.resources:
                    adapter = _recovery_adapter(self._adapters, journal)
                    adapter.cleanup(
                        run_root / "generated" / f"compose-{local_run_id}.json",
                        resources,
                    )
                    journal = replace(journal, resources=())
                    write_local_run_journal(run_root, journal)
                candidate_worktree = _journal_candidate_worktree(journal, run_root)
                if candidate_worktree.exists():
                    self._recovery_candidate_remover(
                        Path(journal.mirror_path), candidate_worktree
                    )
                _remove_managed_macos_runtime_temp(journal.local_run_id)
                assert_git_baseline_unchanged(
                    target,
                    journal.target_git_baseline,
                    self._git_baseline(target),
                )
                assert_git_baseline_unchanged(
                    workspace,
                    filter_git_porcelain_baseline(
                        journal.workspace_git_baseline,
                        _runner_owned_workspace_paths(workspace, run_root),
                    ),
                    filter_git_porcelain_baseline(
                        self._git_baseline(workspace),
                        _runner_owned_workspace_paths(workspace, run_root),
                    ),
                )
            except (LocalEngineError, LocalRunSideEffectError, OSError, RuntimeError) as exc:
                failed = replace(journal, status="cleanup_failed")
                write_local_run_journal(run_root, failed)
                return LocalRunnerResult(
                    "cleanup_failed", local_run_id, None, False, str(exc)
                )
            cleaned = replace(
                journal,
                status="cleaned",
                resources=(),
                completed_actions=tuple(
                    dict.fromkeys((*journal.completed_actions, "cleanup"))
                ),
            )
            write_local_run_journal(run_root, cleaned)
            return LocalRunnerResult(
                "cleanup_complete", local_run_id, None, True,
                "Journalled local resources and managed candidate were cleaned.",
            )

    def _verify_locked(
        self,
        candidate: EffectiveLocalCandidate,
        request: LocalVerificationRequest,
        options: LocalRunnerOptions,
        adapter: LocalEngineAdapter,
        root: Path,
    ) -> LocalRunnerResult:
        local_run_id = f"local-{uuid.uuid4().hex}"
        run_root = root / local_run_id
        run_root.mkdir(parents=True, exist_ok=False)
        status = "host_preflight_failed"
        summary = ""
        cleanup_complete = False
        attestation_path: Path | None = None
        candidate_worktree: Path | None = None
        rendered = None
        resources: LocalResourceSet | None = None
        processes: list[object] = []
        environment: Mapping[str, str] = {}
        runtime_temp_root = _managed_macos_runtime_temp(local_run_id)
        target_before = self._git_baseline(request.target_root)
        owned_workspace_paths = _runner_owned_workspace_paths(
            request.workspace_root, run_root
        )
        workspace_before = filter_git_porcelain_baseline(
            self._git_baseline(request.workspace_root), owned_workspace_paths
        )
        journal = LocalRunJournal(
            local_run_id=local_run_id,
            status="running",
            target_git_baseline=target_before,
            workspace_git_baseline=workspace_before,
            workspace_root=str(request.workspace_root.resolve(strict=True)),
            target_root=str(request.target_root.resolve(strict=True)),
            mirror_path=str(candidate.mirror_path.resolve(strict=True)),
        )
        write_local_run_journal(run_root, journal)
        try:
            profile = adapter.probe()
            candidate_worktree = self._candidate_materializer(
                candidate, run_root / "candidate"
            )
            journal = replace(
                journal,
                candidate_worktree=str(candidate_worktree.resolve(strict=True)),
            )
            write_local_run_journal(run_root, journal)
            contract = _load_matching_contract(candidate_worktree, candidate)
            execution, allowed_services, bindings = _local_execution_from_snapshot(
                candidate, contract
            )
            if execution.profile != "macos-compose-v1":
                raise LocalEngineError("candidate local execution profile is unsupported")
            plan = parse_canonical_compose_plan(
                candidate_worktree, execution.compose_file, allowed_services
            )
            initial_environment = _runner_variables(contract)
            controlled = build_host_execution_environment(
                run_root,
                initial_environment,
                runtime_temp_root=runtime_temp_root,
            )
            _execute_stage(
                execution, "install", candidate_worktree, controlled.values,
                self._command_executor, processes,
            )
            self._browser_installer(candidate_worktree, controlled.values)
            rendered = adapter.render_plan(plan, local_run_id, run_root / "generated")
            resources = adapter.up(rendered)
            journal = replace(
                journal,
                resources=resources.resources,
                completed_actions=("engine_up",),
            )
            write_local_run_journal(run_root, journal)
            resources = adapter.inspect(rendered, resources)
            environment = _bound_environment(
                controlled.values, resources.bindings, bindings
            )
            _execute_stage(
                execution, "bootstrap", candidate_worktree, environment,
                self._command_executor, processes,
            )
            _issue_identity(candidate_worktree, contract, environment)
            _execute_stage(
                execution, "start", candidate_worktree, environment,
                self._command_executor, processes,
            )
            if not self._readiness_probe(contract, environment):
                raise _CandidateLifecycleFailure("application readiness did not pass")
            observation = self._observation_runner(
                candidate_worktree, contract, environment, adapter, resources, False
            )
            _require_passing_observation(observation)
            if contract.persistence_probe is not None:
                _terminate_processes(processes)
                processes.clear()
                _execute_stage(
                    execution, "start", candidate_worktree, environment,
                    self._command_executor, processes,
                )
                if not self._readiness_probe(contract, environment):
                    raise _CandidateLifecycleFailure("application readiness after restart did not pass")
                observation = self._observation_runner(
                    candidate_worktree, contract, environment, adapter, resources, True
                )
                _require_passing_observation(observation, after_restart=True)
            if product_evidence_fingerprint(candidate_worktree) != candidate.product_fingerprint:
                raise _CandidateLifecycleFailure(
                    "candidate lifecycle changed the verified product contents"
                )
            status = "passed"
            summary = "Local browser, restart, and persistence observations passed."
        except _CandidateLifecycleFailure as exc:
            status = "candidate_lifecycle_failed"
            summary = str(exc)
        except (LocalEngineError, RunnabilityContractError, ValueError, OSError) as exc:
            status = "host_preflight_failed" if resources is None else "candidate_lifecycle_failed"
            summary = str(exc)
        finally:
            _terminate_processes(processes)
            if candidate_worktree is not None:
                try:
                    contract = load_runnability_contract(candidate_worktree)
                    if contract is not None and contract.local_journey is not None:
                        execution = contract.local_journey.execution
                        if execution is not None:
                            _execute_stage(
                                execution, "stop", candidate_worktree, environment,
                                self._command_executor, [],
                            )
                except Exception:
                    if status == "passed":
                        status = "candidate_lifecycle_failed"
                        summary = "validated stop lifecycle failed"
            if resources is not None and rendered is not None and not (
                options.keep_on_failure and status != "passed"
            ):
                try:
                    adapter.cleanup(rendered.generated_override_path, resources)
                    resources = None
                    cleanup_complete = True
                    journal = replace(
                        journal,
                        status=status,
                        completed_actions=("engine_up", "cleanup"),
                    )
                    write_local_run_journal(run_root, journal)
                except Exception as exc:
                    cleanup_complete = False
                    status = "cleanup_failed"
                    summary = f"{summary}; cleanup failed: {exc}".strip("; ")
            elif resources is None:
                cleanup_complete = True
            if candidate_worktree is not None and (cleanup_complete or status == "passed"):
                try:
                    self._candidate_remover(candidate, candidate_worktree)
                except Exception as exc:
                    cleanup_complete = False
                    status = "cleanup_failed"
                    summary = f"{summary}; candidate cleanup failed: {exc}".strip("; ")
            if cleanup_complete:
                try:
                    _remove_managed_macos_runtime_temp(local_run_id)
                except OSError as exc:
                    cleanup_complete = False
                    status = "cleanup_failed"
                    summary = f"{summary}; runtime cleanup failed: {exc}".strip("; ")
            try:
                assert_git_baseline_unchanged(
                    request.target_root, target_before, self._git_baseline(request.target_root)
                )
                assert_git_baseline_unchanged(
                    request.workspace_root,
                    workspace_before,
                    filter_git_porcelain_baseline(
                        self._git_baseline(request.workspace_root),
                        owned_workspace_paths,
                    ),
                )
            except LocalRunSideEffectError as exc:
                status = "cleanup_failed"
                cleanup_complete = False
                summary = str(exc)
            if cleanup_complete:
                write_local_run_journal(
                    run_root,
                    replace(
                        journal,
                        status="passed" if status == "passed" else "failed",
                        resources=(),
                        completed_actions=tuple(
                            dict.fromkeys((*journal.completed_actions, "cleanup"))
                        ),
                    ),
                )
            try:
                attestation = write_local_runnability_attestation(
                    root.parent / "evidence" / "local-runnability",
                    LocalRunnabilityAttestationInput(
                        status="passed" if status == "passed" else "failed",
                        candidate=candidate,
                        sandbox_receipt_sha256=candidate.sandbox_receipt_sha256,
                        runner_profile_digest=local_runner_profile_digest(candidate),
                        cleanup_complete=cleanup_complete,
                        redacted_logs=summary,
                        attempt_sequence=_next_attempt(root.parent / "evidence" / "local-runnability"),
                        local_run_id=local_run_id,
                    ),
                )
                attestation_path = attestation.path
            except Exception as exc:
                if status == "passed":
                    status = "cleanup_failed"
                    cleanup_complete = False
                    summary = f"could not record local attestation: {exc}"
        return LocalRunnerResult(status, local_run_id, attestation_path, cleanup_complete, summary)


class _CandidateLifecycleFailure(RuntimeError):
    pass


def _require_passing_observation(
    result: bool | LocalObservationResult, *, after_restart: bool = False
) -> None:
    if isinstance(result, LocalObservationResult):
        if not result.passed:
            raise _CandidateLifecycleFailure(result.summary)
        return
    if not result:
        phase = "persistence observation after restart" if after_restart else "independent browser or persistence observation"
        raise _CandidateLifecycleFailure(f"{phase} failed")


def _local_runs_root(requested: Path, candidate: EffectiveLocalCandidate) -> Path:
    expected = candidate.mirror_path.parent / candidate.build_id / "local-runs"
    raw = Path(requested).expanduser()
    try:
        if raw.resolve(strict=False) != expected.resolve(strict=False):
            raise ValueError
    except OSError as exc:
        raise LocalEngineError("managed local-run root is unavailable") from exc
    if raw.is_symlink():
        raise LocalEngineError("managed local-run root is symlinked")
    raw.mkdir(parents=True, exist_ok=True)
    return raw.resolve(strict=True)


def _runner_owned_workspace_paths(workspace_root: Path, run_root: Path) -> tuple[Path, ...]:
    """Return the exact Echelon-owned paths a local run may create.

    The managed candidate, browser cache, journal, and the immutable local
    attestation live below these paths.  Everything else in the user's
    workspace remains protected by the Git baseline check.
    """
    workspace = Path(workspace_root).resolve(strict=True)
    build_root = run_root.parent.parent
    mirror_worktree = run_root.parent.parent.parent / "mirror.git" / "worktrees" / "candidate"
    try:
        return (
            run_root.relative_to(workspace),
            (build_root / "evidence" / "local-runnability").relative_to(workspace),
            mirror_worktree.relative_to(workspace),
        )
    except ValueError as exc:
        raise LocalEngineError(
            "managed local-run paths must be inside the workspace"
        ) from exc


def _managed_macos_runtime_temp(local_run_id: str) -> Path:
    """Keep macOS UNIX sockets short while retaining a per-run ownership key."""
    if not re.fullmatch(r"local-[a-f0-9]{32}", local_run_id):
        raise LocalEngineError("managed local-run ID is invalid")
    return Path("/tmp") / f"echelon-{local_run_id[6:]}"


def _remove_managed_macos_runtime_temp(local_run_id: str) -> None:
    runtime_temp = _managed_macos_runtime_temp(local_run_id)
    if not runtime_temp.exists():
        return
    if runtime_temp.is_symlink() or not runtime_temp.is_dir():
        raise OSError("managed local runtime temporary directory is invalid")
    shutil.rmtree(runtime_temp)


def _existing_regular_directory(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise LocalRunRecoveryRequired(f"{label} is symlinked")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise LocalRunRecoveryRequired(f"{label} is unavailable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise LocalRunRecoveryRequired(f"{label} is unavailable")
    return resolved


def _find_local_run_root(workspace: Path, local_run_id: str) -> Path:
    runs = workspace / "runs"
    if runs.is_symlink() or not runs.is_dir():
        raise LocalRunRecoveryRequired("workspace has no managed local runs")
    candidates: list[Path] = []
    patterns = (
        f"build-*/local-runs/{local_run_id}",
        f"targets/*/runs/build-*/local-runs/{local_run_id}",
    )
    for pattern in patterns:
        for raw in runs.glob(pattern):
            if raw.is_symlink() or not raw.is_dir():
                continue
            try:
                resolved = raw.resolve(strict=True)
                resolved.relative_to(runs.resolve(strict=True))
            except (OSError, ValueError):
                continue
            candidates.append(resolved)
    if len(candidates) != 1:
        raise LocalRunRecoveryRequired(
            "local cleanup requires exactly one managed journal for this run ID"
        )
    return candidates[0]


def _validate_recovery_journal(
    journal: LocalRunJournal, workspace: Path, run_root: Path
) -> None:
    if not journal.workspace_root or not journal.target_root or not journal.mirror_path:
        raise LocalRunRecoveryRequired("local-run journal lacks recovery ownership metadata")
    try:
        journal_workspace = Path(journal.workspace_root).resolve(strict=True)
        expected_mirror = (run_root.parents[2] / "mirror.git").resolve(strict=True)
        journal_mirror = Path(journal.mirror_path).resolve(strict=True)
    except OSError as exc:
        raise LocalRunRecoveryRequired("local-run recovery ownership is unavailable") from exc
    if journal_workspace != workspace:
        raise LocalRunRecoveryRequired("local-run journal belongs to a different workspace")
    if journal_mirror != expected_mirror:
        raise LocalRunRecoveryRequired("local-run journal mirror ownership is invalid")
    for resource in journal.resources:
        labels = dict(resource.labels)
        if (
            resource.engine not in {"docker", "podman"}
            or resource.resource_kind != "container"
            or labels.get("io.echelon.local-managed") != "true"
            or labels.get("io.echelon.local-run-id") != journal.local_run_id
        ):
            raise LocalRunRecoveryRequired("local-run journal resource ownership is invalid")


def _recovery_adapter(
    adapters: Mapping[str, LocalEngineAdapter], journal: LocalRunJournal
) -> LocalEngineAdapter:
    engines = {item.engine for item in journal.resources}
    if len(engines) != 1:
        raise LocalRunRecoveryRequired("local-run journal has inconsistent resource engines")
    engine = next(iter(engines))
    adapter = adapters.get(engine)
    if adapter is None:
        raise LocalRunRecoveryRequired(
            f"local-run journal requires unavailable {engine} cleanup adapter"
        )
    return adapter


def _journal_candidate_worktree(journal: LocalRunJournal, run_root: Path) -> Path:
    expected = run_root / "candidate"
    raw = Path(journal.candidate_worktree) if journal.candidate_worktree else expected
    if raw.is_symlink():
        raise LocalRunRecoveryRequired("local-run candidate worktree is symlinked")
    try:
        resolved = raw.resolve(strict=False)
        expected_resolved = expected.resolve(strict=False)
    except OSError as exc:
        raise LocalRunRecoveryRequired("local-run candidate worktree is unavailable") from exc
    if resolved != expected_resolved:
        raise LocalRunRecoveryRequired("local-run candidate ownership is invalid")
    return raw


def _load_matching_contract(
    worktree: Path, candidate: EffectiveLocalCandidate
) -> RunnabilityContract:
    contract = load_runnability_contract(worktree)
    if contract is None or not contract.enabled or contract.schema_version != 2:
        raise _CandidateLifecycleFailure("candidate requires an enabled schema-version-2 local contract")
    if runnability_contract_sha256(contract) != candidate.contract_hash:
        raise _CandidateLifecycleFailure("candidate contract hash does not match sandbox evidence")
    return contract


def _local_execution_from_snapshot(
    candidate: EffectiveLocalCandidate,
    contract: RunnabilityContract,
) -> tuple[LocalExecution, set[str], Mapping[str, str]]:
    local = contract.local_journey
    execution = local.execution if local is not None else None
    if execution is None:
        raise _CandidateLifecycleFailure("candidate local executable journey is missing")
    resolved = candidate.stack_snapshot.get("resolved")
    if not isinstance(resolved, dict):
        raise LocalEngineError("sandbox stack snapshot is malformed")
    runnability = resolved.get("runnability")
    local_runner = runnability.get("local_runner") if isinstance(runnability, dict) else None
    if not isinstance(local_runner, dict):
        raise LocalEngineError("sandbox stack snapshot lacks local runner ownership")
    profiles = local_runner.get("profiles")
    services = local_runner.get("allowed_services")
    bindings = local_runner.get("environment_bindings")
    if not isinstance(profiles, list) or execution.profile not in profiles:
        raise LocalEngineError("candidate local execution profile is not stack-authorized")
    if not isinstance(services, list) or set(execution.compose_services) != set(services):
        raise LocalEngineError("candidate Compose services are not stack-authorized")
    if not isinstance(bindings, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in bindings.items()
    ):
        raise LocalEngineError("sandbox stack environment bindings are malformed")
    return execution, set(services), bindings


def _runner_variables(contract: RunnabilityContract) -> dict[str, str]:
    template = contract.readiness.url
    generated_port = _free_loopback_port() if "${ECHELON_PORT}" in template else ""
    readiness = _expand(template, {"ECHELON_PORT": generated_port})
    parsed = urlsplit(readiness)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port is None:
        raise _CandidateLifecycleFailure("candidate readiness is not loopback-bound")
    base = f"http://127.0.0.1:{parsed.port}"
    return {
        "ECHELON_PORT": generated_port or str(parsed.port),
        "ECHELON_BASE_URL": base,
        "ECHELON_MARKER": str(uuid.uuid4()),
    }


def _free_loopback_port() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def _bound_environment(
    controlled: Mapping[str, str],
    engine_bindings: tuple[tuple[str, str], ...],
    stack_bindings: Mapping[str, str],
) -> dict[str, str]:
    values = dict(controlled)
    engine = dict(engine_bindings)
    sources = {
        "postgres_url": engine.get("DATABASE_URL", ""),
        "browser_port": values.get("ECHELON_PORT", ""),
        "browser_base_url": values.get("ECHELON_BASE_URL", ""),
        "marker": values.get("ECHELON_MARKER", ""),
        "session_token": values.get("ECHELON_SESSION_TOKEN", ""),
    }
    for name, source in stack_bindings.items():
        value = sources.get(source, "")
        if not value:
            raise LocalEngineError(f"local stack binding {name} has no generated {source}")
        values[name] = value
    return values


def _execute_stage(
    execution: LocalExecution,
    name: str,
    cwd: Path,
    environment: Mapping[str, str],
    executor: CommandExecutor,
    processes: list[object],
) -> None:
    lifecycle = dict(execution.lifecycle)
    for command in lifecycle.get(name, ()):
        background = name == "start"
        result = executor(command.argv, cwd=cwd, env=dict(environment), background=background)
        if background:
            processes.append(result)
        elif int(result) != 0:
            raise _CandidateLifecycleFailure(f"candidate {name} lifecycle command failed")


def _run_command(
    argv: tuple[str, ...], *, cwd: Path, env: Mapping[str, str], background: bool
) -> object:
    if background:
        return subprocess.Popen(
            argv, cwd=str(cwd), env=dict(env), start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    return subprocess.run(argv, cwd=str(cwd), env=dict(env), check=False).returncode


def _install_playwright_chromium(worktree: Path, environment: Mapping[str, str]) -> None:
    """Provision the Playwright headless shell inside the per-run cache only."""
    browser_cache = Path(environment.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not browser_cache.is_absolute() or browser_cache.is_symlink():
        raise _CandidateLifecycleFailure("managed Playwright browser cache is invalid")
    try:
        metadata = _playwright_headless_shell_metadata(worktree, environment)
        archive_platform, extracted_directory = _macos_headless_shell_layout()
        browser_directory = browser_cache / f"chromium_headless_shell-{metadata['revision']}"
        executable = browser_directory / extracted_directory / "chrome-headless-shell"
        marker = browser_directory / "INSTALLATION_COMPLETE"
        if marker.is_file() and executable.is_file():
            return
        if browser_directory.exists():
            raise _CandidateLifecycleFailure("managed Playwright browser cache is incomplete")
        browser_cache.mkdir(parents=True, exist_ok=True)
        temp_root = Path(environment.get("TMPDIR", ""))
        if not temp_root.is_absolute() or temp_root.is_symlink():
            raise _CandidateLifecycleFailure("managed Playwright temporary directory is invalid")
        temp_root.mkdir(parents=True, exist_ok=True)
        archive = temp_root / f"playwright-headless-shell-{uuid.uuid4().hex}.zip"
        url = (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            f"{metadata['browser_version']}/{archive_platform}/"
            f"chrome-headless-shell-{archive_platform}.zip"
        )
        downloaded = subprocess.run(
            ["/usr/bin/curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "300", "--output", str(archive), url],
            cwd=str(worktree),
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=330,
        )
        if downloaded.returncode != 0:
            raise _CandidateLifecycleFailure("managed Playwright headless shell download failed")
        browser_directory.mkdir(parents=True, exist_ok=False)
        extracted = subprocess.run(
            ["/usr/bin/ditto", "-x", "-k", str(archive), str(browser_directory)],
            cwd=str(worktree),
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if extracted.returncode != 0 or not executable.is_file():
            raise _CandidateLifecycleFailure("managed Playwright headless shell extraction failed")
        executable.chmod(0o755)
        marker.write_text("", encoding="utf-8")
        archive.unlink(missing_ok=True)
    except _CandidateLifecycleFailure:
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise _CandidateLifecycleFailure("managed Playwright headless shell provision failed") from exc


def _playwright_headless_shell_metadata(
    worktree: Path, environment: Mapping[str, str]
) -> dict[str, str]:
    """Read the installed candidate's Playwright revision without host lookup."""
    script = (
        "const path=require('node:path');"
        "const test=path.dirname(require.resolve('@playwright/test'));"
        "const core=path.dirname(require.resolve('playwright-core',{paths:[test]}));"
        "const metadata=require(path.join(core,'browsers.json'));"
        "const shell=metadata.browsers.find(item=>item.name==='chromium-headless-shell');"
        "if(!shell)process.exit(2);"
        "process.stdout.write(JSON.stringify({revision:String(shell.revision),browser_version:String(shell.browserVersion)}));"
    )
    try:
        result = subprocess.run(
            ["pnpm", "exec", "node", "-e", script],
            cwd=str(worktree),
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _CandidateLifecycleFailure("managed Playwright metadata lookup could not start") from exc
    if result.returncode != 0:
        raise _CandidateLifecycleFailure(
            "managed Playwright metadata lookup failed; ensure the candidate declares @playwright/test"
        )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _CandidateLifecycleFailure("managed Playwright metadata is invalid") from exc
    if not isinstance(payload, dict):
        raise _CandidateLifecycleFailure("managed Playwright metadata is invalid")
    revision = payload.get("revision")
    browser_version = payload.get("browser_version")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9]{1,20}", revision):
        raise _CandidateLifecycleFailure("managed Playwright revision is invalid")
    if not isinstance(browser_version, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+){3}", browser_version
    ):
        raise _CandidateLifecycleFailure("managed Playwright browser version is invalid")
    return {"revision": revision, "browser_version": browser_version}


def _macos_headless_shell_layout() -> tuple[str, str]:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "mac-arm64", "chrome-headless-shell-mac-arm64"
    if machine in {"x86_64", "amd64"}:
        return "mac", "chrome-headless-shell-mac-x64"
    raise _CandidateLifecycleFailure("managed Playwright browser is unsupported on this macOS architecture")


def _terminate_processes(processes: list[object]) -> None:
    for process in reversed(processes):
        try:
            pid = getattr(process, "pid", None)
            if isinstance(pid, int):
                try:
                    import os
                    os.killpg(pid, signal.SIGTERM)
                except OSError:
                    pass
            elif callable(getattr(process, "terminate", None)):
                process.terminate()
            if callable(getattr(process, "wait", None)):
                process.wait(timeout=10)
        except Exception:
            continue


def _wait_for_readiness(contract: RunnabilityContract, environment: Mapping[str, str]) -> bool:
    url = _expand(contract.readiness.url, environment)
    deadline = time.monotonic() + contract.readiness.timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:  # noqa: S310 - contract parser restricts loopback
                if 200 <= response.status < 300:
                    return True
        except OSError:
            time.sleep(0.2)
    return False


def _run_independent_observations(
    worktree: Path,
    contract: RunnabilityContract,
    environment: Mapping[str, str],
    adapter: object,
    resources: LocalResourceSet,
    after_restart: bool,
    *,
    browser_helper: Path | None = None,
) -> LocalObservationResult:
    """Require browser DOM and direct PostgreSQL observations, never command exit alone."""
    browser = [item for item in contract.primary_journey.observations if item.kind == "browser_dom"]
    postgres = [item for item in contract.primary_journey.observations if item.kind == "postgres_query"]
    required_ids = set(contract.persistence_probe.observation_ids) if contract.persistence_probe else set()
    if required_ids:
        browser = [item for item in browser if item.id in required_ids]
        postgres = [item for item in postgres if item.id in required_ids]
    if not browser or not postgres:
        return LocalObservationResult(False, "local observation contract lacks browser or PostgreSQL evidence")
    helper = browser_helper or (
        Path(__file__).resolve().parents[2]
        / "runtime"
        / "scripts"
        / "user-runnability-browser.mjs"
    )
    if not helper.is_file():
        return LocalObservationResult(False, "managed browser observation helper is unavailable")
    plan = asdict(contract.primary_journey)
    plan = _expand_value(plan, environment)
    if after_restart:
        plan["steps"] = [
            step for step in plan["steps"] if isinstance(step, dict) and step.get("action") == "goto"
        ]
    plan["observation_ids"] = [item.id for item in browser]
    plan_path = worktree / ".echelon-local-browser-plan.json"
    try:
        plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
        browser_result = subprocess.run(
            ["node", str(helper), str(plan_path)], cwd=str(worktree), env=dict(environment),
            capture_output=True, text=True, check=False, timeout=120,
        )
        if browser_result.returncode != 0:
            return LocalObservationResult(False, _browser_observation_failure(browser_result.stderr))
        payload = json.loads(browser_result.stdout)
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if payload.get("status") != "passed" or not isinstance(observations, dict):
            return LocalObservationResult(False, "browser DOM observation was not confirmed")
        if any(observations.get(item.id, {}).get("passed") is not True for item in browser):
            return LocalObservationResult(False, "browser DOM observation did not match the required state")
        execute = getattr(adapter, "exec", None)
        if not callable(execute):
            return LocalObservationResult(False, "managed PostgreSQL observer is unavailable")
        for observation in postgres:
            statement = _postgres_statement(observation.statement or "", observation.parameters, environment)
            result = execute(resources, ("psql", "-U", "echelon", "-d", "echelon", "-AtX", "-c", statement))
            if getattr(result, "returncode", 1) != 0:
                return LocalObservationResult(False, f"PostgreSQL observation {observation.id} could not execute")
            rows = [line for line in str(getattr(result, "stdout", "")).splitlines() if line]
            expected = _expand(observation.parameters[0], environment) if observation.parameters else ""
            if observation.expectation == "one_row_exact" and rows != [expected]:
                return LocalObservationResult(False, f"PostgreSQL observation {observation.id} did not match")
        return LocalObservationResult(True, "browser and PostgreSQL observations passed")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return LocalObservationResult(False, "managed browser or PostgreSQL observation could not complete")
    finally:
        plan_path.unlink(missing_ok=True)


def _browser_observation_failure(stderr: str) -> str:
    """Classify browser failure without persisting candidate page contents or secrets."""
    status_codes = sorted(set(re.findall(r"\bHTTP ([45][0-9]{2})\b", stderr)))
    if status_codes:
        return f"browser DOM observation failed with HTTP {', '.join(status_codes)}"
    if "Timeout" in stderr or "timeout" in stderr:
        return "browser DOM observation timed out"
    if "Cannot find package" in stderr or "ERR_MODULE_NOT_FOUND" in stderr:
        return "browser DOM observer could not load the candidate Playwright dependency"
    return "browser DOM observer exited without confirming the required state"


def _postgres_statement(statement: str, parameters: tuple[str, ...], environment: Mapping[str, str]) -> str:
    for index in range(len(parameters), 0, -1):
        value = _expand(parameters[index - 1], environment).replace("'", "''")
        statement = statement.replace(f"${index}", f"'{value}'")
    return statement


def _issue_identity(
    worktree: Path,
    contract: RunnabilityContract,
    environment: MutableMapping[str, str],
) -> None:
    if contract.identity is None:
        return
    try:
        argv = tuple(shlex.split(contract.identity.command))
    except ValueError as exc:
        raise _CandidateLifecycleFailure("candidate identity command is invalid") from exc
    if not argv or argv[0] in {"sh", "bash", "zsh", "fish", "cmd", "powershell", "pwsh"}:
        raise _CandidateLifecycleFailure("candidate identity command must be argv-safe")
    result = subprocess.run(
        argv,
        cwd=str(worktree),
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise _CandidateLifecycleFailure("candidate identity bootstrap failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _CandidateLifecycleFailure("candidate identity output is invalid") from exc
    if not isinstance(payload, dict):
        raise _CandidateLifecycleFailure("candidate identity output is invalid")
    for source, target in contract.identity.stdout_json:
        value = payload.get(source)
        if not isinstance(value, str) or not value:
            raise _CandidateLifecycleFailure("candidate identity output is incomplete")
        environment[target] = value


def _expand(value: str, environment: Mapping[str, str]) -> str:
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda item: environment.get(item.group(1), item.group(0)), value)


def _expand_value(value: object, environment: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return _expand(value, environment)
    if isinstance(value, list):
        return [_expand_value(item, environment) for item in value]
    if isinstance(value, tuple):
        return tuple(_expand_value(item, environment) for item in value)
    if isinstance(value, dict):
        return {key: _expand_value(item, environment) for key, item in value.items()}
    return value


def _remove_candidate_worktree(candidate: EffectiveLocalCandidate, path: Path) -> None:
    _remove_candidate_at_path(candidate.mirror_path, path)


def _remove_candidate_at_path(mirror_path: Path, path: Path) -> None:
    """Remove only the explicitly managed detached candidate worktree."""
    mirror = _existing_regular_directory(mirror_path, "managed delivery mirror")
    worktree = Path(path)
    if worktree.is_symlink():
        raise LocalRunRecoveryRequired("managed candidate worktree is symlinked")
    try:
        worktree = worktree.resolve(strict=True)
    except OSError as exc:
        raise LocalRunRecoveryRequired("managed candidate worktree is unavailable") from exc
    # A candidate worktree is always nested below the build-local-runs root,
    # never in a user source checkout.  The mirror's containing runs directory
    # is the narrowest stable parent that holds every managed build.
    try:
        worktree.relative_to(mirror.parent)
    except ValueError as exc:
        raise LocalRunRecoveryRequired("managed candidate worktree escapes delivery runs") from exc
    if (
        worktree.name != "candidate"
        or worktree.parent.parent.name != "local-runs"
        or not re.fullmatch(r"local-[a-f0-9]{32}", worktree.parent.name)
    ):
        raise LocalRunRecoveryRequired("managed candidate worktree location is invalid")
    result = subprocess.run(
        ["git", "-C", str(mirror), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Git worktree removal failed"
        raise LocalRunRecoveryRequired(message)
    pruned = subprocess.run(
        ["git", "-C", str(mirror), "worktree", "prune"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pruned.returncode != 0:
        message = pruned.stderr.strip() or pruned.stdout.strip() or "Git worktree prune failed"
        raise LocalRunRecoveryRequired(message)


def _next_attempt(root: Path) -> int:
    highest = 0
    if root.is_dir():
        for path in root.glob("attempt-*.json"):
            match = re.match(r"attempt-(\d+)-", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1

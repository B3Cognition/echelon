"""Fresh-sandbox execution of candidate user-runnability contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
import shlex
from typing import Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit
import uuid

from harness.errors import NotSupportedError
from harness.exec_result import ExecResult
from harness.product_inventory import product_evidence_fingerprint
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.runnability_contract import (
    Observation,
    RunnabilityContract,
    runnability_contract_sha256,
)
from harness.runnability_evidence import (
    RunnabilityEvidenceRef,
    RunnabilityStage,
    write_runnability_report,
)
from harness.stacks.resolver import ResolvedStacks, resolved_stack_contract_sha256
from harness.verification_plan import materialize_services


_BROWSER_HELPER = "/workspace/.echelon/runtime/scripts/user-runnability-browser.mjs"
_PLAN_PATH = "/tmp/echelon-user-runnability-plan.json"
_SERVICE_OBSERVATION = {
    "web": "browser_dom",
    "api": "http",
    "postgres": "postgres_query",
}


@dataclass(frozen=True)
class RunnabilityRunResult:
    status: str
    failed_stage: str | None
    failure_class: str
    summary: str
    stages: tuple[RunnabilityStage, ...]
    evidence: RunnabilityEvidenceRef
    candidate_fingerprint: str
    contract_hash: str
    stack_hash: str
    user_commands: dict[str, tuple[str, ...]]
    local_journey_status: str = "not_required"
    local_journey_reason: str = ""
    local_user_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)


class RunnabilityRunner:
    """Own one complete, disposable execution attempt."""

    def __init__(
        self,
        *,
        provider: SandboxProvider,
        sandbox_spec_factory: Callable[[Path], SandboxSpec],
        spec_id: str,
        target_id: str,
        strategy_id: str,
        build_id: str,
    ) -> None:
        self._provider = provider
        self._sandbox_spec_factory = sandbox_spec_factory
        self._spec_id = spec_id
        self._target_id = target_id
        self._strategy_id = strategy_id
        self._build_id = build_id

    def run(
        self,
        *,
        worktree: Path,
        contract: RunnabilityContract,
        resolved: ResolvedStacks,
        candidate_commit: str,
        evidence_dir: Path,
        attempt_sequence: int,
    ) -> RunnabilityRunResult:
        worktree = worktree.expanduser().resolve(strict=True)
        fingerprint_before = product_evidence_fingerprint(worktree)
        contract_hash = runnability_contract_sha256(contract)
        stack_hash = resolved_stack_contract_sha256(resolved)
        user_commands = _user_commands(contract)
        local_user_commands = _local_user_commands(contract)
        local_journey_status = (
            "unverified" if contract.local_journey is not None else "not_required"
        )
        local_journey_reason = (
            "No compatible local runner executed these candidate-owned commands."
            if contract.local_journey is not None
            else "The resolved stack does not require a local user journey."
        )
        required_stages = _required_stage_names(contract, resolved)
        if (
            "local_journey" in resolved.runnability.capabilities
            and contract.local_journey is None
        ):
            summary = (
                "Resolved stacks require a complete local_journey in "
                ".echelon/runnability.yml; candidate-owned local provisioning, "
                "readiness, verification, start, stop, and cleanup instructions "
                "are missing."
            )
            return self._record(
                evidence_dir=evidence_dir,
                attempt_sequence=attempt_sequence,
                candidate_commit=candidate_commit,
                candidate_fingerprint=fingerprint_before,
                contract_hash=contract_hash,
                stack_hash=stack_hash,
                status="not_runnable",
                failed_stage="local_journey",
                failure_class="local_journey_missing",
                summary=summary,
                stages=(
                    RunnabilityStage(
                        name="local_journey",
                        status="failed",
                        stderr=summary.encode(),
                    ),
                ),
                required_stages=required_stages,
                sensitive_environment={},
                user_commands=user_commands,
                local_journey_status="missing",
                local_journey_reason=summary,
                local_user_commands=local_user_commands,
            )
        missing_required = _missing_stack_observation(contract, resolved)
        if missing_required:
            summary = (
                f"Candidate omits stack-required observation {missing_required!r}; "
                "required observations are owner-controlled and cannot be "
                "weakened by the candidate contract."
            )
            stage = RunnabilityStage(
                name="primary_journey",
                status="failed",
                stderr=summary.encode(),
            )
            return self._record(
                evidence_dir=evidence_dir,
                attempt_sequence=attempt_sequence,
                candidate_commit=candidate_commit,
                candidate_fingerprint=fingerprint_before,
                contract_hash=contract_hash,
                stack_hash=stack_hash,
                status="not_runnable",
                failed_stage="primary_journey",
                failure_class="mocked_dependency_detected",
                summary=summary,
                stages=(stage,),
                required_stages=required_stages,
                sensitive_environment={},
                user_commands=user_commands,
                local_journey_status=local_journey_status,
                local_journey_reason=local_journey_reason,
                local_user_commands=local_user_commands,
            )
        missing_boundary = _missing_service_boundary(contract)
        if missing_boundary:
            summary = (
                f"Declared real service {missing_boundary!r} has no independent "
                "harness-owned observation."
            )
            stage = RunnabilityStage(
                name="primary_journey",
                status="failed",
                stderr=summary.encode(),
            )
            return self._record(
                evidence_dir=evidence_dir,
                attempt_sequence=attempt_sequence,
                candidate_commit=candidate_commit,
                candidate_fingerprint=fingerprint_before,
                contract_hash=contract_hash,
                stack_hash=stack_hash,
                status="not_runnable",
                failed_stage="primary_journey",
                failure_class="mocked_dependency_detected",
                summary=summary,
                stages=(stage,),
                required_stages=required_stages,
                sensitive_environment={},
                user_commands=user_commands,
                local_journey_status=local_journey_status,
                local_journey_reason=local_journey_reason,
                local_user_commands=local_user_commands,
            )

        variables = {
            "ECHELON_PORT": "4173",
            "ECHELON_BASE_URL": "http://127.0.0.1:4173",
            "ECHELON_MARKER": str(uuid.uuid4()),
        }
        handle: SandboxHandle | None = None
        stages: list[RunnabilityStage] = []
        status = "runnable"
        failed_stage: str | None = None
        failure_class = ""
        summary = "The composed user journey and required persistence checks passed."
        started = False
        sensitive_environment: dict[str, str] = {}

        try:
            spec = self._sandbox_spec_factory(worktree)
            spec = replace(spec, env={**spec.env, **variables})
            handle = self._provider.create(spec)

            prerequisite_commands = _sandbox_prerequisite_commands(resolved)
            if prerequisite_commands:
                prerequisites = self._run_commands(
                    handle,
                    "sandbox_prerequisites",
                    prerequisite_commands,
                    variables,
                )
                stages.append(prerequisites)
                if prerequisites.status != "passed":
                    raise _InfrastructureFailure(
                        "sandbox_prerequisites",
                        _stage_error(prerequisites),
                    )

            install = self._run_commands(
                handle, "install", contract.install_commands, variables
            )
            stages.append(install)
            if install.status != "passed":
                raise _StageFailure("install", "install_failed", _stage_error(install))

            try:
                materialized = materialize_services(
                    tuple(resolved.services), session_id=handle.session_id
                )
                if materialized.services:
                    self._provider.start_services(handle, materialized.services)
                service_environment = dict(materialized.verifier_environment)
                variables.update(service_environment)
                sensitive_environment.update(service_environment)
                stages.append(RunnabilityStage(name="provision", status="passed"))
            except NotSupportedError as exc:
                raise _InfrastructureFailure("provision", str(exc)) from exc
            except Exception as exc:
                raise _StageFailure(
                    "provision", "provisioning_failed", str(exc)
                ) from exc

            bootstrap = self._run_commands(
                handle, "bootstrap", contract.bootstrap_commands, variables
            )
            stages.append(bootstrap)
            if bootstrap.status != "passed":
                raise _StageFailure(
                    "bootstrap", "bootstrap_failed", _stage_error(bootstrap)
                )

            identity = self._run_identity(handle, contract, variables)
            stages.append(identity)
            sensitive_environment.update(
                {
                    key: value
                    for key, value in variables.items()
                    if key.endswith("TOKEN") or key.endswith("KEY")
                }
            )
            if identity.status != "passed":
                raise _StageFailure(
                    "identity",
                    "missing_local_auth_bootstrap",
                    _stage_error(identity),
                )

            start = self._start_application(handle, contract, variables)
            stages.append(start)
            if start.status != "passed":
                raise _StageFailure("start", "start_failed", _stage_error(start))
            started = True

            readiness = self._wait_for_readiness(handle, contract, variables)
            if readiness.status != "passed":
                readiness = self._attach_application_logs(handle, readiness)
                stages.append(readiness)
                raise _StageFailure(
                    "readiness", "readiness_failed", _stage_error(readiness)
                )
            stages.append(readiness)

            primary = self._run_observations(
                handle,
                contract,
                variables,
                observation_ids=tuple(
                    item.id
                    for item in contract.primary_journey.observations
                    if contract.persistence_probe is None
                    or item.id not in contract.persistence_probe.observation_ids
                    or item.kind != "postgres_query"
                ),
                stage_name="primary_journey",
            )
            if primary.status != "passed":
                primary = self._attach_application_logs(handle, primary)
                stages.append(primary)
                raise _StageFailure(
                    "primary_journey",
                    "primary_journey_failed",
                    _stage_error(primary),
                )
            stages.append(primary)

            if contract.persistence_probe is not None:
                before = self._run_observations(
                    handle,
                    contract,
                    variables,
                    observation_ids=contract.persistence_probe.observation_ids,
                    stage_name="persistence_before_restart",
                    execute_browser_steps=False,
                )
                if before.status != "passed":
                    before = self._attach_application_logs(handle, before)
                    stages.append(before)
                    raise _StageFailure(
                        "persistence_before_restart",
                        "persistence_failed",
                        _stage_error(before),
                    )
                stages.append(before)
                restart = self._start_application(
                    handle,
                    contract,
                    variables,
                    commands=contract.persistence_probe.restart_commands,
                    stage_name="restart",
                )
                if restart.status != "passed":
                    restart = self._attach_application_logs(handle, restart)
                    stages.append(restart)
                    raise _StageFailure(
                        "restart", "persistence_failed", _stage_error(restart)
                    )
                stages.append(restart)
                readiness_after = self._wait_for_readiness(
                    handle,
                    contract,
                    variables,
                    stage_name="readiness_after_restart",
                    initial_delay_seconds=1,
                    consecutive_successes=3,
                )
                if readiness_after.status != "passed":
                    readiness_after = self._attach_application_logs(
                        handle, readiness_after
                    )
                    stages.append(readiness_after)
                    raise _StageFailure(
                        "readiness_after_restart",
                        "persistence_failed",
                        _stage_error(readiness_after),
                    )
                stages.append(readiness_after)
                after = self._run_observations(
                    handle,
                    contract,
                    variables,
                    observation_ids=contract.persistence_probe.observation_ids,
                    stage_name="persistence_after_restart",
                    execute_browser_steps=False,
                )
                if after.status != "passed":
                    after = self._attach_application_logs(handle, after)
                    stages.append(after)
                    raise _StageFailure(
                        "persistence_after_restart",
                        "persistence_failed",
                        _stage_error(after),
                    )
                stages.append(after)
        except _InfrastructureFailure as exc:
            status = "blocked"
            failed_stage = exc.stage
            failure_class = "sandbox_prerequisite_missing"
            summary = exc.message
            if not any(item.name == exc.stage for item in stages):
                stages.append(
                    RunnabilityStage(
                        name=exc.stage,
                        status="blocked",
                        stderr=exc.message.encode(),
                    )
                )
        except _StageFailure as exc:
            status = "not_runnable"
            failed_stage = exc.stage
            failure_class = exc.failure_class
            summary = exc.message
            if not any(item.name == exc.stage for item in stages):
                stages.append(
                    RunnabilityStage(
                        name=exc.stage,
                        status="failed",
                        stderr=exc.message.encode(),
                    )
                )
        except Exception as exc:
            status = "blocked"
            failed_stage = failed_stage or "sandbox"
            failure_class = "sandbox_prerequisite_missing"
            summary = str(exc)
            stages.append(
                RunnabilityStage(
                    name=failed_stage,
                    status="blocked",
                    stderr=summary.encode(),
                )
            )
        finally:
            if handle is not None:
                stop = self._stop_application(
                    handle,
                    contract,
                    variables,
                    started=started,
                )
                stages.append(stop)
                if stop.status != "passed" and status == "runnable":
                    status = "not_runnable"
                    failed_stage = "stop"
                    failure_class = "teardown_failed"
                    summary = _stage_error(stop)
                try:
                    self._provider.destroy(handle)
                    teardown = RunnabilityStage(name="teardown", status="passed")
                except Exception as exc:
                    teardown = RunnabilityStage(
                        name="teardown",
                        status="failed",
                        stderr=str(exc).encode(),
                    )
                    if status == "runnable":
                        status = "not_runnable"
                        failed_stage = "teardown"
                        failure_class = "teardown_failed"
                        summary = str(exc)
                stages.append(teardown)

        fingerprint_after = product_evidence_fingerprint(worktree)
        if fingerprint_after != fingerprint_before:
            status = "not_runnable"
            failed_stage = "candidate_integrity"
            failure_class = "candidate_mutated_during_runnability"
            summary = "Candidate product content changed during runnability execution."
            stages.append(
                RunnabilityStage(
                    name="candidate_integrity",
                    status="failed",
                    stderr=summary.encode(),
                )
            )
        return self._record(
            evidence_dir=evidence_dir,
            attempt_sequence=attempt_sequence,
            candidate_commit=candidate_commit,
            candidate_fingerprint=fingerprint_after,
            contract_hash=contract_hash,
            stack_hash=stack_hash,
            status=status,
            failed_stage=failed_stage,
            failure_class=failure_class,
            summary=summary,
            stages=tuple(stages),
            required_stages=required_stages,
            sensitive_environment=sensitive_environment,
            user_commands=user_commands,
            local_journey_status=local_journey_status,
            local_journey_reason=local_journey_reason,
            local_user_commands=local_user_commands,
        )

    def _run_commands(
        self,
        handle: SandboxHandle,
        stage_name: str,
        commands: Sequence[str],
        environment: Mapping[str, str],
    ) -> RunnabilityStage:
        if not commands:
            return RunnabilityStage(name=stage_name, status="passed")
        results: list[ExecResult] = []
        for command in commands:
            result = self._provider.exec(
                handle,
                command,
                cwd="/workspace",
                env=dict(environment),
                timeout_ms=600_000,
            )
            results.append(result)
            if result.exit_code != 0:
                break
        return _combine_results(stage_name, commands, results)

    def _run_identity(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: dict[str, str],
    ) -> RunnabilityStage:
        if contract.identity is None:
            return RunnabilityStage(name="identity", status="passed")
        result = self._provider.exec(
            handle,
            contract.identity.command,
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=120_000,
        )
        stage = _combine_results("identity", (contract.identity.command,), (result,))
        if result.exit_code != 0:
            return stage
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError("identity output is not an object")
            for source, target in contract.identity.stdout_json:
                value = payload.get(source)
                if not isinstance(value, str) or not value:
                    raise ValueError(f"identity output is missing {source}")
                variables[target] = value
        except (json.JSONDecodeError, ValueError) as exc:
            return replace(
                stage,
                status="failed",
                exit_code=1,
                stderr=str(exc).encode(),
            )
        return stage

    def _start_application(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: Mapping[str, str],
        *,
        commands: Sequence[str] | None = None,
        stage_name: str = "start",
    ) -> RunnabilityStage:
        results: list[ExecResult] = []
        wrapped: list[str] = []
        command_sequence = contract.start_commands if commands is None else commands
        for index, command in enumerate(command_sequence):
            log_path = f"/tmp/echelon-runnability-{stage_name}-app-{index}.log"
            inner = (
                f"({command}) > {log_path} 2>&1 & "
                f"echo $! > /tmp/echelon-runnability-app-{index}.pid"
            )
            shell = (
                f"sh -lc {shlex.quote(inner)} "
                f"# echelon-runnability-{stage_name}"
            )
            wrapped.append(shell)
            result = self._provider.exec(
                handle,
                shell,
                cwd="/workspace",
                env=dict(variables),
                timeout_ms=30_000,
            )
            results.append(result)
            if result.exit_code != 0:
                break
        return _combine_results(stage_name, wrapped, results)

    def _wait_for_readiness(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: Mapping[str, str],
        *,
        stage_name: str = "readiness",
        initial_delay_seconds: int = 0,
        consecutive_successes: int = 1,
    ) -> RunnabilityStage:
        url = _expand(contract.readiness.url, variables)
        timeout_s = max(1, contract.readiness.timeout_ms // 1000)
        delay = (
            f"sleep {initial_delay_seconds}; " if initial_delay_seconds > 0 else ""
        )
        script = (
            f"attempts={timeout_s}; successes=0; {delay}"
            "while [ $attempts -gt 0 ]; do "
            f"if node -e 'fetch(process.argv[1]).then(r=>{{if(!r.ok)process.exit(1)}})"
            f".catch(()=>process.exit(1))' {shlex.quote(url)}; then "
            "successes=$((successes+1)); "
            f"if [ $successes -ge {consecutive_successes} ]; then exit 0; fi; "
            "else successes=0; fi; attempts=$((attempts-1)); sleep 1; done; exit 1"
        )
        command = (
            f"sh -lc {shlex.quote(script)} "
            f"# echelon-runnability-{stage_name.replace('_', '-')}"
        )
        result = self._provider.exec(
            handle,
            command,
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=contract.readiness.timeout_ms + 5_000,
        )
        return _combine_results(stage_name, (command,), (result,))

    def _run_observations(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: Mapping[str, str],
        *,
        observation_ids: Sequence[str],
        stage_name: str,
        execute_browser_steps: bool = True,
    ) -> RunnabilityStage:
        selected = {
            item.id: item
            for item in contract.primary_journey.observations
            if item.id in observation_ids
        }
        results: list[ExecResult] = []
        command_labels: list[str] = []
        browser_ids = [
            item.id for item in selected.values() if item.kind == "browser_dom"
        ]
        if browser_ids:
            result = self._run_browser(
                handle,
                contract,
                variables,
                browser_ids,
                execute_steps=execute_browser_steps,
            )
            results.append(result)
            command_labels.append("browser journey")
        for observation in selected.values():
            if observation.kind == "browser_dom":
                continue
            if observation.kind == "postgres_query":
                result = self._run_postgres(handle, observation, variables)
            elif observation.kind == "http":
                result = self._run_http(handle, observation, variables)
            else:
                result = self._run_exec(handle, observation, variables)
            results.append(result)
            command_labels.append(f"{observation.kind}:{observation.id}")
            if result.exit_code != 0:
                break
        if not results:
            return RunnabilityStage(
                name=stage_name,
                status="failed",
                exit_code=1,
                stderr=b"No harness-owned observation executed.",
            )
        return _combine_results(stage_name, command_labels, results)

    def _attach_application_logs(
        self,
        handle: SandboxHandle,
        stage: RunnabilityStage,
    ) -> RunnabilityStage:
        """Attach bounded background-process output to a readiness failure."""
        command = (
            "sh -lc 'for file in /tmp/echelon-runnability-*-app-*.log; do "
            "test ! -f \"$file\" || { echo \"== $file ==\"; tail -n 120 \"$file\"; }; "
            "done' # echelon-runnability-app-logs"
        )
        result = self._provider.exec(
            handle,
            command,
            cwd="/workspace",
            timeout_ms=10_000,
        )
        diagnostics = "\n".join(
            item.replace("\x00", "").strip()
            for item in (result.stdout, result.stderr)
            if item.replace("\x00", "").strip()
        )
        if not diagnostics:
            return stage
        existing = stage.stderr.decode(errors="replace").rstrip()
        message = f"{existing}\nApplication process logs:\n{diagnostics}".lstrip()
        return replace(stage, stderr=message.encode())

    def _run_browser(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: Mapping[str, str],
        observation_ids: Sequence[str],
        *,
        execute_steps: bool,
    ) -> ExecResult:
        plan = _expand_value(asdict(contract.primary_journey), variables)
        if not execute_steps:
            plan["steps"] = [
                step
                for step in plan.get("steps", [])
                if isinstance(step, dict) and step.get("action") == "goto"
            ]
        plan["observation_ids"] = list(observation_ids)
        self._provider.write_file(
            handle,
            _PLAN_PATH,
            (json.dumps(plan, sort_keys=True) + "\n").encode(),
        )
        command = f"node {_BROWSER_HELPER} {_PLAN_PATH}"
        result = self._provider.exec(
            handle,
            command,
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=120_000,
        )
        if result.exit_code != 0:
            return result
        try:
            payload = json.loads(result.stdout)
            observations = payload.get("observations")
            if payload.get("status") != "passed" or not isinstance(observations, dict):
                raise ValueError("browser helper did not return a passing observation set")
            for observation_id in observation_ids:
                item = observations.get(observation_id)
                if not isinstance(item, dict) or item.get("passed") is not True:
                    raise ValueError(f"browser observation failed: {observation_id}")
        except (json.JSONDecodeError, ValueError) as exc:
            return _synthetic_failure(result, str(exc))
        return result

    def _run_postgres(
        self,
        handle: SandboxHandle,
        observation: Observation,
        variables: Mapping[str, str],
    ) -> ExecResult:
        assert observation.statement is not None
        statement = observation.statement
        argv = ["psql", "-AtX", "-v", "ON_ERROR_STOP=1"]
        database_url = variables.get("TEST_DATABASE_URL") or variables.get(
            "DATABASE_URL"
        )
        if database_url:
            parsed = urlsplit(database_url)
            username = unquote(parsed.username or "")
            database = unquote(parsed.path.lstrip("/"))
            if username and database:
                argv.extend(("--username", username, "--dbname", database))
        expected_values = [
            _expand(parameter, variables) for parameter in observation.parameters
        ]
        for index in range(len(expected_values), 0, -1):
            value = expected_values[index - 1]
            literal = "'" + value.replace("'", "''") + "'"
            statement = statement.replace(f"${index}", literal)
        argv.extend(("-c", statement))
        result = self._provider.exec_service(
            handle,
            "postgres",
            tuple(argv),
            timeout_ms=30_000,
        )
        if result.exit_code != 0:
            return result
        rows = [line for line in result.stdout.splitlines() if line]
        if observation.expectation == "one_row_exact":
            expected = expected_values[0] if expected_values else ""
            if rows != [expected]:
                return _synthetic_failure(
                    result,
                    f"expected one exact marker row, observed {len(rows)} row(s)",
                )
        elif observation.expectation == "zero_rows" and rows:
            return _synthetic_failure(result, "expected zero rows")
        elif observation.expectation == "one_row" and len(rows) != 1:
            return _synthetic_failure(result, "expected one row")
        return result

    def _run_http(
        self,
        handle: SandboxHandle,
        observation: Observation,
        variables: Mapping[str, str],
    ) -> ExecResult:
        assert observation.url is not None
        url = _expand(observation.url, variables)
        method = observation.method or "GET"
        script = (
            "fetch(process.argv[1],{method:process.argv[2]})"
            ".then(async r=>{console.log(JSON.stringify({status:r.status,body:await r.text()}));"
            "if(!r.ok)process.exit(1)})"
            ".catch(e=>{console.error(e.message);process.exit(1)})"
        )
        result = self._provider.exec(
            handle,
            f"node -e {shlex.quote(script)} {shlex.quote(url)} {shlex.quote(method)}",
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=30_000,
        )
        if result.exit_code != 0:
            return result
        try:
            payload = json.loads(result.stdout.splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return _synthetic_failure(result, "HTTP observation returned malformed evidence")
        if observation.expectation.startswith("status_"):
            expected = int(observation.expectation.removeprefix("status_"))
            if payload.get("status") != expected:
                return _synthetic_failure(result, f"expected HTTP status {expected}")
        elif observation.expectation.startswith("contains:"):
            expected = _expand(observation.expectation.split(":", 1)[1], variables)
            if expected not in str(payload.get("body") or ""):
                return _synthetic_failure(result, "HTTP body expectation failed")
        else:
            return _synthetic_failure(result, "unsupported HTTP expectation")
        return result

    def _run_exec(
        self,
        handle: SandboxHandle,
        observation: Observation,
        variables: Mapping[str, str],
    ) -> ExecResult:
        assert observation.command is not None
        result = self._provider.exec(
            handle,
            observation.command,
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=30_000,
        )
        if result.exit_code != 0:
            return result
        if observation.expectation == "exit_zero":
            return result
        if observation.expectation.startswith("contains:"):
            expected = _expand(observation.expectation.split(":", 1)[1], variables)
            if expected in result.stdout:
                return result
        if observation.expectation.startswith("exact:"):
            expected = _expand(observation.expectation.split(":", 1)[1], variables)
            if result.stdout.strip() == expected:
                return result
        return _synthetic_failure(result, "exec output expectation failed")

    def _stop_application(
        self,
        handle: SandboxHandle,
        contract: RunnabilityContract,
        variables: Mapping[str, str],
        *,
        started: bool,
    ) -> RunnabilityStage:
        if not started:
            return RunnabilityStage(name="stop", status="passed")
        stage = self._run_commands(
            handle, "stop", contract.stop_commands, variables
        )
        kill = self._provider.exec(
            handle,
            "sh -lc 'for pid in /tmp/echelon-runnability-app-*.pid; do "
            "test ! -f \"$pid\" || kill $(cat \"$pid\") 2>/dev/null || true; "
            "done' # echelon-runnability-stop",
            cwd="/workspace",
            env=dict(variables),
            timeout_ms=30_000,
        )
        if stage.status == "passed" and kill.exit_code != 0:
            return _combine_results("stop", ("kill background apps",), (kill,))
        return stage

    def _record(
        self,
        *,
        evidence_dir: Path,
        attempt_sequence: int,
        candidate_commit: str,
        candidate_fingerprint: str,
        contract_hash: str,
        stack_hash: str,
        status: str,
        failed_stage: str | None,
        failure_class: str,
        summary: str,
        stages: tuple[RunnabilityStage, ...],
        required_stages: tuple[str, ...],
        sensitive_environment: Mapping[str, str],
        user_commands: dict[str, tuple[str, ...]],
        local_journey_status: str,
        local_journey_reason: str,
        local_user_commands: dict[str, tuple[str, ...]],
    ) -> RunnabilityRunResult:
        evidence = write_runnability_report(
            evidence_dir=evidence_dir,
            spec_id=self._spec_id,
            target_id=self._target_id,
            strategy_id=self._strategy_id,
            build_id=self._build_id,
            candidate_commit=candidate_commit,
            candidate_fingerprint=candidate_fingerprint,
            contract_hash=contract_hash,
            stack_hash=stack_hash,
            status=status,
            failure_class=failure_class,
            summary=summary,
            stages=stages,
            required_stages=required_stages,
            attempt_sequence=attempt_sequence,
            sensitive_environment=sensitive_environment,
            user_commands=user_commands,
            local_journey_status=local_journey_status,
            local_journey_reason=local_journey_reason,
            local_user_commands=local_user_commands,
        )
        return RunnabilityRunResult(
            status=status,
            failed_stage=failed_stage,
            failure_class=failure_class,
            summary=summary,
            stages=stages,
            evidence=evidence,
            candidate_fingerprint=candidate_fingerprint,
            contract_hash=contract_hash,
            stack_hash=stack_hash,
            user_commands=user_commands,
            local_journey_status=local_journey_status,
            local_journey_reason=local_journey_reason,
            local_user_commands=local_user_commands,
        )


class _StageFailure(Exception):
    def __init__(self, stage: str, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.failure_class = failure_class
        self.message = message


class _InfrastructureFailure(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def _required_stage_names(
    contract: RunnabilityContract,
    resolved: ResolvedStacks,
) -> tuple[str, ...]:
    names: list[str] = []
    if _sandbox_prerequisite_commands(resolved):
        names.append("sandbox_prerequisites")
    if contract.install_commands:
        names.append("install")
    if resolved.services:
        names.append("provision")
    if contract.bootstrap_commands:
        names.append("bootstrap")
    if contract.identity is not None:
        names.append("identity")
    names.extend(("start", "readiness", "primary_journey"))
    if contract.persistence_probe is not None:
        names.extend(
            (
                "persistence_before_restart",
                "restart",
                "readiness_after_restart",
                "persistence_after_restart",
            )
        )
    names.extend(("stop", "teardown"))
    return tuple(names)


def _sandbox_prerequisite_commands(resolved: ResolvedStacks) -> tuple[str, ...]:
    """Prepare stack-declared package managers without touching the host."""
    commands: list[str] = []
    if "pnpm" in resolved.required_commands:
        commands.append("corepack enable")
    return tuple(commands)


def _missing_service_boundary(contract: RunnabilityContract) -> str | None:
    kinds = {item.kind for item in contract.primary_journey.observations}
    for service in contract.primary_journey.real_services_required:
        required_kind = _SERVICE_OBSERVATION[service]
        if required_kind not in kinds:
            return service
    return None


def _missing_stack_observation(
    contract: RunnabilityContract,
    resolved: ResolvedStacks,
) -> str | None:
    kinds = {item.kind for item in contract.primary_journey.observations}
    return next(
        (
            required
            for required in resolved.runnability.required_observations
            if required not in kinds
        ),
        None,
    )


def _combine_results(
    stage_name: str,
    commands: Sequence[str],
    results: Sequence[ExecResult],
) -> RunnabilityStage:
    failed = next((item for item in results if item.exit_code != 0), None)
    return RunnabilityStage(
        name=stage_name,
        status="failed" if failed is not None else "passed",
        command=tuple(commands),
        exit_code=failed.exit_code if failed is not None else 0,
        duration_ms=sum(item.duration_ms for item in results),
        stdout="\n".join(item.stdout for item in results).encode(),
        stderr="\n".join(item.stderr for item in results).encode(),
    )


def _synthetic_failure(result: ExecResult, message: str) -> ExecResult:
    return ExecResult(
        exit_code=1,
        stdout=result.stdout,
        stderr=(result.stderr + "\n" + message).strip(),
        duration_ms=result.duration_ms,
        resource_stats=result.resource_stats,
        truncated=result.truncated,
    )


def _stage_error(stage: RunnabilityStage) -> str:
    text = (stage.stderr or stage.stdout).decode("utf-8", errors="replace").strip()
    return text or f"{stage.name} failed"


def _expand(value: str, variables: Mapping[str, str]) -> str:
    expanded = value
    for key, replacement in variables.items():
        expanded = expanded.replace("${" + key + "}", replacement)
    return expanded


def _expand_value(value: object, variables: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return _expand(value, variables)
    if isinstance(value, list):
        return [_expand_value(item, variables) for item in value]
    if isinstance(value, tuple):
        return [_expand_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _expand_value(item, variables) for key, item in value.items()
        }
    return value


def _user_commands(contract: RunnabilityContract) -> dict[str, tuple[str, ...]]:
    return {
        "install": contract.install_commands,
        "bootstrap": contract.bootstrap_commands,
        "start": contract.start_commands,
        "open": (contract.primary_journey.url or "",),
        "stop": contract.stop_commands,
    }


def _local_user_commands(
    contract: RunnabilityContract,
) -> dict[str, tuple[str, ...]]:
    journey = contract.local_journey
    if journey is None:
        return {}
    return {
        "prerequisites": journey.prerequisites,
        "provision": journey.provision_commands,
        "readiness": journey.readiness_commands,
        "prepare": journey.prepare_commands,
        "verify": journey.verify_commands,
        "start": journey.start_commands,
        "open": journey.open_urls,
        "stop": journey.stop_commands,
        "cleanup": journey.cleanup_commands,
    }

"""VisualRalphController — Phase 2 visual verification loop.

Runs Playwright headless tests inside the container sandbox after Phase 1
(unit/logic) converges. Retrieves screenshots via container cp and passes
them as evidence to echelon build --fix.
"""
from __future__ import annotations

from dataclasses import replace
import json
import logging
import shlex
import subprocess
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from harness.config import HarnessConfig
from harness.exec_result import ExecResult
from harness.delivery_results import VisualResult
from harness.playwright_evidence import PlaywrightEvidenceError, parse_playwright_json
from harness.product_inventory import product_evidence_fingerprint
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from harness.verification_plan import build_verification_plan, materialize_services
from harness.verification_evidence import redact_verification_text
from harness.visual_evidence import VisualEvidenceRef, write_visual_receipt

logger = logging.getLogger(__name__)


class VisualRalphController:
    """Phase 2 visual verification loop.

    Assumes Phase 1 (RalphController) converged — the worktree is in a
    passing-unit-tests state. Iterates: verify → feedback → fix.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        config: HarnessConfig,
        spec_id: str,
        strategy_id: str,
        base_dir: str = ".",
        build_id: str = "",
        sandbox_spec_factory: Callable[[str], SandboxSpec] | None = None,
        feedback_runner: (
            Callable[[SandboxHandle, str, VerifyResult, List[str]], Dict[str, Any]]
            | None
        ) = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._spec_id = spec_id
        self._strategy_id = strategy_id
        self._base_dir = base_dir
        self._build_id = build_id or "unscoped"
        self._vc = config.visual_tests
        self._last_staging_dir: Path | None = None
        self._sandbox_spec_factory = sandbox_spec_factory
        self._feedback_runner = feedback_runner
        self._runtime_env: dict[str, str] = {}

    # === Public entry point ===

    def run_loop(
        self,
        worktree_path: str,
        token_budget: Optional[int] = None,
    ) -> VisualResult:
        """Run visual verification loop until convergence or max_iterations."""
        tokens_used = 0

        for iteration in range(self._vc.max_iterations):
            logger.info(
                "Visual loop iteration %d/%d for %s/%s",
                iteration + 1, self._vc.max_iterations,
                self._spec_id, self._strategy_id,
            )

            sandbox_spec = self._build_sandbox_spec(worktree_path)
            handle = self._provider.create(sandbox_spec)

            try:
                try:
                    self._prepare_verification_runtime(handle, worktree_path)
                    self._setup_app_runtime(handle)
                    self._start_app_runtime(handle)
                    self._wait_for_app_runtime(handle)
                except RuntimeError as exc:
                    failure = VerifyResult(
                        passed=False,
                        failures=[
                            FailureEntry(
                                category=FailureCategory.OTHER,
                                id="app-runtime",
                                error=str(exc),
                            )
                        ],
                        duration_s=0.0,
                        token_usage=0,
                    )
                    return VisualResult(
                        status="blocked",
                        termination_reason="app_runtime_failed",
                        iterations=iteration + 1,
                        tokens_used=tokens_used,
                        final_verify=failure,
                    )

                verify_result = self._exec_visual_verify(handle)
                tokens_used += verify_result.token_usage

                attempt_sequence = self._next_visual_attempt_sequence()
                screenshots = self._retrieve_screenshots(handle, attempt_sequence)
                try:
                    evidence = self._record_visual_evidence(
                        worktree_path=Path(worktree_path),
                        verify_result=verify_result,
                        screenshots=screenshots,
                        attempt_sequence=attempt_sequence,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    evidence = None
                    verify_result = self._with_visual_failure(
                        verify_result,
                        failure_id="visual_evidence_unavailable",
                        error=str(exc),
                    )

                if evidence is not None:
                    verify_result.verification_evidence["visual"] = evidence.as_mapping()
                    if verify_result.passed and not evidence.passed:
                        verify_result = self._with_visual_failure(
                            verify_result,
                            failure_id="visual_artifacts_missing",
                            error=(
                                "The required browser visual gate produced no retained "
                                "PNG or JPEG screenshot artifacts."
                            ),
                        )

                if verify_result.passed and evidence is not None and evidence.passed:
                    return VisualResult(
                        status="passed",
                        termination_reason="converged",
                        iterations=iteration + 1,
                        tokens_used=tokens_used,
                        final_verify=verify_result,
                        evidence=evidence,
                    )

                fix_result = self._exec_visual_feedback(
                    handle,
                    worktree_path,
                    verify_result,
                    screenshots,
                )
                reported_fix_tokens = fix_result.get("tokens")
                if isinstance(reported_fix_tokens, int) and reported_fix_tokens > 0:
                    tokens_used += reported_fix_tokens
                if not fix_result["passed"]:
                    verify_result = self._with_visual_failure(
                        verify_result,
                        failure_id="visual_feedback_command_failed",
                        error=str(
                            fix_result.get("diagnostic")
                            or fix_result.get("build_reason")
                            or "The configured delivery provider could not apply the visual repair."
                        ),
                        prepend=False,
                    )
                    return VisualResult(
                        status="blocked",
                        termination_reason="visual_feedback_failed",
                        iterations=iteration + 1,
                        tokens_used=tokens_used,
                        final_verify=verify_result,
                        evidence=evidence,
                    )
                return VisualResult(
                    status="fix_applied",
                    termination_reason="fix_applied",
                    iterations=iteration + 1,
                    tokens_used=tokens_used,
                    final_verify=verify_result,
                    evidence=evidence,
                )

            finally:
                self._cleanup_screenshot_staging()
                self._stop_app_runtime(handle)
                self._provider.destroy(handle)

        return VisualResult(
            status="blocked",
            termination_reason="visual_failed",
            iterations=self._vc.max_iterations,
            tokens_used=tokens_used,
            final_verify=None,
        )

    # === Verify ===

    def _exec_visual_verify(self, handle: SandboxHandle) -> VerifyResult:
        """Run Playwright tests inside the sandbox.

        Expects playwright.config.ts to handle server startup via webServer.
        """
        result = self._provider.exec(
            handle,
            self._vc.test_command,
            cwd="/workspace",
            env=dict(self._runtime_env),
            timeout_ms=self._vc.timeout_ms,
        )

        try:
            evidence = parse_playwright_json(result.stdout)
        except PlaywrightEvidenceError as exc:
            diagnostic = self._command_diagnostic(result)
            return VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    category=FailureCategory.PLAYWRIGHT_TEST,
                    id="playwright_parse_error",
                    error=f"{exc}: {diagnostic[-1000:]}",
                )],
                duration_s=result.duration_ms / 1000.0,
                token_usage=_estimate_tokens(result),
            )

        failures: list[FailureEntry] = []
        if evidence.total == 0:
            diagnostic = self._command_diagnostic(result)
            failures.append(FailureEntry(
                category=FailureCategory.PLAYWRIGHT_TEST,
                id="playwright_no_tests",
                error=(
                    "Playwright exited without executing any tests."
                    + (f" Command output: {diagnostic[-1000:]}" if diagnostic else "")
                ),
            ))
        for test in evidence.tests:
            if test.status == "failed":
                failures.append(FailureEntry(
                    category=FailureCategory.PLAYWRIGHT_TEST,
                    id=test.title,
                    error=test.error,
                    details={"test_id": test.id, "file": test.file, "project": test.project},
                ))
            elif test.status == "skipped":
                failures.append(FailureEntry(
                    category=FailureCategory.PLAYWRIGHT_TEST,
                    id=f"playwright_skipped::{test.title}",
                    error=test.error,
                    details={"test_id": test.id, "file": test.file, "project": test.project},
                ))
        if result.exit_code != 0 and not failures:
            failures.append(FailureEntry(
                category=FailureCategory.PLAYWRIGHT_TEST,
                id="playwright_command_failed",
                error=(result.stderr or result.stdout or "Playwright command failed")[:1000],
            ))
        return VerifyResult(
            passed=not failures and result.exit_code == 0,
            failures=failures,
            duration_s=result.duration_ms / 1000.0,
            token_usage=_estimate_tokens(result),
            verification_evidence={"playwright": evidence.to_dict()},
        )

    # === App runtime ===

    def _prepare_verification_runtime(
        self, handle: SandboxHandle, worktree_path: str
    ) -> None:
        """Install dependencies and start the ordinary verifier's sidecars."""
        self._runtime_env = {}
        try:
            verification_plan = build_verification_plan(
                Path(worktree_path),
                self._config,
                services=tuple(self._config.verification_services),
            )
            materialized = materialize_services(
                verification_plan.services,
                session_id=handle.session_id,
            )
            if materialized.services:
                self._provider.start_services(handle, materialized.services)
            self._runtime_env.update(materialized.verifier_environment)
            for command in verification_plan.bootstrap_commands:
                result = self._provider.exec(
                    handle,
                    command,
                    cwd="/workspace",
                    env=dict(self._runtime_env),
                    timeout_ms=1_200_000,
                )
                if result.exit_code != 0:
                    raise RuntimeError(
                        "visual verification dependency bootstrap failed: "
                        f"{command}\n{self._command_diagnostic(result)}"
                    )
        except Exception as exc:
            raise RuntimeError(
                f"visual verification runtime could not be prepared: {exc}"
            ) from exc

    def _setup_app_runtime(self, handle: SandboxHandle) -> None:
        """Run configured foreground setup commands inside the visual sandbox."""
        app = self._config.app
        if not app.enabled or app.mode != "command":
            return

        for command in app.setup_commands:
            if not command:
                continue
            result = self._provider.exec(
                handle,
                command,
                cwd="/workspace",
                env=dict(self._runtime_env),
                timeout_ms=app.readiness_timeout_ms,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    "harness.app setup command failed: "
                    f"{command}\n{self._command_diagnostic(result)}"
                )

    def _start_app_runtime(self, handle: SandboxHandle) -> None:
        """Start configured app runtime inside the visual sandbox."""
        app = self._config.app
        if not app.enabled or app.mode != "command":
            return

        commands = app.start_commands or ([app.start_command] if app.start_command else [])
        for index, command in enumerate(commands):
            if not command:
                continue
            log_path = f"/tmp/echelon-app-{index}.log"
            pid_path = f"/tmp/echelon-app-{index}.pid"
            background_cmd = (
                f"sh -lc {shlex.quote(f'({command}) > {log_path} 2>&1 & echo $! > {pid_path}')}"
            )
            result = self._provider.exec(
                handle,
                background_cmd,
                cwd="/workspace",
                env=dict(self._runtime_env),
                timeout_ms=30_000,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    "harness.app start command failed: "
                    f"{command}\n{self._command_diagnostic(result)}"
                )

    def _wait_for_app_runtime(self, handle: SandboxHandle) -> None:
        """Wait for configured app URL to become reachable."""
        app = self._config.app
        if not app.enabled or app.mode != "command" or not app.url:
            return

        timeout_s = max(1, app.readiness_timeout_ms // 1000)
        wait_cmd = (
            "sh -lc "
            + shlex.quote(
                f"deadline=$((SECONDS+{timeout_s})); "
                f"until curl -fsS {shlex.quote(app.url)} >/tmp/echelon-app-ready.txt; do "
                f"  if [ $SECONDS -ge $deadline ]; then exit 1; fi; "
                f"  sleep 1; "
                f"done; cat /tmp/echelon-app-ready.txt"
            )
        )
        result = self._provider.exec(
            handle,
            wait_cmd,
            cwd="/workspace",
            env=dict(self._runtime_env),
            timeout_ms=app.readiness_timeout_ms + 5_000,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                "harness.app URL did not become ready: "
                f"{app.url}\n{self._command_diagnostic(result)}"
            )

    def _stop_app_runtime(self, handle: SandboxHandle) -> None:
        """Stop configured app runtime, best-effort."""
        app = self._config.app
        if not app.enabled or app.mode != "command":
            return

        for command in app.stop_commands:
            if not command:
                continue
            self._provider.exec(
                handle,
                command,
                cwd="/workspace",
                env=dict(self._runtime_env),
                timeout_ms=30_000,
            )

        commands = app.start_commands or ([app.start_command] if app.start_command else [])
        for index, _ in enumerate(commands):
            self._provider.exec(
                handle,
                f"sh -lc 'test ! -f /tmp/echelon-app-{index}.pid || kill $(cat /tmp/echelon-app-{index}.pid) 2>/dev/null || true'",
                cwd="/workspace",
                env=dict(self._runtime_env),
                timeout_ms=30_000,
            )

    # === Screenshots ===

    def _retrieve_screenshots(
        self, handle: SandboxHandle, attempt_sequence: int | None = None
    ) -> List[str]:
        """Pull screenshot files from the container via the configured CLI."""
        container_src = f"/workspace/{self._vc.screenshot_dir}"

        try:
            sequence = attempt_sequence or self._next_visual_attempt_sequence()
            staging_root = self._visual_evidence_dir() / "staging"
            staging_root.mkdir(parents=True, exist_ok=True)
            dest = staging_root / f"attempt-{sequence:04d}"
            if dest.exists() or dest.is_symlink():
                raise FileExistsError(f"visual staging path already exists: {dest}")
            proc = subprocess.run(
                [self._config.container_cli, "cp", f"{handle.id}:{container_src}", str(dest)],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                logger.debug(
                    "%s cp failed for screenshots (%s): %s",
                    self._config.container_cli,
                    self._vc.screenshot_dir,
                    proc.stderr.decode(errors="replace").strip(),
                )
                return []

            self._last_staging_dir = dest
            screenshots = (
                list(dest.glob("**/*.png"))
                + list(dest.glob("**/*.jpg"))
                + list(dest.glob("**/*.jpeg"))
            )
            logger.info("Retrieved %d screenshots from container", len(screenshots))
            return [str(p) for p in screenshots]
        except Exception as e:
            logger.warning("Screenshot retrieval failed: %s", e)
            return []

    def _visual_evidence_dir(self) -> Path:
        return (
            Path(self._base_dir)
            / "runs"
            / self._build_id
            / "evidence"
            / "visual"
            / self._strategy_id
        )

    def _next_visual_attempt_sequence(self) -> int:
        root = self._visual_evidence_dir()
        sequences: list[int] = []
        for path in root.glob("attempt-*.json") if root.exists() else ():
            try:
                sequences.append(int(path.name.split("-", 2)[1]))
            except (IndexError, ValueError):
                continue
        return max(sequences, default=0) + 1

    def _record_visual_evidence(
        self,
        *,
        worktree_path: Path,
        verify_result: VerifyResult,
        screenshots: List[str],
        attempt_sequence: int,
    ) -> VisualEvidenceRef:
        fingerprint = product_evidence_fingerprint(worktree_path)
        return write_visual_receipt(
            evidence_dir=self._visual_evidence_dir(),
            spec_id=self._spec_id,
            strategy_id=self._strategy_id,
            build_id=self._build_id,
            candidate_commit=self._worktree_head(worktree_path),
            candidate_fingerprint=fingerprint,
            screenshot_dir=self._vc.screenshot_dir,
            playwright=dict(verify_result.verification_evidence.get("playwright", {})),
            artifact_paths=[Path(path) for path in screenshots],
            required_artifacts=True,
            attempt_sequence=attempt_sequence,
        )

    @staticmethod
    def _worktree_head(worktree_path: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def _with_visual_failure(
        verify_result: VerifyResult,
        *,
        failure_id: str,
        error: str,
        prepend: bool = True,
    ) -> VerifyResult:
        added = FailureEntry(
            category=FailureCategory.PLAYWRIGHT_TEST,
            id=failure_id,
            error=error,
        )
        return VerifyResult(
            passed=False,
            failures=(
                [added, *verify_result.failures]
                if prepend
                else [*verify_result.failures, added]
            ),
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
        )

    def _cleanup_screenshot_staging(self) -> None:
        staging = self._last_staging_dir
        self._last_staging_dir = None
        if staging is not None and staging.is_dir() and staging.parent.name == "staging":
            shutil.rmtree(staging)

    # === Feedback ===

    def _exec_visual_feedback(
        self,
        handle: SandboxHandle,
        worktree_path: str,
        verify_result: VerifyResult,
        screenshots: List[str],
    ) -> Dict[str, Any]:
        """Run echelon build --fix with visual failure context."""
        if self._feedback_runner is not None:
            try:
                result = dict(
                    self._feedback_runner(
                        handle,
                        worktree_path,
                        verify_result,
                        screenshots,
                    )
                )
            except Exception as exc:
                return {
                    "exit_code": 1,
                    "passed": False,
                    "duration_s": 0.0,
                    "tokens": 0,
                    "diagnostic": str(exc),
                }
            diagnostic = str(result.get("stderr") or result.get("stdout") or "")
            result["diagnostic"] = redact_verification_text(
                diagnostic,
                self._runtime_env,
            )[-1000:]
            return result

        failures_json = json.dumps([
            {"category": f.category.value, "id": f.id, "error": f.error}
            for f in verify_result.failures
        ])

        screenshot_env = ""
        if screenshots:
            screenshot_env = f"VISUAL_SCREENSHOTS='{json.dumps(screenshots)}' "

        cmd = (
            f"{screenshot_env}"
            f"echelon build --fix --failures '{failures_json}' --context 'visual'"
        )

        result = self._provider.exec(
            handle,
            cmd,
            cwd="/workspace",
            env=dict(self._runtime_env),
            timeout_ms=1_200_000,
        )
        return {
            "exit_code": result.exit_code,
            "passed": result.exit_code == 0,
            "duration_s": result.duration_ms / 1000.0,
            "tokens": _estimate_tokens(result),
            "diagnostic": self._command_diagnostic(result),
        }

    # === Sandbox spec ===

    def _build_sandbox_spec(self, worktree_path: str) -> SandboxSpec:
        """Build sandbox spec using Playwright image."""
        from harness.provider import NetworkPolicy, ResourceLimits as ProviderResourceLimits

        if self._sandbox_spec_factory is not None:
            spec = self._sandbox_spec_factory(worktree_path)
            return replace(
                spec,
                labels={
                    **dict(spec.labels),
                    "phase": "visual",
                    "spec_id": self._spec_id,
                    "strategy_id": self._strategy_id,
                },
            )

        return SandboxSpec(
            image=self._config.base_image or "mcr.microsoft.com/playwright:v1.42.0-jammy",
            image_source="playwright",
            worktree_mount=worktree_path,
            container_mount="/workspace",
            resource_limits=ProviderResourceLimits(
                memory=self._config.resource_limits.memory,
                cpu=self._config.resource_limits.cpu,
                pids=self._config.resource_limits.pids,
                storage=self._config.resource_limits.storage,
            ),
            network_policy=NetworkPolicy(
                allowlist=self._config.network.allowlist,
                proxy_image=self._config.network.proxy_image,
            ),
            env={},
            secrets_env={},
            post_create_command=None,
            forward_ports=[],
            labels={
                "phase": "visual",
                "spec_id": self._spec_id,
                "strategy_id": self._strategy_id,
            },
        )

    def _command_diagnostic(self, result: ExecResult, limit: int = 1000) -> str:
        """Return bounded command diagnostics without attempt-scoped secrets."""
        raw = (result.stderr or result.stdout).strip()
        return redact_verification_text(raw, self._runtime_env)[-limit:]


# === Helpers ===

def _estimate_tokens(result: ExecResult) -> int:
    """Rough token estimate from stdout/stderr byte length."""
    total_bytes = len(result.stdout.encode()) + len(result.stderr.encode())
    return max(1, total_bytes // 4)

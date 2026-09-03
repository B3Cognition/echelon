"""VisualRalphController — Phase 2 visual verification loop.

Runs Playwright headless tests inside the container sandbox after Phase 1
(unit/logic) converges. Retrieves screenshots via container cp and passes
them as evidence to echelon build --fix.
"""
from __future__ import annotations

import json
import logging
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.config import HarnessConfig
from harness.exec_result import ExecResult
from harness.delivery_results import VisualResult
from harness.playwright_evidence import PlaywrightEvidenceError, parse_playwright_json
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

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
    ) -> None:
        self._provider = provider
        self._config = config
        self._spec_id = spec_id
        self._strategy_id = strategy_id
        self._base_dir = base_dir
        self._vc = config.visual_tests

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

                if verify_result.passed:
                    return VisualResult(
                        status="passed",
                        termination_reason="converged",
                        iterations=iteration + 1,
                        tokens_used=tokens_used,
                        final_verify=verify_result,
                    )

                screenshots = self._retrieve_screenshots(handle)
                fix_result = self._exec_visual_feedback(handle, verify_result, screenshots)
                tokens_used += fix_result.get("tokens", 0)
                if not fix_result["passed"]:
                    return VisualResult(
                        status="blocked",
                        termination_reason="visual_feedback_failed",
                        iterations=iteration + 1,
                        tokens_used=tokens_used,
                        final_verify=verify_result,
                    )
                return VisualResult(
                    status="fix_applied",
                    termination_reason="fix_applied",
                    iterations=iteration + 1,
                    tokens_used=tokens_used,
                    final_verify=verify_result,
                )

            finally:
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
            timeout_ms=self._vc.timeout_ms,
        )

        try:
            evidence = parse_playwright_json(result.stdout)
        except PlaywrightEvidenceError as exc:
            return VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    category=FailureCategory.PLAYWRIGHT_TEST,
                    id="playwright_parse_error",
                    error=f"{exc}: {result.stdout[:500]}",
                )],
                duration_s=result.duration_ms / 1000.0,
                token_usage=_estimate_tokens(result),
            )

        failures: list[FailureEntry] = []
        if evidence.total == 0:
            failures.append(FailureEntry(
                category=FailureCategory.PLAYWRIGHT_TEST,
                id="playwright_no_tests",
                error="Playwright exited without executing any tests.",
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
                timeout_ms=app.readiness_timeout_ms,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"harness.app setup command failed: {command}\n{result.stderr or result.stdout}"
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
                timeout_ms=30_000,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"harness.app start command failed: {command}\n{result.stderr or result.stdout}"
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
            timeout_ms=app.readiness_timeout_ms + 5_000,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"harness.app URL did not become ready: {app.url}\n{result.stderr or result.stdout}"
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
                timeout_ms=30_000,
            )

        commands = app.start_commands or ([app.start_command] if app.start_command else [])
        for index, _ in enumerate(commands):
            self._provider.exec(
                handle,
                f"sh -lc 'test ! -f /tmp/echelon-app-{index}.pid || kill $(cat /tmp/echelon-app-{index}.pid) 2>/dev/null || true'",
                cwd="/workspace",
                timeout_ms=30_000,
            )

    # === Screenshots ===

    def _retrieve_screenshots(self, handle: SandboxHandle) -> List[str]:
        """Pull screenshot files from the container via the configured CLI."""
        container_src = f"/workspace/{self._vc.screenshot_dir}"

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "playwright-report"
                proc = subprocess.run(
                    [self._config.container_cli, "cp", f"{handle.id}:{container_src}", str(dest)],
                    capture_output=True,
                    timeout=30,
                )
                if proc.returncode != 0:
                    logger.debug(
                        "%s cp failed for screenshots (no playwright-report yet): %s",
                        self._config.container_cli,
                        proc.stderr.decode(errors="replace").strip(),
                    )
                    return []

                screenshots = list(dest.glob("**/*.png")) + list(dest.glob("**/*.jpg"))
                logger.info("Retrieved %d screenshots from container", len(screenshots))
                return [str(p) for p in screenshots]
        except Exception as e:
            logger.warning("Screenshot retrieval failed: %s", e)
            return []

    # === Feedback ===

    def _exec_visual_feedback(
        self,
        handle: SandboxHandle,
        verify_result: VerifyResult,
        screenshots: List[str],
    ) -> Dict[str, Any]:
        """Run echelon build --fix with visual failure context."""
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

        result = self._provider.exec(handle, cmd, timeout_ms=1_200_000)
        return {
            "exit_code": result.exit_code,
            "passed": result.exit_code == 0,
            "duration_s": result.duration_ms / 1000.0,
            "tokens": _estimate_tokens(result),
        }

    # === Sandbox spec ===

    def _build_sandbox_spec(self, worktree_path: str) -> SandboxSpec:
        """Build sandbox spec using Playwright image."""
        from harness.provider import NetworkPolicy, ResourceLimits as ProviderResourceLimits

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


# === Helpers ===

def _estimate_tokens(result: ExecResult) -> int:
    """Rough token estimate from stdout/stderr byte length."""
    total_bytes = len(result.stdout.encode()) + len(result.stderr.encode())
    return max(1, total_bytes // 4)

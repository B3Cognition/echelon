"""DockerWorktreeProvider — Phase 1 SandboxProvider using Docker.

Per contracts/sandbox-provider.md:
- Container lifecycle: create/exec/write_file/read_file/destroy
- Resource limits enforcement
- Network policy via Squid proxy sidecar
- Credential leak detection (FR-SANDBOX-005, FR-CREDS-001b)
- Timeout handling (FR-SANDBOX-003a/b/c)
- Bounded buffer truncation (FR-STREAM-001a/b)
- Resource stats collection (FR-EXEC-STATS-001)

Per ADR-001: Python orchestration + shell scripts for Docker CLI.
Per ADR-003: Squid forward proxy on internal Docker network.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set

from harness.errors import (
    CredentialLeakError,
    SandboxCreationError,
    SandboxExecError,
)
from harness.exec_result import (
    EXIT_FORCE_KILL,
    EXIT_OOM,
    EXIT_PID_LIMIT,
    EXIT_TIMEOUT,
    ExecResult,
    ResourceStats,
)
from harness.provider import (
    Capability,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
    register_provider,
)
from harness.verification_plan import SandboxServiceSpec

logger = logging.getLogger(__name__)

# --- Constants ---

# Git credential patterns to detect (FR-SANDBOX-005)
CREDENTIAL_PATTERNS = [
    re.compile(r"GIT_ASKPASS", re.IGNORECASE),
    re.compile(r"GIT_PASSWORD", re.IGNORECASE),
    re.compile(r"GIT_TOKEN", re.IGNORECASE),
    re.compile(r"GIT_CREDENTIAL", re.IGNORECASE),
    re.compile(r"GITHUB_TOKEN", re.IGNORECASE),
    re.compile(r"GITLAB_TOKEN", re.IGNORECASE),
    re.compile(r"GH_TOKEN", re.IGNORECASE),
]

# Host credential mount patterns (FR-CREDS-001b)
CREDENTIAL_MOUNT_PATTERNS = [
    ".docker/config.json",
    ".ssh/",
    ".gitconfig",
    ".git-credentials",
]

# Default buffer limit (10MB per FR-STREAM-001a)
DEFAULT_BUFFER_LIMIT_BYTES = 10_485_760

# Truncation tail ratio (80% per FR-STREAM-001b)
TRUNCATION_TAIL_RATIO = 0.80

# Timeout for docker commands themselves
DOCKER_CMD_TIMEOUT = 30
_SAFE_PROXY_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def _generate_squid_conf(allowlist: List[str]) -> str:
    """Create one private proxy policy file for this sandbox lifecycle."""
    template = Path(__file__).resolve().parents[2] / "network" / "squid.conf.template"
    try:
        content = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise SandboxCreationError(f"could not load squid policy template: {exc}") from exc
    additions = "\n".join(
        f"acl allowlist dstdomain {host}"
        for host in allowlist
        if _SAFE_PROXY_HOST.fullmatch(host)
    )
    content = content.replace("# {{ADDITIONAL_ALLOWLIST}}", additions)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="echelon-squid-", suffix=".conf", delete=False
    ) as output:
        output.write(content)
        return output.name


def _run_docker(
    args: List[str],
    cli: str = "docker",
    timeout: int = DOCKER_CMD_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a Docker-compatible container CLI command with timeout."""
    cmd = [cli] + args
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxExecError(
            f"Docker command timed out: {' '.join(cmd)}",
            cause=str(e),
        )
    except subprocess.CalledProcessError as e:
        raise SandboxExecError(
            f"Docker command failed: {' '.join(cmd)}: {e.stderr.strip()}",
            cause=str(e),
        )


def _check_credential_leak(
    env: Dict[str, str],
    secrets_env: Dict[str, str],
) -> None:
    """Check for git credentials in environment variables.

    Per FR-SANDBOX-005: no git credentials in sandbox.
    Per FR-CREDS-001b: no host credential stores in sandbox.

    Raises:
        CredentialLeakError: If git credentials detected.
    """
    all_env = {**env, **secrets_env}
    for key in all_env:
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(key):
                raise CredentialLeakError(
                    f"Git credential detected in environment variable: {key}. "
                    f"Per FR-SANDBOX-005: sandbox must never hold git credentials."
                )


def _truncate_output(
    output: str,
    limit_bytes: int,
) -> tuple:
    """Apply bounded-buffer truncation per FR-STREAM-001a/b.

    Returns:
        Tuple of (truncated_output, was_truncated)
    """
    output_bytes = output.encode("utf-8", errors="replace")
    if len(output_bytes) <= limit_bytes:
        return output, False

    # Tail-preserving: keep last 80% of buffer (FR-STREAM-001b)
    tail_size = int(limit_bytes * TRUNCATION_TAIL_RATIO)
    tail_bytes = output_bytes[-tail_size:]
    marker = f"[TRUNCATED: {len(output_bytes)}]\n"
    truncated = marker + tail_bytes.decode("utf-8", errors="replace")
    return truncated, True


def _parse_docker_stats(container_id: str, cli: str = "docker") -> Optional[ResourceStats]:
    """Collect resource stats via docker stats (FR-EXEC-STATS-001).

    Returns None with warning on collection failure.
    """
    try:
        result = subprocess.run(
            [
                cli, "stats", "--no-stream",
                "--format", "{{json .}}",
                container_id,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(
                "Failed to collect resource stats for %s: %s",
                container_id,
                result.stderr.strip(),
            )
            return None

        stats = json.loads(result.stdout.strip())

        # Parse memory usage (e.g., "123.4MiB / 4GiB")
        mem_usage_str = stats.get("MemUsage", "0B / 0B")
        peak_memory = _parse_memory_string(mem_usage_str.split("/")[0].strip())

        return ResourceStats(
            peak_memory_bytes=peak_memory,
            cpu_time_ms=0,  # docker stats doesn't provide cumulative CPU time
            wall_time_ms=0,  # Will be set by caller from timing
        )
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning("Could not parse resource stats for %s: %s", container_id, e)
        return None


def _parse_memory_string(mem_str: str) -> int:
    """Parse Docker memory string (e.g., '123.4MiB') to bytes."""
    mem_str = mem_str.strip()
    units = {
        "B": 1,
        "KiB": 1024,
        "MiB": 1024 ** 2,
        "GiB": 1024 ** 3,
        "kB": 1000,
        "MB": 1000 ** 2,
        "GB": 1000 ** 3,
    }
    for suffix, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if mem_str.endswith(suffix):
            try:
                value = float(mem_str[:-len(suffix)])
                return int(value * multiplier)
            except ValueError:
                return 0
    try:
        return int(float(mem_str))
    except ValueError:
        return 0


class DockerWorktreeProvider(SandboxProvider):
    """Phase 1 SandboxProvider implementation using Docker.

    Container lifecycle:
    1. create(): docker network create (internal) + docker run (squid proxy)
                 + docker run (sandbox)
    2. exec(): docker exec with timeout
    3. write_file(): docker cp (host -> container)
    4. read_file(): docker cp (container -> host)
    5. destroy(): docker rm -f (sandbox + proxy) + docker network rm

    capabilities(): returns empty set (no bulk ops, no streaming, no snapshots)
    """

    def __init__(
        self,
        buffer_limit_bytes: int = DEFAULT_BUFFER_LIMIT_BYTES,
        squid_conf_path: Optional[str] = None,
        container_cli: str = "docker",
    ) -> None:
        self._buffer_limit_bytes = buffer_limit_bytes
        self._squid_conf_path = squid_conf_path
        self._container_cli = container_cli
        # Track resources for cleanup
        self._containers: Dict[str, _ContainerInfo] = {}

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        """Create a sandbox with Docker container + Squid proxy sidecar.

        Per contract:
        - Validate spec
        - Check for credential leaks (FR-SANDBOX-005, FR-CREDS-001b)
        - Create Docker network (internal)
        - Start Squid proxy sidecar
        - Start sandbox container with resource limits, bind-mount, env
        - Execute post_create_command if present
        - Return SandboxHandle with unique session_id
        """
        # Check credential leaks (FR-SANDBOX-005, FR-CREDS-001b)
        _check_credential_leak(spec.env, spec.secrets_env)

        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        network_name = f"harness-net-{session_id}"
        proxy_container_id = None
        sandbox_container_id = None
        generated_squid_conf: str | None = None

        try:
            # Create internal Docker network
            result = _run_docker([
                "network", "create", "--internal",
                "--label", f"echelon-harness.session_id={session_id}",
                network_name,
            ], cli=self._container_cli)
            network_id = result.stdout.strip()

            # The private network needs a proxy for package/bootstrap traffic.
            squid_conf_path = self._squid_conf_path
            if not squid_conf_path or not os.path.isfile(squid_conf_path):
                generated_squid_conf = _generate_squid_conf(spec.network_policy.allowlist)
                squid_conf_path = generated_squid_conf
            if squid_conf_path:
                proxy_result = _run_docker([
                    "run", "-d",
                    "--network", network_name,
                    "--name", f"harness-proxy-{session_id}",
                    "--volume", f"{squid_conf_path}:/etc/squid/squid.conf:ro",
                    "--label", f"echelon-harness.session_id={session_id}",
                    "--label", "echelon-harness.type=squid-proxy",
                    spec.network_policy.proxy_image,
                ], cli=self._container_cli)
                proxy_container_id = proxy_result.stdout.strip()
                # The verifier remains on the internal network only. The proxy
                # has a second bridge attachment solely to reach allowlisted
                # registries and browser-download hosts.
                egress_network = "podman" if self._container_cli == "podman" else "bridge"
                _run_docker(
                    ["network", "connect", egress_network, proxy_container_id],
                    cli=self._container_cli,
                )

            # Build sandbox container args
            docker_args = [
                "run", "-d",
                "--network", network_name,
                "--memory", spec.resource_limits.memory,
                "--cpus", str(spec.resource_limits.cpu),
                "--pids-limit", str(spec.resource_limits.pids),
                "--volume", f"{spec.worktree_mount}:{spec.container_mount}",
                "--workdir", spec.container_mount,
                "--label", f"echelon-harness.session_id={session_id}",
                "--label", "echelon-harness.type=sandbox",
            ]

            # Add spec labels
            for key, value in spec.labels.items():
                docker_args.extend([
                    "--label", f"echelon-harness.{key}={value}",
                ])

            ephemeral_volumes = [
                f"harness-volume-{session_id}-{path.replace('/', '-').strip('-')}"
                for path in spec.ephemeral_volumes
            ]
            for volume_name, path in zip(ephemeral_volumes, spec.ephemeral_volumes):
                docker_args.extend(["--volume", f"{volume_name}:{spec.container_mount}/{path}"])

            # Inject environment variables
            for key, value in spec.env.items():
                docker_args.extend(["--env", f"{key}={value}"])

            # Inject secrets (same mechanism, kept separate for clarity)
            for key, value in spec.secrets_env.items():
                docker_args.extend(["--env", f"{key}={value}"])

            # Set proxy env vars so sandbox routes through Squid
            if proxy_container_id:
                proxy_name = f"harness-proxy-{session_id}"
                docker_args.extend([
                    "--env", f"http_proxy=http://{proxy_name}:3128",
                    "--env", f"https_proxy=http://{proxy_name}:3128",
                    "--env", f"HTTP_PROXY=http://{proxy_name}:3128",
                    "--env", f"HTTPS_PROXY=http://{proxy_name}:3128",
                ])

            # Image + keep-alive command
            docker_args.extend([spec.image, "tail", "-f", "/dev/null"])

            sandbox_result = _run_docker(docker_args, cli=self._container_cli)
            sandbox_container_id = sandbox_result.stdout.strip()

            # Execute post_create_command (FR-SANDBOX spec)
            if spec.post_create_command:
                post_result = subprocess.run(
                    [self._container_cli, "exec", sandbox_container_id,
                     "sh", "-c", spec.post_create_command],
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 min for post-create
                    check=False,
                )
                if post_result.returncode != 0:
                    logger.warning(
                        "post_create_command failed (exit %d): %s",
                        post_result.returncode,
                        post_result.stderr.strip(),
                    )

            # Track for cleanup
            handle = SandboxHandle(
                id=sandbox_container_id,
                session_id=session_id,
            )
            self._containers[session_id] = _ContainerInfo(
                sandbox_id=sandbox_container_id,
                proxy_id=proxy_container_id,
                network_name=network_name,
                volume_names=ephemeral_volumes,
                generated_squid_conf=generated_squid_conf,
            )

            return handle

        except Exception as e:
            # Clean up partial resources on failure
            self._cleanup_partial(sandbox_container_id, proxy_container_id, network_name)
            if generated_squid_conf:
                Path(generated_squid_conf).unlink(missing_ok=True)
            if isinstance(e, (CredentialLeakError, SandboxCreationError, SandboxExecError)):
                raise
            raise SandboxCreationError(
                f"Failed to create sandbox: {e}",
                cause=str(e),
            )

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        """Execute a command in the sandbox.

        Per contract:
        - Honor timeout_ms (FR-SANDBOX-003a)
        - On timeout: kill within 5s, exit_code=124 (FR-SANDBOX-003b)
        - If kill fails: destroy sandbox, exit_code=137 (FR-SANDBOX-003c)
        - Bounded buffer truncation (FR-STREAM-001a/b)
        - Resource stats collection (FR-EXEC-STATS-001)
        """
        timeout_seconds = max(1, timeout_ms // 1000)
        container_id = handle.id

        docker_args = ["exec"]
        if cwd:
            docker_args.extend(["--workdir", cwd])
        if env:
            for key, value in env.items():
                docker_args.extend(["--env", f"{key}={value}"])
        docker_args.extend([container_id, "sh", "-c", cmd])

        start_time = time.monotonic()

        try:
            result = subprocess.run(
                [self._container_cli] + docker_args,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            wall_time_ms = int((time.monotonic() - start_time) * 1000)

            stdout_str = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout
            stderr_str = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr

            # Apply buffer truncation (FR-STREAM-001a/b)
            stdout_str, stdout_truncated = _truncate_output(stdout_str, self._buffer_limit_bytes)
            stderr_str, stderr_truncated = _truncate_output(stderr_str, self._buffer_limit_bytes)
            truncated = stdout_truncated or stderr_truncated

            # Map exit codes for resource limit violations
            exit_code = result.returncode
            if exit_code == 139:
                exit_code = EXIT_OOM  # OOM kill
            elif exit_code == 155:
                exit_code = EXIT_PID_LIMIT

            # Collect resource stats (FR-EXEC-STATS-001)
            resource_stats = _parse_docker_stats(container_id, cli=self._container_cli)
            if resource_stats is not None:
                resource_stats = ResourceStats(
                    peak_memory_bytes=resource_stats.peak_memory_bytes,
                    cpu_time_ms=resource_stats.cpu_time_ms,
                    wall_time_ms=wall_time_ms,
                )

            return ExecResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_ms=wall_time_ms,
                resource_stats=resource_stats,
                truncated=truncated,
            )

        except subprocess.TimeoutExpired:
            wall_time_ms = int((time.monotonic() - start_time) * 1000)

            # FR-SANDBOX-003b: kill within 5s
            try:
                subprocess.run(
                    [self._container_cli, "exec", container_id, "kill", "-TERM", "1"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                # Wait for graceful shutdown
                time.sleep(1)
                return ExecResult(
                    exit_code=EXIT_TIMEOUT,
                    stdout="",
                    stderr=f"Process timed out after {timeout_ms}ms",
                    duration_ms=wall_time_ms,
                    resource_stats=None,
                    truncated=False,
                )
            except (subprocess.TimeoutExpired, OSError):
                # FR-SANDBOX-003c: force-kill, destroy sandbox
                logger.error(
                    "Process unresponsive after timeout, force-killing sandbox %s",
                    container_id,
                )
                self.destroy(handle)
                return ExecResult(
                    exit_code=EXIT_FORCE_KILL,
                    stdout="",
                    stderr="force-kill: sandbox destroyed after unresponsive process.",
                    duration_ms=wall_time_ms,
                    resource_stats=None,
                    truncated=False,
                )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        """Write a file into the sandbox via docker cp."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            _run_docker(["cp", tmp_path, f"{handle.id}:{path}"], cli=self._container_cli)
        finally:
            os.unlink(tmp_path)

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        """Read a file from the sandbox via docker cp."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_path = os.path.join(tmp_dir, "file")
            _run_docker(["cp", f"{handle.id}:{path}", local_path], cli=self._container_cli)
            return Path(local_path).read_bytes()

    def destroy(self, handle: SandboxHandle) -> None:
        """Destroy sandbox, proxy, and network.

        Per contract: docker rm -f sandbox + proxy, docker network rm.
        """
        info = self._containers.pop(handle.session_id, None)
        if info is None:
            # Best-effort: just try to remove the container by ID
            subprocess.run(
                [self._container_cli, "rm", "-f", handle.id],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return

        # Remove verification sidecars before their internal network.
        for service_id in info.service_ids:
            subprocess.run(
                [self._container_cli, "rm", "-f", service_id],
                capture_output=True,
                timeout=10,
                check=False,
            )

        # Remove sandbox container
        subprocess.run(
            [self._container_cli, "rm", "-f", info.sandbox_id],
            capture_output=True,
            timeout=10,
            check=False,
        )

        # Remove proxy container
        if info.proxy_id:
            subprocess.run(
                [self._container_cli, "rm", "-f", info.proxy_id],
                capture_output=True,
                timeout=10,
                check=False,
            )

        # Remove network
        subprocess.run(
            [self._container_cli, "network", "rm", info.network_name],
            capture_output=True,
            timeout=10,
            check=False,
        )
        for volume_name in getattr(info, "volume_names", []):
            subprocess.run(
                [self._container_cli, "volume", "rm", "-f", volume_name],
                capture_output=True, timeout=10, check=False,
            )
        generated_squid_conf = getattr(info, "generated_squid_conf", None)
        if generated_squid_conf:
            Path(generated_squid_conf).unlink(missing_ok=True)

    def capabilities(self) -> Set[Capability]:
        """Phase 1: no optional capabilities."""
        return set()

    def start_services(
        self,
        handle: SandboxHandle,
        services: tuple[SandboxServiceSpec, ...],
    ) -> tuple[str, ...]:
        """Start labelled verification sidecars on the sandbox internal network."""
        info = self._containers.get(handle.session_id)
        if info is None:
            raise SandboxCreationError("sandbox handle is not active")
        started: list[str] = []
        try:
            for service in services:
                result = _run_docker([
                    "run", "-d",
                    "--network", info.network_name,
                    "--network-alias", service.service_name,
                    "--label", f"echelon-harness.session_id={handle.session_id}",
                    "--label", "echelon-harness.type=verification-service",
                    "--label", f"echelon-harness.service={service.service_name}",
                    "--name", f"harness-service-{service.service_name}-{handle.session_id}",
                    *sum((["--env", f"{key}={value}"] for key, value in service.environment), []),
                    service.image,
                ], cli=self._container_cli)
                service_id = result.stdout.strip()
                if not service_id:
                    raise SandboxCreationError(
                        f"verification service {service.service_name!r} did not return an id"
                    )
                started.append(service_id)
                if service.health_command:
                    deadline = time.monotonic() + 30
                    while True:
                        health = _run_docker(
                            ["exec", service_id, *service.health_command],
                            cli=self._container_cli,
                            check=False,
                        )
                        if health.returncode == 0:
                            break
                        if time.monotonic() >= deadline:
                            raise SandboxCreationError(
                                f"verification service {service.service_name!r} "
                                "did not become healthy within 30 seconds"
                            )
                        time.sleep(0.5)
            info.service_ids.extend(started)
            return tuple(started)
        except Exception:
            for service_id in started:
                subprocess.run(
                    [self._container_cli, "rm", "-f", service_id],
                    capture_output=True, timeout=10, check=False,
                )
            raise

    # --- Internal helpers ---

    def _cleanup_partial(
        self,
        sandbox_id: Optional[str],
        proxy_id: Optional[str],
        network_name: Optional[str],
    ) -> None:
        """Clean up partially created resources on failure."""
        if sandbox_id:
            subprocess.run(
                [self._container_cli, "rm", "-f", sandbox_id],
                capture_output=True, timeout=10, check=False,
            )
        if proxy_id:
            subprocess.run(
                [self._container_cli, "rm", "-f", proxy_id],
                capture_output=True, timeout=10, check=False,
            )
        if network_name:
            subprocess.run(
                [self._container_cli, "network", "rm", network_name],
                capture_output=True, timeout=10, check=False,
            )


class _ContainerInfo:
    """Internal tracking of container resources for cleanup."""

    __slots__ = ("sandbox_id", "proxy_id", "network_name", "service_ids", "volume_names", "generated_squid_conf")

    def __init__(
        self,
        sandbox_id: str,
        proxy_id: Optional[str],
        network_name: str,
        volume_names: list[str] | None = None,
        generated_squid_conf: str | None = None,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.proxy_id = proxy_id
        self.network_name = network_name
        self.service_ids: list[str] = []
        self.volume_names = volume_names or []
        self.generated_squid_conf = generated_squid_conf


# --- Registration ---

register_provider("docker", DockerWorktreeProvider)

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.docker_provider import DockerWorktreeProvider
from harness.errors import NotSupportedError
from harness.provider import SandboxHandle
from harness.verification_plan import SandboxServiceSpec


def _active_provider() -> tuple[DockerWorktreeProvider, SandboxHandle]:
    provider = DockerWorktreeProvider(buffer_limit_bytes=1024)
    handle = SandboxHandle(id="sandbox-id", session_id="session-id")
    provider._containers[handle.session_id] = SimpleNamespace(
        sandbox_id="sandbox-id",
        proxy_id=None,
        network_name="internal-net",
        service_ids=[],
        service_ids_by_name={},
    )
    return provider, handle


@pytest.mark.unit
def test_exec_service_uses_attempt_owned_named_sidecar_without_shell() -> None:
    provider, handle = _active_provider()
    service = SandboxServiceSpec(
        service_name="postgres",
        image="postgres:16.4-alpine",
    )
    with patch("harness.docker_provider._run_docker") as run:
        run.return_value = MagicMock(stdout="service-id\n", stderr="", returncode=0)
        provider.start_services(handle, (service,))
    with patch("harness.docker_provider.subprocess.run") as run:
        run.return_value = MagicMock(
            stdout=b"1\n",
            stderr=b"",
            returncode=0,
        )

        result = provider.exec_service(
            handle,
            "postgres",
            ("psql", "-Atqc", "SELECT 1"),
            timeout_ms=30_000,
        )

    assert result.exit_code == 0
    assert result.stdout == "1\n"
    assert run.call_args.args[0] == [
        "docker",
        "exec",
        "service-id",
        "psql",
        "-Atqc",
        "SELECT 1",
    ]


@pytest.mark.unit
def test_exec_service_rejects_unknown_service() -> None:
    provider, handle = _active_provider()

    with pytest.raises(NotSupportedError, match="service.*not active"):
        provider.exec_service(handle, "postgres", ("true",))

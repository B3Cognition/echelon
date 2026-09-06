"""Small, engine-neutral adapters for the approved macOS local profile."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Callable, Protocol

from harness.local_runner_compose import CanonicalComposePlan
from harness.local_runner_journal import ResourceJournalEntry


_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PORT = re.compile(r"^[1-9][0-9]{0,4}$")
_LABEL_RUN_ID = "io.echelon.local-run-id"
_LABEL_MANAGED = "io.echelon.local-managed"


class LocalEngineError(RuntimeError):
    """Raised when a local container engine cannot meet the runner policy."""


@dataclass(frozen=True)
class EngineProfile:
    profile_id: str
    engine: str
    endpoint: str


@dataclass(frozen=True)
class RenderedEnginePlan:
    canonical_plan: CanonicalComposePlan
    command_argv: tuple[str, ...]
    generated_override_path: Path
    generated_bindings: tuple[tuple[str, str], ...]
    project_name: str
    postgres_password: str = field(repr=False)


@dataclass(frozen=True)
class LocalResourceSet:
    run_id: str
    resources: tuple[ResourceJournalEntry, ...]
    bindings: tuple[tuple[str, str], ...] = ()


class LocalEngineAdapter(Protocol):
    profile_id: str

    def probe(self) -> EngineProfile: ...

    def render_plan(
        self, plan: CanonicalComposePlan, run_id: str, generated_root: Path
    ) -> RenderedEnginePlan: ...

    def up(self, rendered: RenderedEnginePlan) -> LocalResourceSet: ...

    def inspect(
        self, rendered: RenderedEnginePlan, resources: LocalResourceSet
    ) -> LocalResourceSet: ...

    def down(
        self, rendered: RenderedEnginePlan, resources: LocalResourceSet
    ) -> LocalResourceSet: ...


Executor = Callable[..., subprocess.CompletedProcess[str]]


class _MacOSComposeAdapter:
    profile_id = ""
    engine = ""

    def __init__(self, *, executor: Executor | None = None, platform: str | None = None) -> None:
        self._executor = executor or _subprocess_executor
        self._platform = platform or sys.platform

    def render_plan(
        self, plan: CanonicalComposePlan, run_id: str, generated_root: Path
    ) -> RenderedEnginePlan:
        if not _RUN_ID.fullmatch(run_id):
            raise LocalEngineError("local run identity is invalid")
        root = Path(generated_root).expanduser()
        if root.is_symlink():
            raise LocalEngineError("generated Compose root is symlinked")
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        project_name = f"echelon-local-{run_id}"
        password = secrets.token_urlsafe(24)
        override = root / f"compose-{run_id}.json"
        if override.exists() or override.is_symlink():
            raise LocalEngineError("generated Compose override already exists")
        payload = {
            "services": {
                "postgres": {
                    "labels": {
                        _LABEL_MANAGED: "true",
                        _LABEL_RUN_ID: run_id,
                    },
                    "environment": {
                        "POSTGRES_USER": "echelon",
                        "POSTGRES_PASSWORD": password,
                        "POSTGRES_DB": "echelon",
                    },
                    "ports": ["127.0.0.1::5432"],
                    "tmpfs": ["/var/lib/postgresql/data"],
                }
            }
        }
        override.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        override.chmod(0o600)
        command = self._compose_argv(
            project_name,
            plan.compose_path,
            override,
            "up",
            "--detach",
        )
        return RenderedEnginePlan(
            canonical_plan=plan,
            command_argv=command,
            generated_override_path=override,
            generated_bindings=(),
            project_name=project_name,
            postgres_password=password,
        )

    def up(self, rendered: RenderedEnginePlan) -> LocalResourceSet:
        self._run(rendered.command_argv, cwd=rendered.canonical_plan.worktree)
        listed = self._run(
            self._compose_argv(
                rendered.project_name,
                rendered.canonical_plan.compose_path,
                rendered.generated_override_path,
                "ps",
                "-q",
            ),
            cwd=rendered.canonical_plan.worktree,
        ).stdout
        ids = tuple(item.strip() for item in listed.splitlines() if item.strip())
        if len(ids) != 1:
            raise LocalEngineError("local engine did not report exactly one managed service")
        resource = ResourceJournalEntry(
            engine=self.engine,
            resource_kind="container",
            resource_id=ids[0],
            labels=((_LABEL_MANAGED, "true"), (_LABEL_RUN_ID, rendered.project_name.removeprefix("echelon-local-"))),
        )
        return LocalResourceSet(run_id=resource.labels[1][1], resources=(resource,))

    def inspect(
        self, rendered: RenderedEnginePlan, resources: LocalResourceSet
    ) -> LocalResourceSet:
        if len(resources.resources) != 1:
            raise LocalEngineError("local engine resource journal is incomplete")
        resource = resources.resources[0]
        self._assert_owned_resource(resource, resources.run_id)
        port_result = self._run(
            (
                self.engine,
                "inspect",
                resource.resource_id,
                "--format",
                "{{(index (index .NetworkSettings.Ports \"5432/tcp\") 0).HostPort}}",
            )
        )
        port = port_result.stdout.strip()
        if not _PORT.fullmatch(port) or not 1 <= int(port) <= 65535:
            raise LocalEngineError("local PostgreSQL service has no dynamic loopback port")
        url = (
            f"postgresql://echelon:{rendered.postgres_password}@127.0.0.1:{port}/echelon"
        )
        return LocalResourceSet(
            run_id=resources.run_id,
            resources=resources.resources,
            bindings=(("DATABASE_URL", url), ("TEST_DATABASE_URL", url)),
        )

    def down(
        self, rendered: RenderedEnginePlan, resources: LocalResourceSet
    ) -> LocalResourceSet:
        for resource in resources.resources:
            self._assert_owned_resource(resource, resources.run_id)
            self._run((self.engine, "rm", "--force", resource.resource_id))
        try:
            rendered.generated_override_path.unlink(missing_ok=True)
        except OSError as exc:
            raise LocalEngineError("could not remove generated Compose override") from exc
        return LocalResourceSet(run_id=resources.run_id, resources=())

    def _assert_owned_resource(self, resource: ResourceJournalEntry, run_id: str) -> None:
        if resource.engine != self.engine or resource.resource_kind != "container":
            raise LocalEngineError("local engine resource journal is invalid")
        expected = dict(resource.labels)
        if expected.get(_LABEL_MANAGED) != "true" or expected.get(_LABEL_RUN_ID) != run_id:
            raise LocalEngineError("local engine resource journal is invalid")
        raw = self._run(
            (self.engine, "inspect", resource.resource_id, "--format", "{{json .Config.Labels}}")
        ).stdout.strip()
        try:
            labels = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LocalEngineError("could not validate managed local resource labels") from exc
        if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
            raise LocalEngineError("refusing to clean an unlabelled local resource")

    def _run(
        self, argv: tuple[str, ...], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._executor(argv, cwd=cwd)
        except OSError as exc:
            raise LocalEngineError(f"{self.engine} command could not start") from exc
        if result.returncode != 0:
            raise LocalEngineError(
                result.stderr.strip() or result.stdout.strip() or f"{self.engine} command failed"
            )
        return result

    def _compose_argv(self, project: str, source: Path, override: Path, *tail: str) -> tuple[str, ...]:
        raise NotImplementedError


class DockerDesktopMacOSAdapter(_MacOSComposeAdapter):
    profile_id = "docker-desktop-macos-v1"
    engine = "docker"

    def probe(self) -> EngineProfile:
        _require_macos(self._platform)
        context = self._run(("docker", "context", "show")).stdout.strip()
        if not context:
            raise LocalEngineError("Docker has no active context")
        endpoint = self._run(
            ("docker", "context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}")
        ).stdout.strip()
        if not endpoint.startswith("unix://"):
            raise LocalEngineError("Docker active context is not a local Unix socket")
        return EngineProfile(self.profile_id, self.engine, endpoint)

    def _compose_argv(self, project: str, source: Path, override: Path, *tail: str) -> tuple[str, ...]:
        return (
            "docker", "compose", "--project-name", project, "--file", str(source),
            "--file", str(override), *tail,
        )


class PodmanMacOSAdapter(_MacOSComposeAdapter):
    profile_id = "podman-macos-v1"
    engine = "podman"

    def probe(self) -> EngineProfile:
        _require_macos(self._platform)
        endpoint = self._run(
            ("podman", "machine", "inspect", "--format", "{{.ConnectionInfo.PodmanSocket.Path}}")
        ).stdout.strip()
        if not endpoint.startswith("/"):
            raise LocalEngineError("Podman has no local macOS machine socket")
        return EngineProfile(self.profile_id, self.engine, endpoint)

    def _compose_argv(self, project: str, source: Path, override: Path, *tail: str) -> tuple[str, ...]:
        return (
            "podman", "compose", "--project-name", project, "--file", str(source),
            "--file", str(override), *tail,
        )


def _require_macos(platform: str) -> None:
    if platform != "darwin":
        raise LocalEngineError("local verification is supported on macOS only")


def _subprocess_executor(
    argv: tuple[str, ...], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)

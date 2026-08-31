from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from harness.stacks.resolver import ResolvedStackProvisioner, ResolvedStacks
from harness.stacks.schema import StackProvisioner


class ProvisioningError(Exception):
    """Raised when verification provisioning cannot be safely rendered."""


@dataclass(frozen=True)
class ProvisioningStatus:
    state: str
    provisioner_id: str
    owner_stack_id: str
    message: str
    path: Path | None = None


def provisioning_statuses(
    resolved: ResolvedStacks,
    target_root: Path,
    environment: Mapping[str, str],
) -> list[ProvisioningStatus]:
    """Evaluate provisioners without running commands or changing the target."""
    root = target_root.resolve()
    return [
        _provisioning_status(item, root, environment)
        for item in resolved.provisioners
    ]


def render_provisioner(
    provisioner: ResolvedStackProvisioner | StackProvisioner,
    target_root: Path,
    force: bool = False,
) -> list[Path]:
    """Render compose artifacts for a resolved provisioner without invoking Compose."""
    root = target_root.resolve()
    definition = _provisioner_definition(provisioner)
    artifacts = _compose_artifacts(definition, root)
    if not artifacts:
        raise ProvisioningError(
            f"provisioner {definition.id} has no compose-template outputs"
        )
    outputs = [path for path, _content in artifacts]
    existing = [path for path in outputs if path.exists()]
    if existing and not force:
        names = ", ".join(str(path) for path in existing)
        raise ProvisioningError(f"provisioning artifact already exists: {names}")

    for path, content in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return outputs


def _provisioning_status(
    resolved: ResolvedStackProvisioner,
    root: Path,
    environment: Mapping[str, str],
) -> ProvisioningStatus:
    provisioner = resolved.provisioner
    if all(str(environment.get(name, "")).strip() for name in provisioner.required_environment):
        return ProvisioningStatus(
            state="ready",
            provisioner_id=provisioner.id,
            owner_stack_id=resolved.owner_stack_id,
            message="required environment is configured",
        )

    outputs = _compose_outputs(provisioner, root)
    if outputs and all(path.is_file() for path in outputs):
        return ProvisioningStatus(
            state="prepared",
            provisioner_id=provisioner.id,
            owner_stack_id=resolved.owner_stack_id,
            message="Compose provisioning artifacts are prepared",
            path=outputs[0],
        )

    return ProvisioningStatus(
        state="missing",
        provisioner_id=provisioner.id,
        owner_stack_id=resolved.owner_stack_id,
        message="required environment is unset and provisioning artifacts are missing",
    )


def _compose_outputs(provisioner: StackProvisioner, root: Path) -> list[Path]:
    return [path for path, _content in _compose_artifacts(provisioner, root)]


def _compose_artifacts(
    provisioner: StackProvisioner, root: Path
) -> list[tuple[Path, str]]:
    templates = [
        satisfier
        for satisfier in provisioner.satisfiers
        if satisfier.kind == "compose-template"
    ]
    if not templates:
        return []

    for satisfier in templates:
        if satisfier.output is not None:
            _target_path(root, satisfier.output)
        if satisfier.env_example is not None:
            _target_path(root, satisfier.env_example)

    if len(templates) != 1:
        raise ProvisioningError("compose-template must declare the fixed artifact pair")

    template = templates[0]
    if (
        template.output != "docker-compose.echelon-verify.yml"
        or template.env_example != ".env.echelon-verify.example"
    ):
        raise ProvisioningError("compose-template must declare the fixed artifact pair")

    return [
        (
            _target_path(root, "docker-compose.echelon-verify.yml"),
            _compose_content(provisioner),
        ),
        (
            _target_path(root, ".env.echelon-verify.example"),
            _env_example_content(provisioner),
        ),
    ]


def _provisioner_definition(
    provisioner: ResolvedStackProvisioner | StackProvisioner,
) -> StackProvisioner:
    if isinstance(provisioner, ResolvedStackProvisioner):
        return provisioner.provisioner
    return provisioner


def _target_path(root: Path, output: str) -> Path:
    path = (root / output).resolve()
    if not path.is_relative_to(root):
        raise ProvisioningError(f"provisioning output is outside target root: {output}")
    return path


def _compose_content(provisioner: StackProvisioner) -> str:
    service = provisioner.services[0]
    return f"""# Verification-only Postgres. It deliberately publishes no host port.
# Start: docker compose -f docker-compose.echelon-verify.yml --env-file .env.echelon-verify.example up -d
# Check: docker compose -f docker-compose.echelon-verify.yml exec {service} {provisioner.readiness_command} -U echelon -d echelon_verify
# Connect: docker compose -f docker-compose.echelon-verify.yml exec {service} psql -U echelon -d echelon_verify
services:
  {service}:
    image: postgres:16.4-alpine
    environment:
      POSTGRES_DB: echelon_verify
      POSTGRES_USER: echelon
      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD:-echelon_verify_only}}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U echelon -d echelon_verify"]
      interval: 5s
      timeout: 5s
      retries: 12
    volumes:
      - echelon_verify_postgres_data:/var/lib/postgresql/data

volumes:
  echelon_verify_postgres_data:
"""


def _env_example_content(provisioner: StackProvisioner) -> str:
    required = "\n".join(
        f"{name}=# supply an externally reachable verification database URL"
        for name in provisioner.required_environment
    )
    return f"""# Set one of these values when your verification target has its own database.
# The Compose service has no host port. Use `docker compose exec` above or a connection path you choose.
{required}
POSTGRES_PASSWORD=echelon_verify_only
"""

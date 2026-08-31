from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks.provisioning import (
    ProvisioningError,
    provisioning_statuses,
    render_provisioner,
)
from harness.stacks.resolver import ResolvedStackProvisioner, ResolvedStacks
from harness.stacks.schema import StackProvisioner, StackProvisionerSatisfier


def _resolved_postgres() -> ResolvedStacks:
    provisioner = StackProvisioner(
        id="postgres-verify",
        scope="verification",
        services=["postgres"],
        required_environment=["DATABASE_URL"],
        readiness_command="pg_isready",
        satisfiers=[
            StackProvisionerSatisfier(kind="environment", variable="DATABASE_URL"),
            StackProvisionerSatisfier(
                kind="compose-template",
                output="docker-compose.echelon-verify.yml",
                env_example=".env.echelon-verify.example",
            ),
        ],
    )
    return ResolvedStacks(
        selected_ids=["game-persistence-postgres"],
        resolved_ids=["game-persistence-postgres"],
        implied_by={},
        capabilities={},
        tools={},
        required_commands=[],
        required_registries=[],
        context_files=[],
        provisioners=[
            ResolvedStackProvisioner(
                owner_stack_id="game-persistence-postgres",
                provisioner=provisioner,
            )
        ],
    )


@pytest.mark.unit
def test_external_database_url_marks_postgres_ready(tmp_path: Path) -> None:
    statuses = provisioning_statuses(
        _resolved_postgres(), tmp_path, {"DATABASE_URL": "postgresql://isolated"}
    )

    assert statuses[0].state == "ready"


@pytest.mark.unit
def test_render_compose_writes_only_fixed_target_files(tmp_path: Path) -> None:
    written = render_provisioner(_resolved_postgres().provisioners[0], tmp_path)

    assert written == [
        tmp_path / "docker-compose.echelon-verify.yml",
        tmp_path / ".env.echelon-verify.example",
    ]
    assert "postgres" in written[0].read_text(encoding="utf-8")


@pytest.mark.unit
def test_render_refuses_existing_file_without_force(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.echelon-verify.yml").write_text(
        "keep", encoding="utf-8"
    )

    with pytest.raises(ProvisioningError, match="already exists"):
        render_provisioner(_resolved_postgres().provisioners[0], tmp_path)


@pytest.mark.unit
def test_generated_files_mark_provisioner_prepared(tmp_path: Path) -> None:
    resolved = _resolved_postgres()
    render_provisioner(resolved.provisioners[0], tmp_path)

    statuses = provisioning_statuses(resolved, tmp_path, {})

    assert statuses[0].state == "prepared"
    assert statuses[0].path == tmp_path / "docker-compose.echelon-verify.yml"


@pytest.mark.unit
def test_empty_required_environment_value_is_not_ready(tmp_path: Path) -> None:
    statuses = provisioning_statuses(_resolved_postgres(), tmp_path, {"DATABASE_URL": ""})

    assert statuses[0].state == "missing"


@pytest.mark.unit
def test_render_rejects_outputs_outside_target_root(tmp_path: Path) -> None:
    unsafe = StackProvisioner(
        id="unsafe",
        scope="verification",
        services=["postgres"],
        required_environment=["DATABASE_URL"],
        readiness_command="pg_isready",
        satisfiers=[
            StackProvisionerSatisfier(kind="compose-template", output="../escape.yml")
        ],
    )

    with pytest.raises(ProvisioningError, match="outside target root"):
        render_provisioner(unsafe, tmp_path)


@pytest.mark.unit
def test_render_rejects_compose_template_with_nonstandard_output(tmp_path: Path) -> None:
    provisioner = _resolved_postgres().provisioners[0].provisioner
    wrong_output = StackProvisioner(
        **{
            **provisioner.__dict__,
            "satisfiers": [
                StackProvisionerSatisfier(kind="environment", variable="DATABASE_URL"),
                StackProvisionerSatisfier(
                    kind="compose-template",
                    output="nested/compose.yml",
                    env_example=".env.echelon-verify.example",
                ),
            ],
        }
    )

    with pytest.raises(ProvisioningError, match="fixed artifact pair"):
        render_provisioner(wrong_output, tmp_path)


@pytest.mark.unit
def test_render_rejects_compose_template_without_env_example(tmp_path: Path) -> None:
    provisioner = _resolved_postgres().provisioners[0].provisioner
    missing_example = StackProvisioner(
        **{
            **provisioner.__dict__,
            "satisfiers": [
                StackProvisionerSatisfier(kind="environment", variable="DATABASE_URL"),
                StackProvisionerSatisfier(
                    kind="compose-template",
                    output="docker-compose.echelon-verify.yml",
                ),
            ],
        }
    )

    with pytest.raises(ProvisioningError, match="fixed artifact pair"):
        render_provisioner(missing_example, tmp_path)

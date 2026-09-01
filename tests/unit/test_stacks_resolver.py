from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from harness.stacks.errors import StackConflictError, StackResolutionError
from harness.stacks.loader import load_stack_definitions
from harness.stacks.renderer import render_resolved_markdown, resolved_to_dict
from harness.stacks.resolver import resolved_stack_contract_sha256, resolve_stacks
from harness.stacks.schema import (
    StackDefinition,
    StackProvisioner,
    StackProvisionerSatisfier,
    StackRunnability,
    StackTool,
)


def _stack(
    stack_id: str,
    *,
    provides: dict[str, str],
    archetypes: list[str] | None = None,
    implies: list[str] | None = None,
    context_files: list[str] | None = None,
    requires_commands: list[str] | None = None,
    requires_registries: list[str] | None = None,
    tools: dict[str, StackTool] | None = None,
    provisioners: list[StackProvisioner] | None = None,
    runnability: StackRunnability | None = None,
) -> StackDefinition:
    return StackDefinition(
        id=stack_id,
        name=stack_id,
        version="1.0.0",
        kind="capability",
        owner="test",
        description="",
        source_path=Path(f"{stack_id}/stack.yml"),
        applies_to_archetypes=archetypes or ["web_app"],
        provides=provides,
        implies=implies or [],
        requires_commands=requires_commands or [],
        requires_registries=requires_registries or [],
        tools=tools or {},
        context_files=context_files or ["context.md"],
        provisioners=provisioners or [],
        runnability=runnability or StackRunnability(),
    )


def _write_stack(root: Path, stack_id: str, *, provides: dict[str, str]) -> None:
    stack_dir = root / "stacks" / stack_id
    stack_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / "stack.yml").write_text(
        dedent(
            f"""
            schema_version: "1.0"
            stack:
              id: {stack_id}
              name: {stack_id}
              version: 1.0.0
              kind: capability
              owner: test
              description: test stack
            applies_to:
              archetypes:
                - web_app
            provides:
        """
        ).lstrip()
        + "".join(
            f"  {key}: {value}\n" for key, value in provides.items()
        )
        + dedent(
            """
            requires:
              commands: []
              registries: []
            tools: {}
            context:
              files:
                - context.md
            implies: []
            conflicts: []
            """
        ),
        encoding="utf-8",
    )
    (stack_dir / "context.md").write_text(f"{stack_id} context\n", encoding="utf-8")


@pytest.mark.unit
def test_resolve_no_selected_stacks_is_empty() -> None:
    resolved = resolve_stacks([], {})

    assert resolved.selected_ids == []
    assert resolved.resolved_ids == []
    assert resolved.capabilities == {}
    assert resolved.tools == {}
    assert resolved.required_commands == []
    assert resolved.required_registries == []
    assert resolved.context_files == []
    assert resolved.provisioners == []
    assert resolved.runnability.policy == "not_applicable"


@pytest.mark.unit
def test_resolve_runnability_unions_obligations_and_uses_strongest_policy() -> None:
    definitions = {
        "web": _stack(
            "web",
            provides={"web_app.framework": "vite-react"},
            runnability=StackRunnability(
                classification="user_facing",
                policy="required",
                runner="linux_container",
                capabilities=("start", "primary_journey"),
                required_observations=("browser_dom",),
            ),
        ),
        "persistence": _stack(
            "persistence",
            provides={"data.database": "postgres"},
            runnability=StackRunnability(
                classification="non_runnable",
                policy="advisory",
                runner="linux_container",
                capabilities=("provision",),
                required_observations=("postgres_query",),
            ),
        ),
    }

    resolved = resolve_stacks(["web", "persistence"], definitions)

    assert resolved.runnability.classification == "user_facing"
    assert resolved.runnability.policy == "required"
    assert resolved.runnability.runner == "linux_container"
    assert resolved.runnability.capabilities == (
        "start",
        "primary_journey",
        "provision",
    )
    assert resolved.runnability.required_observations == (
        "browser_dom",
        "postgres_query",
    )
    assert resolved.runnability.sources == ("web", "persistence")


@pytest.mark.unit
def test_resolve_runnability_rejects_incompatible_runners() -> None:
    definitions = {
        "linux": _stack(
            "linux",
            provides={"web_app.framework": "vite"},
            runnability=StackRunnability(runner="linux_container"),
        ),
        "mac": _stack(
            "mac",
            provides={"test.framework": "xctest"},
            runnability=StackRunnability(runner="macos_simulator"),
        ),
    }

    with pytest.raises(StackConflictError, match="runnability runner"):
        resolve_stacks(["linux", "mac"], definitions)


@pytest.mark.unit
def test_resolved_stack_contract_hash_is_selection_order_stable() -> None:
    definitions = {
        "web": _stack(
            "web",
            provides={"web_app.framework": "vite"},
            runnability=StackRunnability(
                classification="user_facing",
                policy="required",
                runner="linux_container",
                capabilities=("start",),
                required_observations=("browser_dom",),
            ),
        ),
        "persistence": _stack(
            "persistence",
            provides={"data.database": "postgres"},
            runnability=StackRunnability(
                policy="advisory",
                runner="linux_container",
                capabilities=("provision",),
                required_observations=("postgres_query",),
            ),
        ),
    }

    first = resolve_stacks(["web", "persistence"], definitions)
    second = resolve_stacks(["persistence", "web"], definitions)

    assert resolved_stack_contract_sha256(first) == resolved_stack_contract_sha256(second)


@pytest.mark.unit
def test_rendered_resolution_explains_runnability_obligations() -> None:
    resolved = resolve_stacks(
        ["web"],
        {
            "web": _stack(
                "web",
                provides={"web_app.framework": "vite"},
                runnability=StackRunnability(
                    classification="user_facing",
                    policy="required",
                    runner="linux_container",
                    capabilities=("start", "primary_journey"),
                    required_observations=("browser_dom",),
                ),
            )
        },
    )

    data = resolved_to_dict(resolved)
    markdown = render_resolved_markdown(resolved)

    assert data["runnability"] == {
        "classification": "user_facing",
        "policy": "required",
        "runner": "linux_container",
        "capabilities": ["start", "primary_journey"],
        "required_observations": ["browser_dom"],
        "sources": ["web"],
    }
    assert "## User Runnability" in markdown
    assert "Policy: `required`" in markdown


def test_postgres_verification_provisioner_resolves_sandbox_service() -> None:
    provisioner = StackProvisioner(
        id="postgres-verify",
        scope="verification",
        services=["postgres"],
        required_environment=["DATABASE_URL"],
        readiness_command="pg_isready",
        satisfiers=[],
    )

    resolved = resolve_stacks(
        ["postgres"],
        {"postgres": _stack("postgres", provides={}, provisioners=[provisioner])},
    )

    assert resolved.services[0].image == "postgres:16.4-alpine"
    assert resolved.services[0].environment_names == ("TEST_DATABASE_URL",)


@pytest.mark.unit
def test_resolve_provisioners_preserves_resolution_order_and_owner() -> None:
    provisioner = StackProvisioner(
        id="postgres-verify",
        scope="verification",
        services=["postgres"],
        required_environment=["DATABASE_URL"],
        readiness_command="pg_isready",
        satisfiers=[
            StackProvisionerSatisfier(kind="environment", variable="DATABASE_URL")
        ],
    )
    definitions = {
        "application": _stack(
            "application",
            provides={"web_app.framework": "nextjs"},
            implies=["database"],
        ),
        "database": _stack(
            "database",
            provides={"data.database": "postgres"},
            provisioners=[provisioner],
        ),
    }

    resolved = resolve_stacks(["application"], definitions)

    assert [(item.owner_stack_id, item.provisioner.id) for item in resolved.provisioners] == [
        ("database", "postgres-verify")
    ]


@pytest.mark.unit
def test_conflicting_provisioner_ids_fail() -> None:
    def provisioner(readiness_command: str) -> StackProvisioner:
        return StackProvisioner(
            id="postgres-verify",
            scope="verification",
            services=["postgres"],
            required_environment=["DATABASE_URL"],
            readiness_command=readiness_command,
            satisfiers=[
                StackProvisionerSatisfier(
                    kind="environment", variable="DATABASE_URL"
                )
            ],
        )

    definitions = {
        "a": _stack(
            "a",
            provides={"data.database": "postgres"},
            provisioners=[provisioner("pg_isready")],
        ),
        "b": _stack(
            "b",
            provides={"data.migrations": "checked-in"},
            provisioners=[provisioner("pg_isready --quiet")],
        ),
    }

    with pytest.raises(StackConflictError, match="postgres-verify"):
        resolve_stacks(["a", "b"], definitions)


@pytest.mark.unit
def test_equal_provisioner_ids_preserve_each_declaring_stack() -> None:
    shared = StackProvisioner(
        id="shared",
        scope="verification",
        services=["postgres"],
        required_environment=["DATABASE_URL"],
        readiness_command="pg_isready",
        satisfiers=[
            StackProvisionerSatisfier(kind="environment", variable="DATABASE_URL")
        ],
    )
    definitions = {
        "a": _stack(
            "a",
            provides={"data.database": "postgres"},
            provisioners=[shared],
        ),
        "b": _stack(
            "b",
            provides={"data.migrations": "checked-in"},
            provisioners=[shared],
        ),
    }

    resolved = resolve_stacks(["a", "b"], definitions)

    assert [(item.owner_stack_id, item.provisioner.id) for item in resolved.provisioners] == [
        ("a", "shared"),
        ("b", "shared"),
    ]


@pytest.mark.unit
def test_resolve_implied_stack() -> None:
    definitions = {
        "stark": _stack(
            "stark",
            provides={"web_app.framework": "nextjs"},
            implies=["playbook"],
        ),
        "playbook": _stack("playbook", provides={"ui.components": "playbook"}),
    }

    resolved = resolve_stacks(["stark"], definitions, target_archetypes={"web_app"})

    assert resolved.selected_ids == ["stark"]
    assert resolved.resolved_ids == ["playbook", "stark"]
    assert resolved.implied_by == {"playbook": "stark"}
    assert resolved.capabilities["ui.components"].value == "playbook"


@pytest.mark.unit
def test_resolve_implied_stack_before_dependent_in_rendered_outputs() -> None:
    definitions = {
        "statsperform-stark-webapp": _stack(
            "statsperform-stark-webapp",
            provides={"web_app.framework": "nextjs"},
            implies=["statsperform-playbook"],
        ),
        "statsperform-playbook": _stack(
            "statsperform-playbook",
            provides={"ui.components": "playbook"},
        ),
    }

    resolved = resolve_stacks(["statsperform-stark-webapp"], definitions)
    data = resolved_to_dict(resolved)
    markdown = render_resolved_markdown(resolved)

    assert resolved.resolved_ids == [
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]
    assert data["resolved"] == [
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]
    assert markdown.index("- statsperform-playbook (implied by statsperform-stark-webapp)") < (
        markdown.index("- statsperform-stark-webapp")
    )


@pytest.mark.unit
def test_unknown_stack_fails() -> None:
    with pytest.raises(StackResolutionError, match="Unknown Echelon stack"):
        resolve_stacks(["missing"], {})


@pytest.mark.unit
def test_implication_cycle_fails() -> None:
    definitions = {
        "a": _stack("a", provides={"ui.components": "a"}, implies=["b"]),
        "b": _stack("b", provides={"ui.tokens": "b"}, implies=["a"]),
    }

    with pytest.raises(StackResolutionError, match="cycle"):
        resolve_stacks(["a"], definitions)


@pytest.mark.unit
def test_capability_conflict_fails() -> None:
    definitions = {
        "playbook": _stack("playbook", provides={"ui.components": "playbook"}),
        "mui": _stack("mui", provides={"ui.components": "mui"}),
    }

    with pytest.raises(StackConflictError, match="ui.components"):
        resolve_stacks(["playbook", "mui"], definitions)


@pytest.mark.unit
def test_tool_id_conflict_fails_when_definitions_differ() -> None:
    definitions = {
        "playbook": _stack(
            "playbook",
            provides={"ui.components": "playbook"},
            tools={
                "design-audit": StackTool(
                    id="design-audit",
                    type="cli",
                    command="playbook-audit",
                ),
            },
        ),
        "mui": _stack(
            "mui",
            provides={"ui.tokens": "mui"},
            tools={
                "design-audit": StackTool(
                    id="design-audit",
                    type="cli",
                    command="mui-audit",
                ),
            },
        ),
    }

    with pytest.raises(StackConflictError, match="design-audit"):
        resolve_stacks(["playbook", "mui"], definitions)


@pytest.mark.unit
def test_same_capability_same_value_composes() -> None:
    definitions = {
        "a": _stack("a", provides={"audit.design_system": "playbook-cli"}),
        "b": _stack("b", provides={"audit.design_system": "playbook-cli"}),
    }

    resolved = resolve_stacks(["a", "b"], definitions)

    assert resolved.capabilities["audit.design_system"].sources == ["a", "b"]


@pytest.mark.unit
def test_archetype_mismatch_fails() -> None:
    definitions = {
        "msa": _stack(
            "msa",
            provides={"service.framework": "fastapi"},
            archetypes=["service"],
        ),
    }

    with pytest.raises(StackResolutionError, match="applies to"):
        resolve_stacks(["msa"], definitions, target_archetypes={"web_app"})


@pytest.mark.unit
def test_requirements_tools_and_context_aggregate() -> None:
    definitions = {
        "playbook": _stack(
            "playbook",
            provides={"ui.components": "playbook"},
            requires_commands=["npx"],
            requires_registries=["npm"],
            context_files=["context.md", "extra.md"],
        ),
    }

    resolved = resolve_stacks(["playbook"], definitions, target_archetypes={"web_app"})
    data = resolved_to_dict(resolved)
    markdown = render_resolved_markdown(resolved)

    assert resolved.required_commands == ["npx"]
    assert resolved.required_registries == ["npm"]
    assert resolved.context_files == [
        str(Path("playbook/stack.yml").parent / "context.md"),
        str(Path("playbook/stack.yml").parent / "extra.md"),
    ]
    assert data["capabilities"]["ui.components"]["value"] == "playbook"
    assert "| ui.components | playbook | playbook |" in markdown


@pytest.mark.unit
def test_loader_rejects_project_local_duplicate_bundled_id(tmp_path: Path) -> None:
    extension_root = tmp_path / "extension"
    project_root = tmp_path / "project"

    _write_stack(extension_root, "playbook", provides={"ui.components": "playbook"})
    _write_stack(project_root / ".echelon", "playbook", provides={"ui.components": "playbook"})

    with pytest.raises(StackResolutionError, match="Duplicate Echelon stack ID"):
        load_stack_definitions(extension_root=extension_root, project_root=project_root)

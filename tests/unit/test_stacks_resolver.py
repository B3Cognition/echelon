from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from harness.stacks.errors import StackConflictError, StackResolutionError
from harness.stacks.loader import load_stack_definitions
from harness.stacks.renderer import render_resolved_markdown, resolved_to_dict
from harness.stacks.resolver import resolve_stacks
from harness.stacks.schema import StackDefinition, StackTool


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

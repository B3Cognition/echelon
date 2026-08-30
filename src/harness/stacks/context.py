"""Shared stack constraints for spec authoring and delivery prompts."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from harness.spec_frontmatter import read_frontmatter
from harness.stacks.loader import load_stack_definitions
from harness.stacks.paths import find_stack_extension_root
from harness.stacks.preflight import render_preflight_markdown, run_stack_preflight
from harness.stacks.renderer import render_resolved_markdown
from harness.stacks.resolver import resolve_stacks


def build_stack_context(
    project_root: Path,
    *,
    selected_stacks: Iterable[str],
    target_archetypes: Iterable[str] = (),
    spec_dir: Path | None = None,
) -> str:
    """Render selected stacks as a binding constraint for agent prompts.

    Stack selection is a project decision, not delivery-only information.  The
    same resolved contract therefore accompanies Phase A discovery and Phase B
    implementation.  Spec frontmatter may refine the configured archetypes
    once a spec exists.
    """
    selected = [
        str(stack).strip()
        for stack in selected_stacks
        if str(stack).strip()
    ]
    if not selected:
        return ""

    archetypes = resolve_target_archetypes(target_archetypes, spec_dir=spec_dir)
    definitions = load_stack_definitions(
        extension_root=find_stack_extension_root(project_root),
        project_root=project_root,
    )
    resolved = resolve_stacks(
        selected,
        definitions,
        target_archetypes=archetypes or None,
    )
    stack_archetypes = sorted(
        {
            archetype
            for stack_id in resolved.resolved_ids
            for archetype in definitions[stack_id].applies_to_archetypes
        }
    )
    declared_archetypes = ", ".join(sorted(archetypes)) or "not explicitly declared"
    applicable_archetypes = (
        ", ".join(stack_archetypes) or "not declared by selected stacks"
    )

    contract = "\n".join(
        [
            "## Echelon Stack Contract",
            "",
            (
                "The selected stack is an explicit project constraint. Base discovery, "
                "requirements, and architecture on its capabilities and guidance."
            ),
            (
                "Do not present an incompatible application modality as an equal default; "
                "surface a requirement conflict instead."
            ),
            f"- Declared target archetypes: {declared_archetypes}",
            f"- Selected-stack archetypes: {applicable_archetypes}",
            "",
        ]
    )
    stack_context = render_resolved_markdown(resolved)
    preflight = render_preflight_markdown(run_stack_preflight(resolved))
    return f"{contract}{stack_context.rstrip()}\n\n{preflight}"


def resolve_target_archetypes(
    configured_archetypes: Iterable[str],
    *,
    spec_dir: Path | None = None,
) -> set[str]:
    """Combine configured and spec-declared target archetypes."""
    archetypes = {
        str(archetype).strip()
        for archetype in configured_archetypes
        if str(archetype).strip()
    }
    if spec_dir is None:
        return archetypes

    frontmatter = read_frontmatter(spec_dir)
    for key in ("target_archetypes", "stack_archetypes", "archetypes"):
        raw = frontmatter.get(key)
        if isinstance(raw, list):
            archetypes.update(str(item).strip() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            archetypes.add(raw.strip())
    return archetypes

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
    runnability_schema = _render_runnability_contract_schema(resolved.runnability)
    return (
        f"{contract}{stack_context.rstrip()}"
        f"{runnability_schema}\n\n{preflight}"
    )


def _render_runnability_contract_schema(runnability: object) -> str:
    """Render the exact candidate contract shape for required delivery agents."""
    if getattr(runnability, "policy", None) != "required":
        return ""
    observations = set(getattr(runnability, "required_observations", ()))
    real_services = ["web"]
    if "postgres_query" in observations:
        real_services.extend(("api", "postgres"))
    service_list = ", ".join(real_services)
    observation_rows: list[str] = []
    persistence = ""
    if "browser_dom" in observations:
        observation_rows.extend(
            (
                "    - id: primary-view-visible",
                "      kind: browser_dom",
                "      selector: '<stable product selector>'",
                "      expectation: present",
            )
        )
    if "postgres_query" in observations:
        observation_rows.extend(
            (
                "    - id: durable-marker-present",
                "      kind: postgres_query",
                "      statement: SELECT marker FROM <table> WHERE marker = $1",
                "      parameters: ['${ECHELON_MARKER}']",
                "      expectation: one_row_exact",
            )
        )
        persistence = """
persistence_probe:
  restart_commands:
    - <command that restarts only the application boundary>
  observations:
    - primary-view-visible
    - durable-marker-present
"""
    if not observation_rows:
        observation_rows.extend(
            (
                "    - id: primary-result",
                "      kind: exec",
                "      command: <harness-observable assertion command>",
                "      expectation: exit_zero",
            )
        )
    observation_block = "\n".join(observation_rows)
    return f"""

## Candidate Runnability Contract Schema

For this required stack, create `.echelon/runnability.yml` using exactly the
schema below. Replace angle-bracket placeholders with candidate-owned commands,
requirement IDs, selectors, and SQL. Omit optional `identity` and
`persistence_probe` only when the selected stack does not need them. Do not
invent aliases such as `runtime`, `provision`, `bootstrap`, `start`, `restart`,
`observations`, or `stop`; they are not root keys. The only supported template
variables are `${{ECHELON_PORT}}`, `${{ECHELON_BASE_URL}}`, `${{ECHELON_MARKER}}`,
and `${{ECHELON_SESSION_TOKEN}}`. Echelon injects selected-stack service
environment such as `DATABASE_URL` directly into every command.

```yaml
schema_version: 1
enabled: true
install_commands:
  - <project install command>
bootstrap_commands:
  - <migration or bootstrap command>
start_commands:
  - <foreground application start command using ${{ECHELON_PORT}}>
readiness:
  url: http://127.0.0.1:${{ECHELON_PORT}}/<readiness path>
  timeout_ms: 120000
identity:  # optional; omit when the journey needs no session identity
  command: <command printing one JSON object>
  stdout_json:
    token: ECHELON_SESSION_TOKEN
primary_journey:
  kind: browser
  url: ${{ECHELON_BASE_URL}}
  requirements: [<FR-ID>]
  real_services_required: [{service_list}]
  session_storage: {{}}
  steps:
    - action: goto
      path: /
    - action: expect
      selector: '<stable product selector>'
      state: visible
  observations:
{observation_block}
{persistence.rstrip()}
stop_commands:
  - <application stop command>
```
""".rstrip()


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

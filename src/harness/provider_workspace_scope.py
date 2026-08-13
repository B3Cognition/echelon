"""Define the workspace boundary presented to dispatched AI providers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


PRODUCT_PLANE_BOUNDARY_HEADING = "## Echelon Product-Plane Boundary"

_CONTROL_PLANE_PATHS = (
    ".echelon",
    ".claude",
    ".codex",
    ".opencode",
    ".prosaic",
    ".prosaic-manifest.json",
    ".prosaic-backups",
    "CLAUDE.md",
    "AGENTS.md",
    ".github/copilot-instructions.md",
    ".github/instructions",
    ".mcp.json",
    "opencode.json",
    "opencode.jsonc",
)

_PRODUCT_PLANE_CONTRACT = f"""{PRODUCT_PLANE_BOUNDARY_HEADING}

Echelon has already embedded all selected instructions and companion material in
this prompt. Work only with product artifacts needed for the requested task.

- Never inspect, search, read, or modify Echelon or provider control-plane paths,
  including `.echelon`, provider directories, `CLAUDE.md`, `AGENTS.md`, Copilot
  instructions, MCP configuration, and OpenCode configuration.
- Do not search the workspace for agent, command, subagent, workflow, template,
  validator, or other instruction prose.
- Do not run workspace-wide `find`, `grep`, or `rg` to discover instructions.
- Treat inaccessible control-plane files as intentional. Do not retry or broaden
  the search when a control-plane read is rejected.
- You may execute explicitly named Echelon runtime helpers under
  `.echelon/runtime/scripts` only when this prompt provides the exact command.
  Never inspect or search those helper files, and never execute an unreferenced
  helper.
"""


def apply_product_plane_boundary(
    cwd: str | Path,
    prompt: str,
    request_metadata: Mapping[str, object] | None,
) -> tuple[str, dict[str, object]]:
    """Add the provider contract and merge control-plane forbidden roots."""
    root = Path(cwd).expanduser().resolve(strict=False)
    metadata = dict(request_metadata or {})
    raw_prompt_metadata = metadata.get("prompt_metadata")
    prompt_metadata = (
        dict(raw_prompt_metadata) if isinstance(raw_prompt_metadata, Mapping) else {}
    )

    existing = _normalized_paths(
        root,
        prompt_metadata.get("tool_forbidden_roots"),
    )
    defaults = tuple(
        str((root / relative).resolve(strict=False))
        for relative in _CONTROL_PLANE_PATHS
    )
    prompt_metadata["tool_forbidden_roots"] = list(
        dict.fromkeys((*existing, *defaults))
    )
    prompt_metadata["tool_operational_roots"] = [
        str((root / ".echelon/runtime/scripts").resolve(strict=False))
    ]
    prompt_metadata["tool_operational_read_paths"] = [
        str((root / ".echelon/config.yml").resolve(strict=False)),
        str((root / ".echelon/local.yml").resolve(strict=False)),
    ]
    prompt_metadata["tool_operational_metadata_paths"] = [
        str((root / ".echelon").resolve(strict=False))
    ]
    prompt_metadata["product_plane_boundary"] = "echelon-v1"
    metadata["prompt_metadata"] = prompt_metadata

    if PRODUCT_PLANE_BOUNDARY_HEADING not in prompt:
        prompt = f"{_PRODUCT_PLANE_CONTRACT}\n{prompt}"
    return prompt, metadata


def _normalized_paths(root: Path, raw_paths: object) -> tuple[str, ...]:
    if not isinstance(raw_paths, (list, tuple)):
        return ()
    paths: list[str] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        paths.append(str(candidate.resolve(strict=False)))
    return tuple(paths)

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is present in test env
    yaml = None  # type: ignore[assignment]

from harness.stacks.errors import StackResolutionError, StackValidationError
from harness.stacks.schema import StackDefinition, parse_stack_definition

STACK_FILENAME = "stack.yml"


def load_stack_definitions(
    extension_root: Path,
    project_root: Path | None = None,
) -> dict[str, StackDefinition]:
    """Load bundled and project-local stack definitions."""
    definitions: dict[str, StackDefinition] = {}
    _load_stack_tree(extension_root / "stacks", definitions)
    if project_root is not None:
        _load_stack_tree(project_root / ".echelon" / "stacks", definitions)
    return definitions


def _load_stack_tree(root: Path, definitions: dict[str, StackDefinition]) -> None:
    if not root.exists():
        return
    for stack_path in sorted(root.glob(f"*/{STACK_FILENAME}")):
        stack = _load_stack_file(stack_path)
        if stack.id in definitions:
            raise StackResolutionError(f"Duplicate Echelon stack ID: {stack.id}")
        definitions[stack.id] = stack


def _load_stack_file(path: Path) -> StackDefinition:
    if yaml is None:
        raise StackValidationError("PyYAML is required for stack loading", path=path)
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exercised only on invalid YAML
        raise StackValidationError(
            f"Could not read stack definition: {exc}",
            path=path,
        ) from exc
    if raw is None:
        raw = {}
    return parse_stack_definition(raw, path)

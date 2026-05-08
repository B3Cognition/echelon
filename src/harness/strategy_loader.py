"""Strategy file loader -- load strategy .md files from disk.

Per T038 / FR-STRATEGY-002:
  load_strategies(spec_id, strategy_ids) -> dict[str, StrategySpec]
  Default strategy with no file returns StrategySpec with defaults.
  Missing non-default strategy raises with available file list.

Strategy files may declare a build command override via YAML frontmatter:

  ---
  command: echelon codegen
  ---
  # rest of file is strategy context

If no frontmatter is present, build_command defaults to "echelon build".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

DEFAULT_BUILD_COMMAND = "echelon build"


class StrategyNotFoundError(Exception):
    """Raised when a strategy file is not found."""


@dataclass
class StrategySpec:
    """Parsed strategy file: build command + context text."""

    build_command: str = DEFAULT_BUILD_COMMAND
    context: str = ""


# Built-in strategies that don't require a file on disk.
# A per-spec file always wins if present (allows context/override).
BUILTIN_STRATEGIES: Dict[str, StrategySpec] = {
    "default": StrategySpec(build_command="echelon build"),
    "codegen": StrategySpec(build_command="echelon codegen"),
}


def load_strategies(
    spec_id: str,
    strategy_ids: List[str],
    base_dir: str = ".specify/extensions/echelon/harness/strategies",
) -> Dict[str, StrategySpec]:
    """Load strategy definition files from disk.

    Args:
        spec_id: Spec identifier.
        strategy_ids: List of strategy IDs to load.
        base_dir: Base directory for strategy files.

    Returns:
        Dict of strategy_id -> StrategySpec.

    Raises:
        StrategyNotFoundError: If a non-default strategy file is missing.
    """
    strategies_dir = Path(base_dir) / spec_id
    result: Dict[str, StrategySpec] = {}

    for sid in strategy_ids:
        filepath = strategies_dir / f"{sid}.md"

        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            spec = _parse_strategy(content)
            result[sid] = spec
            logger.info(
                "Loaded strategy '%s' from %s (command: %s)",
                sid, filepath, spec.build_command,
            )
        elif sid in BUILTIN_STRATEGIES:
            result[sid] = BUILTIN_STRATEGIES[sid]
            logger.info(
                "Using built-in strategy '%s' (command: %s, no context file)",
                sid, BUILTIN_STRATEGIES[sid].build_command,
            )
        else:
            available = _list_available(strategies_dir)
            builtin_names = sorted(BUILTIN_STRATEGIES)
            raise StrategyNotFoundError(
                f"Strategy file not found: {filepath}. "
                f"Available on disk: {available or 'none'}. "
                f"Built-in strategies (no file needed): {builtin_names}"
            )

    return result


def _parse_strategy(content: str) -> StrategySpec:
    """Parse optional YAML frontmatter from strategy file content.

    Frontmatter format::

        ---
        command: echelon codegen
        ---
        rest of file is context

    Only the ``command`` key is recognized. All other keys are ignored.
    If no frontmatter is present, defaults are used.
    """
    if not content.startswith("---"):
        return StrategySpec(context=content)

    # Find closing ---
    close = content.find("\n---", 3)
    if close == -1:
        return StrategySpec(context=content)

    frontmatter = content[3:close].strip()
    rest = content[close + 4:].lstrip("\n")

    build_command = DEFAULT_BUILD_COMMAND
    for line in frontmatter.splitlines():
        line = line.strip()
        if line.startswith("command:"):
            value = line[len("command:"):].strip()
            if value:
                build_command = value
            break

    return StrategySpec(build_command=build_command, context=rest)


def _list_available(directory: Path) -> List[str]:
    """List available strategy files in directory."""
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))

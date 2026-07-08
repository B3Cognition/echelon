"""MemPalaceContext — single source of truth for wing, run_id, and palace_path."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _get_palace_path() -> str:
    """Resolve MemPalace palace path: env var → mempalace config → default."""
    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        return MempalaceConfig().palace_path
    except ImportError:
        return os.path.expanduser("~/.mempalace/palace")


def _read_wing_from_echelon_yml(project_dir: Path) -> str:
    """Read mempalace.wing from the project config. Hard-exits with clear message if absent."""
    echelon_yml = project_dir / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not echelon_yml.exists():
        sys.exit(
            f"echelon-config.yml not found at {echelon_yml}.\n"
            "Run 'specify extension add echelon' then 'echelon workspace init' to initialize this project."
        )
    try:
        import yaml  # type: ignore[import]
        config = yaml.safe_load(echelon_yml.read_text()) or {}
    except Exception as exc:
        sys.exit(f"Cannot parse echelon-config.yml: {exc}")

    wing = config.get("mempalace", {}).get("wing", "")
    if not wing:
        sys.exit(
            "wing not set in echelon-config.yml — run 'echelon workspace init' to configure it.\n"
            "  Expected:\n"
            "    mempalace:\n"
            "      wing: <your-project-name>"
        )
    return wing


@dataclass(frozen=True)
class MemPalaceContext:
    """Immutable per-run memory context. Single source of truth for wing/run_id/palace_path."""
    wing: str
    run_id: str
    palace_path: str

    @classmethod
    def from_project(
        cls,
        project_dir: Path,
        run_id: str,
        wing_override: Optional[str] = None,
    ) -> "MemPalaceContext":
        """Build context from echelon-config.yml. wing_override (--wing CLI arg) takes precedence."""
        wing = wing_override if wing_override is not None else _read_wing_from_echelon_yml(project_dir)
        return cls(wing=wing, run_id=run_id, palace_path=_get_palace_path())

    @classmethod
    def from_wing(cls, wing: str, run_id: str) -> "MemPalaceContext":
        """Build context when wing is already known (e.g. read from codegen-state.json)."""
        return cls(wing=wing, run_id=run_id, palace_path=_get_palace_path())

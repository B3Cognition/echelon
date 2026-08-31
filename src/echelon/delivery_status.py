"""Delivery-status command boundary for the Typer CLI."""

from __future__ import annotations

from pathlib import Path


def command(args: list[str], project_root: Path | None = None) -> None:
    """Render status for one or more Phase B delivery runs.

    The legacy parser remains supported temporarily through its existing shim;
    Typer enters through this boundary so status can be migrated independently.
    """
    from echelon.cli import _cmd_delivery_status

    _cmd_delivery_status(args, project_root=project_root)

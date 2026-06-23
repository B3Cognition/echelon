"""The runnable_contract — RE's machine-checkable declaration of what "runs"
means for a codegen project. Executed by the RUNNABLE phase; never authored by
the gate. See docs/superpowers/specs/2026-06-22-codegen-runnable-composition-gate-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

VALID_KINDS = ("spa", "service", "cli", "library")
DEFAULT_PROBE = {"spa": "browser", "service": "http", "cli": "exec", "library": "exec"}


@dataclass(frozen=True)
class RunnableContract:
    kind: str
    build: str
    liveness: str
    primary_surface: dict[str, str]
    probe: str
    start: Optional[str] = None
    surfaces: list[dict[str, str]] = field(default_factory=list)


def _require_surface(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or "req" not in value or "assert" not in value:
        raise ValueError(f"{label} must be a mapping with 'req' and 'assert' keys")
    return {"req": str(value["req"]), "assert": str(value["assert"])}


def parse_runnable_contract(data: dict[str, Any]) -> RunnableContract:
    """Validate and construct a RunnableContract. Raises ValueError naming the
    offending field on any violation (fail-closed at authoring time)."""
    if not isinstance(data, dict):
        raise ValueError("runnable_contract must be a mapping")

    kind = str(data.get("kind", ""))
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}; got {kind!r}")

    for required in ("build", "liveness", "primary_surface"):
        if not data.get(required):
            raise ValueError(f"runnable_contract missing required field: {required}")

    primary = _require_surface(data["primary_surface"], "primary_surface")
    surfaces = [_require_surface(s, "surfaces[]") for s in data.get("surfaces", []) or []]

    probe = str(data.get("probe") or DEFAULT_PROBE[kind])
    if probe not in ("browser", "http", "exec"):
        raise ValueError(f"probe must be browser|http|exec; got {probe!r}")

    return RunnableContract(
        kind=kind,
        build=str(data["build"]),
        liveness=str(data["liveness"]),
        primary_surface=primary,
        probe=probe,
        start=(str(data["start"]) if data.get("start") else None),
        surfaces=surfaces,
    )

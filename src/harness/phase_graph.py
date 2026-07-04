"""PhaseGraph — loads workflow/definition.yaml into typed PhaseNode objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class PhaseNode:
    id: str
    type: str                          # agent | staged_parallel | commander_internal | ...
    label: str = ""
    spec_file: Optional[str] = None
    agent: Optional[str] = None        # dash-notation dispatch id
    agents: list = field(default_factory=list)
    context_pack: list = field(default_factory=list)
    pre_dispatch: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    condition: Optional[str] = None
    on_greenfield: dict = field(default_factory=dict)
    allowed_state_updates: Optional[list] = None
    transitions: list = field(default_factory=list)


class PhaseGraph:
    """Loads the main squad phases from definition.yaml.

    Also reads extension.yml to map agent dispatch ids to file paths.
    """

    def __init__(self, definition_path: Path, extension_yml_path: Path) -> None:
        raw = yaml.safe_load(definition_path.read_text())
        self._phases: dict[str, PhaseNode] = {}
        for p in raw.get("phases", []):
            node = PhaseNode(
                id=p["id"],
                type=p.get("type", "agent"),
                label=p.get("label", ""),
                spec_file=p.get("spec_file"),
                agent=p.get("agent"),
                agents=p.get("agents", []),
                context_pack=p.get("context_pack", []),
                pre_dispatch=p.get("pre_dispatch", []),
                outputs=p.get("outputs", []),
                condition=p.get("condition"),
                on_greenfield=p.get("on_greenfield", {}),
                allowed_state_updates=(
                    p.get("allowed_state_updates")
                    if "allowed_state_updates" in p
                    else None
                ),
                transitions=p.get("transitions", []),
            )
            self._phases[node.id] = node

        # Build dispatch-id → file path map from extension.yml
        self._agent_files: dict[str, str] = {}
        ext = yaml.safe_load(extension_yml_path.read_text())
        for cmd in ext.get("provides", {}).get("commands", []):
            if cmd.get("behavior", {}).get("execution") == "agent":
                # "speckit.echelon.scout" → "speckit-echelon-scout"
                dispatch_id = cmd["name"].replace(".", "-")
                self._agent_files[dispatch_id] = cmd["file"]

    def get(self, phase_id: str) -> PhaseNode:
        if phase_id not in self._phases:
            raise KeyError(f"Phase not found in definition.yaml: {phase_id!r}")
        return self._phases[phase_id]

    def entry_phase(self) -> str:
        return next(iter(self._phases))

    def all_phase_ids(self) -> list[str]:
        return list(self._phases.keys())

    def agent_file(self, dispatch_id: str) -> Optional[str]:
        """Return the relative file path for an agent dispatch id, or None."""
        return self._agent_files.get(dispatch_id)

    def all_conditions(self) -> set[str]:
        """Return all unique condition strings across all transitions."""
        return {
            t.get("condition", "")
            for node in self._phases.values()
            for t in node.transitions
        }

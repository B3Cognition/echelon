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
    understanding_target: Optional[str] = None
    timing_window_start: Optional[str] = None
    budget_seconds: Optional[float] = None
    timing_window_transition: dict = field(default_factory=dict)
    agents: list = field(default_factory=list)
    context_pack: list = field(default_factory=list)
    pre_dispatch: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    condition: Optional[str] = None
    on_greenfield: dict = field(default_factory=dict)
    allowed_state_updates: Optional[list] = None
    controller_state_updates: list = field(default_factory=list)
    required_state_updates: list = field(default_factory=list)
    state_update_types: dict = field(default_factory=dict)
    state_update_enums: dict = field(default_factory=dict)
    allowed_verdicts: Optional[list] = None
    unexpected_state_updates: str = "quarantine"
    transitions: list = field(default_factory=list)

    def result_contract(self, agent_entry: dict | None = None):
        """Build the immutable result contract for one concrete dispatch."""
        from harness.echelon_result_schema import EchelonResultContract

        entry = agent_entry or {}
        allowed = entry.get("allowed_state_updates", self.allowed_state_updates)
        required = entry.get("required_state_updates", self.required_state_updates)
        value_types = entry.get("state_update_types", self.state_update_types)
        value_enums = entry.get("state_update_enums", self.state_update_enums)
        verdicts = entry.get("allowed_verdicts", self.allowed_verdicts)
        unexpected = entry.get(
            "unexpected_state_updates", self.unexpected_state_updates
        )
        return EchelonResultContract(
            allowed_state_update_keys=(
                frozenset(str(key) for key in allowed)
                if allowed is not None
                else None
            ),
            required_state_update_keys=frozenset(str(key) for key in (required or [])),
            state_update_types={
                str(key): str(value_type)
                for key, value_type in (value_types or {}).items()
            },
            state_update_enums={
                str(key): frozenset(values)
                for key, values in (value_enums or {}).items()
            },
            allowed_verdicts=(
                frozenset(str(verdict) for verdict in verdicts)
                if verdicts is not None
                else None
            ),
            unexpected_state_updates=str(unexpected),
        )


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
                understanding_target=p.get("understanding_target"),
                timing_window_start=p.get("timing_window_start"),
                budget_seconds=p.get("budget_seconds"),
                timing_window_transition=p.get("timing_window_transition", {}),
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
                controller_state_updates=p.get("controller_state_updates", []),
                required_state_updates=p.get("required_state_updates", []),
                state_update_types=p.get("state_update_types", {}),
                state_update_enums=p.get("state_update_enums", {}),
                allowed_verdicts=(
                    p.get("allowed_verdicts")
                    if "allowed_verdicts" in p
                    else None
                ),
                unexpected_state_updates=p.get(
                    "unexpected_state_updates", "quarantine"
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

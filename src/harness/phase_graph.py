"""PhaseGraph — loads workflow/definition.yaml into typed PhaseNode objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from harness.controller_state_contracts import (
    CompiledControllerStateContract,
    ControllerContractRegistryError,
    load_controller_state_contracts,
)
from harness.controller_state_contract_requirements import (
    is_controller_producing_phase,
    required_controller_contract_name,
)


def _validate_controller_provider_allowlist(
    *,
    phase_id: object,
    allowed: object,
    contract: CompiledControllerStateContract,
    nested: bool = False,
) -> None:
    boundary = "nested controller boundary" if nested else "controller boundary"
    if type(allowed) is not list:
        raise ControllerContractRegistryError(
            f"phase {phase_id!r} {boundary} requires "
            "allowed_state_updates to be a list"
        )
    if not all(isinstance(key, str) and key for key in allowed):
        raise ControllerContractRegistryError(
            f"phase {phase_id!r} {boundary} requires "
            "allowed_state_updates to contain only non-empty strings"
        )
    overlap = contract.state_update_keys.intersection(allowed)
    if overlap:
        raise ControllerContractRegistryError(
            f"phase {phase_id!r} {boundary}: controller state contract "
            "must not overlap allowed_state_updates: "
            f"{', '.join(sorted(overlap))}"
        )


@dataclass
class PhaseNode:
    id: str
    type: str                          # agent | staged_parallel | commander_internal | ...
    label: str = ""
    spec_file: Optional[str] = None
    agent: Optional[str] = None        # dash-notation dispatch id
    understanding_target: Optional[str] = None
    lexicon_artifact: Optional[str] = None
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
    controller_state_contract: CompiledControllerStateContract | None = None
    required_state_updates: list = field(default_factory=list)
    state_update_types: dict = field(default_factory=dict)
    state_update_enums: dict = field(default_factory=dict)
    allowed_verdicts: Optional[list] = None
    unexpected_state_updates: str = "quarantine"
    evidence_routing: str = "none"
    transitions: list = field(default_factory=list)

    @property
    def controller_state_update_keys(self) -> frozenset[str]:
        contract = self.controller_state_contract
        return contract.state_update_keys if contract is not None else frozenset()

    def result_contract(self, agent_entry: dict | None = None):
        """Build the immutable result contract for one concrete dispatch."""
        from harness.echelon_result_schema import EchelonResultContract

        entry = agent_entry or {}
        allowed = entry.get("allowed_state_updates", self.allowed_state_updates)
        if self.controller_state_contract is not None:
            _validate_controller_provider_allowlist(
                phase_id=self.id,
                allowed=allowed,
                contract=self.controller_state_contract,
                nested=agent_entry is not None,
            )
        required = entry.get("required_state_updates", self.required_state_updates)
        value_types = entry.get("state_update_types", self.state_update_types)
        value_enums = entry.get("state_update_enums", self.state_update_enums)
        verdicts = entry.get("allowed_verdicts", self.allowed_verdicts)
        unexpected = entry.get(
            "unexpected_state_updates", self.unexpected_state_updates
        )
        evidence_routing = entry.get("evidence_routing", self.evidence_routing)
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
            evidence_routing=str(evidence_routing),
        )


class PhaseGraph:
    """Loads the main squad phases from definition.yaml.

    Also reads extension.yml to map agent dispatch ids to file paths.
    """

    def __init__(self, definition_path: Path, extension_yml_path: Path) -> None:
        raw = yaml.safe_load(definition_path.read_text())
        if not isinstance(raw, dict):
            raise ControllerContractRegistryError(
                "workflow definition must be a mapping"
            )
        raw_phases = raw.get("phases", [])
        phases = raw_phases if isinstance(raw_phases, list) else []
        controller_producers = [
            phase
            for phase in phases
            if isinstance(phase, dict)
            and is_controller_producing_phase(phase)
        ]
        contracts_file = raw.get("controller_state_contracts_file")
        if contracts_file is None:
            if controller_producers:
                raise ControllerContractRegistryError(
                    "controller-producing phases require "
                    "controller_state_contracts_file"
                )
            self._controller_contracts = {}
        elif not isinstance(contracts_file, str) or not contracts_file.strip():
            raise ControllerContractRegistryError(
                "controller_state_contracts_file must be a non-empty path"
            )
        else:
            self._controller_contracts = load_controller_state_contracts(
                definition_path.parent / contracts_file
            )
        self._phases: dict[str, PhaseNode] = {}
        for p in phases:
            expected_contract = required_controller_contract_name(p)
            contract_name = p.get("controller_state_contract")
            if is_controller_producing_phase(p):
                if expected_contract is None:
                    raise ControllerContractRegistryError(
                        f"controller-producing phase {p.get('id')!r} has an "
                        "unsupported role/type"
                    )
                if contract_name != expected_contract:
                    raise ControllerContractRegistryError(
                        f"phase {p.get('id')!r} requires controller state "
                        f"contract {expected_contract!r}; got "
                        f"{contract_name!r}"
                    )
            if contract_name is None:
                contract = None
            elif not isinstance(contract_name, str) or not contract_name.strip():
                raise ControllerContractRegistryError(
                    f"phase {p.get('id')!r} has an invalid controller state "
                    "contract reference"
                )
            else:
                contract = self._controller_contracts.get(contract_name)
                if contract is None:
                    raise ControllerContractRegistryError(
                        f"unknown controller state contract {contract_name!r} "
                        f"referenced by phase {p.get('id')!r}"
                    )
            if contract is not None:
                _validate_controller_provider_allowlist(
                    phase_id=p.get("id"),
                    allowed=p.get("allowed_state_updates"),
                    contract=contract,
                )
                for nested_name in ("agents", "pre_dispatch"):
                    nested_entries = p.get(nested_name, [])
                    if not isinstance(nested_entries, list):
                        continue
                    for entry in nested_entries:
                        if isinstance(entry, dict):
                            _validate_controller_provider_allowlist(
                                phase_id=p.get("id"),
                                allowed=entry.get(
                                    "allowed_state_updates",
                                    p.get("allowed_state_updates"),
                                ),
                                contract=contract,
                                nested=True,
                            )
            node = PhaseNode(
                id=p["id"],
                type=p.get("type", "agent"),
                label=p.get("label", ""),
                spec_file=p.get("spec_file"),
                agent=p.get("agent"),
                understanding_target=p.get("understanding_target"),
                lexicon_artifact=p.get("lexicon_artifact"),
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
                controller_state_contract=contract,
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
                evidence_routing=p.get("evidence_routing", "none"),
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

    def controller_contract(self, name: str) -> CompiledControllerStateContract:
        contract = self._controller_contracts.get(name)
        if contract is None:
            raise ControllerContractRegistryError(
                f"unknown controller state contract {name!r}"
            )
        return contract

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

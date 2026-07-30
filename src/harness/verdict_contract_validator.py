"""Static validation for workflow/prompt verdict contract drift."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class VerdictContractFinding:
    path: Path
    line: int
    phase_id: str
    reason: str
    details: str


def validate_verdict_contracts(repo_root: Path) -> list[VerdictContractFinding]:
    """Validate explicit routing verdict contracts against workflow and prompts."""
    extension_root = repo_root / "extension"
    definition = yaml.safe_load(
        (extension_root / "workflow/definition.yaml").read_text(encoding="utf-8")
    )
    extension_yml = yaml.safe_load(
        (extension_root / "extension.yml").read_text(encoding="utf-8")
    )
    agent_registry = _agent_registry(extension_yml)

    findings: list[VerdictContractFinding] = []
    for phase in definition.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        spec_file = phase.get("spec_file")
        if not isinstance(spec_file, str):
            continue
        spec_path = extension_root / spec_file
        contract = _phase_contract(spec_path)
        if contract is None:
            continue

        phase_id = str(phase.get("id") or spec_file)
        allowed = contract.canonical | contract.legacy
        workflow_values = _workflow_verdict_values(phase.get("transitions") or [])
        declared_verdicts = phase.get("allowed_verdicts")
        if isinstance(declared_verdicts, list):
            workflow_values.update(
                verdict
                for verdict in declared_verdicts
                if isinstance(verdict, str)
            )
        unexpected = sorted(workflow_values - allowed)
        if unexpected:
            findings.append(
                VerdictContractFinding(
                    path=extension_root / "workflow/definition.yaml",
                    line=1,
                    phase_id=phase_id,
                    reason="workflow_unexpected_verdict",
                    details=", ".join(unexpected),
                )
            )

        missing = sorted(contract.canonical - workflow_values)
        if missing:
            findings.append(
                VerdictContractFinding(
                    path=extension_root / "workflow/definition.yaml",
                    line=1,
                    phase_id=phase_id,
                    reason="workflow_missing_canonical_verdict",
                    details=", ".join(missing),
                )
            )

        for prompt_path in _related_prompt_paths(extension_root, phase, spec_path, agent_registry):
            findings.extend(_prompt_findings(prompt_path, phase_id, contract))

    return findings


@dataclass(frozen=True)
class _VerdictContract:
    canonical: set[str]
    legacy: set[str]


def _phase_contract(spec_path: Path) -> _VerdictContract | None:
    text = spec_path.read_text(encoding="utf-8")
    if "Routing Verdict Contract" not in text:
        return None

    canonical: set[str] = set()
    legacy: set[str] = set()
    in_contract = False
    for line in text.splitlines():
        if "Routing Verdict Contract" in line:
            in_contract = True
            continue
        if in_contract:
            if line.startswith("### ") and "Routing Verdict Contract" not in line:
                break
            if re.match(r"\s*-\s+`[A-Z][A-Z0-9_]+`", line):
                canonical.update(_backtick_verdicts(line))
            if "legacy" in line.lower():
                legacy.update(_backtick_verdicts(line))

    if not canonical:
        return None
    return _VerdictContract(canonical=canonical, legacy=legacy)


def _workflow_verdict_values(transitions: Iterable[Any]) -> set[str]:
    values: set[str] = set()
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        condition = transition.get("condition")
        if isinstance(condition, str):
            values.update(_condition_verdict_values(condition))
    return values


def _condition_verdict_values(condition: str) -> set[str]:
    values = set(re.findall(r"\bverdict\s*=\s*([A-Z][A-Z0-9_]*)", condition))
    for match in re.finditer(r"\bverdict\s+in\s+\[([^\]]+)\]", condition):
        values.update(
            value.strip()
            for value in match.group(1).split(",")
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", value.strip())
        )
    return values


def _related_prompt_paths(
    extension_root: Path,
    phase: dict[str, Any],
    spec_path: Path,
    agent_registry: dict[str, Path],
) -> list[Path]:
    paths: list[Path] = []
    agent_id = phase.get("agent")
    if isinstance(agent_id, str):
        agent_path = agent_registry.get(_manifest_agent_name(agent_id))
        if agent_path is not None:
            paths.append(extension_root / agent_path)

    text = spec_path.read_text(encoding="utf-8")
    for rel in re.findall(r"extension/(templates/[^\s`,)]+\.md)", text):
        paths.append(extension_root / rel)
    return [path for path in paths if path.exists()]


def _agent_registry(extension_yml: dict[str, Any]) -> dict[str, Path]:
    registry: dict[str, Path] = {}
    commands = (extension_yml.get("provides") or {}).get("commands") or []
    for command in commands:
        if not isinstance(command, dict):
            continue
        name = command.get("name")
        file_ref = command.get("file")
        if isinstance(name, str) and isinstance(file_ref, str):
            registry[name] = Path(file_ref)
    return registry


def _manifest_agent_name(agent_id: str) -> str:
    if agent_id.startswith("speckit-echelon-"):
        return "speckit.echelon." + agent_id.removeprefix("speckit-echelon-")
    return agent_id.replace("-", ".")


def _prompt_findings(
    path: Path,
    phase_id: str,
    contract: _VerdictContract,
) -> list[VerdictContractFinding]:
    findings: list[VerdictContractFinding] = []
    values_of_interest = contract.canonical | contract.legacy
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        lowered = line.lower()
        if not _is_verdict_contract_line(lowered):
            continue
        for values in _verdict_sets(line):
            if not values & values_of_interest:
                continue
            if values == contract.canonical:
                continue
            if "legacy" in lowered and values <= contract.legacy:
                continue
            findings.append(
                VerdictContractFinding(
                    path=path,
                    line=line_no,
                    phase_id=phase_id,
                    reason="prompt_verdict_contract_drift",
                    details=(
                        f"found {', '.join(sorted(values))}; expected canonical "
                        f"{', '.join(sorted(contract.canonical))}"
                    ),
                )
            )
    return findings


def _is_verdict_contract_line(lowered: str) -> bool:
    return any(
        marker in lowered
        for marker in (
            "verdict:",
            "echelon_result.verdict",
            "missing-verdict",
            "verdict values",
            "verdict =",
            "<verdict",
        )
    )


def _verdict_sets(line: str) -> list[set[str]]:
    sets: list[set[str]] = []
    for raw in re.findall(r"[A-Z][A-Z0-9_]+(?:\s*(?:/|\|)\s*[A-Z][A-Z0-9_]+)+", line):
        values = set(re.findall(r"[A-Z][A-Z0-9_]+", raw))
        if len(values) > 1:
            sets.append(values)
    return sets


def _backtick_verdicts(line: str) -> set[str]:
    return set(re.findall(r"`([A-Z][A-Z0-9_]*)`", line))

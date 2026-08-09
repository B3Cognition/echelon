"""Deterministic validation for routed squad role contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from harness.phase_graph import PhaseGraph


REQUIRED_ECHELON_RESULT_FIELDS = (
    "verdict",
    "output_files",
    "state_updates",
    "journal_entries",
)


@dataclass(frozen=True)
class RoleContractIssue:
    """A machine-checkable role contract problem."""

    message: str
    phase_id: str | None = None
    agent: str | None = None
    path: str | None = None


@dataclass
class RoleContractReport:
    """Validation report for all routed role contracts."""

    issues: list[RoleContractIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def format(self) -> str:
        if self.ok:
            return "role contracts valid"
        lines = ["role contract validation failed:"]
        for issue in self.issues:
            where = " ".join(
                part
                for part in [
                    issue.phase_id or "",
                    issue.agent or "",
                    issue.path or "",
                ]
                if part
            )
            lines.append(f"- {where}: {issue.message}".rstrip())
        return "\n".join(lines)


def validate_agent_result_contract(
    markdown: str,
    *,
    path: str | None = None,
    phase_id: str | None = None,
    agent: str | None = None,
) -> list[RoleContractIssue]:
    """Validate that an agent prompt declares a usable final echelon_result shape."""
    blocks = _echelon_result_blocks(markdown)
    if not blocks:
        return [
            RoleContractIssue(
                "missing echelon_result block",
                phase_id=phase_id,
                agent=agent,
                path=path,
            )
        ]

    missing_sets = [_missing_required_fields(block) for block in blocks]
    if any(not missing for missing in missing_sets):
        return []

    missing = sorted(min(missing_sets, key=len))
    return [
        RoleContractIssue(
            f"echelon_result contract missing required field: {field}",
            phase_id=phase_id,
            agent=agent,
            path=path,
        )
        for field in missing
    ]


def validate_role_contracts(
    *,
    definition_path: Path,
    prosaic_subagents_dir: Path,
) -> RoleContractReport:
    """Validate routed agents in workflow/definition.yaml against prompt contracts."""
    graph = PhaseGraph(definition_path, prosaic_subagents_dir=prosaic_subagents_dir)
    issues: list[RoleContractIssue] = []

    seen: set[tuple[str, str]] = set()
    for phase_id, agent, outputs, allowed_state_updates in _routed_agents(graph):
        if not outputs:
            issues.append(
                RoleContractIssue(
                    "routed role has no declared outputs",
                    phase_id=phase_id,
                    agent=agent,
                )
            )
        if allowed_state_updates is None:
            issues.append(
                RoleContractIssue(
                    "routed role has no declared state_updates allowlist",
                    phase_id=phase_id,
                    agent=agent,
                )
            )
        elif (
            not isinstance(allowed_state_updates, list)
            or any(not isinstance(key, str) for key in allowed_state_updates)
        ):
            issues.append(
                RoleContractIssue(
                    "routed role state_updates allowlist must be a list of strings",
                    phase_id=phase_id,
                    agent=agent,
                )
            )

        if (phase_id, agent) in seen:
            continue
        seen.add((phase_id, agent))

        rel = graph.agent_file(agent)
        if rel is None:
            issues.append(
                RoleContractIssue(
                    "routed agent is not registered in Prosaic subagents",
                    phase_id=phase_id,
                    agent=agent,
                )
            )
            continue

        path = Path(rel)
        if not path.exists():
            issues.append(
                RoleContractIssue(
                    "registered Prosaic agent file does not exist",
                    phase_id=phase_id,
                    agent=agent,
                    path=str(path),
                )
            )
            continue

        issues.extend(
            validate_agent_result_contract(
                path.read_text(encoding="utf-8"),
                path=str(path),
                phase_id=phase_id,
                agent=agent,
            )
        )

    return RoleContractReport(issues=issues)


def _routed_agents(graph: PhaseGraph) -> list[tuple[str, str, list, list | None]]:
    routed: list[tuple[str, str, list, list | None]] = []
    for phase_id in graph.all_phase_ids():
        node = graph.get(phase_id)
        if node.agent:
            routed.append(
                (phase_id, node.agent, node.outputs, node.allowed_state_updates)
            )
        for entry in node.agents:
            if isinstance(entry, dict):
                agent = entry.get("id")
                if isinstance(agent, str) and agent.strip():
                    routed.append(
                        (
                            phase_id,
                            agent,
                            entry.get("outputs", []),
                            entry.get(
                                "allowed_state_updates",
                                node.allowed_state_updates,
                            ),
                        )
                    )
            elif isinstance(entry, str) and entry.strip():
                routed.append(
                    (phase_id, entry, [], node.allowed_state_updates)
                )
    return routed


def _echelon_result_blocks(markdown: str) -> list[str]:
    matches = list(re.finditer(r"(?m)^echelon_result:\s*$", markdown))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        blocks.append(markdown[match.start():end])
    return blocks


def _missing_required_fields(block: str) -> set[str]:
    missing: set[str] = set()
    for field in REQUIRED_ECHELON_RESULT_FIELDS:
        if not re.search(rf"(?m)^\s{{2}}{re.escape(field)}\s*:", block):
            missing.add(field)
    return missing

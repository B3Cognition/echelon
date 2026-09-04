from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Iterable

from harness.stacks.errors import StackConflictError, StackResolutionError
from harness.stacks.schema import (
    StackDefinition,
    StackProvisioner,
    StackRunnability,
    StackTool,
)
from harness.verification_plan import SandboxServiceSpec


@dataclass(frozen=True)
class ResolvedCapability:
    value: str
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedStackProvisioner:
    owner_stack_id: str
    provisioner: StackProvisioner


@dataclass(frozen=True)
class ResolvedRunnability:
    classification: str = "non_runnable"
    policy: str = "not_applicable"
    runner: str | None = None
    capabilities: tuple[str, ...] = ()
    required_observations: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedStacks:
    selected_ids: list[str]
    resolved_ids: list[str]
    implied_by: dict[str, str]
    capabilities: dict[str, ResolvedCapability]
    tools: dict[str, StackTool]
    required_commands: list[str]
    required_registries: list[str]
    context_files: list[str]
    provisioners: list[ResolvedStackProvisioner] = field(default_factory=list)
    services: list[SandboxServiceSpec] = field(default_factory=list)
    runnability: ResolvedRunnability = field(default_factory=ResolvedRunnability)


def resolve_stacks(
    selected_ids: list[str],
    definitions: dict[str, StackDefinition],
    target_archetypes: set[str] | None = None,
) -> ResolvedStacks:
    if not selected_ids:
        return ResolvedStacks(
            selected_ids=[],
            resolved_ids=[],
            implied_by={},
            capabilities={},
            tools={},
            required_commands=[],
            required_registries=[],
            context_files=[],
            provisioners=[],
            services=[],
            runnability=ResolvedRunnability(),
        )

    normalized_selected = _normalize_stack_ids(selected_ids)
    selected_set = set(normalized_selected)

    for stack_id in normalized_selected:
        if stack_id not in definitions:
            available = ", ".join(sorted(definitions)) or "none"
            raise StackResolutionError(
                f"Unknown Echelon stack: {stack_id}. Available stacks: {available}"
            )

    resolved_ids: list[str] = []
    resolved_seen: set[str] = set()
    visiting: set[str] = set()
    implied_by: dict[str, str] = {}

    def visit(stack_id: str, parent: str | None = None) -> None:
        if stack_id in visiting:
            raise StackResolutionError(
                f"Stack implication cycle detected at {stack_id}"
            )
        if stack_id in resolved_seen:
            return
        if stack_id not in definitions:
            available = ", ".join(sorted(definitions)) or "none"
            raise StackResolutionError(
                f"Unknown Echelon stack: {stack_id}. Available stacks: {available}"
            )

        visiting.add(stack_id)
        try:
            stack = definitions[stack_id]
            if parent is not None and stack_id not in selected_set:
                implied_by.setdefault(stack_id, parent)

            for implied_id in stack.implies:
                visit(implied_id, stack_id)

            resolved_ids.append(stack_id)
            resolved_seen.add(stack_id)
        finally:
            visiting.remove(stack_id)

    for stack_id in normalized_selected:
        visit(stack_id)

    if target_archetypes is not None:
        _validate_archetypes(resolved_ids, definitions, target_archetypes)

    capabilities: dict[str, ResolvedCapability] = {}
    tools: dict[str, StackTool] = {}
    required_commands: list[str] = []
    required_registries: list[str] = []
    context_files: list[str] = []
    provisioners: list[ResolvedStackProvisioner] = []
    services: list[SandboxServiceSpec] = []
    provisioners_by_id: dict[str, StackProvisioner] = {}
    runnability = ResolvedRunnability()

    for stack_id in resolved_ids:
        stack = definitions[stack_id]
        runnability = _merge_runnability(runnability, stack_id, stack.runnability)
        for capability, value in stack.provides.items():
            existing = capabilities.get(capability)
            if existing is None:
                capabilities[capability] = ResolvedCapability(
                    value=value,
                    sources=[stack_id],
                )
                continue
            if existing.value != value:
                sources = ", ".join(existing.sources)
                raise StackConflictError(
                    "Stack capability conflict for "
                    f"{capability}: {existing.value!r} from {sources} "
                    f"conflicts with {value!r} from {stack_id}"
                )
            capabilities[capability] = ResolvedCapability(
                value=value,
                sources=_append_unique(existing.sources, stack_id),
            )

        for tool_id, tool in stack.tools.items():
            existing = tools.get(tool_id)
            if existing is None:
                tools[tool_id] = tool
                continue
            if existing != tool:
                raise StackConflictError(
                    f"Stack tool conflict for {tool_id}: "
                    f"{existing.command!r} does not match {tool.command!r}"
                )

        for command in stack.requires_commands:
            required_commands = _append_unique(required_commands, command)
        for registry in stack.requires_registries:
            required_registries = _append_unique(required_registries, registry)
        for context_file in stack.context_files:
            resolved_context = str(stack.source_path.parent / context_file)
            context_files = _append_unique(context_files, resolved_context)

        for provisioner in stack.provisioners:
            existing = provisioners_by_id.get(provisioner.id)
            if existing is None:
                provisioners_by_id[provisioner.id] = provisioner
            elif existing != provisioner:
                raise StackConflictError(
                    f"Stack provisioner conflict for {provisioner.id}: "
                    f"definitions do not match between resolved stacks"
                )
            provisioners.append(
                ResolvedStackProvisioner(
                    owner_stack_id=stack_id,
                    provisioner=provisioner,
                )
            )
            if provisioner.id == "postgres-verify":
                services.append(
                    SandboxServiceSpec(
                        service_name="postgres",
                        image="postgres:16.4-alpine",
                        environment_names=tuple(
                            _append_unique(
                                list(provisioner.required_environment),
                                "TEST_DATABASE_URL",
                            )
                        ),
                        health_command=("pg_isready", "-U", "echelon", "-d", "echelon_verify"),
                    )
                )

    return ResolvedStacks(
        selected_ids=normalized_selected,
        resolved_ids=resolved_ids,
        implied_by=implied_by,
        capabilities=capabilities,
        tools=tools,
        required_commands=required_commands,
        required_registries=required_registries,
        context_files=context_files,
        provisioners=provisioners,
        services=services,
        runnability=runnability,
    )


def resolved_stack_contract_sha256(resolved: ResolvedStacks) -> str:
    """Return a selection-order-independent digest of resolved stack behavior."""
    payload = {
        "selected_ids": sorted(resolved.selected_ids),
        "resolved_ids": sorted(resolved.resolved_ids),
        "capabilities": {
            key: {
                "value": capability.value,
                "sources": sorted(capability.sources),
            }
            for key, capability in sorted(resolved.capabilities.items())
        },
        "tools": {
            key: asdict(tool) for key, tool in sorted(resolved.tools.items())
        },
        "required_commands": sorted(resolved.required_commands),
        "required_registries": sorted(resolved.required_registries),
        "context_files": sorted(resolved.context_files),
        "provisioners": sorted(
            (
                {
                    "owner_stack_id": item.owner_stack_id,
                    "provisioner": asdict(item.provisioner),
                }
                for item in resolved.provisioners
            ),
            key=lambda item: (
                item["owner_stack_id"],
                item["provisioner"]["id"],
            ),
        ),
        "services": sorted(
            (asdict(service) for service in resolved.services),
            key=lambda item: (item["service_name"], item["image"]),
        ),
        "runnability": {
            "classification": resolved.runnability.classification,
            "policy": resolved.runnability.policy,
            "runner": resolved.runnability.runner,
            "capabilities": sorted(resolved.runnability.capabilities),
            "required_observations": sorted(
                resolved.runnability.required_observations
            ),
            "sources": sorted(resolved.runnability.sources),
        },
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_RUNNABILITY_POLICY_RANK = {
    "not_applicable": 0,
    "advisory": 1,
    "required": 2,
}


def _merge_runnability(
    current: ResolvedRunnability,
    stack_id: str,
    declared: StackRunnability,
) -> ResolvedRunnability:
    if declared == StackRunnability():
        return current

    if current.runner and declared.runner and current.runner != declared.runner:
        raise StackConflictError(
            "Stack runnability runner conflict: "
            f"{current.runner!r} conflicts with {declared.runner!r} from {stack_id}"
        )
    policy = current.policy
    if _RUNNABILITY_POLICY_RANK[declared.policy] > _RUNNABILITY_POLICY_RANK[policy]:
        policy = declared.policy
    classification = (
        "user_facing"
        if "user_facing" in {current.classification, declared.classification}
        else "non_runnable"
    )
    return ResolvedRunnability(
        classification=classification,
        policy=policy,
        runner=current.runner or declared.runner,
        capabilities=tuple(
            _append_unique_many(current.capabilities, declared.capabilities)
        ),
        required_observations=tuple(
            _append_unique_many(
                current.required_observations,
                declared.required_observations,
            )
        ),
        sources=tuple(_append_unique_many(current.sources, (stack_id,))),
    )


def _normalize_stack_ids(stack_ids: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_stack_id in enumerate(stack_ids):
        stack_id = str(raw_stack_id).strip()
        if not stack_id:
            raise StackResolutionError(
                f"Empty Echelon stack ID at position {index}"
            )
        if stack_id in seen:
            continue
        seen.add(stack_id)
        normalized.append(stack_id)
    return normalized


def _append_unique(values: list[str], value: str) -> list[str]:
    if value in values:
        return values
    return [*values, value]


def _append_unique_many(
    values: Iterable[str], additions: Iterable[str]
) -> list[str]:
    result = list(values)
    for value in additions:
        if value not in result:
            result.append(value)
    return result


def _validate_archetypes(
    resolved_ids: list[str],
    definitions: dict[str, StackDefinition],
    target_archetypes: set[str],
) -> None:
    for stack_id in resolved_ids:
        stack = definitions[stack_id]
        applies_to = set(stack.applies_to_archetypes)
        if applies_to.intersection(target_archetypes):
            continue
        applies_display = ", ".join(stack.applies_to_archetypes) or "none"
        target_display = ", ".join(sorted(target_archetypes)) or "none"
        raise StackResolutionError(
            f"Stack {stack_id} applies to {applies_display}, "
            f"but target archetypes are {target_display}"
        )

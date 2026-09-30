"""Shared resolution of the stack contract governing target verification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from harness.config import get_full_resolved_config
from harness.stacks.loader import load_stack_definitions
from harness.stacks.paths import find_stack_extension_root
from harness.stacks.resolver import ResolvedStacks, resolve_stacks
from harness.provider import NetworkPolicy, ResourceLimits, SandboxSpec
from harness.verification_plan import build_verification_plan


class VerificationStackResolutionError(ValueError):
    """Raised when a target's verification stack selection is malformed."""


def require_spec_stack_selection(
    project_root: Path, *, target_roots: tuple[Path, ...] = (),
) -> tuple[ResolvedStacks, ...]:
    """Admit discovery only with explicit, owner-controlled stack intent."""
    roots = target_roots or (project_root,)
    selections = tuple(resolve_verification_stacks(project_root, root) for root in roots)
    for root, resolved in zip(roots, selections, strict=True):
        if not resolved.selected_ids:
            raise VerificationStackResolutionError(
                f"stack_selection_required: {root}: explicitly select a concrete "
                "stack or generic for discovery using echelon stack select"
            )
    return selections


def resolve_verification_stacks(
    project_root: Path,
    target_root: Path,
) -> ResolvedStacks:
    """Resolve the owner-controlled stack contract for one target.

    A source with its own Echelon configuration owns stack selection. Targets
    without source-local configuration retain workspace-root selection for
    compatibility with existing workspaces.
    """
    project = Path(project_root).resolve()
    config_root = verification_owner_root(project, target_root)
    raw = get_full_resolved_config(config_root)
    stacks = raw.get("stacks") or {}
    if not isinstance(stacks, Mapping):
        raise VerificationStackResolutionError("stacks must be a mapping")
    selected = stacks.get("selected") or []
    archetypes = stacks.get("target_archetypes") or []
    if not isinstance(selected, list) or not all(
        isinstance(item, str) and item.strip() for item in selected
    ):
        raise VerificationStackResolutionError(
            "stacks.selected must be a list of non-empty stack IDs"
        )
    if not isinstance(archetypes, list) or not all(
        isinstance(item, str) and item.strip() for item in archetypes
    ):
        raise VerificationStackResolutionError(
            "stacks.target_archetypes must be a list of non-empty archetype IDs"
        )
    definitions = load_stack_definitions(
        extension_root=find_stack_extension_root(project),
        project_root=project,
    )
    return resolve_stacks(
        selected,
        definitions,
        target_archetypes=set(archetypes) or None,
    )


def verification_owner_root(project_root: Path, target_root: Path) -> Path:
    """Use the same owner precedence for selection, prompts and execution policy."""
    project = Path(project_root).resolve()
    target = Path(target_root).resolve()
    target_config = target / ".echelon"
    target_owned = target != project and any(
        (target_config / name).is_file() for name in ("config.yml", "local.yml")
    )
    return target if target_owned else project


def apply_verification_stacks(
    config: object,
    *,
    project_root: Path,
    target_root: Path,
) -> ResolvedStacks:
    """Attach resolved services and policy to a harness configuration."""
    resolved = resolve_verification_stacks(project_root, target_root)
    config.verification_services = list(resolved.services)
    config.resolved_stacks = resolved
    config.resolved_runnability = resolved.runnability
    return resolved


def build_verification_sandbox_spec(
    config: object,
    *,
    worktree: Path,
    spec_id: str,
    run_id: str,
) -> SandboxSpec:
    """Build the common isolated sandbox contract used by every verifier."""
    candidate = Path(worktree).resolve()
    plan = build_verification_plan(
        candidate,
        config,
        services=tuple(getattr(config, "verification_services", ())),
    )
    limits = getattr(config, "resource_limits")
    network = getattr(config, "network")
    return SandboxSpec(
        image=plan.image,
        image_source=(
            "config_override" if getattr(config, "base_image", None) else "fingerprint"
        ),
        worktree_mount=str(candidate),
        container_mount="/workspace",
        resource_limits=ResourceLimits(
            memory=limits.memory,
            cpu=limits.cpu,
            pids=limits.pids,
            storage=limits.storage,
        ),
        network_policy=NetworkPolicy(
            allowlist=network.allowlist,
            proxy_image=network.proxy_image,
        ),
        env={
            "ECHELON_HARNESS_RUN": "1",
            "NODE_OPTIONS": "--use-env-proxy",
        },
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
        labels={
            "spec_id": spec_id,
            "run_id": run_id,
        },
        ephemeral_volumes=["node_modules"],
    )

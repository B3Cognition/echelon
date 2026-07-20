"""Resolved, immutable resource and convergence goals for RE runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping

from harness.config import get_full_resolved_config


@dataclass(frozen=True)
class ReExecutionProfile:
    name: str
    performance_target_minutes: int | None
    hard_active_minutes: int | None
    hard_token_limit: int | None
    max_domain_repairs: int
    max_source_cycles: int
    max_source_reanalysis: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


BUILTIN_RE_PROFILES: dict[str, ReExecutionProfile] = {
    "fast": ReExecutionProfile("fast", 30, 60, 1_000_000, 1, 1, 1),
    "balanced": ReExecutionProfile("balanced", 60, 180, 5_000_000, 3, 2, 2),
    "high": ReExecutionProfile("high", 180, 720, 15_000_000, 5, 5, 5),
}


def builtin_re_profile(name: str) -> ReExecutionProfile:
    normalized = name.strip().lower()
    try:
        return BUILTIN_RE_PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(
            f"unknown RE execution profile {name!r}; expected fast, balanced, or high"
        ) from exc


def resolve_re_execution_profile(
    project_root: Path,
    *,
    name: str | None = None,
    hard_token_limit: int | None = None,
    hard_active_minutes: int | None = None,
) -> ReExecutionProfile:
    config = get_full_resolved_config(project_root)
    re_config = config.get("re") if isinstance(config.get("re"), Mapping) else {}
    profile_name = str(name or re_config.get("default_profile") or "balanced")
    profile = builtin_re_profile(profile_name)
    raw_profiles = re_config.get("profiles")
    if isinstance(raw_profiles, Mapping):
        custom = raw_profiles.get(profile.name)
        if isinstance(custom, Mapping):
            profile = _apply_mapping(profile, custom)
    if hard_token_limit is not None:
        profile = replace(profile, hard_token_limit=_positive(hard_token_limit, "token limit"))
    if hard_active_minutes is not None:
        profile = replace(
            profile,
            hard_active_minutes=_positive(hard_active_minutes, "time limit"),
        )
    return profile


def migrate_legacy_re_profile(state: Mapping[str, object]) -> ReExecutionProfile:
    raw = state.get("re_source_budgets")
    budgets = raw if isinstance(raw, Mapping) else {}
    return ReExecutionProfile(
        name="legacy",
        performance_target_minutes=None,
        hard_active_minutes=None,
        hard_token_limit=None,
        max_domain_repairs=_positive_or_default(budgets.get("max_domain_repairs"), 5),
        max_source_cycles=_positive_or_default(budgets.get("max_source_cycles"), 5),
        max_source_reanalysis=_positive_or_default(
            budgets.get("max_source_reanalysis"), 5
        ),
    )


def _apply_mapping(
    profile: ReExecutionProfile, value: Mapping[str, object]
) -> ReExecutionProfile:
    replacements: dict[str, int] = {}
    for key in (
        "performance_target_minutes",
        "hard_active_minutes",
        "hard_token_limit",
        "max_domain_repairs",
        "max_source_cycles",
        "max_source_reanalysis",
    ):
        if key in value:
            replacements[key] = _positive(value[key], key.replace("_", " "))
    return replace(profile, **replacements)


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) < 1:
        raise ValueError(f"RE {label} must be a positive integer")
    return int(value)


def _positive_or_default(value: object, default: int) -> int:
    try:
        return _positive(value, "legacy convergence limit")
    except ValueError:
        return default

"""Small, provider-neutral option resolution for ordinary RE actions."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Literal


KnowledgeDepth = Literal["quick", "standard", "deep"]
_DEPTHS = frozenset({"quick", "standard", "deep"})


class KnowledgeDepthError(ValueError):
    """Raised when user or durable depth configuration cannot be interpreted."""


def resolve_knowledge_depth(
    *,
    explicit: str | None,
    published: str | None,
    workspace_default: str | None,
) -> KnowledgeDepth:
    """Resolve explicit, established, configured, then product-default depth."""

    if explicit is not None:
        normalized = explicit.strip().lower()
        if normalized == "full":
            return "deep"
        return _validated_depth(normalized, "--depth")
    if published is not None:
        return _validated_depth(published, "published depth")
    if workspace_default is not None:
        return _validated_depth(workspace_default, "re.default_depth")
    return "standard"


def resolve_source_depths(
    source_ids: tuple[str, ...],
    *,
    explicit: str | None,
    published: Mapping[str, str | None],
    workspace_default: str | None,
) -> dict[str, KnowledgeDepth]:
    """Resolve deterministic per-source depths without flattening prior choices."""

    if any(not isinstance(source_id, str) or not source_id for source_id in source_ids):
        raise KnowledgeDepthError("source IDs must be non-empty strings")
    if len(set(source_ids)) != len(source_ids):
        raise KnowledgeDepthError("source IDs must be unique")
    return {
        source_id: resolve_knowledge_depth(
            explicit=explicit,
            published=published.get(source_id),
            workspace_default=workspace_default,
        )
        for source_id in sorted(source_ids)
    }


def configured_workspace_depth(workspace_root: Path) -> str | None:
    """Read the optional ordinary-workflow default from resolved Echelon config."""

    from harness.config import get_full_resolved_config

    config = get_full_resolved_config(Path(workspace_root).resolve())
    raw_re = config.get("re")
    if not isinstance(raw_re, Mapping) or "default_depth" not in raw_re:
        return None
    value = raw_re["default_depth"]
    if not isinstance(value, str):
        raise KnowledgeDepthError("re.default_depth must be quick, standard, or deep")
    return _validated_depth(value, "re.default_depth")


def _validated_depth(value: str, label: str) -> KnowledgeDepth:
    if not isinstance(value, str) or value not in _DEPTHS:
        raise KnowledgeDepthError(
            f"{label} must be quick, standard, or deep; got {value!r}"
        )
    return value  # type: ignore[return-value]


__all__ = (
    "KnowledgeDepth",
    "KnowledgeDepthError",
    "configured_workspace_depth",
    "resolve_knowledge_depth",
    "resolve_source_depths",
)

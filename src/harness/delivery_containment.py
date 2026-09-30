"""Provider-facing containment policy validation for controlled delivery."""

from __future__ import annotations

import json
from pathlib import Path


def containment_policy_env(
    policy_file: str,
    *,
    worktree_path: str,
) -> tuple[dict[str, str], str | None]:
    """Return root-boundary environment variables derived from policy JSON."""
    path = Path(policy_file)
    if not path.exists():
        return {}, "missing containment policy"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"malformed containment policy: {exc}"
    if not isinstance(data, dict):
        return {}, "malformed containment policy: expected JSON object"

    allowed_roots: list[str] = []
    allowed = data.get("allowed_roots")
    if isinstance(allowed, dict):
        for roots in allowed.values():
            allowed_roots.extend(_string_list(roots))

    forbidden_roots = _string_list(data.get("forbidden_source_roots"))
    forbidden_aliases = _string_list(data.get("forbidden_source_root_aliases"))
    if not allowed_roots and not forbidden_roots:
        return {}, "empty containment policy"
    boundary_error = _worktree_boundary_error(
        worktree_path,
        allowed_roots=allowed_roots,
        forbidden_roots=forbidden_roots,
    )
    if boundary_error:
        return {}, boundary_error

    return (
        {
            "ECHELON_ALLOWED_ROOTS_JSON": json.dumps(allowed_roots),
            "ECHELON_FORBIDDEN_ROOTS_JSON": json.dumps(forbidden_roots),
            "ECHELON_FORBIDDEN_ROOT_ALIASES_JSON": json.dumps(forbidden_aliases),
        },
        None,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _worktree_boundary_error(
    worktree_path: str,
    *,
    allowed_roots: list[str],
    forbidden_roots: list[str],
) -> str | None:
    worktree = _resolved_path(worktree_path)
    for forbidden in (_resolved_path(path) for path in forbidden_roots):
        if _path_is_relative_to(worktree, forbidden):
            return f"worktree under containment policy forbidden root {forbidden}"
    if allowed_roots and not any(
        _path_is_relative_to(worktree, _resolved_path(root)) for root in allowed_roots
    ):
        return "worktree outside containment policy allowed roots"
    return None


def _resolved_path(path: object) -> Path:
    return Path(str(path)).expanduser().resolve(strict=False)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

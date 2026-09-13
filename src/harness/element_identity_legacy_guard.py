"""Early negative admission for legacy execution; never enrolls managed content."""

from pathlib import Path
import stat

from harness.element_identity_lifecycle import text
from harness.element_identity_store import IdentityStore, IdentityStoreError


LEGACY_IDENTITY_EXECUTION_BLOCKED = "identity authority does not permit legacy execution"


def _require_existing_unmanaged_authority(
    project_root: Path, *, spec_id: str | None = None,
    run_dir: Path | None = None, state: dict | None = None,
) -> None:
    parent = project_root / ".echelon"
    try:
        parent_mode = parent.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(parent_mode):
        raise ValueError("identity parent must be a real directory")
    try:
        (parent / "identity").lstat()
    except FileNotFoundError:
        return None

    run_ids = []
    if run_dir is not None:
        # Preserve legacy execution's presence-before-claim-validation order.
        run_ids.append(run_dir.name)
        declared_run = state.get("run_id")
        if declared_run is not None and not (type(declared_run) is str and declared_run == ""):
            text(declared_run, "run_id")
            if declared_run not in run_ids:
                run_ids.append(declared_run)
        spec_id = state.get("spec_id")
        if spec_id is None or (type(spec_id) is str and spec_id == ""):
            spec_id = None
        else:
            text(spec_id, "spec_id")
    store = IdentityStore.open(project_root)
    if spec_id is None and not run_ids:
        store.require_unmanaged_workspace()
    else:
        store.require_unmanaged_execution(spec_id=spec_id, run_ids=tuple(run_ids))


def require_legacy_identity_workspace(*, project_root: Path) -> None:
    """Observe workspace-wide ownership without inventing a selected spec or run."""
    try:
        _require_existing_unmanaged_authority(project_root)
        return None
    except Exception:
        pass
    raise IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)


def require_legacy_identity_spec(*, project_root: Path, spec_id: str) -> None:
    """Observe the exact selected spec without enrollment or source inference."""
    try:
        text(spec_id, "spec_id")
        _require_existing_unmanaged_authority(project_root, spec_id=spec_id)
        return None
    except Exception:
        pass
    raise IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)


def require_legacy_identity_execution(
    *, project_root: Path, run_dir: Path, state: dict,
) -> None:
    """Permit legacy entry only in the absence of observed managed ownership."""
    try:
        if type(state) is not dict or "managed_identity" in state:
            raise ValueError("managed or invalid state cannot enter legacy execution")
        _require_existing_unmanaged_authority(
            project_root, run_dir=run_dir, state=state,
        )
        return None
    except Exception:
        pass
    raise IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)

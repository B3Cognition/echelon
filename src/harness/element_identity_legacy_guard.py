"""Early negative admission for legacy execution; never enrolls managed content."""

from pathlib import Path
import stat

from harness.element_identity_lifecycle import text
from harness.element_identity_store import IdentityStore, IdentityStoreError


LEGACY_IDENTITY_EXECUTION_BLOCKED = "identity authority does not permit legacy execution"


def require_legacy_identity_execution(
    *, project_root: Path, run_dir: Path, state: dict,
) -> None:
    """Permit legacy entry only in the absence of observed managed ownership."""
    try:
        if type(state) is not dict or "managed_identity" in state:
            raise ValueError("managed or invalid state cannot enter legacy execution")
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

        run_ids = [run_dir.name]
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
        IdentityStore.open(project_root).require_unmanaged_execution(
            spec_id=spec_id, run_ids=tuple(run_ids),
        )
        return None
    except Exception:
        pass
    raise IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)

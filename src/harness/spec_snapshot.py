"""Safety snapshots for spec artifacts before harness mutation.

Specs may be untracked when a user starts a harness build. Preserve them under
``runs/`` before branch switching, target dispatch, or recovery paths can make
manual salvage harder.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from harness.paths import runs_dir


def snapshot_spec_dir(spec_dir: Path, project_root: Path) -> Path:
    """Copy a spec directory into runs/spec-snapshots and return the snapshot path."""
    spec_dir = spec_dir.resolve()
    project_root = project_root.resolve()
    created_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    snapshot_root = runs_dir(project_root) / "spec-snapshots"
    snapshot_dir = snapshot_root / f"{spec_dir.name}-{created_at}"
    snapshot_spec = snapshot_dir / "spec"

    snapshot_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(spec_dir, snapshot_spec, symlinks=True)

    manifest = {
        "kind": "echelon.spec_snapshot",
        "spec_id": spec_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_spec_dir": str(spec_dir),
        "snapshot_spec_dir": str(snapshot_spec),
    }
    (snapshot_dir / "snapshot.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot_dir

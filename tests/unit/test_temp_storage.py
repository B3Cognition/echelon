from __future__ import annotations

import stat
from pathlib import Path

from tests.support.temp_storage import (
    copy_package_build_tree,
    package_checkout_files,
    restore_owner_write_permissions,
)


def test_package_staging_excludes_ignored_dependency_trees(tmp_path: Path) -> None:
    source = tmp_path / "runtime"
    tracked = source / "workflow" / "definition.yaml"
    ignored = source / "scripts" / "node" / "tool" / "node_modules" / "large.bin"
    tracked.parent.mkdir(parents=True)
    ignored.parent.mkdir(parents=True)
    tracked.write_text("phases: []\n", encoding="utf-8")
    ignored.write_bytes(b"ignored dependency")

    destination = tmp_path / "staged-runtime"
    copy_package_build_tree(source, destination)
    captured = package_checkout_files(source)

    assert (destination / "workflow" / "definition.yaml").is_file()
    assert not (destination / "scripts" / "node" / "tool" / "node_modules").exists()
    assert ignored not in captured


def test_temp_cleanup_restores_nested_owner_write_permissions(tmp_path: Path) -> None:
    immutable_root = tmp_path / "snapshot"
    immutable_child = immutable_root / "objects"
    immutable_file = immutable_child / "artifact.json"
    immutable_child.mkdir(parents=True)
    immutable_file.write_text("{}\n", encoding="utf-8")
    immutable_file.chmod(0o400)
    immutable_child.chmod(0o500)
    immutable_root.chmod(0o500)

    restore_owner_write_permissions(immutable_root)

    for path in (immutable_root, immutable_child, immutable_file):
        assert stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR

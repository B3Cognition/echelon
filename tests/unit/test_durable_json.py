from __future__ import annotations

import json
from pathlib import Path

import pytest


def _tree_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


@pytest.mark.unit
@pytest.mark.parametrize("linked_component", ("parent", "ancestor"))
def test_durable_json_rejects_linked_directory_components_before_external_writes(
    tmp_path: Path,
    linked_component: str,
) -> None:
    from harness.durable_json import DurableJsonError, write_json_atomic

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    if linked_component == "parent":
        workspace.mkdir()
        (workspace / "run").symlink_to(outside, target_is_directory=True)
        destination = workspace / "run/state.json"
    else:
        workspace.mkdir()
        (outside / "run").mkdir()
        (workspace / "runs").symlink_to(outside, target_is_directory=True)
        destination = workspace / "runs/run/state.json"

    before = _tree_snapshot(outside)
    with pytest.raises(DurableJsonError, match="symlink|directory"):
        write_json_atomic(destination, {"status": "complete"})

    assert _tree_snapshot(outside) == before


@pytest.mark.unit
def test_durable_json_pins_parent_across_ancestor_path_swap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness import durable_json

    workspace = tmp_path / "workspace"
    parent = workspace / "runs/verify-spec-001"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "verify-spec-001").mkdir(parents=True)
    destination = parent / "state.json"
    original_replace = durable_json.os.replace
    swapped = False

    def swap_then_replace(src, dst, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            (workspace / "runs").rename(workspace / "runs-pinned")
            (workspace / "runs").symlink_to(outside, target_is_directory=True)
        return original_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(durable_json.os, "replace", swap_then_replace)

    durable_json.write_json_atomic(destination, {"status": "complete"})

    pinned_destination = workspace / "runs-pinned/verify-spec-001/state.json"
    assert json.loads(pinned_destination.read_text()) == {"status": "complete"}
    assert not (outside / "verify-spec-001/state.json").exists()


@pytest.mark.unit
def test_durable_json_replaces_normally_and_cleans_temps_idempotently(
    tmp_path: Path,
) -> None:
    from harness.durable_json import write_json_atomic

    destination = tmp_path / "state.json"
    write_json_atomic(destination, {"generation": 1})
    write_json_atomic(destination, {"generation": 2})

    assert json.loads(destination.read_text()) == {"generation": 2}
    assert [path for path in tmp_path.iterdir() if path.name != "state.json"] == []


@pytest.mark.unit
def test_durable_json_allows_alias_in_declared_trusted_base(tmp_path: Path) -> None:
    from harness.durable_json import write_json_atomic

    trusted = tmp_path / "trusted-workspace"
    destination_parent = trusted / "runs/verify-spec-001"
    destination_parent.mkdir(parents=True)
    trusted_alias = tmp_path / "workspace-alias"
    trusted_alias.symlink_to(trusted, target_is_directory=True)

    write_json_atomic(
        trusted_alias / "runs/verify-spec-001/state.json",
        {"status": "complete"},
        trusted_root=trusted_alias,
    )

    assert json.loads((destination_parent / "state.json").read_text()) == {
        "status": "complete"
    }


@pytest.mark.unit
def test_durable_json_rejects_alias_below_trusted_base_without_external_writes(
    tmp_path: Path,
) -> None:
    from harness.durable_json import DurableJsonError, write_json_atomic

    trusted = tmp_path / "trusted-workspace"
    trusted.mkdir()
    trusted_alias = tmp_path / "workspace-alias"
    trusted_alias.symlink_to(trusted, target_is_directory=True)
    outside = tmp_path / "outside"
    (outside / "verify-spec-001").mkdir(parents=True)
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    (trusted / "runs").symlink_to(outside, target_is_directory=True)

    before = _tree_snapshot(outside)
    with pytest.raises(DurableJsonError, match="unsafe|directory"):
        write_json_atomic(
            trusted_alias / "runs/verify-spec-001/state.json",
            {"status": "complete"},
            trusted_root=trusted_alias,
        )

    assert _tree_snapshot(outside) == before

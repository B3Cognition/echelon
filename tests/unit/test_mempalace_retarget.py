from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from echelon.mempalace_retarget import (
    RetargetMemoryError,
    exclude_retarget_spec_drawers,
    purge_retarget_spec_memory,
    refresh_retarget_spec_memory,
)


class FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, object]]] = {}
        self.deleted_batches: list[tuple[str, ...]] = []
        self.force_truncated = False
        self.delete_limit: int | None = None
        self.ignore_delete = False
        self.get_calls = 0
        self.post_delete_hook = None
        self.delete_results: list[object] | None = None

    def get(
        self,
        *,
        where: dict[str, object],
        include: list[str],
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        self.get_calls += 1
        if self.deleted_batches and self.post_delete_hook is not None:
            hook = self.post_delete_hook
            self.post_delete_hook = None
            hook(self.rows)
        if self.force_truncated:
            raise TypeError("offset pagination is unsupported")
        wing = where["wing"]
        rows = [
            (drawer_id, row)
            for drawer_id, row in sorted(self.rows.items())
            if row[1].get("wing") == wing
        ][offset : offset + limit]
        return {
            "ids": [drawer_id for drawer_id, _row in rows],
            "documents": [row[0] for _drawer_id, row in rows],
            "metadatas": [row[1] for _drawer_id, row in rows],
        }

    def delete(self, *, ids: list[str]) -> object:
        self.deleted_batches.append(tuple(ids))
        deleted = 0
        if not self.ignore_delete:
            selected = ids[: self.delete_limit] if self.delete_limit is not None else ids
            for drawer_id in selected:
                if self.rows.pop(drawer_id, None) is not None:
                    deleted += 1
        if self.delete_results is not None:
            return self.delete_results.pop(0)
        return {"deleted": deleted}


@dataclass
class MemoryWorkspace:
    root: Path
    spec_dir: Path
    collection: FakeCollection


@pytest.fixture
def memory_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MemoryWorkspace:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text("mempalace:\n  wing: demo\n", encoding="utf-8")
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "FR-001: Preserve exact ownership.\n",
        encoding="utf-8",
    )
    collection = FakeCollection()

    class FakeAdapter:
        wing = "demo"
        palace_path = tmp_path / ".mempalace" / "palace"

        def open_collection_read_only(self) -> FakeCollection:
            return collection

    monkeypatch.setattr(
        "echelon.mempalace_retarget.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    return MemoryWorkspace(tmp_path, spec_dir, collection)


@pytest.mark.unit
def test_retarget_purge_deletes_only_exact_spec_owned_drawers(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned-canonical": (
            "old",
            {
                "wing": "demo",
                "canonical": True,
                "artifact_path": "specs/001-demo/spec.md",
                "spec_id": "001-demo",
            },
        ),
        "owned-support": (
            "old plan",
            {
                "wing": "demo",
                "artifact_path": "specs/001-demo/plan.md",
                "spec_id": "001-demo",
            },
        ),
        "workspace-re": (
            "re",
            {"wing": "demo", "artifact_path": "re/sources/api/overview.md"},
        ),
        "other-spec": (
            "other",
            {
                "wing": "demo",
                "artifact_path": "specs/002-other/spec.md",
                "spec_id": "002-other",
            },
        ),
    }

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert receipt.status == "pass"
    assert receipt.deleted_ids == ("owned-canonical", "owned-support")
    assert set(memory_workspace.collection.rows) == {"workspace-re", "other-spec"}


@pytest.mark.unit
def test_retarget_purge_fails_before_delete_when_scan_is_truncated(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.force_truncated = True

    with pytest.raises(RetargetMemoryError, match="complete scan"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert memory_workspace.collection.deleted_batches == []


@pytest.mark.unit
def test_retarget_memory_is_not_applicable_without_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.mempalace_retarget.create_requirement_memory_adapter",
        lambda *_args, **_kwargs: pytest.fail("adapter creation is forbidden"),
    )

    receipt = purge_retarget_spec_memory(tmp_path, "001-demo")

    assert receipt.status == "not_applicable"
    assert receipt.deleted_ids == ()


@pytest.mark.unit
def test_retarget_memory_rejects_malformed_existing_configuration(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text("[]\n", encoding="utf-8")

    with pytest.raises(RetargetMemoryError, match="config"):
        purge_retarget_spec_memory(tmp_path, "001-demo")


@pytest.mark.unit
def test_retarget_purge_rejects_contradictory_ownership_before_delete(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "contradictory": (
            "old",
            {
                "wing": "demo",
                "artifact_path": "specs/001-demo/spec.md",
                "spec_id": "002-other",
            },
        )
    }

    with pytest.raises(RetargetMemoryError, match="ownership metadata"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert memory_workspace.collection.deleted_batches == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "metadata",
    [
        {"wing": "demo", "artifact_path": "/specs/001-demo/spec.md"},
        {"wing": "demo", "artifact_path": "C:/specs/001-demo/spec.md"},
        {"wing": "demo", "artifact_path": "specs/001-demo/../002-other/spec.md"},
        {"wing": "demo", "artifact_path": "specs/001-demo/%2e%2e/002-other/spec.md"},
        {"wing": "demo", "artifact_path": "specs%2f001-demo/spec.md"},
        {"wing": "demo", "artifact_path": "specs%5c001-demo/spec.md"},
        {"wing": "demo", "artifact_path": "specs%252f001-demo/spec.md"},
        {"wing": "demo", "artifact_path": ["specs/001-demo/spec.md"]},
        {"wing": "demo", "spec_id": 1},
        {"wing": "demo", "spec_id": "001-demo"},
        {
            "wing": "demo",
            "artifact_path": "specs/001-demo/spec.md",
            "canonical": False,
        },
        {
            "wing": "demo",
            "artifact_path": "specs/001-demo/spec.md",
            "scope": "external-input",
        },
        {
            "wing": "demo",
            "artifact_path": "specs/001-demo/spec.md",
            "artifact_kind": "external-input",
        },
        {
            "wing": "demo",
            "spec_id": "001-demo",
            "canonical": True,
            "scope": "external-input",
            "artifact_kind": "external-input",
        },
        {
            "wing": "demo",
            "canonical": True,
            "scope": "canonical",
        },
        {
            "wing": "demo",
            "artifact_path": "re/hidden.md",
            "canonical": True,
            "scope": "canonical",
        },
        {
            "wing": "demo",
            "artifact_path": "inputs/external.md",
            "canonical": True,
            "scope": "canonical-support",
            "artifact_kind": "supporting-context",
        },
        {
            "wing": "demo",
            "artifact_path": "specs/001-demo/spec.md",
            "source_file": "specs/002-other/spec.md",
        },
    ],
)
def test_retarget_purge_rejects_unsafe_ownership_metadata(
    memory_workspace: MemoryWorkspace,
    metadata: dict[str, object],
) -> None:
    memory_workspace.collection.rows = {"unsafe": ("old", metadata)}

    with pytest.raises(RetargetMemoryError, match="ownership metadata"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert memory_workspace.collection.deleted_batches == []


@pytest.mark.unit
def test_retarget_purge_accepts_exact_source_file_ownership(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": (
            "old",
            {"wing": "demo", "source_file": "specs/001-demo/tasks.md"},
        )
    }

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert receipt.deleted_ids == ("owned",)
    assert memory_workspace.collection.rows == {}


@pytest.mark.unit
def test_retarget_purge_accepts_exact_spec_evidence_metadata(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "evidence": (
            "old evidence",
            {
                "wing": "demo",
                "spec_id": "001-demo",
                "canonical": True,
                "scope": "spec-evidence",
                "artifact_kind": "spec-evidence",
            },
        )
    }

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert receipt.deleted_ids == ("evidence",)
    assert memory_workspace.collection.rows == {}


@pytest.mark.unit
def test_retarget_purge_rejects_spec_id_on_workspace_re_before_delete(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "workspace-re": (
            "workspace fact",
            {
                "wing": "demo",
                "spec_id": "001-demo",
                "artifact_path": "re/workspace/overview.md",
            },
        )
    }

    with pytest.raises(RetargetMemoryError, match="ownership metadata"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert memory_workspace.collection.deleted_batches == []
    assert set(memory_workspace.collection.rows) == {"workspace-re"}


@pytest.mark.unit
def test_retarget_purge_reports_partial_delete_after_complete_rescan(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        drawer_id: (
            "old",
            {
                "wing": "demo",
                "artifact_path": f"specs/001-demo/{drawer_id}.md",
                "spec_id": "001-demo",
            },
        )
        for drawer_id in ("owned-a", "owned-b")
    }
    memory_workspace.collection.delete_limit = 1

    with pytest.raises(RetargetMemoryError, match="partial deletion") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.deleted_ids == ("owned-a",)
    assert caught.value.receipt.remaining_owned_ids == ("owned-b",)
    assert set(memory_workspace.collection.rows) == {"owned-b"}


@pytest.mark.unit
def test_retarget_purge_rejects_missing_delete_effect_even_with_acknowledgement(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": (
            "old",
            {
                "wing": "demo",
                "artifact_path": "specs/001-demo/spec.md",
                "spec_id": "001-demo",
            },
        )
    }
    memory_workspace.collection.ignore_delete = True

    with pytest.raises(RetargetMemoryError, match="partial deletion") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.remaining_owned_ids == ("owned",)


@pytest.mark.unit
@pytest.mark.parametrize(
    "replacement",
    [
        (
            "replacement document",
            {"wing": "demo", "artifact_path": "re/reclassified.md"},
        ),
        (
            "old",
            {
                "wing": "demo",
                "artifact_path": "re/reclassified.md",
                "rank": True,
            },
        ),
    ],
)
def test_retarget_purge_rejects_initial_owned_id_reclassified_after_delete(
    memory_workspace: MemoryWorkspace,
    replacement: tuple[str, dict[str, object]],
) -> None:
    memory_workspace.collection.rows = {
        "owned": (
            "old",
            {
                "wing": "demo",
                "artifact_path": "specs/001-demo/spec.md",
                "rank": 1,
            },
        ),
        "workspace-re": (
            "preserve",
            {"wing": "demo", "artifact_path": "re/workspace.md"},
        ),
    }
    memory_workspace.collection.post_delete_hook = lambda rows: rows.__setitem__(
        "owned",
        replacement,
    )

    with pytest.raises(RetargetMemoryError, match="partial deletion") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.status == "fail"
    assert caught.value.receipt.deleted_ids == ()
    assert caught.value.receipt.remaining_owned_ids == ("owned",)
    assert caught.value.receipt.failure_code == "retarget_memory_delete_partial"
    assert caught.value.receipt.delete_acknowledged_count == 1
    assert "replacement document" not in json.dumps(
        caught.value.receipt.to_dict(),
        sort_keys=True,
    )
    assert memory_workspace.collection.rows["workspace-re"] == (
        "preserve",
        {"wing": "demo", "artifact_path": "re/workspace.md"},
    )


@pytest.mark.unit
def test_retarget_purge_rejects_unrelated_document_mutation(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": ("old", {"wing": "demo", "artifact_path": "specs/001-demo/spec.md"}),
        "workspace-re": ("before", {"wing": "demo", "artifact_path": "re/workspace.md"}),
    }
    memory_workspace.collection.post_delete_hook = lambda rows: rows.__setitem__(
        "workspace-re",
        ("after", rows["workspace-re"][1]),
    )

    with pytest.raises(RetargetMemoryError, match="unrelated") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.failure_code == "retarget_memory_unrelated_changed"


@pytest.mark.unit
def test_retarget_purge_rejects_type_confused_unrelated_metadata_mutation(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": ("old", {"wing": "demo", "artifact_path": "specs/001-demo/spec.md"}),
        "workspace-re": (
            "same",
            {"wing": "demo", "artifact_path": "re/workspace.md", "rank": 1},
        ),
    }
    memory_workspace.collection.post_delete_hook = lambda rows: rows.__setitem__(
        "workspace-re",
        ("same", {**rows["workspace-re"][1], "rank": True}),
    )

    with pytest.raises(RetargetMemoryError, match="unrelated") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.failure_code == "retarget_memory_unrelated_changed"


@pytest.mark.unit
def test_retarget_purge_rejects_new_row_after_delete(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": ("old", {"wing": "demo", "artifact_path": "specs/001-demo/spec.md"}),
    }
    memory_workspace.collection.post_delete_hook = lambda rows: rows.__setitem__(
        "concurrent",
        ("new", {"wing": "demo", "artifact_path": "re/concurrent.md"}),
    )

    with pytest.raises(RetargetMemoryError, match="unrelated") as caught:
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert caught.value.receipt is not None
    assert caught.value.receipt.failure_code == "retarget_memory_unexpected_added"


@pytest.mark.unit
def test_retarget_purge_accepts_raw_integer_delete_acknowledgement(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        "owned": ("old", {"wing": "demo", "artifact_path": "specs/001-demo/spec.md"}),
    }
    memory_workspace.collection.delete_results = [1]

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert receipt.delete_acknowledged_count == 1


@pytest.mark.unit
def test_retarget_purge_does_not_report_partial_mixed_acknowledgements(
    memory_workspace: MemoryWorkspace,
) -> None:
    memory_workspace.collection.rows = {
        f"owned-{index:03d}": (
            "old",
            {"wing": "demo", "artifact_path": f"specs/001-demo/{index}.md"},
        )
        for index in range(129)
    }
    memory_workspace.collection.delete_results = [128, None]

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert receipt.deleted_count == 129
    assert receipt.delete_acknowledged_count is None


@pytest.mark.unit
def test_retarget_purge_validates_receipt_identity_before_scan(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SimpleNamespace(
        wing="demo",
        palace_path="p" * 5_000,
        open_collection_read_only=lambda: memory_workspace.collection,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.create_requirement_memory_adapter",
        lambda *_args, **_kwargs: adapter,
    )

    with pytest.raises(RetargetMemoryError, match="identity"):
        purge_retarget_spec_memory(memory_workspace.root, "001-demo")

    assert memory_workspace.collection.get_calls == 0
    assert memory_workspace.collection.deleted_batches == []


@pytest.mark.unit
def test_retarget_purge_receipt_is_stable_and_contains_no_document_text(
    memory_workspace: MemoryWorkspace,
) -> None:
    secret_document = "do-not-copy-this-document"
    memory_workspace.collection.rows = {
        "owned-b": (
            secret_document,
            {
                "wing": "demo",
                "spec_id": "001-demo",
                "canonical": True,
                "scope": "spec-evidence",
                "artifact_kind": "spec-evidence",
            },
        ),
        "owned-a": (
            secret_document,
            {
                "wing": "demo",
                "spec_id": "001-demo",
                "canonical": True,
                "scope": "spec-evidence",
                "artifact_kind": "spec-evidence",
            },
        ),
    }

    receipt = purge_retarget_spec_memory(memory_workspace.root, "001-demo")
    serialized = json.dumps(receipt.to_dict(), sort_keys=True)

    assert receipt.deleted_ids == ("owned-a", "owned-b")
    assert receipt.drawer_set_digest.startswith("sha256:")
    assert len(receipt.drawer_set_digest) == 71
    assert secret_document not in serialized
    assert receipt.wing == "demo"
    assert receipt.adapter.endswith(".FakeAdapter")


def _complete_mine(workspace: MemoryWorkspace):
    from echelon.mempalace_requirements import SpecMemoryMineReport

    return SpecMemoryMineReport(
        schema_version=1,
        spec_id="001-demo",
        spec_dir=str(workspace.spec_dir.resolve()),
        wing="demo",
        palace_path=str(workspace.root / ".mempalace" / "palace"),
        status="complete",
        expected_count=1,
        written_count=1,
        adopted_count=0,
        skipped_count=0,
        failed_count=0,
        drifted_count=0,
        unavailable_count=0,
        drawer_ids=["new-drawer"],
        expected_drawer_ids=["new-drawer"],
        errors=[],
    )


def _cleanup(workspace: MemoryWorkspace):
    from echelon.mempalace_audit import SpecMemoryCleanupReport

    return SpecMemoryCleanupReport(
        schema_version=1,
        spec_id="001-demo",
        spec_dir=str(workspace.spec_dir.resolve()),
        wing="demo",
        palace_path=str(workspace.root / ".mempalace" / "palace"),
        deleted_count=0,
        deleted_ids=[],
    )


def _audit(workspace: MemoryWorkspace, *, status: str = "warn"):
    from echelon.mempalace_audit import SpecMemoryAuditReport

    return SpecMemoryAuditReport(
        schema_version=1,
        spec_id="001-demo",
        spec_dir=str(workspace.spec_dir.resolve()),
        wing="demo",
        palace_path=str(workspace.root / ".mempalace" / "palace"),
        status=status,
        expected_count=1,
        present_current_count=1,
        retrieval_probe={"status": "warn", "checked": 0},
    )


@pytest.mark.unit
def test_retarget_refresh_requires_acceptable_mine_and_audit(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: calls.append("mine")
        or _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: calls.append("cleanup")
        or _cleanup(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: calls.append("audit")
        or _audit(memory_workspace),
    )

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert calls == ["mine", "cleanup", "audit"]
    assert receipt.status == "pass"
    assert receipt.mine_status == "complete"
    assert receipt.audit_status in {"pass", "warn"}
    assert (memory_workspace.spec_dir / "mempalace-mine.json").is_file()
    assert (memory_workspace.spec_dir / "mempalace-audit.json").is_file()
    manifest_path = memory_workspace.spec_dir / "mempalace-refresh-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert receipt.report_set_digest == manifest["report_set_digest"]
    assert [entry["path"] for entry in manifest["files"]] == [
        "mempalace-audit.json",
        "mempalace-audit.md",
        "mempalace-mine.json",
    ]
    for entry in manifest["files"]:
        content = (memory_workspace.spec_dir / entry["path"]).read_bytes()
        assert entry["sha256"] == f"sha256:{hashlib.sha256(content).hexdigest()}"


def _stub_refresh_reports(
    workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: _cleanup(workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: _audit(workspace),
    )


def _prepare_detached_cleanup(
    workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    from echelon import mempalace_retarget

    real_rename = mempalace_retarget._atomic_rename_no_replace_at
    interrupted = False

    def interrupt_after_detach(
        parent_fd: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal interrupted
        real_rename(parent_fd, source_name, destination_name)
        if (
            destination_name.startswith(".mempalace-refresh-detached-")
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt("cleanup interrupted after detach")

    monkeypatch.setattr(
        "echelon.mempalace_retarget._atomic_rename_no_replace_at",
        interrupt_after_detach,
    )
    with pytest.raises(KeyboardInterrupt, match="cleanup"):
        refresh_retarget_spec_memory(workspace.root, workspace.spec_dir)
    monkeypatch.setattr(
        "echelon.mempalace_retarget._atomic_rename_no_replace_at",
        real_rename,
    )
    detached = next(
        workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    receipt = workspace.spec_dir / ".mempalace-refresh-cleanup.json"
    assert receipt.is_file()
    return detached, receipt


def _legacy_transaction_copy(
    workspace: MemoryWorkspace,
    source: Path,
) -> Path:
    legacy = workspace.spec_dir / ".mempalace-refresh-legacy-test"
    new_dir = legacy / "new"
    old_dir = legacy / "old"
    new_dir.mkdir(parents=True)
    old_dir.mkdir()
    for entry in source.joinpath("new").iterdir():
        shutil.copy2(entry, new_dir / entry.name)
    records = []
    for name in (
        "mempalace-audit.json",
        "mempalace-audit.md",
        "mempalace-mine.json",
    ):
        content = new_dir.joinpath(name).read_text(encoding="utf-8")
        records.append(
            {
                "path": name,
                "old_present": False,
                "old_sha256": None,
                "new_sha256": (
                    "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                ),
            }
        )
    manifest = new_dir.joinpath(
        "mempalace-refresh-manifest.json"
    ).read_text(encoding="utf-8")
    descriptor = {
        "schema_version": 1,
        "spec_id": workspace.spec_dir.name,
        "files": records,
        "old_manifest_present": False,
        "old_manifest_sha256": None,
        "new_manifest_sha256": (
            "sha256:" + hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        ),
    }
    legacy.joinpath("transaction.json").write_text(
        json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return legacy


def _process_fd_count() -> int:
    fd_root = Path("/dev/fd")
    if not fd_root.is_dir():
        fd_root = Path("/proc/self/fd")
    return len(list(fd_root.iterdir()))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("schema", "child_name"),
    [
        ("legacy", "new"),
        ("legacy", "old"),
        ("v2", "new"),
        ("v2", "old"),
        ("v2", "slots"),
    ],
)
def test_retarget_transaction_reauthenticates_child_after_bound_tree_read(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    schema: str,
    child_name: str,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    from echelon import mempalace_retarget

    completed = next(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    transaction = (
        _legacy_transaction_copy(memory_workspace, completed)
        if schema == "legacy"
        else completed
    )
    child = transaction / child_name
    authentic = memory_workspace.root / f"authentic-{schema}-{child_name}"
    real_manifest = mempalace_retarget._report_manifest
    swapped = False

    def swap_after_tree_read(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            child.rename(authentic)
            shutil.copytree(authentic, child)
        return real_manifest(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._report_manifest",
        swap_after_tree_read,
    )

    with pytest.raises(RetargetMemoryError, match="identity changed|transaction"):
        mempalace_retarget._load_report_transaction(
            memory_workspace.spec_dir,
            transaction_path=transaction,
        )

    assert swapped is True
    assert authentic.is_dir()
    assert child.is_dir()
    assert authentic.stat().st_ino != child.stat().st_ino


@pytest.mark.unit
@pytest.mark.parametrize(
    ("schema", "fail_at"),
    [
        ("legacy", 1),
        ("legacy", 2),
        ("v2", 1),
        ("v2", 2),
        ("v2", 3),
    ],
)
def test_retarget_transaction_parser_closes_partial_child_fd_acquisitions(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    schema: str,
    fail_at: int,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    from echelon import mempalace_retarget

    completed = next(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    transaction = (
        _legacy_transaction_copy(memory_workspace, completed)
        if schema == "legacy"
        else completed
    )
    journal_fd = os.open(
        transaction,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    real_open_child = mempalace_retarget._open_transaction_child
    attempt_calls = 0

    def fail_selected_child(*args, **kwargs):
        nonlocal attempt_calls
        attempt_calls += 1
        if attempt_calls == fail_at:
            raise RetargetMemoryError("injected child open failure")
        return real_open_child(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._open_transaction_child",
        fail_selected_child,
    )
    try:
        baseline = _process_fd_count()
        for _attempt in range(24):
            attempt_calls = 0
            with pytest.raises(RetargetMemoryError, match="injected"):
                mempalace_retarget._parse_bound_report_transaction(
                    spec_id=memory_workspace.spec_dir.name,
                    journal_fd=journal_fd,
                )
        assert _process_fd_count() == baseline
    finally:
        os.close(journal_fd)


@pytest.mark.unit
@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_retarget_staging_closes_partial_child_fd_acquisitions(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: int,
) -> None:
    from echelon import mempalace_retarget

    parent_fd, parent_identity = mempalace_retarget._open_report_parent(
        memory_workspace.spec_dir
    )
    contents = {
        "mempalace-mine.json": "new mine\n",
        "mempalace-audit.json": "new audit\n",
        "mempalace-audit.md": "new markdown\n",
    }
    manifest, _digest = mempalace_retarget._report_manifest(
        spec_id=memory_workspace.spec_dir.name,
        contents=contents,
    )
    real_open_child = mempalace_retarget._open_transaction_child
    attempt_calls = 0

    def fail_selected_child(*args, **kwargs):
        nonlocal attempt_calls
        attempt_calls += 1
        if attempt_calls == fail_at:
            raise RetargetMemoryError("injected staging child open failure")
        return real_open_child(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._open_transaction_child",
        fail_selected_child,
    )
    try:
        baseline = _process_fd_count()
        for _attempt in range(24):
            attempt_calls = 0
            with pytest.raises(RetargetMemoryError, match="injected"):
                mempalace_retarget._stage_report_transaction_at(
                    memory_workspace.spec_dir,
                    parent_fd,
                    parent_identity,
                    spec_id=memory_workspace.spec_dir.name,
                    contents=contents,
                    manifest_content=manifest,
                )
        assert _process_fd_count() == baseline
    finally:
        os.close(parent_fd)


@pytest.mark.unit
def test_retarget_owned_active_loader_closes_parent_after_open_failure(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import mempalace_retarget

    memory_workspace.spec_dir.joinpath(
        ".mempalace-refresh-transaction"
    ).mkdir()
    real_open_entry = mempalace_retarget._open_entry_at

    def fail_active_open(parent_fd: int, name: str, *, directory: bool) -> int:
        if name == ".mempalace-refresh-transaction":
            raise RetargetMemoryError("injected active open failure")
        return real_open_entry(parent_fd, name, directory=directory)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._open_entry_at",
        fail_active_open,
    )
    baseline = _process_fd_count()
    for _attempt in range(24):
        with pytest.raises(RetargetMemoryError, match="injected"):
            mempalace_retarget._load_report_transaction(
                memory_workspace.spec_dir,
            )
    assert _process_fd_count() == baseline


@pytest.mark.unit
def test_retarget_refresh_archives_cleanup_evidence_without_deleting_it(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    recursive_delete_called = False
    receipt_unlink_called = False

    def reject_recursive_delete(_directory_fd: int) -> None:
        nonlocal recursive_delete_called
        recursive_delete_called = True
        raise AssertionError("completed journals must remain append-only")

    real_unlink = os.unlink

    def reject_receipt_unlink(path, *args, **kwargs) -> None:
        nonlocal receipt_unlink_called
        if Path(path).name.startswith(
            (
                ".mempalace-refresh-cleanup",
                ".mempalace-refresh-transaction",
                ".mempalace-refresh-detached-",
                ".mempalace-refresh-completed-",
                ".mempalace-refresh-staging-",
            )
        ):
            receipt_unlink_called = True
            raise AssertionError("completion evidence must remain append-only")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._remove_bound_cleanup_contents",
        reject_recursive_delete,
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.os.unlink",
        reject_receipt_unlink,
    )

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert receipt.status == "pass"
    assert recursive_delete_called is False
    assert receipt_unlink_called is False
    completed_journals = list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    completed_receipts = list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )
    assert len(completed_journals) == 1
    assert {entry.name for entry in completed_journals[0].iterdir()} == {
        "new",
        "old",
        "slots",
        "transaction.json",
    }
    assert len(completed_receipts) == 1
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-cleanup.json"
    ).exists()


@pytest.mark.unit
def test_retarget_refresh_rejects_missing_authenticated_detached_journal(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    detached, active_receipt = _prepare_detached_cleanup(
        memory_workspace,
        monkeypatch,
    )
    moved = memory_workspace.root / "moved-authenticated-journal"
    detached.rename(moved)

    with pytest.raises(RetargetMemoryError, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert moved.is_dir()
    assert active_receipt.is_file()
    assert not list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )


@pytest.mark.unit
def test_retarget_refresh_rejects_byte_identical_active_receipt_replacement(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    _detached, active_receipt = _prepare_detached_cleanup(
        memory_workspace,
        monkeypatch,
    )
    from echelon import mempalace_retarget

    authentic = memory_workspace.root / "authentic-cleanup-receipt.json"
    real_retire = mempalace_retarget._retire_report_cleanup_receipt
    swapped = False

    def swap_before_bound_archive(*args, **kwargs) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            active_receipt.rename(authentic)
            shutil.copy2(authentic, active_receipt)
        real_retire(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._retire_report_cleanup_receipt",
        swap_before_bound_archive,
    )

    with pytest.raises(RetargetMemoryError, match="receipt identity changed"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert swapped is True
    assert authentic.is_file()
    assert active_receipt.is_file()
    assert authentic.stat().st_ino != active_receipt.stat().st_ino


@pytest.mark.unit
def test_retarget_refresh_archives_receipt_through_pinned_parent(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_retire = mempalace_retarget._retire_report_cleanup_receipt
    saved_parent = memory_workspace.root / "saved-canonical-spec"
    replacement_parent = memory_workspace.spec_dir
    replacement_receipt = replacement_parent / ".mempalace-refresh-cleanup.json"
    swapped = False

    def swap_parent_before_receipt_archive(*args, **kwargs) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            replacement_parent.rename(saved_parent)
            replacement_parent.mkdir()
            replacement_receipt.write_text(
                "preserve replacement parent\n",
                encoding="utf-8",
            )
        real_retire(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._retire_report_cleanup_receipt",
        swap_parent_before_receipt_archive,
    )

    with pytest.raises(RetargetMemoryError, match="parent"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert swapped is True
    assert replacement_receipt.read_text(encoding="utf-8") == (
        "preserve replacement parent\n"
    )
    assert len(list(saved_parent.glob(".mempalace-refresh-detached-*"))) == 1
    assert len(
        list(saved_parent.glob(".mempalace-refresh-completed-*.json"))
    ) == 1


@pytest.mark.unit
def test_retarget_refresh_rejects_missing_completed_journal(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    journal = next(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    moved = memory_workspace.root / "moved-completed-journal"
    journal.rename(moved)

    with pytest.raises(RetargetMemoryError, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert moved.is_dir()
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )) == 1


@pytest.mark.unit
def test_retarget_refresh_accumulates_unique_completed_transactions(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    first_journals = {
        path.name
        for path in memory_workspace.spec_dir.glob(
            ".mempalace-refresh-detached-*"
        )
    }
    first_receipts = {
        path.name
        for path in memory_workspace.spec_dir.glob(
            ".mempalace-refresh-completed-*.json"
        )
    }
    monkeypatch.setattr(
        "echelon.mempalace_retarget.render_audit_markdown",
        lambda _audit_report: "# changed replacement audit\n",
    )

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    journals = {
        path.name
        for path in memory_workspace.spec_dir.glob(
            ".mempalace-refresh-detached-*"
        )
    }
    receipts = {
        path.name
        for path in memory_workspace.spec_dir.glob(
            ".mempalace-refresh-completed-*.json"
        )
    }
    assert receipt.status == "pass"
    assert len(journals) == 2
    assert len(receipts) == 2
    assert first_journals < journals
    assert first_receipts < receipts


@pytest.mark.unit
def test_retarget_refresh_rejects_byte_identical_completed_journal_replacement(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch archive validation that reopens a checked pathname."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    from echelon import mempalace_retarget

    journal = next(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )
    authentic = memory_workspace.root / "authentic-completed-journal"
    real_load = mempalace_retarget._load_report_transaction
    swapped = False

    def swap_after_identity_check(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            journal.rename(authentic)
            shutil.copytree(authentic, journal)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._load_report_transaction",
        swap_after_identity_check,
    )

    with pytest.raises(RetargetMemoryError, match="journal|identity|changed"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert swapped is True
    assert authentic.is_dir()
    assert journal.is_dir()
    assert authentic.stat().st_ino != journal.stat().st_ino


@pytest.mark.unit
def test_retarget_refresh_rejects_new_transaction_at_exact_archive_capacity(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch admission that checks only after the bound is exceeded."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    monkeypatch.setattr(
        "echelon.mempalace_retarget._MAX_COMPLETED_REPORT_TRANSACTIONS",
        1,
    )
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.render_audit_markdown",
        lambda _audit_report: "# capacity-changing report\n",
    )

    with pytest.raises(RetargetMemoryError, match="history is full"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )) == 1
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )) == 1
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).exists()


@pytest.mark.unit
def test_retarget_refresh_exact_existing_set_is_idempotent_at_capacity(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    monkeypatch.setattr(
        "echelon.mempalace_retarget._MAX_COMPLETED_REPORT_TRANSACTIONS",
        1,
    )
    first = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    second = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert second.report_set_digest == first.report_set_digest
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )) == 1


@pytest.mark.unit
def test_retarget_refresh_recovers_admitted_transaction_to_exact_capacity(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active journal is recovered before new-capacity admission."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    monkeypatch.setattr(
        "echelon.mempalace_retarget._MAX_COMPLETED_REPORT_TRANSACTIONS",
        1,
    )
    from echelon import mempalace_retarget

    real_remove = mempalace_retarget._remove_report_transaction
    interrupted = False

    def interrupt_after_publication(*args, **kwargs) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("leave admitted transaction active")
        real_remove(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._remove_report_transaction",
        interrupt_after_publication,
    )
    with pytest.raises(KeyboardInterrupt, match="admitted"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )
    monkeypatch.setattr(
        "echelon.mempalace_retarget._remove_report_transaction",
        real_remove,
    )

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert receipt.status == "pass"
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )) == 1
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).exists()


@pytest.mark.unit
def test_retarget_refresh_rejects_active_journal_replacement_before_recovery(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch rollback that validates and later mutates through active names."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_exchange = getattr(
        mempalace_retarget,
        "_exchange_report_entry_at",
        lambda *_args, **_kwargs: None,
    )
    interrupted = False

    def interrupt_publish(*args, **kwargs) -> None:
        nonlocal interrupted
        if (
            kwargs.get("name") == "mempalace-audit.json"
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt("leave active journal")
        real_exchange(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._exchange_report_entry_at",
        interrupt_publish,
        raising=False,
    )
    with pytest.raises(KeyboardInterrupt, match="active journal"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )
    monkeypatch.setattr(
        "echelon.mempalace_retarget._exchange_report_entry_at",
        real_exchange,
        raising=False,
    )

    journal = memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    authentic = memory_workspace.root / "authentic-active-journal"
    real_load = mempalace_retarget._load_report_transaction
    swapped = False

    def swap_bound_active_journal(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            journal.rename(authentic)
            shutil.copytree(authentic, journal)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._load_report_transaction",
        swap_bound_active_journal,
    )

    with pytest.raises(RetargetMemoryError, match="journal|identity|changed"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert swapped is True
    assert authentic.is_dir()
    assert journal.is_dir()


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["publish", "rollback"])
def test_retarget_refresh_parent_replacement_cannot_touch_replacement_tree(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    """The public path may move, but the authenticated parent stays authoritative."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.render_audit_markdown",
        lambda _audit_report: "# parent-bound replacement report\n",
    )
    from echelon import mempalace_retarget

    saved_parent = memory_workspace.root / f"saved-parent-{boundary}"
    replacement_contents = {
        "mempalace-mine.json": "unrelated mine\n",
        "mempalace-audit.json": "unrelated audit\n",
        "mempalace-audit.md": "unrelated markdown\n",
        "mempalace-refresh-manifest.json": "unrelated manifest\n",
        "unrelated.txt": "preserve replacement tree\n",
    }
    swapped = False
    real_parent_check = getattr(
        mempalace_retarget,
        "_require_report_parent_binding",
        lambda *_args, **_kwargs: None,
    )

    def swap_at_boundary(*args, **kwargs):
        nonlocal swapped
        phase = kwargs.get("boundary")
        if phase == boundary and not swapped:
            swapped = True
            memory_workspace.spec_dir.rename(saved_parent)
            memory_workspace.spec_dir.mkdir()
            for name, content in replacement_contents.items():
                memory_workspace.spec_dir.joinpath(name).write_text(
                    content,
                    encoding="utf-8",
                )
        return real_parent_check(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._require_report_parent_binding",
        swap_at_boundary,
        raising=False,
    )

    if boundary == "rollback":
        real_exchange = getattr(
            mempalace_retarget,
            "_exchange_report_entry_at",
            lambda *_args, **_kwargs: None,
        )
        exchanges = 0

        def fail_after_one_exchange(*args, **kwargs):
            nonlocal exchanges
            result = real_exchange(*args, **kwargs)
            exchanges += 1
            if exchanges == 1:
                raise OSError("force descriptor-bound rollback")
            return result

        monkeypatch.setattr(
            "echelon.mempalace_retarget._exchange_report_entry_at",
            fail_after_one_exchange,
            raising=False,
        )

    with pytest.raises(RetargetMemoryError, match="report write|parent"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert swapped is True
    assert {
        name: memory_workspace.spec_dir.joinpath(name).read_text(encoding="utf-8")
        for name in replacement_contents
    } == replacement_contents
    assert saved_parent.is_dir()
    assert (
        saved_parent / ".mempalace-refresh-transaction"
    ).exists() or list(saved_parent.glob(".mempalace-refresh-staging-*"))


@pytest.mark.unit
def test_retarget_refresh_reparses_post_publication_tree_before_archive(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_load = mempalace_retarget._load_report_transaction
    parse_count = 0

    def count_parse(*args, **kwargs):
        nonlocal parse_count
        parse_count += 1
        return real_load(*args, **kwargs)

    real_remove = mempalace_retarget._remove_report_transaction
    mutated = False

    def mutate_before_archive(*args, **kwargs) -> None:
        nonlocal mutated
        transaction = (
            memory_workspace.spec_dir / ".mempalace-refresh-transaction"
        )
        transaction.joinpath("slots", "unexpected-entry").write_text(
            "preserve post-publication mutation\n",
            encoding="utf-8",
        )
        mutated = True
        real_remove(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._load_report_transaction",
        count_parse,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget._remove_report_transaction",
        mutate_before_archive,
    )

    with pytest.raises(RetargetMemoryError, match="transaction|report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert mutated is True
    assert parse_count >= 2
    assert (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).is_dir()
    assert not list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )


@pytest.mark.unit
def test_retarget_refresh_reparses_post_rollback_tree_before_archive(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    old = {
        "mempalace-mine.json": "old mine\n",
        "mempalace-audit.json": "old audit\n",
        "mempalace-audit.md": "old markdown\n",
        "mempalace-refresh-manifest.json": "old manifest\n",
    }
    for name, content in old.items():
        memory_workspace.spec_dir.joinpath(name).write_text(content, encoding="utf-8")
    from echelon import mempalace_retarget

    real_load = mempalace_retarget._load_report_transaction
    parse_count = 0

    def count_parse(*args, **kwargs):
        nonlocal parse_count
        parse_count += 1
        return real_load(*args, **kwargs)

    real_exchange = mempalace_retarget._exchange_report_entry_at
    exchanges = 0

    def fail_after_first_publish(*args, **kwargs):
        nonlocal exchanges
        result = real_exchange(*args, **kwargs)
        exchanges += 1
        if exchanges == 1:
            raise OSError("force rollback before archival reparse")
        return result

    real_remove = mempalace_retarget._remove_report_transaction
    mutated = False

    def mutate_rollback_before_archive(*args, **kwargs) -> None:
        nonlocal mutated
        if kwargs.get("expected_live") == "old":
            transaction = (
                memory_workspace.spec_dir / ".mempalace-refresh-transaction"
            )
            transaction.joinpath("slots", "unexpected-entry").write_text(
                "preserve post-rollback mutation\n",
                encoding="utf-8",
            )
            mutated = True
        real_remove(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._load_report_transaction",
        count_parse,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget._exchange_report_entry_at",
        fail_after_first_publish,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget._remove_report_transaction",
        mutate_rollback_before_archive,
    )

    with pytest.raises(RetargetMemoryError, match="report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert mutated is True
    assert parse_count >= 3
    assert {
        name: memory_workspace.spec_dir.joinpath(name).read_text(encoding="utf-8")
        for name in old
    } == old
    assert (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).is_dir()
    assert not list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )


@pytest.mark.unit
def test_retarget_refresh_retains_failed_staging_evidence(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch staging rollback that recursively erases forensic evidence."""
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_write = getattr(
        mempalace_retarget,
        "_write_transaction_text_at",
        lambda *_args, **_kwargs: None,
    )
    writes = 0
    recursive_delete_called = False

    def fail_staging_write(*args, **kwargs) -> None:
        nonlocal writes
        writes += 1
        real_write(*args, **kwargs)
        if writes == 2:
            raise OSError("staging interrupted")

    real_rmtree = shutil.rmtree

    def reject_recursive_delete(path, *args, **kwargs):
        nonlocal recursive_delete_called
        if Path(path).name.startswith(".mempalace-refresh-staging-"):
            recursive_delete_called = True
            raise AssertionError("staging evidence must remain append-only")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._write_transaction_text_at",
        fail_staging_write,
        raising=False,
    )
    monkeypatch.setattr(shutil, "rmtree", reject_recursive_delete)

    with pytest.raises(RetargetMemoryError, match="report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert recursive_delete_called is False
    assert list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-staging-*")
    )


@pytest.mark.unit
def test_retarget_refresh_rejects_byte_identical_staging_directory_replacement(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_write = mempalace_retarget._write_transaction_text_at
    saved = memory_workspace.root / "authentic-staging-journal"
    replacement: Path | None = None
    writes = 0

    def swap_staging_entry(*args, **kwargs):
        nonlocal replacement, writes
        result = real_write(*args, **kwargs)
        writes += 1
        if writes == 2:
            staging = next(
                memory_workspace.spec_dir.glob(".mempalace-refresh-staging-*")
            )
            staging.rename(saved)
            shutil.copytree(saved, staging)
            replacement = staging
        return result

    monkeypatch.setattr(
        "echelon.mempalace_retarget._write_transaction_text_at",
        swap_staging_entry,
    )

    with pytest.raises(RetargetMemoryError, match="staging|identity|report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert saved.is_dir()
    assert replacement is not None and replacement.is_dir()
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).exists()
    assert not (
        memory_workspace.spec_dir / "mempalace-refresh-manifest.json"
    ).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "failing_name",
    [
        "mempalace-mine.json",
        "mempalace-audit.json",
        "mempalace-audit.md",
        "mempalace-refresh-manifest.json",
    ],
)
def test_retarget_refresh_rolls_back_the_whole_report_set_on_publish_failure(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    failing_name: str,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    old = {
        "mempalace-mine.json": "old mine\n",
        "mempalace-audit.json": "old audit\n",
        "mempalace-audit.md": "old markdown\n",
        "mempalace-refresh-manifest.json": "old manifest\n",
    }
    for name, content in old.items():
        memory_workspace.spec_dir.joinpath(name).write_text(content, encoding="utf-8")
    from echelon import mempalace_retarget

    real_exchange = getattr(
        mempalace_retarget,
        "_exchange_report_entry_at",
        lambda *_args, **_kwargs: None,
    )
    failed = False
    old_manifest_preserved_during_publish = False

    def fail_once(*args, **kwargs) -> None:
        nonlocal failed, old_manifest_preserved_during_publish
        name = kwargs.get("name")
        if name != "mempalace-refresh-manifest.json":
            old_manifest_preserved_during_publish |= (
                memory_workspace.spec_dir.joinpath(
                    "mempalace-refresh-manifest.json"
                ).read_text(encoding="utf-8")
                == old["mempalace-refresh-manifest.json"]
            )
        if name == failing_name and not failed:
            failed = True
            raise OSError("injected report publication failure")
        real_exchange(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._exchange_report_entry_at",
        fail_once,
        raising=False,
    )

    with pytest.raises(RetargetMemoryError, match="report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert failed is True
    if failing_name != "mempalace-mine.json":
        assert old_manifest_preserved_during_publish is True
    assert {
        name: memory_workspace.spec_dir.joinpath(name).read_text(encoding="utf-8")
        for name in old
    } == old
    assert not (memory_workspace.spec_dir / ".mempalace-refresh-transaction").exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "target_name",
    [
        "mempalace-mine.json",
        "mempalace-audit.json",
        "mempalace-audit.md",
        "mempalace-refresh-manifest.json",
    ],
)
def test_retarget_refresh_rejects_symlinked_report_set_member(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    unrelated = memory_workspace.root / "unrelated.txt"
    unrelated.write_text("preserve me\n", encoding="utf-8")
    memory_workspace.spec_dir.joinpath(target_name).symlink_to(unrelated)

    with pytest.raises(RetargetMemoryError, match="report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert unrelated.read_text(encoding="utf-8") == "preserve me\n"
    assert memory_workspace.spec_dir.joinpath(target_name).is_symlink()


@pytest.mark.unit
def test_retarget_refresh_recovers_interrupted_report_publication_on_retry(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_exchange = getattr(
        mempalace_retarget,
        "_exchange_report_entry_at",
        lambda *_args, **_kwargs: None,
    )
    interrupted = False

    def interrupt_once(*args, **kwargs) -> None:
        nonlocal interrupted
        if (
            kwargs.get("name") == "mempalace-audit.json"
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt("simulated crash")
        real_exchange(*args, **kwargs)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._exchange_report_entry_at",
        interrupt_once,
        raising=False,
    )

    with pytest.raises(KeyboardInterrupt, match="simulated crash"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert not (
        memory_workspace.spec_dir / "mempalace-refresh-manifest.json"
    ).exists()
    assert (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).is_dir()

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert receipt.status == "pass"
    assert (
        memory_workspace.spec_dir / "mempalace-refresh-manifest.json"
    ).is_file()
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "cleanup_boundary",
    ["detach", "receipt_archive"],
)
def test_retarget_refresh_recovers_interrupted_transaction_cleanup(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_boundary: str,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    interrupted = False
    real_rename = mempalace_retarget._atomic_rename_no_replace_at

    def interrupt_archive(
        parent_fd: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal interrupted
        is_boundary = (
            cleanup_boundary == "detach"
            and destination_name.startswith(".mempalace-refresh-detached-")
        ) or (
            cleanup_boundary == "receipt_archive"
            and destination_name.startswith(".mempalace-refresh-completed-")
        )
        if is_boundary and not interrupted:
            interrupted = True
            if cleanup_boundary == "receipt_archive":
                real_rename(parent_fd, source_name, destination_name)
            raise KeyboardInterrupt(f"cleanup {cleanup_boundary} interrupted")
        real_rename(parent_fd, source_name, destination_name)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._atomic_rename_no_replace_at",
        interrupt_archive,
    )

    with pytest.raises(KeyboardInterrupt, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    manifest_before_retry = memory_workspace.spec_dir.joinpath(
        "mempalace-refresh-manifest.json"
    ).read_text(encoding="utf-8")
    if cleanup_boundary == "detach":
        assert (
            memory_workspace.spec_dir / ".mempalace-refresh-cleanup.json"
        ).is_file()
    else:
        assert len(list(
            memory_workspace.spec_dir.glob(
                ".mempalace-refresh-completed-*.json"
            )
        )) == 1

    receipt = refresh_retarget_spec_memory(
        memory_workspace.root,
        memory_workspace.spec_dir,
    )

    assert receipt.status == "pass"
    assert memory_workspace.spec_dir.joinpath(
        "mempalace-refresh-manifest.json"
    ).read_text(encoding="utf-8") == manifest_before_retry
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    ).exists()
    assert not (
        memory_workspace.spec_dir / ".mempalace-refresh-cleanup.json"
    ).exists()
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-detached-*")
    )) == 1
    assert len(list(
        memory_workspace.spec_dir.glob(".mempalace-refresh-completed-*.json")
    )) == 1


@pytest.mark.unit
def test_retarget_refresh_rejects_detached_cleanup_symlink_replacement(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    detached, _receipt = _prepare_detached_cleanup(
        memory_workspace,
        monkeypatch,
    )
    saved = memory_workspace.root / "saved-authenticated-journal"
    detached.rename(saved)
    unrelated = memory_workspace.root / "unrelated-cleanup-target"
    unrelated.mkdir()
    unrelated.joinpath("preserve.txt").write_text("preserve me\n", encoding="utf-8")
    detached.symlink_to(unrelated, target_is_directory=True)

    with pytest.raises(RetargetMemoryError, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert unrelated.joinpath("preserve.txt").read_text(
        encoding="utf-8"
    ) == "preserve me\n"
    assert saved.is_dir()
    assert detached.is_symlink()


@pytest.mark.unit
def test_retarget_refresh_rejects_forged_cleanup_receipt_relabel(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    detached, _receipt = _prepare_detached_cleanup(
        memory_workspace,
        monkeypatch,
    )
    detached.rename(memory_workspace.root / "saved-authenticated-journal")
    forged = memory_workspace.spec_dir / (
        ".mempalace-refresh-detached-" + "f" * 64
    )
    forged.mkdir()
    forged.joinpath("preserve.txt").write_text("preserve me\n", encoding="utf-8")
    forged_identity = forged.stat(follow_symlinks=False)
    receipt_path = (
        memory_workspace.spec_dir / ".mempalace-refresh-cleanup.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["cleanup_name"] = forged.name
    receipt["device"] = forged_identity.st_dev
    receipt["inode"] = forged_identity.st_ino
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RetargetMemoryError, match="cleanup receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert forged.joinpath("preserve.txt").read_text(
        encoding="utf-8"
    ) == "preserve me\n"


@pytest.mark.unit
def test_retarget_refresh_rejects_multiple_detached_cleanup_artifacts(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    _prepare_detached_cleanup(memory_workspace, monkeypatch)
    extra = memory_workspace.spec_dir / (
        ".mempalace-refresh-detached-" + "f" * 64
    )
    extra.mkdir()
    extra.joinpath("preserve.txt").write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(RetargetMemoryError, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert extra.joinpath("preserve.txt").read_text(encoding="utf-8") == "preserve me\n"


@pytest.mark.unit
def test_retarget_refresh_reauthenticates_active_journal_before_cleanup(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    from echelon import mempalace_retarget

    real_rename = mempalace_retarget._atomic_rename_no_replace_at
    interrupted = False

    def interrupt_detach(
        parent_fd: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal interrupted
        if (
            destination_name.startswith(".mempalace-refresh-detached-")
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt("cleanup interrupted")
        real_rename(parent_fd, source_name, destination_name)

    monkeypatch.setattr(
        "echelon.mempalace_retarget._atomic_rename_no_replace_at",
        interrupt_detach,
    )
    with pytest.raises(KeyboardInterrupt, match="cleanup"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    transaction = memory_workspace.spec_dir / ".mempalace-refresh-transaction"
    descriptor = transaction / "transaction.json"
    malformed = '{"schema_version": 1, "schema_version": 1}\n'
    descriptor.write_text(malformed, encoding="utf-8")
    receipt_path = (
        memory_workspace.spec_dir / ".mempalace-refresh-cleanup.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    transaction_sha256 = (
        "sha256:" + hashlib.sha256(malformed.encode("utf-8")).hexdigest()
    )
    receipt["transaction_sha256"] = transaction_sha256
    receipt["cleanup_name"] = mempalace_retarget._report_cleanup_name(
        transaction_sha256=transaction_sha256,
        expected_live=receipt["expected_live"],
        device=receipt["device"],
        inode=receipt["inode"],
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RetargetMemoryError, match="transaction is invalid"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert transaction.is_dir()
    assert receipt_path.is_file()


@pytest.mark.unit
def test_retarget_refresh_rejects_symlinked_cleanup_receipt(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_refresh_reports(memory_workspace, monkeypatch)
    unrelated = memory_workspace.root / "unrelated-cleanup-receipt.json"
    unrelated.write_text("preserve me\n", encoding="utf-8")
    memory_workspace.spec_dir.joinpath(
        ".mempalace-refresh-cleanup.json"
    ).symlink_to(unrelated)

    with pytest.raises(RetargetMemoryError, match="report write"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert unrelated.read_text(encoding="utf-8") == "preserve me\n"


@pytest.mark.unit
def test_retarget_refresh_rejects_unavailable_configured_memory(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: _cleanup(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: _audit(memory_workspace, status="unavailable"),
    )

    with pytest.raises(RetargetMemoryError, match="audit"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_refresh_stops_before_cleanup_when_mine_is_incomplete(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = replace(_complete_mine(memory_workspace), status="partial")
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: mine,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: pytest.fail("cleanup is forbidden"),
    )

    with pytest.raises(RetargetMemoryError, match="mine"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "mine",
    [
        lambda workspace: replace(
            _complete_mine(workspace),
            schema_version=2,
        ),
        lambda workspace: replace(
            _complete_mine(workspace),
            errors=["unexpected_complete_error"],
        ),
    ],
)
def test_retarget_refresh_rejects_inconsistent_complete_mine_receipt(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    mine,
) -> None:
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: pytest.fail("cleanup is forbidden"),
    )

    with pytest.raises(RetargetMemoryError, match="mine receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_refresh_rejects_mine_serializer_with_document_text(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = _complete_mine(memory_workspace)
    mine = SimpleNamespace(
        **complete.__dict__,
        to_dict=lambda: {
            **complete.to_dict(),
            "document": "must-not-enter-a-retarget-report",
        },
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: mine,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: pytest.fail("cleanup is forbidden"),
    )

    with pytest.raises(RetargetMemoryError, match="mine receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )

    assert not (memory_workspace.spec_dir / "mempalace-mine.json").exists()


@pytest.mark.unit
def test_retarget_refresh_rejects_cleanup_that_deletes_current_drawer(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = replace(
        _cleanup(memory_workspace),
        deleted_count=1,
        deleted_ids=["new-drawer"],
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: cleanup,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: pytest.fail("audit is forbidden"),
    )

    with pytest.raises(RetargetMemoryError, match="cleanup receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_refresh_rejects_type_confused_cleanup_count(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = replace(
        _cleanup(memory_workspace),
        deleted_count=True,
        deleted_ids=["old-drawer"],
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: cleanup,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: _audit(memory_workspace),
    )

    with pytest.raises(RetargetMemoryError, match="cleanup receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_refresh_rejects_type_confused_audit_counts(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = replace(
        _audit(memory_workspace),
        expected_count=True,
        present_current_count=True,
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: _cleanup(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: audit,
    )

    with pytest.raises(RetargetMemoryError, match="audit receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_refresh_rejects_audit_errors_despite_warn_status(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = replace(
        _audit(memory_workspace, status="warn"),
        errors=["malformed_scan_response"],
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: _cleanup(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: audit,
    )

    with pytest.raises(RetargetMemoryError, match="audit receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes",
    [
        {"missing": ["hidden"]},
        {"stale": ["hidden"]},
        {"wrong_wing": ["hidden"]},
        {"wrong_room": ["hidden"]},
        {"duplicate": ["hidden"]},
        {"non_canonical": ["hidden"]},
        {"lifecycle_excluded": ["hidden"]},
        {"recommendations": ["bounded_extra_scan_unsupported"]},
        {"missing": ("hidden",)},
        {"retrieval_probe": {"status": "fail", "checked": 0}},
        {"retrieval_probe": {"status": "warn", "checked": True}},
        {"retrieval_probe": {"status": "warn", "checked": 0, "error": "hidden"}},
        {"status": "pass"},
        {
            "status": "pass",
            "retrieval_probe": {"status": "pass", "checked": 0},
        },
        {
            "status": "warn",
            "retrieval_probe": {"status": "pass", "checked": 1},
        },
    ],
)
def test_retarget_refresh_rejects_inconsistent_audit_fields(
    memory_workspace: MemoryWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    audit = replace(_audit(memory_workspace), **changes)
    monkeypatch.setattr(
        "echelon.mempalace_retarget.mine_spec_requirements",
        lambda *_args, **_kwargs: _complete_mine(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.cleanup_stale_spec_memory",
        lambda *_args, **_kwargs: _cleanup(memory_workspace),
    )
    monkeypatch.setattr(
        "echelon.mempalace_retarget.audit_spec_memory",
        lambda *_args, **_kwargs: audit,
    )

    with pytest.raises(RetargetMemoryError, match="audit receipt"):
        refresh_retarget_spec_memory(
            memory_workspace.root,
            memory_workspace.spec_dir,
        )


@pytest.mark.unit
def test_retarget_context_filter_excludes_only_selected_spec_without_mutation() -> None:
    from codegen.memory.mempalace_reader import DrawerResult

    drawers = [
        DrawerResult(
            drawer_id="selected",
            content="old selected spec",
            room="functional-requirements",
            wing="demo",
            distance=0.1,
            metadata={
                "spec_id": "001-demo",
                "artifact_path": "specs/001-demo/spec.md",
            },
        ),
        DrawerResult(
            drawer_id="workspace-re",
            content="workspace RE",
            room="re-workspace-context",
            wing="demo",
            distance=0.2,
            metadata={"artifact_path": "re/workspace/overview.md"},
        ),
        DrawerResult(
            drawer_id="other-spec",
            content="other spec",
            room="functional-requirements",
            wing="demo",
            distance=0.3,
            metadata={
                "spec_id": "002-other",
                "artifact_path": "specs/002-other/spec.md",
            },
        ),
    ]
    original = list(drawers)

    filtered = exclude_retarget_spec_drawers(drawers, "001-demo")

    assert [drawer.drawer_id for drawer in filtered] == [
        "workspace-re",
        "other-spec",
    ]
    assert drawers == original
    assert all(
        observed is expected for observed, expected in zip(drawers, original)
    )


@pytest.mark.unit
def test_retarget_context_filter_rejects_contradictory_metadata() -> None:
    from codegen.memory.mempalace_reader import DrawerResult

    drawers = [
        DrawerResult(
            drawer_id="contradictory",
            content="old",
            room="functional-requirements",
            wing="demo",
            distance=0.1,
            metadata={
                "spec_id": "002-other",
                "artifact_path": "specs/001-demo/spec.md",
            },
        )
    ]

    with pytest.raises(RetargetMemoryError, match="ownership metadata"):
        exclude_retarget_spec_drawers(drawers, "001-demo")

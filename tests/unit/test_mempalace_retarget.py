from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
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

    def get(
        self,
        *,
        where: dict[str, object],
        include: list[str],
        limit: int,
        offset: int,
    ) -> dict[str, object]:
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

    def delete(self, *, ids: list[str]) -> dict[str, int]:
        self.deleted_batches.append(tuple(ids))
        deleted = 0
        if not self.ignore_delete:
            selected = ids[: self.delete_limit] if self.delete_limit is not None else ids
            for drawer_id in selected:
                if self.rows.pop(drawer_id, None) is not None:
                    deleted += 1
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
        {"wing": "demo", "artifact_path": ["specs/001-demo/spec.md"]},
        {"wing": "demo", "spec_id": 1},
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
def test_retarget_purge_receipt_is_stable_and_contains_no_document_text(
    memory_workspace: MemoryWorkspace,
) -> None:
    secret_document = "do-not-copy-this-document"
    memory_workspace.collection.rows = {
        "owned-b": (
            secret_document,
            {"wing": "demo", "spec_id": "001-demo"},
        ),
        "owned-a": (
            secret_document,
            {"wing": "demo", "spec_id": "001-demo"},
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


def _audit(workspace: MemoryWorkspace, *, status: str = "pass"):
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

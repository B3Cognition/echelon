from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest


def _transaction(root: Path):
    from harness.publication_transaction import PublicationOperation, PublicationTransaction

    stage = root / "re/.staging/owner"
    (stage / "new/first").parent.mkdir(parents=True)
    (stage / "new/first").write_text("new-first\n", encoding="utf-8")
    (stage / "new/second").write_text("new-second\n", encoding="utf-8")
    return PublicationTransaction(
        workspace_root=root / "re",
        staging_root=stage,
        journal=stage / "rollback-journal.json",
        operations=(
            PublicationOperation(PurePosixPath("first"), PurePosixPath("new/first")),
            PublicationOperation(PurePosixPath("second"), PurePosixPath("new/second")),
            PublicationOperation(PurePosixPath("removed"), None),
        ),
    )


@pytest.mark.unit
def test_transaction_replaces_deletes_and_rolls_back_exact_bytes(tmp_path: Path) -> None:
    from harness.publication_transaction import (
        apply_publication_transaction,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("old-first\n", encoding="utf-8")
    (root / "second").write_text("old-second\n", encoding="utf-8")
    (root / "removed").write_text("old-removed\n", encoding="utf-8")
    transaction = _transaction(tmp_path)

    apply_publication_transaction(transaction)
    assert (root / "first").read_text() == "new-first\n"
    assert (root / "second").read_text() == "new-second\n"
    assert not (root / "removed").exists()

    rollback_publication_transaction(transaction)
    assert (root / "first").read_text() == "old-first\n"
    assert (root / "second").read_text() == "old-second\n"
    assert (root / "removed").read_text() == "old-removed\n"


@pytest.mark.unit
def test_transaction_failure_rolls_back_and_leaves_unrelated_files(tmp_path: Path) -> None:
    from harness.publication_transaction import apply_publication_transaction

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("old-first\n", encoding="utf-8")
    (root / "second").write_text("old-second\n", encoding="utf-8")
    (root / "removed").write_text("old-removed\n", encoding="utf-8")
    (root / "unrelated").write_text("keep\n", encoding="utf-8")
    transaction = _transaction(tmp_path)

    def fail(point: str) -> None:
        if point == "before_replace:second":
            raise OSError("stop")

    with pytest.raises(OSError, match="stop"):
        apply_publication_transaction(transaction, fault_hook=fail)
    assert (root / "first").read_text() == "old-first\n"
    assert (root / "second").read_text() == "old-second\n"
    assert (root / "removed").read_text() == "old-removed\n"
    assert (root / "unrelated").read_text() == "keep\n"


@pytest.mark.unit
def test_transaction_rejects_unsafe_and_duplicate_final_paths(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationOperation, PublicationTransaction, PublicationTransactionError

    stage = tmp_path / "re/.staging/owner"
    stage.mkdir(parents=True)
    with pytest.raises(PublicationTransactionError, match="unsafe"):
        PublicationOperation(PurePosixPath("../outside"), None)
    with pytest.raises(PublicationTransactionError, match="duplicate"):
        PublicationTransaction(
            workspace_root=tmp_path / "re",
            staging_root=stage,
            journal=stage / "rollback-journal.json",
            operations=(
                PublicationOperation(PurePosixPath("same"), None),
                PublicationOperation(PurePosixPath("same"), None),
            ),
        )


@pytest.mark.unit
def test_transaction_rejects_unsafe_recovery_journal(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationTransaction, PublicationTransactionError

    stage = tmp_path / "re/.staging/owner"
    stage.mkdir(parents=True)
    journal = stage / "rollback-journal.json"
    journal.write_text(
        '{"schema_version":1,"operations":[{"final":"../outside","staged":null,"backup":"rollback/../outside","backed_up":false,"installed":false}]}',
        encoding="utf-8",
    )
    with pytest.raises(PublicationTransactionError, match="unsafe"):
        PublicationTransaction.from_journal(
            workspace_root=tmp_path / "re", staging_root=stage, journal=journal
        )


@pytest.mark.unit
@pytest.mark.parametrize("checkpoint", ("after_backup_intent:first", "after_backup_rename:first", "after_install_intent:first", "after_install_rename:first"))
def test_crash_windows_leave_a_recoverable_write_ahead_journal(tmp_path: Path, checkpoint: str) -> None:
    from harness.publication_transaction import (
        PublicationTransaction,
        apply_publication_transaction,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("old-first\n", encoding="utf-8")
    transaction = _transaction(tmp_path)

    class Crash(BaseException):
        pass

    def crash(point: str) -> None:
        if point == checkpoint:
            raise Crash()

    with pytest.raises(Crash):
        apply_publication_transaction(transaction, fault_hook=crash)
    recovered = PublicationTransaction.from_journal(
        workspace_root=root, staging_root=transaction.staging_root, journal=transaction.journal
    )
    rollback_publication_transaction(recovered)
    assert (root / "first").read_text(encoding="utf-8") == "old-first\n"


@pytest.mark.unit
def test_transaction_rejects_overlapping_and_staging_alias_paths(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationOperation, PublicationTransaction, PublicationTransactionError

    root = tmp_path / "re"
    stage = root / ".staging/owner"
    stage.mkdir(parents=True)
    (stage / "new/a").parent.mkdir(parents=True)
    (stage / "new/a").write_text("new\n", encoding="utf-8")
    with pytest.raises(PublicationTransactionError, match="overlap"):
        PublicationTransaction(root, stage, stage / "rollback-journal.json", (
            PublicationOperation(PurePosixPath("sources"), None),
            PublicationOperation(PurePosixPath("sources/api"), None),
        ))
    with pytest.raises(PublicationTransactionError, match="staging"):
        PublicationTransaction(root, stage, stage / "rollback-journal.json", (
            PublicationOperation(PurePosixPath(".staging/owner/unsafe"), None),
        ))
    with pytest.raises(PublicationTransactionError, match="overlap"):
        PublicationTransaction(root, stage, stage / "rollback-journal.json", (
            PublicationOperation(PurePosixPath("one"), PurePosixPath("new/a")),
            PublicationOperation(PurePosixPath("two"), PurePosixPath("new/a/child")),
        ))
    with pytest.raises(PublicationTransactionError, match="backup"):
        PublicationTransaction(root, stage, stage / "rollback-journal.json", (
            PublicationOperation(PurePosixPath("one"), PurePosixPath("rollback/one")),
        ))
    with pytest.raises(PublicationTransactionError, match="journal"):
        PublicationTransaction(root, stage, stage / "new/a", (
            PublicationOperation(PurePosixPath("one"), PurePosixPath("new/a")),
        ))


@pytest.mark.unit
def test_transaction_rejects_tampered_staged_artifact_before_install(tmp_path: Path) -> None:
    from harness.publication_transaction import apply_publication_transaction

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("old-first\n", encoding="utf-8")
    transaction = _transaction(tmp_path)
    (transaction.staging_root / "new/first").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(Exception, match="staged artifact"):
        apply_publication_transaction(transaction)
    assert (root / "first").read_text(encoding="utf-8") == "old-first\n"


@pytest.mark.unit
def test_legacy_journal_restores_backup_after_rename_before_boolean_persistence(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationTransaction, rollback_publication_transaction

    root = tmp_path / "re"
    root.mkdir()
    stage = root / ".staging/legacy"
    backup = stage / "rollback/first"
    backup.parent.mkdir(parents=True)
    backup.write_text("old-first\n", encoding="utf-8")
    (stage / "new").mkdir()
    (stage / "new/first").write_text("new-first\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text('{"schema_version":1,"status":"replacing","operations":[{"final":"first","staged":"new/first","backup":"rollback/first","backed_up":false,"installed":false}]}', encoding="utf-8")
    transaction = PublicationTransaction.from_journal(workspace_root=root, staging_root=stage, journal=journal)
    rollback_publication_transaction(transaction)
    assert (root / "first").read_text(encoding="utf-8") == "old-first\n"


@pytest.mark.unit
def test_rollback_refuses_unrelated_replacement_and_preserves_journal(tmp_path: Path) -> None:
    from harness.publication_transaction import apply_publication_transaction, rollback_publication_transaction, PublicationTransactionError

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("old-first\n", encoding="utf-8")
    transaction = _transaction(tmp_path)
    apply_publication_transaction(transaction)
    (root / "first").write_text("unrelated\n", encoding="utf-8")
    with pytest.raises(PublicationTransactionError, match="refuses"):
        rollback_publication_transaction(transaction)
    assert (root / "first").read_text(encoding="utf-8") == "unrelated\n"
    assert transaction.journal.is_file()


@pytest.mark.unit
@pytest.mark.parametrize("backed_up, installed, final_present, backup_present", ((True, False, True, True), (False, False, True, False)))
def test_legacy_journal_reconciles_deterministic_install_crash_windows(tmp_path: Path, backed_up: bool, installed: bool, final_present: bool, backup_present: bool) -> None:
    from harness.publication_transaction import PublicationTransaction, rollback_publication_transaction
    root = tmp_path / "re"; root.mkdir(); stage = root / ".staging/legacy"; stage.mkdir(parents=True)
    if final_present: (root / "first").write_text("new\n", encoding="utf-8")
    if backup_present:
        backup = stage / "rollback/first"; backup.parent.mkdir(parents=True); backup.write_text("old\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text(json.dumps({"schema_version": 1, "status": "replacing", "operations": [{"final": "first", "staged": "new/first", "backup": "rollback/first", "backed_up": backed_up, "installed": installed}]}), encoding="utf-8")
    transaction = PublicationTransaction.from_journal(workspace_root=root, staging_root=stage, journal=journal)
    rollback_publication_transaction(transaction)
    if backup_present:
        assert (root / "first").read_text(encoding="utf-8") == "old\n"
    else:
        assert not (root / "first").exists()


@pytest.mark.unit
def test_directory_digest_distinguishes_tree_shape_before_install(tmp_path: Path) -> None:
    from harness.publication_transaction import apply_publication_transaction, PublicationTransactionError
    root = tmp_path / "re"; root.mkdir(); (root / "first").write_text("old\n", encoding="utf-8")
    transaction = _transaction(tmp_path)
    staged = transaction.staging_root / "new/first"; staged.unlink(); staged.mkdir(); (staged / "ab").write_text("c", encoding="utf-8")
    with pytest.raises(PublicationTransactionError, match="changed"):
        apply_publication_transaction(transaction)


@pytest.mark.unit
def test_legacy_restored_original_and_missing_or_stray_backups_do_not_mutate(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationOperation, PublicationTransaction, PublicationTransactionError, rollback_publication_transaction
    root = tmp_path / "re"; root.mkdir(); stage = root / ".staging/legacy"; stage.mkdir(parents=True)
    (root / "first").write_text("old\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text(json.dumps({"schema_version": 1, "status": "replacing", "operations": [{"final": "first", "staged": "new/first", "backup": "rollback/first", "backed_up": True, "installed": True}]}), encoding="utf-8")
    transaction = PublicationTransaction.from_journal(workspace_root=root, staging_root=stage, journal=journal)
    rollback_publication_transaction(transaction)
    assert (root / "first").read_text(encoding="utf-8") == "old\n"
    # A new-journal replacement missing its backup must fail before deleting final bytes.
    stage2 = root / ".staging/new"; stage2.mkdir(parents=True); (stage2 / "new/first").parent.mkdir(exist_ok=True); (stage2 / "new/first").write_text("new\n")
    transaction2 = PublicationTransaction(root, stage2, stage2 / "rollback-journal.json", (PublicationOperation(PurePosixPath("first"), PurePosixPath("new/first")),))
    transaction2._states[0].update({"phase": "installed", "had_final": True})
    with pytest.raises(PublicationTransactionError, match="backup"):
        rollback_publication_transaction(transaction2)
    assert (root / "first").read_text(encoding="utf-8") == "old\n"
    # A no-original operation must not consume a backup that it never owned.
    stage3 = root / ".staging/stray"; stage3.mkdir(parents=True)
    (stage3 / "new/first").parent.mkdir(exist_ok=True)
    (stage3 / "new/first").write_text("new\n", encoding="utf-8")
    backup = stage3 / "rollback/first"; backup.parent.mkdir(); backup.write_text("stray\n", encoding="utf-8")
    transaction3 = PublicationTransaction(root, stage3, stage3 / "rollback-journal.json", (PublicationOperation(PurePosixPath("first"), PurePosixPath("new/first")),))
    transaction3._states[0].update({"phase": "installed", "had_final": False})
    with pytest.raises(PublicationTransactionError, match="stray"):
        rollback_publication_transaction(transaction3)
    assert (root / "first").read_text(encoding="utf-8") == "old\n"
    assert backup.read_text(encoding="utf-8") == "stray\n"


@pytest.mark.unit
def test_legacy_rollback_resumes_after_removing_installed_final(tmp_path: Path) -> None:
    from harness.publication_transaction import PublicationTransaction, rollback_publication_transaction

    root = tmp_path / "re"
    root.mkdir()
    stage = root / ".staging/legacy"
    backup = stage / "rollback/first"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "rolling_back",
                "operations": [
                    {
                        "final": "first",
                        "staged": "new/first",
                        "backup": "rollback/first",
                        "backed_up": True,
                        "installed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    transaction = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )
    rollback_publication_transaction(transaction)

    assert (root / "first").read_text(encoding="utf-8") == "old\n"
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "rolled_back"


@pytest.mark.unit
def test_legacy_rollback_remains_reloadable_after_restore_intent_interruption(
    tmp_path: Path,
) -> None:
    from harness.publication_transaction import (
        PublicationTransaction,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    stage = root / ".staging/legacy"
    backup = stage / "rollback/first"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "rolling_back",
                "operations": [
                    {
                        "final": "first",
                        "staged": "new/first",
                        "backup": "rollback/first",
                        "backed_up": True,
                        "installed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    transaction = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )

    class Interrupted(BaseException):
        pass

    def interrupt_before_restore(point: str) -> None:
        if point == "before_restore:first":
            raise Interrupted()

    with pytest.raises(Interrupted):
        rollback_publication_transaction(
            transaction,
            fault_hook=interrupt_before_restore,
        )

    rewritten = json.loads(journal.read_text(encoding="utf-8"))
    assert rewritten["operations"][0]["legacy"] is True
    resumed = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )
    rollback_publication_transaction(resumed)

    assert (root / "first").read_text(encoding="utf-8") == "old\n"
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "rolled_back"


@pytest.mark.unit
def test_rewritten_legacy_journal_rejects_forged_deletion_states(tmp_path: Path) -> None:
    from harness.publication_transaction import (
        PublicationTransaction,
        PublicationTransactionError,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("unrelated\n", encoding="utf-8")
    stage = root / ".staging/legacy"
    stage.mkdir(parents=True)
    backup = stage / "rollback/first"
    backup.parent.mkdir()
    backup.write_text("old\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    base = {
        "final": "first",
        "staged": "new/first",
        "backup": "rollback/first",
        "backed_up": True,
        "installed": True,
        "phase": "installed",
        "had_final": True,
        "staged_digest": None,
        "legacy": True,
    }

    journal.write_text(
        json.dumps({"schema_version": 1, "status": "rolling_back", "operations": [base]}),
        encoding="utf-8",
    )
    with pytest.raises(PublicationTransactionError, match="ownership digest"):
        PublicationTransaction.from_journal(
            workspace_root=root,
            staging_root=stage,
            journal=journal,
        )

    contradictory = {**base, "backed_up": False, "rollback_digest": "sha256:" + "0" * 64}
    journal.write_text(
        json.dumps({"schema_version": 1, "status": "rolling_back", "operations": [contradictory]}),
        encoding="utf-8",
    )
    with pytest.raises(PublicationTransactionError, match="contradict"):
        PublicationTransaction.from_journal(
            workspace_root=root,
            staging_root=stage,
            journal=journal,
        )

    forged = {**base, "rollback_digest": "sha256:" + "0" * 64}
    journal.write_text(
        json.dumps({"schema_version": 1, "status": "rolling_back", "operations": [forged]}),
        encoding="utf-8",
    )
    transaction = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )
    with pytest.raises(PublicationTransactionError, match="refuses"):
        rollback_publication_transaction(transaction)
    assert (root / "first").read_text(encoding="utf-8") == "unrelated\n"


@pytest.mark.unit
def test_raw_legacy_normalization_reloads_all_operations_after_first_journal_write(
    tmp_path: Path,
) -> None:
    from harness.publication_transaction import (
        PublicationTransaction,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("new-first\n", encoding="utf-8")
    (root / "second").write_text("new-second\n", encoding="utf-8")
    stage = root / ".staging/legacy"
    first_backup = stage / "rollback/first"
    first_backup.parent.mkdir(parents=True)
    first_backup.write_text("old-first\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "replacing",
                "operations": [
                    {
                        "final": "first",
                        "staged": "new/first",
                        "backup": "rollback/first",
                        "backed_up": True,
                        "installed": True,
                    },
                    {
                        "final": "second",
                        "staged": "new/second",
                        "backup": "rollback/second",
                        "backed_up": False,
                        "installed": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    transaction = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )

    class Interrupted(BaseException):
        pass

    def interrupt_after_normalization(point: str) -> None:
        if point == "after_legacy_normalized":
            raise Interrupted()

    with pytest.raises(Interrupted):
        rollback_publication_transaction(
            transaction,
            fault_hook=interrupt_after_normalization,
        )

    rewritten = json.loads(journal.read_text(encoding="utf-8"))
    assert rewritten["status"] == "rolling_back"
    assert all(row["legacy"] is True for row in rewritten["operations"])
    assert all(row["rollback_digest"] for row in rewritten["operations"])
    resumed = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )
    rollback_publication_transaction(resumed)

    assert (root / "first").read_text(encoding="utf-8") == "old-first\n"
    assert not (root / "second").exists()
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "rolled_back"


@pytest.mark.unit
def test_invalid_raw_legacy_operation_prevents_any_normalization_or_mutation(
    tmp_path: Path,
) -> None:
    from harness.publication_transaction import (
        PublicationTransaction,
        PublicationTransactionError,
        rollback_publication_transaction,
    )

    root = tmp_path / "re"
    root.mkdir()
    (root / "first").write_text("new-first\n", encoding="utf-8")
    (root / "second").write_text("new-second\n", encoding="utf-8")
    stage = root / ".staging/legacy"
    first_backup = stage / "rollback/first"
    second_backup = stage / "rollback/second"
    first_backup.parent.mkdir(parents=True)
    first_backup.write_text("old-first\n", encoding="utf-8")
    second_backup.write_text("old-second\n", encoding="utf-8")
    journal = stage / "rollback-journal.json"
    raw = {
        "schema_version": 1,
        "status": "replacing",
        "operations": [
            {
                "final": "first",
                "staged": "new/first",
                "backup": "rollback/first",
                "backed_up": True,
                "installed": True,
            },
            {
                "final": "second",
                "staged": "new/second",
                "backup": "rollback/second",
                "backed_up": False,
                "installed": False,
            },
        ],
    }
    journal.write_text(json.dumps(raw), encoding="utf-8")
    before_journal = journal.read_bytes()
    transaction = PublicationTransaction.from_journal(
        workspace_root=root,
        staging_root=stage,
        journal=journal,
    )

    with pytest.raises(PublicationTransactionError, match="ambiguous"):
        rollback_publication_transaction(transaction)

    assert journal.read_bytes() == before_journal
    assert (root / "first").read_text(encoding="utf-8") == "new-first\n"
    assert (root / "second").read_text(encoding="utf-8") == "new-second\n"
    assert first_backup.read_text(encoding="utf-8") == "old-first\n"
    assert second_backup.read_text(encoding="utf-8") == "old-second\n"

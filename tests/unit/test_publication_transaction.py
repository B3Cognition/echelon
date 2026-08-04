from __future__ import annotations

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

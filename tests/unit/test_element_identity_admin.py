from contextlib import closing
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


ROOT = Path(__file__).parents[2]
DATABASE = Path(".echelon/identity/registry.sqlite3")
HASH = hashlib.sha256(b"report bytes").hexdigest()


def database_rows(workspace):
    with closing(sqlite3.connect(workspace / DATABASE)) as connection:
        return tuple(connection.iterdump())


def authority_files(workspace):
    directory = workspace / ".echelon/identity"
    return tuple((path.name, path.read_bytes()) for path in sorted(directory.iterdir()))


def run_admin(*arguments):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "harness.element_identity_admin", *map(str, arguments)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def assert_failed(result):
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr


def seed_complete_authority(workspace):
    store = IdentityStore.initialize(workspace)
    store.reserve(spec_id="demo", kind="AC", operation_id="allocate-ac", count=2)
    store.reserve(spec_id="demo", kind="ISS", operation_id="allocate-iss", count=1)
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create-ac",
        changes=(ElementCreate("AC-000001", "Movement", "Move safely.", "allocate-ac"),),
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create-iss",
        changes=(ElementCreate("ISS-000001", "Movement", "Move safely.", "allocate-iss"),),
    )
    store.record_reference_claims(
        spec_id="demo",
        operation_id="reference",
        claims=(ReferenceClaim("evidence.md", HASH, "E1", "AC-000001", "1", "evidence"),),
    )
    store.record_issue_occurrences(
        spec_id="demo",
        operation_id="occurrence",
        occurrences=(IssueOccurrence(
            "ISS-000001", "1", "report-1", HASH, "ISS-historical",
            "Movement", "Move safely.",
        ),),
    )
    store.import_identities(
        spec_id="unseen",
        operation_id="remote-import",
        definitions=(("FR-001", "Outside recently accessed spec"),),
    )
    return store


def test_audit_reports_exact_authority_without_mutation(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(
        spec_id="demo",
        operation_id="import",
        definitions=(("FR-001", "Scene"),),
    )
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000002"
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        before = tuple(connection.iterdump())
    result = store.audit()
    assert set(result) == {
        "report_version", "authority", "database_schema_version", "table_counts",
    }
    assert result["report_version"] == 1
    assert result["database_schema_version"] == "6"
    marker = json.loads((tmp_path / ".echelon/identity/authority.json").read_text())
    assert result["authority"] == marker
    assert result["table_counts"]["entities"] == "1"
    assert result["table_counts"]["reservations"] == "1"
    assert result["table_counts"]["revisions"] == "0"
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        assert tuple(connection.iterdump()) == before


def test_audit_uses_one_query_only_transaction_and_returns_detached_report(tmp_path, monkeypatch):
    store = seed_complete_authority(tmp_path)
    original_transaction = store._transaction
    observed = []

    @contextmanager
    def transaction(*, write=False):
        observed.append(write)
        with original_transaction(write=write) as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    monkeypatch.setattr(store, "_transaction", transaction)
    report = store.audit()
    assert observed == [False]
    assert report["table_counts"] == {
        "counters": "3",
        "operations": "7",
        "reservations": "2",
        "entities": "3",
        "revisions": "2",
        "lifecycle_heads": "3",
        "lifecycle_lineage": "0",
        "lifecycle_receipts": "2",
        "reference_claims": "1",
        "issue_occurrences": "1",
        "binding_receipts": "2",
        "publication_intents": "0",
        "publication_operation_claims": "0",
        "source_contexts": "0",
        "source_publications": "0",
        "managed_identity_specs": "0",
    }
    report["authority"]["epoch_uuid"] = "changed"
    report["table_counts"]["entities"] = "999"
    fresh = store.audit()
    assert fresh["authority"]["epoch_uuid"] != "changed"
    assert fresh["table_counts"]["entities"] == "3"
    assert observed == [False, False]


@pytest.mark.parametrize("damage", [
    "DELETE FROM counters WHERE spec_id='demo' AND kind='AC'",
    "UPDATE entities SET kind='AC' WHERE spec_id='unseen' AND element_id='FR-001'",
    "UPDATE revisions SET content_sha256='broken' WHERE element_id='AC-000001'",
    "DELETE FROM lifecycle_receipts WHERE operation_id='create-ac'",
    "UPDATE reference_claims SET source_anchor='changed' WHERE operation_id='reference'",
    "UPDATE issue_occurrences SET body='changed' WHERE operation_id='occurrence'",
])
def test_audit_rejects_full_authority_corruption_without_repair(tmp_path, damage):
    store = seed_complete_authority(tmp_path)
    with sqlite3.connect(tmp_path / DATABASE) as connection:
        connection.execute(damage)
    before = database_rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.audit()
    assert database_rows(tmp_path) == before


@pytest.mark.parametrize("arguments", [
    (),
    ("initialize",),
    ("audit",),
    ("upgrade",),
    ("backup", "--workspace", "somewhere"),
    ("restore", "--workspace", "somewhere"),
    ("import-labels", "--workspace", "somewhere"),
])
def test_cli_requires_an_explicit_command_and_every_path(arguments):
    assert_failed(run_admin(*arguments))


def test_cli_initialize_is_the_only_command_that_claims_authority(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing_before = tuple(workspace.iterdir())
    assert_failed(run_admin("audit", "--workspace", workspace))
    assert tuple(workspace.iterdir()) == missing_before
    request = tmp_path / "import.json"
    request.write_text(json.dumps({
        "schema_version": 1, "spec_id": "demo", "operation_id": "import",
        "definitions": [{"element_id": "FR-001", "subject": "Scene"}],
    }))
    assert_failed(run_admin("import-labels", "--workspace", workspace, "--input", request))
    assert tuple(workspace.iterdir()) == missing_before

    result = run_admin("initialize", "--workspace", workspace)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == '{"command":"initialize","completed":true}\n'
    before = database_rows(workspace)
    assert_failed(run_admin("initialize", "--workspace", workspace))
    assert database_rows(workspace) == before


def test_cli_audit_prints_the_deterministic_store_report(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = seed_complete_authority(workspace)
    expected = store.audit()
    result = run_admin("audit", "--workspace", workspace)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"


def test_cli_import_labels_is_subject_only_atomic_and_idempotent(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    IdentityStore.initialize(workspace)
    request = tmp_path / "import.json"
    request.write_text(json.dumps({
        "schema_version": 1,
        "spec_id": "demo",
        "operation_id": "history-import-1",
        "definitions": [{"element_id": "U-005", "subject": "Largest-step collision behavior"}],
    }))
    for _ in range(2):
        result = run_admin("import-labels", "--workspace", workspace, "--input", request)
        assert result.returncode == 0 and result.stderr == ""
        assert result.stdout == '{"command":"import-labels","completed":true}\n'
    stored = IdentityStore.open(workspace).lookup(spec_id="demo", element_id="U-005")
    assert stored == {
        "spec_id": "demo", "element_id": "U-005", "kind": "U",
        "subject": "Largest-step collision behavior", "ordinal": "5",
        "status": "imported", "revision": None, "content": None,
        "content_sha256": None,
    }

    conflict = tmp_path / "conflict.json"
    conflict.write_text(json.dumps({
        "schema_version": 1,
        "spec_id": "demo",
        "operation_id": "history-import-2",
        "definitions": [{"element_id": "U-005", "subject": "Different"}],
    }))
    before = database_rows(workspace)
    assert_failed(run_admin("import-labels", "--workspace", workspace, "--input", conflict))
    assert database_rows(workspace) == before


@pytest.mark.parametrize("contents", [
    '{"schema_version":1,"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","subject":"s"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","element_id":"U-2","subject":"s"}]}',
    '{"schema_version":true,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","subject":"s"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","subject":"s","content":"invented"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1"}]}',
    '{"schema_version":1,"spec_id":[],"operation_id":"op","definitions":[{"element_id":"U-1","subject":"s"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":3,"definitions":[{"element_id":"U-1","subject":"s"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":true,"subject":"s"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","subject":3}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":[{"element_id":"U-1","subject":"\\ud800"}]}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","definitions":{}}',
    '{"schema_version":1,"spec_id":"demo","operation_id":"op","unexpected":[]}',
    'not json',
])
def test_cli_import_rejects_malformed_or_wrong_shape_without_writes(tmp_path, contents):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    IdentityStore.initialize(workspace)
    request = tmp_path / "invalid.json"
    request.write_text(contents)
    before = database_rows(workspace)
    files_before = authority_files(workspace)
    assert_failed(run_admin("import-labels", "--workspace", workspace, "--input", request))
    assert database_rows(workspace) == before
    assert authority_files(workspace) == files_before


def test_cli_import_rejects_invalid_utf8_without_writes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    IdentityStore.initialize(workspace)
    request = tmp_path / "invalid.json"
    request.write_bytes(b"\xff")
    before = database_rows(workspace)
    files_before = authority_files(workspace)
    assert_failed(run_admin("import-labels", "--workspace", workspace, "--input", request))
    assert database_rows(workspace) == before
    assert authority_files(workspace) == files_before


def test_cli_import_rejects_decoder_value_error_without_traceback_or_writes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    IdentityStore.initialize(workspace)
    request = tmp_path / "invalid.json"
    request.write_text(
        '{"schema_version":' + "9" * 5000
        + ',"spec_id":"demo","operation_id":"op","definitions":'
        '[{"element_id":"U-1","subject":"s"}]}'
    )
    before = database_rows(workspace)
    files_before = authority_files(workspace)
    result = run_admin("import-labels", "--workspace", workspace, "--input", request)
    assert_failed(result)
    assert database_rows(workspace) == before
    assert authority_files(workspace) == files_before


def test_cli_requires_explicit_upgrade_before_audit_or_import(tmp_path):
    from tests.unit.test_element_identity_bindings import older_authority

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = older_authority(workspace, "2")
    marker = (directory / "authority.json").read_bytes()
    source_before = database_rows(workspace)
    request = tmp_path / "import.json"
    request.write_text(json.dumps({
        "schema_version": 1, "spec_id": "demo", "operation_id": "new",
        "definitions": [{"element_id": "U-001", "subject": "New"}],
    }))
    assert_failed(run_admin("audit", "--workspace", workspace))
    assert_failed(run_admin("import-labels", "--workspace", workspace, "--input", request))
    assert database_rows(workspace) == source_before
    assert (directory / "authority.json").read_bytes() == marker

    upgraded = run_admin("upgrade", "--workspace", workspace)
    assert upgraded.returncode == 0 and upgraded.stderr == ""
    assert upgraded.stdout == '{"command":"upgrade","completed":true}\n'
    audited = run_admin("audit", "--workspace", workspace)
    assert audited.returncode == 0
    assert IdentityStore.open(workspace).lookup(spec_id="demo", element_id="FR-001")["status"] == "imported"
    assert (directory / "authority.json").read_bytes() == marker


def test_cli_backup_restore_retains_complete_authority_and_rejects_collisions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    store = seed_complete_authority(source)
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="revise-ac",
        changes=(ElementRevision("AC-000001", "1", "Movement", "Move more safely."),),
    )
    expected_reference = store.record_reference_claims(
        spec_id="demo",
        operation_id="reference-2",
        claims=(ReferenceClaim("evidence.md", HASH, "E2", "AC-000001", "2", "reference"),),
    )
    source_before = database_rows(source)
    expected_audit = store.audit()
    backup = tmp_path / "backup"
    result = run_admin("backup", "--workspace", source, "--destination", backup)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == '{"command":"backup","completed":true}\n'
    backup_before = tuple((path.name, path.read_bytes()) for path in sorted(backup.iterdir()))

    destination = tmp_path / "destination"
    destination.mkdir()
    result = run_admin("restore", "--workspace", destination, "--backup", backup)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == '{"command":"restore","completed":true}\n'
    restored = IdentityStore.open(destination)
    assert restored.audit() == expected_audit
    assert restored.lookup(spec_id="unseen", element_id="FR-001")["subject"] == "Outside recently accessed spec"
    assert restored.high_water(spec_id="demo", kind="AC") == "2"
    assert restored.read_revision(spec_id="demo", element_id="AC-000001", revision="1")["content"] == "Move safely."
    assert restored.record_reference_claims(
        spec_id="demo",
        operation_id="reference-2",
        claims=(ReferenceClaim("evidence.md", HASH, "E2", "AC-000001", "2", "reference"),),
    ) == expected_reference
    assert restored.issue_occurrences(spec_id="demo", issue_id="ISS-000001")[0]["report_id"] == "report-1"

    destination_before = database_rows(destination)
    assert_failed(run_admin("restore", "--workspace", destination, "--backup", backup))
    assert database_rows(destination) == destination_before
    assert tuple((path.name, path.read_bytes()) for path in sorted(backup.iterdir())) == backup_before
    assert database_rows(source) == source_before

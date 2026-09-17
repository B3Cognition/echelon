# Identity authority administration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose explicit integrity auditing and administration of the inactive identity authority without treating imported labels as assessed historical truth.

**Architecture:** Add a read-only full-audit boundary around the existing connection-owned audit and a small module CLI that delegates to existing store operations. No alternate storage, allocator, migration algorithm or automatic initialization. This is an independently testable administration checkpoint, not completion of historical reconciliation or managed publication.

**Tech Stack:** Python standard library argparse/JSON/SQLite; existing IdentityStore; pytest subprocess tests; no dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- Failed or abandoned reservations leave gaps; numbers are never recycled.
- Database corruption or a missing previously established ledger blocks allocation; it must not silently initialize from current document maxima.
- The local database is authoritative for allocation; graph and Markdown are consumers, not independent allocators.
- Imported histories with competing allocations block for explicit reconciliation; do not merge same-looking IDs by assumption.
- No schema change, automatic upgrade, provider routing, canonical publication, semantic assessment or activation in this task.

---

### Task 1: explicit audit API and safe administration entry point

**Files:** Create `src/harness/element_identity_admin.py` and `tests/unit/test_element_identity_admin.py`; modify `src/harness/element_identity_store.py` only for a thin public audit method and its private audit docstring; extend `docs/element-identity-storage.md`. Set `pytestmark = pytest.mark.unit` in the new test module so the repository's full-unit selector includes it. Do not modify the large Echelon CLI or install new console scripts in this checkpoint.

**Interfaces:** Add `IdentityStore.audit(self) -> dict`. It opens the existing authority transaction once, makes it query-only, invokes the complete existing `_audit` appropriate to the current schema, and returns a detached JSON-compatible report from that same snapshot. Do not copy integrity logic or call public store APIs from inside the transaction. Existing ordinary `open` remains indexed/lightweight; full scanning occurs only through explicit audit/upgrade/restore. Old schemas still require the explicit existing upgrade before this new current-store audit.

Audit report exact shape:

```python
{
    "report_version": 1,
    "authority": {"version": 1, "workspace_uuid": "...", "epoch_uuid": "..."},
    "database_schema_version": "3",
    "table_counts": {
        "counters": "0", "operations": "0", "reservations": "0",
        "entities": "0", "revisions": "0", "lifecycle_heads": "0",
        "lifecycle_lineage": "0", "lifecycle_receipts": "0",
        "reference_claims": "0", "issue_occurrences": "0", "binding_receipts": "0"
    }
}
```

Use the actual current schema constant, not a second hard-coded version authority; the example reflects the reviewed schema at plan preparation. Table names are a fixed allowlist of current data tables, never caller-controlled SQL. Counts are non-negative canonical decimal strings. Authority is the authenticated marker, returned as a copy. Do not add `approved`, `current_evidence` or publication-success fields. Every existing integrity exception must propagate through IdentityStoreError. Audit never repairs counters/rows, initializes directories, upgrades, creates receipts or checkpoints.

Add `main(argv: Sequence[str] | None = None) -> int` and a module main guard in `harness.element_identity_admin`. The supported explicit command shapes are:

```text
python -m harness.element_identity_admin initialize --workspace PATH
python -m harness.element_identity_admin audit --workspace PATH
python -m harness.element_identity_admin upgrade --workspace PATH
python -m harness.element_identity_admin backup --workspace PATH --destination PATH
python -m harness.element_identity_admin restore --workspace PATH --backup PATH
python -m harness.element_identity_admin import-labels --workspace PATH --input PATH
```

All paths are required; never default authority/workspace to CWD or discover a ledger from files. `initialize` alone calls initialize; `upgrade` alone upgrades; `restore` uses the existing fresh-destination restore. All other commands call open and fail for missing/old authority without changing it. Backup/restore keep the existing whole-ledger manifest and no-overwrite rules; do not implement a second export format. Import-labels uses existing atomic `import_identities` and idempotency rules, without allocating through document maxima or inventing lifecycle revisions.

Input for import-labels is an explicitly selected UTF-8 JSON document with exactly this shape:

```json
{"schema_version":1,"spec_id":"demo","operation_id":"history-import-1","definitions":[{"element_id":"U-005","subject":"Largest-step collision behavior"}]}
```

Validate exact top-level and row keys, integer (not bool) version, nonempty definitions array and exact scalar types using existing request validation. Reject duplicate JSON object keys and malformed Unicode/JSON. No Markdown file scanning, filenames-as-ID inference, latest-file bootstrap, evidence/occurrence imports or content adoption in this command. Existing imported entries remain imported/unassessed until separate explicit lifecycle/history reconciliation. Invalid requests leave the entire existing authority unchanged. Conflict handling is exactly the existing store policy, not an override or best-effort partial import.

On success print one deterministic JSON object to stdout and return 0. Audit prints its report directly. Other commands print `{"command": COMMAND, "completed": true}` after the delegated operation succeeds; this acknowledges only that storage operation, not semantic or managed readiness. Do not include raw source contents or a fabricated successful audit. Usage/input/IdentityStoreError/OSError/Unicode errors return 2 with a concise stderr diagnostic, no success JSON and no traceback; preserve programming exceptions rather than a blanket catch-all. Argparse help remains conventional. Do not auto-run a full audit after every operation or duplicate backup/restore verification.

- [ ] Write this real-store regression before implementation:

```python
def test_audit_reports_exact_authority_without_mutation(tmp_path):
    from contextlib import closing
    import json
    import sqlite3
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-001", "Scene"),))
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000002"
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        before = tuple(connection.iterdump())
    result = store.audit()
    assert result["report_version"] == 1
    assert result["database_schema_version"] == "3"
    marker = json.loads((tmp_path / ".echelon/identity/authority.json").read_text())
    assert result["authority"] == marker
    assert result["table_counts"]["entities"] == "1"
    assert result["table_counts"]["reservations"] == "1"
    assert result["table_counts"]["revisions"] == "0"
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        assert tuple(connection.iterdump()) == before
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_admin.py -q`, retain failing missing-audit behavior before implementation.
- [ ] Add one-query-only-snapshot and detached-report tests, real corruption checks across counter/entity/revision/lifecycle receipt/reference/issue occurrence authority, and full SQL-prestate equality on successful and rejected audits. Reuse fixtures and shared audit behavior; do not fabricate mock audit success. Include entities outside any recently accessed spec to prove full audit coverage.
- [ ] Add real subprocess CLI tests in a temporary workspace for missing required arguments, initialize/open distinction, audit output, subject-only import/retry/conflict, duplicate JSON keys/bool version/wrong keys/types/invalid encoding, no automatic upgrade, explicit upgrade, complete backup/restore with retained original labels/counters/history/receipts, and destination collision. Set subprocess `PYTHONPATH` to this checkout's `src`; never use the installed global CLI. Verify no files created on missing-authority read or invalid import and no old authority/source-backup mutations.
- [ ] Implement the thin audit wrapper and delegated module CLI. Keep imports/help side-effect free and all administrative writes explicit. Do not introduce another allocation/history writer or generic command framework.
- [ ] Run new admin tests with `tests/unit/test_element_identity_store.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, and `tests/unit/test_element_ids.py`. The existing million-record capacity test is not part of these unit files; do not launch the full repository suite or repeat capacity measurement unless an allocation/import/index path changes.
- [ ] Document exact commands and distinguish label reservation from historical adoption/reconciliation, backup from independently writable cloning, audit integrity from semantic correctness, and inactive managed rollout. Self-review, run `git diff --check`, commit only task files, and retain complete RED/GREEN commands/output and concerns in the ignored task report.

## Following work

Historical typed-artifact inventory and explicit conflict reconciliation, canonical/staged authentication, semantic review, durable publication/graph completion, all-family managed producers and bounded repair remain required. These commands must not be used on the stopped smoke or global authority during implementation.

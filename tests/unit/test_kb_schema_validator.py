"""Tests for deterministic knowledge-base schema validation."""

from __future__ import annotations

from codegen.memory.kb_schema_validator import (
    validate_kb_document,
    validate_pending_operation,
)


def test_internalization_log_accepts_versioned_provenance_record() -> None:
    result = validate_kb_document(
        "internalization-log.yaml",
        {
            "schema_version": 2,
            "append_only": True,
            "entries": [
                {
                    "id": "int-001",
                    "run_id": "squad-001",
                    "source": "AUDITOR",
                    "created_at": "2026-06-23T10:00:00Z",
                    "agent": "IMPLEMENTER",
                    "agent_tier": "deep",
                    "prompt_version": "v1.0.0",
                    "int_gate_verdict": "PASS",
                    "chk_doubt_count": 0,
                    "computation_health": {
                        "inputs_available": 8,
                        "inputs_missing": 8,
                        "formulas_valid": 8,
                        "formulas_failed": 0,
                    },
                }
            ],
        },
    )

    assert result.ok is True
    assert result.issues == []


def test_internalization_log_rejects_wrong_schema_version() -> None:
    result = validate_kb_document(
        "internalization-log.yaml",
        {
            "schema_version": 1,
            "append_only": True,
            "entries": [],
        },
    )

    assert result.ok is False
    assert result.issues[0].path == "schema_version"
    assert "expected 2" in result.issues[0].message


def test_learning_entry_requires_project_scope_for_local_patterns() -> None:
    result = validate_kb_document(
        "patterns.yaml",
        {
            "schema_version": 1,
            "entries": [
                {
                    "id": "pat-001",
                    "source": "AUDITOR",
                    "created_at": "2026-06-23T10:00:00Z",
                    "confidence": 0.8,
                    "run_id": "squad-001",
                    "scope": "local_only",
                }
            ],
        },
    )

    assert result.ok is False
    assert any(issue.path == "entries[0].project_fingerprint" for issue in result.issues)


def test_global_learning_entry_allows_missing_project_fingerprint() -> None:
    result = validate_kb_document(
        "pitfalls.yaml",
        {
            "schema_version": 1,
            "entries": [
                {
                    "id": "pit-001",
                    "source": "AUDITOR",
                    "created_at": "2026-06-23T10:00:00Z",
                    "confidence": 0.6,
                    "run_id": "squad-001",
                    "scope": "global",
                }
            ],
        },
    )

    assert result.ok is True


def test_learning_entry_requires_documented_id() -> None:
    result = validate_kb_document(
        "patterns.yaml",
        {
            "schema_version": 1,
            "entries": [
                {
                    "source": "AUDITOR",
                    "created_at": "2026-06-23T10:00:00Z",
                    "confidence": 0.8,
                    "run_id": "squad-001",
                    "scope": "global",
                }
            ],
        },
    )

    assert result.ok is False
    assert any(issue.path == "entries[0].id" for issue in result.issues)


def test_sage_decision_requires_documented_fields_and_boolean_correctness() -> None:
    result = validate_kb_document(
        "sage-decisions.yaml",
        {
            "schema_version": 2,
            "append_only": True,
            "entries": [
                {
                    "run_id": "squad-001",
                    "artifact": "spec.md",
                    "challenge_type": "missing_evidence",
                    "challenge_summary": "Evidence is incomplete.",
                    "outcome": "blocked",
                    "resolution": "Obtain evidence.",
                    "was_correct": "true",
                }
            ],
        },
    )

    assert result.ok is False
    assert any(issue.path == "entries[0].was_correct" for issue in result.issues)


def test_pending_operation_requires_checksum_and_provenance() -> None:
    result = validate_pending_operation(
        {
            "schema_version": 1,
            "operation_id": "op-20260623-0001",
            "created_at": "2026-06-23T10:00:00Z",
            "source": {"run_id": "squad-001"},
            "target_file": "knowledge-base/patterns.yaml",
            "operation": "append_entry",
            "payload": {},
            "checksum": "abc123",
        }
    )

    assert result.ok is False
    assert any(issue.path == "source.agent" for issue in result.issues)
    assert any(issue.path == "checksum" for issue in result.issues)

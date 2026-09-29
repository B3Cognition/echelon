"""Closed semantic replies; Python alone renders fulfillment artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata

from harness.canonical_requirements import REQ_ID_RE
from harness.judgment_prepass import FULFILLMENT_STATUSES


_MAPPER_COLUMNS = (
    ("id", "ID"),
    ("verified_implementation_evidence", "Verified Implementation Evidence"),
    ("verified_test_evidence", "Verified Test Evidence"),
    ("codegraph_candidates", "CodeGraph Candidates"),
    ("candidate_disposition", "Candidate Disposition"),
    ("evidence_kind", "Evidence Kind"),
    ("evidence_strength", "Evidence Strength"),
    ("runtime_threshold", "Runtime Threshold"),
    ("confidence", "Confidence"),
    ("notes", "Notes"),
)
_ENUMS = {
    "candidate_disposition": {"accepted", "candidate_only", "contradicted", "unrelated", "none"},
    "evidence_kind": {"source_and_test", "source_only", "test_only", "measured_runtime",
                      "assertion_only", "missing", "meta"},
    "evidence_strength": {"strong", "medium", "weak", "none"},
    "confidence": {"high", "medium", "low", "none"},
    "status": FULFILLMENT_STATUSES - {"DEFERRED_SCOPE"},
}
CORRECTABLE_ASSIGNED_DIGEST_ECHO = "fulfillment assigned-ID digest echo mismatch"


@dataclass(frozen=True)
class FulfillmentAssignment:
    run_id: str
    step: str
    dispatch_id: str
    input_fingerprint: str
    assigned_ids: tuple[str, ...]

    def identity(self) -> dict[str, object]:
        if self.step not in {"mapper", "judge"}:
            raise ValueError("unknown fulfillment semantic step")
        for label in (self.run_id, self.dispatch_id):
            _cell(label, required=True)
        if type(self.input_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.input_fingerprint):
            raise ValueError("invalid fulfillment input fingerprint")
        _ids(self.assigned_ids)
        return {"schema_version": 1, "run_id": self.run_id, "step": self.step,
                "dispatch_id": self.dispatch_id, "input_fingerprint": self.input_fingerprint,
                "assigned_ids": list(self.assigned_ids)}

    def reply_identity(self) -> dict[str, object]:
        """Compact reply binding; the host retains and validates the full ID list."""
        identity = self.identity()
        encoded_ids = json.dumps(identity["assigned_ids"], ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        return {"schema_version": 2, "run_id": self.run_id, "step": self.step,
                "dispatch_id": self.dispatch_id, "input_fingerprint": self.input_fingerprint,
                "assigned_ids_sha256": hashlib.sha256(encoded_ids).hexdigest()}


def _cell(value: object, *, required: bool = False) -> str:
    if (type(value) is not str or len(value) > 8192 or (required and not value.strip())
            or "|" in value or any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value)):
        raise ValueError("fulfillment text must be a safe single-line literal cell")
    return value


def _ids(values) -> None:
    if not isinstance(values, (tuple, list)) or any(
        type(item) is not str or not REQ_ID_RE.fullmatch(item) for item in values
    ) or len(set(values)) != len(values):
        raise ValueError("invalid or duplicate fulfillment IDs")


def _validate_rows(rows: object, step: str) -> list[dict]:
    if type(rows) is not list:
        raise ValueError("fulfillment rows must be a list")
    fields = {key for key, _ in _MAPPER_COLUMNS} if step == "mapper" else {"id", "status", "evidence"}
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("fulfillment row has an invalid schema")
        for key, value in row.items():
            if key == "runtime_threshold":
                if type(value) is not bool:
                    raise ValueError("runtime_threshold must be boolean")
            else:
                _cell(value, required=key in {"id", "status", "evidence"})
                if key in _ENUMS and value not in _ENUMS[key]:
                    raise ValueError(f"invalid fulfillment {key}")
    _ids([row["id"] for row in rows])
    return rows


def validate_semantic_result(value: object, assignment: FulfillmentAssignment) -> dict:
    identity = assignment.reply_identity()
    if type(value) is not dict or type(value.get("schema_version")) is not int:
        raise ValueError("fulfillment reply must be a versioned object")
    if any(value.get(key) != expected for key, expected in identity.items()):
        raise ValueError("fulfillment assignment binding mismatch")
    action = value.get("action")
    # Some providers flatten a single read object even when asked for the
    # canonical nested shape. Normalize only the two exact, host-readable
    # single-operation schemas. Batches and unknown fields remain invalid.
    if action == "read" and "request" not in value and "requests" not in value:
        operation = value.get("op")
        operation_fields = {
            "read_file": {"op", "root", "path", "start_line", "line_count"},
            "list_directory": {"op", "root", "path"},
        }.get(operation) if type(operation) is str else None
        if operation_fields is not None and set(value) == set(identity) | {"action"} | operation_fields:
            value = {
                **identity,
                "action": "read",
                "request": {key: value[key] for key in operation_fields},
            }
    extra = {"rows", "unmapped_candidates"} if action == "final" else (
        {"request"} if action == "read" else {"reason"} if action == "blocked" else None)
    if extra is None or set(value) != set(identity) | {"action"} | extra:
        raise ValueError("fulfillment reply has an invalid schema")
    if action == "final":
        rows = _validate_rows(value["rows"], assignment.step)
        if [row["id"] for row in rows] != list(assignment.assigned_ids):
            raise ValueError("fulfillment rows must match exact assigned IDs in order")
        notes = value["unmapped_candidates"]
        if type(notes) is not list or len(notes) > 100:
            raise ValueError("unmapped candidates must be a bounded list")
        for note in notes:
            _cell(note, required=True)
    elif action == "blocked":
        _cell(value["reason"], required=True)
    elif type(value["request"]) is not dict:
        raise ValueError("inspection read request must be an object")
    # Return an independent JSON value; later caller mutation cannot change the
    # accepted reply. The host read channel validates the read's closed schema.
    return json.loads(json.dumps(value, allow_nan=False))


def _parse_semantic_json(raw: str) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate fulfillment JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite fulfillment JSON value")

    if type(raw) is not str or len(raw.encode("utf-8")) > 256 * 1024:
        raise ValueError("invalid or oversized fulfillment reply")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid fulfillment JSON") from exc
    return value


def parse_semantic_reply(raw: str, assignment: FulfillmentAssignment) -> dict:
    """Strictly validate a reply whose complete binding is already authoritative."""
    return validate_semantic_result(_parse_semantic_json(raw), assignment)


def is_correctable_assigned_digest_echo(raw: str, assignment: FulfillmentAssignment) -> bool:
    """Identify an unexecuted read with only its assigned-ID digest echo wrong."""
    try:
        value = _parse_semantic_json(raw)
        identity = assignment.reply_identity()
    except (ValueError, TypeError):
        return False
    return (
        type(value) is dict
        and set(value) == set(identity) | {"action", "request"}
        and value.get("action") == "read"
        and type(value.get("request")) is dict
        and all(value.get(key) == expected for key, expected in identity.items()
                if key != "assigned_ids_sha256")
        and type(value.get("assigned_ids_sha256")) is str
        and 0 < len(value["assigned_ids_sha256"]) <= 128
        and value["assigned_ids_sha256"] != identity["assigned_ids_sha256"]
    )


def bind_semantic_reply(raw: str, assignment: FulfillmentAssignment) -> dict:
    """Retain a raw provider reply while binding its host-owned input digest.

    The run, step, dispatch, schema, and exact assigned-ID digest remain strict
    transport identity. The input fingerprint describes host-observed content;
    a provider echo cannot become authoritative merely by repeating it.
    """
    value = _parse_semantic_json(raw)
    identity = assignment.reply_identity()
    if type(value) is not dict or type(value.get("schema_version")) is not int:
        raise ValueError("fulfillment reply must be a versioned object")
    for key in ("schema_version", "run_id", "step", "dispatch_id", "assigned_ids_sha256"):
        if value.get(key) != identity[key]:
            raise ValueError("fulfillment assignment binding mismatch")
    echo = value.get("input_fingerprint")
    if type(echo) is not str or not echo or len(echo) > 128:
        raise ValueError("invalid fulfillment input fingerprint echo")
    bound = dict(value)
    bound["input_fingerprint"] = assignment.input_fingerprint
    return validate_semantic_result(bound, assignment)


def render_implementation_map(rows: list[dict]) -> str:
    _validate_rows(rows, "mapper")
    lines = ["# Implementation Map", "", "schema_version: 2", "",
             "| " + " | ".join(title for _, title in _MAPPER_COLUMNS) + " |",
             "| " + " | ".join("---" for _ in _MAPPER_COLUMNS) + " |"]
    for row in rows:
        values = [str(row[key]).lower() if key == "runtime_threshold" else row[key]
                  for key, _ in _MAPPER_COLUMNS]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def render_fallback_report(rows: list[dict]) -> str:
    _validate_rows(rows, "judge")
    lines = ["# Fallback Fulfillment Judgment", "", "| ID | Status | Evidence |", "| --- | --- | --- |"]
    lines.extend(f"| {row['id']} | {row['status']} | {row['evidence']} |" for row in rows)
    return "\n".join(lines) + "\n"

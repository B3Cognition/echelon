"""Strict dispatch and journal schemas for controller-owned documentation."""
from __future__ import annotations

import json
import math
import re

import yaml

from harness.delivery_slice import DeliverySliceError

REPORTS = ("documentation-impact-report.md", "docs-verification-report.md")
DOCS = ("README.md", "CHANGELOG.md")
STEPS = ("tech_writer", "docs_verifier")
IDENTITY = {"schema_version", "dispatch_id", "step", "task_ids", "candidate_fingerprint", "input_fingerprint"}


class _ReportLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    value = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        _require(isinstance(key, str) and key not in value, "duplicate or invalid documentation report field")
        value[key] = loader.construct_object(value_node)
    return value


_ReportLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _require(condition, message):
    if not condition:
        raise DeliverySliceError(message)


def _strings(value, maximum=50):
    return isinstance(value, list) and len(value) <= maximum and all(
        isinstance(item, str) and item.strip() and len(item) <= 8000 for item in value)


def _fingerprint(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def report_metadata(text):
    _require(isinstance(text, str) and 0 < len(text.encode()) <= 100_000,
             "invalid documentation report size")
    _require(text.startswith("---\n") and len(text.split("---", 2)) == 3,
             "documentation report requires frontmatter")
    try:
        metadata = yaml.load(text.split("---", 2)[1], Loader=_ReportLoader)
    except yaml.YAMLError as exc:
        raise DeliverySliceError("invalid documentation report frontmatter") from exc
    _require(isinstance(metadata, dict) and type(metadata.get("schema_version")) is int
             and metadata["schema_version"] == 2, "invalid documentation report schema")
    return metadata


def validate_result(raw, assignment):
    _require(isinstance(raw, str) and len(raw.encode()) <= 200_000, "invalid documentation result size")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate documentation result field")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise DeliverySliceError("documentation result must be JSON") from exc
    _require(isinstance(value, dict) and set(value) == IDENTITY | {"verdict", "summary", "findings", "report_markdown"},
             "invalid documentation result fields")
    _require(type(value["schema_version"]) is int and all(value[key] == item for key, item in assignment.items()),
             "documentation result identity mismatch")
    verdict = value["verdict"]
    _require(isinstance(verdict, str) and verdict in ({"DONE", "BLOCKED", "NEEDS_CONTEXT"}
             if assignment["step"] == "tech_writer" else {"PASS", "FAIL", "BLOCKED"}), "invalid documentation verdict")
    _require(isinstance(value["summary"], str) and 0 < len(value["summary"].strip()) <= 8000,
             "invalid documentation summary")
    _require(_strings(value["findings"]), "invalid documentation findings")
    _require(not (verdict in {"DONE", "PASS"} and value["findings"]), "passing documentation has findings")
    _require(verdict != "FAIL" or bool(value["findings"]), "failed documentation requires findings")
    text = value["report_markdown"]
    _require(isinstance(text, str) and len(text.encode()) <= 100_000, "invalid documentation report size")
    if verdict in {"DONE", "PASS", "FAIL"}:
        metadata = report_metadata(text)
        if assignment["step"] == "tech_writer":
            _require(type(metadata.get("docs_required")) is bool, "invalid documentation impact decision")
            for key in ("readme_updated", "changelog_updated"):
                _require(type(metadata.get(key)) is bool, "invalid documentation impact flag")
            _require(_strings(metadata.get("delivery_change_ids")) and bool(metadata["delivery_change_ids"]),
                     "invalid documentation change inventory")
        else:
            _require(metadata.get("verdict") == verdict, "documentation report verdict mismatch")
            _require(type(metadata.get("blocking_findings")) is int and metadata["blocking_findings"] >= 0,
                     "invalid report blocking findings")
            for key in ("reviewed_change_ids", "uncovered_change_ids", "unsupported_claims"):
                _require(_strings(metadata.get(key)), "invalid report findings inventory")
            for key in ("readme_first_run_manual", "changelog_valid", "impact_report_valid", "project_evidence_checked", "runnability_commands_current"):
                _require(type(metadata.get(key)) is bool, "invalid documentation review flag")
            _require(type(metadata.get("evidence_items_checked")) is int and metadata["evidence_items_checked"] >= 0,
                     "invalid documentation evidence count")
            _require(isinstance(metadata.get("runnability_evidence_sha256"), str), "invalid documentation evidence digest")
            if verdict == "PASS":
                _require(metadata["blocking_findings"] == 0 and not metadata["uncovered_change_ids"]
                         and not metadata["unsupported_claims"], "passing report has findings")
                _require(metadata["evidence_items_checked"] >= 4 and all(metadata[key] for key in (
                    "readme_first_run_manual", "changelog_valid", "impact_report_valid", "project_evidence_checked")),
                    "passing report requires independent project evidence")
            else:
                _require(metadata["blocking_findings"] > 0 and bool(metadata["uncovered_change_ids"] or metadata["unsupported_claims"]),
                         "failed report must preserve independent findings")
    return value


def validate_journal(data):
    _require(len(json.dumps(data).encode()) <= 2_000_000, "documentation journal exceeds size limit")
    fields = {"schema_version", "run_id", "binding", "input_fingerprint", "source_fingerprint", "candidate_fingerprint",
              "budget_limit", "task_ids", "records", "reports_before", "docs_before", "publication"}
    _require(isinstance(data, dict) and set(data) == fields and type(data["schema_version"]) is int
             and data["schema_version"] == 1, "invalid documentation journal schema")
    _require(isinstance(data["run_id"], str) and bool(data["run_id"]), "invalid documentation run identity")
    for field in ("binding", "input_fingerprint", "source_fingerprint", "candidate_fingerprint"):
        _require(_fingerprint(data[field]), "invalid documentation fingerprint")
    scope = data["task_ids"]
    _require(_strings(scope) and bool(scope) and scope == sorted(set(scope)), "invalid documentation scope")
    budget = data["budget_limit"]
    _require(budget is None or type(budget) in (int, float) and math.isfinite(budget), "invalid documentation budget")
    for field, names in (("reports_before", REPORTS), ("docs_before", DOCS)):
        _require(isinstance(data[field], dict) and set(data[field]) == set(names), "invalid documentation before-images")
        _require(all(text is None or isinstance(text, str) and len(text.encode()) <= 100_000 for text in data[field].values()),
                 "invalid documentation before-image size")
    records = data["records"]
    _require(isinstance(records, list) and len(records) <= 6, "invalid documentation receipt count")
    seen, candidate, terminal = set(), data["candidate_fingerprint"], False
    for index, record in enumerate(records):
        _require(not terminal and isinstance(record, dict) and set(record) == {
            "assignment", "repair_attempt", "result", "candidate_after", "token_usage", "error", "deterministic_findings", "gate_findings"},
            "invalid documentation receipt")
        assignment = record["assignment"]
        _require(isinstance(assignment, dict) and set(assignment) == IDENTITY, "invalid documentation assignment fields")
        _require(type(assignment["schema_version"]) is int and assignment["schema_version"] == 1
                 and assignment["step"] == STEPS[index % 2] and assignment["task_ids"] == scope
                 and assignment["candidate_fingerprint"] == candidate and assignment["input_fingerprint"] == data["input_fingerprint"],
                 "invalid documentation receipt chain")
        dispatch = assignment["dispatch_id"]
        _require(isinstance(dispatch, str) and bool(dispatch) and dispatch not in seen, "invalid documentation dispatch identity")
        seen.add(dispatch)
        _require(type(record["repair_attempt"]) is int and record["repair_attempt"] == index // 2, "invalid documentation attempt")
        usage = record["token_usage"]
        _require(usage is None or type(usage) is int and usage >= 0, "invalid documentation usage")
        _require(_strings(record["deterministic_findings"]) and _strings(record["gate_findings"]), "invalid documentation gate findings")
        if record["error"] is not None:
            _require(isinstance(record["error"], str) and bool(record["error"]) and record["result"] is None,
                     "invalid documentation error receipt")
            terminal = True
        elif record["result"] is None:
            _require(index == len(records) - 1 and record["candidate_after"] is None and usage is None,
                     "invalid pending documentation receipt")
            terminal = True
        else:
            result = validate_result(json.dumps(record["result"]), assignment)
            _require(_fingerprint(record["candidate_after"]), "invalid documentation candidate receipt")
            if index % 2:
                _require(record["candidate_after"] == candidate, "mutating documentation review receipt")
            candidate = record["candidate_after"]
            terminal = result["verdict"] in {"BLOCKED", "NEEDS_CONTEXT"} or (
                index % 2 and result["verdict"] == "PASS" and not record["deterministic_findings"] and not record["gate_findings"])
        _require(not terminal or index == len(records) - 1, "documentation receipts after terminal result")
    publication = data["publication"]
    if publication is not None:
        _require(isinstance(publication, dict) and set(publication) == {"before", "after", "complete"}
                 and type(publication["complete"]) is bool and publication["before"] == data["reports_before"],
                 "invalid documentation publication")
        _require(bool(records) and len(records) % 2 == 0 and records[-1]["result"] is not None
                 and records[-1]["result"]["verdict"] == "PASS" and not records[-1]["deterministic_findings"]
                 and not records[-1]["gate_findings"] and records[-1]["error"] is None,
                 "unapproved documentation publication")
        _require(publication["after"] == {REPORTS[0]: records[-2]["result"]["report_markdown"],
                                         REPORTS[1]: records[-1]["result"]["report_markdown"]},
                 "documentation publication receipt mismatch")

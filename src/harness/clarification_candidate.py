"""Detached clarification candidates; callers retain all decision/source authority.

Resolved decisions must come from the human-input owner, never parsed Markdown.
This module does not publish, route, allocate, regenerate context or access files.
"""
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re

from echelon.feature_policy import (
    derive_feature_policy, merge_feature_policies, render_feature_policy,
    render_feature_policy_reconciliation,
)


@dataclass(frozen=True, slots=True)
class ClarificationRecord:
    decision_id: str
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class ClarificationCandidate:
    decisions: tuple[ClarificationRecord, ...]
    receipt_text: str
    policy_text: str
    policy_context_text: str
    reconciliation_text: str
    reconciliation_json: str


def _text(value):
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("clarification requires nonblank UTF-8 text without NUL")
    value.encode("utf-8")


def _record(value):
    if type(value) is not ClarificationRecord:
        raise ValueError("clarification requires an exact captured record")
    if type(value.decision_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value.decision_id):
        raise ValueError("invalid clarification decision ID")
    _text(value.question)
    _text(value.answer)


def _json(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _render(records):
    policy = None
    sections = []
    for record in records:
        policy = merge_feature_policies(policy, derive_feature_policy(record.answer, decision_id=record.decision_id))
        sections.append(f"## Decision {record.decision_id}\n\n**Question:** {record.question}\n\n**Answer:** {record.answer}\n")
    return "\n".join(sections), policy


def prepare_clarification_candidate(*, decision, previous, receipt_before, policy_before, artifacts):
    """Check captured preimages and append once; no positive authority is inferred.

    A managed history starts with absent receipt/policy files. Existing legacy
    files are not adopted by guessing their history from prose. The eventual
    publisher must authenticate every supplied record and guard every raw input.
    """
    _record(decision)
    if type(previous) is not tuple or type(artifacts) is not dict:
        raise ValueError("clarification requires captured immutable history and a text inventory")
    for item in previous:
        _record(item)
    ids = [item.decision_id for item in previous]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate clarification history")
    for path, text in artifacts.items():
        if (type(path) is not str or not path or "\\" in path or "\x00" in path
                or PurePosixPath(path).is_absolute() or PurePosixPath(path).as_posix() != path
                or ".." in PurePosixPath(path).parts or not path.endswith(".md")):
            raise ValueError("clarification artifact path must be canonical relative Markdown")
        path.encode("utf-8")
        if type(text) is not str or "\x00" in text:
            raise ValueError("clarification artifact must be captured UTF-8 text")
        text.encode("utf-8")
    prior_receipt, prior_policy = _render(previous)
    if previous:
        if type(receipt_before) is not str or type(policy_before) is not str:
            raise ValueError("clarification preimages are missing")
        if receipt_before != prior_receipt or policy_before != _json(prior_policy):
            raise ValueError("clarification preimages differ from captured decision history")
    elif receipt_before is not None or policy_before is not None:
        raise ValueError("unproven clarification history requires reconciliation")
    if decision.decision_id in ids:
        if previous[-1] != decision:
            raise ValueError("clarification retry conflicts with the latest decision")
        records = previous
    else:
        records = previous + (decision,)
    receipt, policy = _render(records)
    report, reconciliation = render_feature_policy_reconciliation(artifacts, policy)
    return ClarificationCandidate(records, receipt, _json(policy), render_feature_policy(policy),
        reconciliation, _json(report))

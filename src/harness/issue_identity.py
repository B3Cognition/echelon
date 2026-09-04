"""Content identity for SAGE findings whose display IDs can be reused."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy


def issue_fingerprint(title: str, body: str) -> str:
    """Bind a finding to its content, excluding numbering and report footers.

    Severity and status describe the review, not the repair. Evidence, affected
    artifacts, actions and resolution guidance do describe it and are included.
    Formatting-only whitespace changes do not create new repair authority.
    """
    title = re.sub(r"^ISS-[A-Za-z0-9-]+:\s*", "", title.strip())
    body = re.split(r"(?m)^##\s", body, maxsplit=1)[0]
    fields: dict[str, str] = {}
    pattern = re.compile(
        r"(?m)^[ \t]*(?:-[ \t]*)?\*\*([^*\n]+)\*\*[ \t]*:?[ \t]*"
    )
    matches = list(pattern.finditer(body))
    for index, match in enumerate(matches):
        label = match.group(1).rstrip(":").strip().casefold()
        if label in {"severity", "status", "banzai eligible"}:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = re.split(r"(?m)^#{1,6}\s", body[match.end():end], maxsplit=1)[0]
        fields[label] = " ".join(value.split())
    payload = {"version": 1, "title": " ".join(title.split()), "fields": fields}
    if not fields:
        payload["body"] = " ".join(body.split())
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def matching_issue_resolution(ledger: object, fingerprint: str) -> Mapping[str, object]:
    """Find the same finding, even after renumbering or reuse of its old ID.

    Legacy records lacking content identity cannot certify a current finding.
    They remain in history when the current finding is resolved again.
    """
    if not isinstance(ledger, Mapping) or not fingerprint:
        return {}
    entries = [entry for entry in ledger.values() if isinstance(entry, Mapping)]
    for entry in entries:
        if entry.get("issue_fingerprint") == fingerprint:
            return entry
    for entry in entries:
        history = entry.get("previous_resolutions")
        history = history if isinstance(history, list) else []
        for record in reversed(history):
            if (
                isinstance(record, Mapping)
                and record.get("status") == "validated"
                and record.get("issue_fingerprint") == fingerprint
            ):
                return record
    return {}


def record_issue_resolution(ledger: object, issue_id: str, entry: dict) -> dict:
    """Replace a display-ID slot while preserving its prior resolution history."""
    result = deepcopy(dict(ledger)) if isinstance(ledger, Mapping) else {}
    previous = result.get(issue_id)
    replacement = deepcopy(entry)
    if isinstance(previous, dict):
        history = previous.pop("previous_resolutions", [])
        history = history if isinstance(history, list) else []
        if previous.get("issue_fingerprint") != replacement.get("issue_fingerprint"):
            history = [*history, previous]
        if history:
            replacement["previous_resolutions"] = history
    result[issue_id] = replacement
    return result

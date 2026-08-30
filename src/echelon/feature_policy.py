"""Canonical, feature-scoped policy derived from a human clarification."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


POLICY_FILENAME = "feature-policy.json"
POLICY_CONTEXT_FILENAME = "feature-policy.md"
RECONCILIATION_FILENAME = "feature-policy-reconciliation.md"

_SCOPE_TERMS = {
    "deployment": ("deployment",),
    "auth": ("auth", "authentication"),
    "persistence": ("persistence", "database"),
    "routing": ("routing",),
    "backend": ("backend",),
    "public_hosting": ("public hosting", "hosting requirement"),
}
_VERIFICATION_TERMS = {
    "compliance_scan": ("compliance",),
    "accessibility_suite": ("axe", "accessibility suite"),
    "visual_regression": ("visual-regression", "visual regression"),
}
_REJECTED_TERMS = {
    "deployment": ("deployment", "production-grade", "pipeline-proving", "public hosting"),
    "backend": ("backend",),
    "auth": ("authentication", "authorization"),
    "persistence": ("persistence", "database"),
    "routing": ("routing",),
}


def derive_feature_policy(answer: str, *, decision_id: str) -> dict[str, Any]:
    """Derive only explicit, unambiguous feature decisions from user prose."""
    normalized = " ".join(answer.lower().split())
    descoping_clauses = _negative_clauses(normalized, r"\bno\s+")
    waiver_clauses = _negative_clauses(normalized, r"\bdo not require\s+")
    scope = {
        name: "descoped"
        for name, terms in _SCOPE_TERMS.items()
        if any(term in clause for clause in descoping_clauses for term in terms)
    }
    verification = {
        name: "not_required"
        for name, terms in _VERIFICATION_TERMS.items()
        if any(term in clause for clause in waiver_clauses for term in terms)
    }
    quality: dict[str, str] = {}
    if verification:
        quality["behavioral"] = "waived_for_feature"
    if "one static greeting" in normalized or "static greeting" in normalized:
        quality["testability"] = "evaluate_only_if_applicable"
    return {
        "schema_version": 1,
        "provenance": {
            "decision_id": decision_id,
            "source": "user_clarification",
            "immutable": True,
        },
        "source_answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        "scope": scope,
        "verification": verification,
        "quality": quality,
    }


def _negative_clauses(text: str, marker: str) -> tuple[str, ...]:
    """Return a bounded list clause introduced by an explicit negative marker."""
    return tuple(
        match.group(1).strip()
        for match in re.finditer(marker + r"([^.;]+)", text)
        if match.group(1).strip()
    )


def persist_feature_policy(staging_dir: Path, policy: Mapping[str, Any]) -> Path:
    """Atomically persist policy and context, refusing to overwrite a decision."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / POLICY_FILENAME
    payload = json.dumps(dict(policy), indent=2, sort_keys=True) + "\n"
    if path.exists():
        existing_payload = path.read_text(encoding="utf-8")
        if existing_payload != payload and not _is_append_only_extension(
            json.loads(existing_payload), policy
        ):
            raise ValueError("feature policy is immutable once persisted")
    else:
        path.write_text(payload, encoding="utf-8")
    (staging_dir / POLICY_CONTEXT_FILENAME).write_text(
        render_feature_policy(policy), encoding="utf-8"
    )
    return path


def load_feature_policy(staging_dir: Path) -> dict[str, Any] | None:
    """Load the accumulated feature policy for a run, when one exists."""
    path = staging_dir / POLICY_FILENAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("persisted feature policy must be an object")
    return payload


def merge_feature_policies(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Append an immutable clarification without replacing earlier decisions."""
    if existing is None:
        return dict(incoming)
    merged = {
        "schema_version": 2,
        "provenance": {
            "source": "user_clarification",
            "immutable": True,
            "decision_ids": _decision_ids(existing) + _decision_ids(incoming),
        },
        "source_answer_sha256": _answer_hashes(existing) + _answer_hashes(incoming),
        "scope": _merge_section(existing, incoming, "scope"),
        "verification": _merge_section(existing, incoming, "verification"),
        "quality": _merge_section(existing, incoming, "quality"),
    }
    return merged


def _decision_ids(policy: Mapping[str, Any]) -> list[str]:
    provenance = policy.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("feature policy is missing provenance")
    decision_ids = provenance.get("decision_ids")
    if isinstance(decision_ids, list) and all(isinstance(item, str) for item in decision_ids):
        return list(decision_ids)
    decision_id = provenance.get("decision_id")
    if isinstance(decision_id, str) and decision_id:
        return [decision_id]
    raise ValueError("feature policy provenance is missing a decision id")


def _answer_hashes(policy: Mapping[str, Any]) -> list[str]:
    value = policy.get("source_answer_sha256")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    if isinstance(value, str) and value:
        return [value]
    raise ValueError("feature policy is missing an answer hash")


def _merge_section(
    existing: Mapping[str, Any], incoming: Mapping[str, Any], section: str
) -> dict[str, str]:
    left = existing.get(section)
    right = incoming.get(section)
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise ValueError(f"feature policy section {section} must be an object")
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"feature policy decisions conflict for {section}.{key}")
        merged[key] = value
    return merged


def _is_append_only_extension(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> bool:
    """Allow new immutable decisions while forbidding changes to old ones."""
    try:
        existing_ids = _decision_ids(existing)
        incoming_ids = _decision_ids(incoming)
        existing_hashes = _answer_hashes(existing)
        incoming_hashes = _answer_hashes(incoming)
    except ValueError:
        return False
    if (
        incoming_ids[: len(existing_ids)] != existing_ids
        or incoming_hashes[: len(existing_hashes)] != existing_hashes
    ):
        return False
    for section in ("scope", "verification", "quality"):
        original = existing.get(section)
        updated = incoming.get(section)
        if not isinstance(original, Mapping) or not isinstance(updated, Mapping):
            return False
        if any(updated.get(key) != value for key, value in original.items()):
            return False
    return len(incoming_ids) > len(existing_ids)


def render_feature_policy(policy: Mapping[str, Any]) -> str:
    lines = [
        "# Authoritative Feature Policy",
        "",
        "This run-local policy was generated from an immutable user decision. "
        "It overrides conflicting feature assumptions but never workspace defaults.",
        "",
    ]
    for section in ("scope", "verification", "quality"):
        values = policy.get(section)
        if not isinstance(values, Mapping) or not values:
            continue
        lines.extend((f"## {section.title()}", ""))
        lines.extend(f"- {key}: {value}" for key, value in values.items())
        lines.append("")
    lines.extend((
        "## Reconciliation Rule",
        "",
        "Treat a requirement or gate contradicted by this policy as descoped or refuted. "
        "Do not re-raise it as an unresolved question and do not replace it with numeric thresholds.",
        "",
    ))
    return "\n".join(lines)


def reconcile_feature_artifacts(spec_dir: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Record stale policy contradictions without erasing their provenance."""
    scope = policy.get("scope")
    descoped = scope if isinstance(scope, Mapping) else {}
    findings: list[dict[str, str]] = []
    for artifact in sorted(spec_dir.rglob("*.md")):
        if artifact.name == RECONCILIATION_FILENAME:
            continue
        text = artifact.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        for feature, terms in _REJECTED_TERMS.items():
            if descoped.get(feature) != "descoped":
                continue
            for term in terms:
                if term in lowered:
                    findings.append({
                        "artifact": artifact.relative_to(spec_dir).as_posix(),
                        "term": term,
                        "policy_key": feature,
                        "status": "refuted",
                    })
    report = {
        "schema_version": 1,
        "decision_id": str((policy.get("provenance") or {}).get("decision_id") or ""),
        "requires_repair": bool(findings),
        "findings": findings,
    }
    lines = ["# Feature Policy Reconciliation", ""]
    if not findings:
        lines.append("No contradictory assumptions were found.")
    else:
        lines.extend((
            "The following retained assumptions are refuted by the user decision and require targeted repair:",
            "",
        ))
        lines.extend(
            f"- `{item['artifact']}`: `{item['term']}` is **{item['status']}** by `{item['policy_key']}`."
            for item in findings
        )
    (spec_dir / RECONCILIATION_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report

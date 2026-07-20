"""Controller-owned, target-scoped semantic repair packets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from harness.re_semantic_contract import SemanticCategory


_CATEGORIES = {
    "public-surface",
    "configuration",
    "error-recovery",
    "boundary",
    "operator-observable",
    "test-demonstrated",
    "evidence-scope",
}


@dataclass(frozen=True)
class ReRepairFinding:
    finding_id: str
    category: SemanticCategory
    text: str
    source_evidence: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, value: Mapping[str, object]) -> "ReRepairFinding":
        evidence = value.get("source_evidence")
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) for item in evidence
        ):
            raise ValueError("repair finding source_evidence must be strings")
        category = _required_string(value, "category")
        if category not in _CATEGORIES:
            raise ValueError(f"invalid repair finding category: {category}")
        return cls(
            finding_id=_required_string(value, "finding_id"),
            category=category,  # type: ignore[arg-type]
            text=_required_string(value, "text"),
            source_evidence=tuple(evidence),
        )


@dataclass(frozen=True)
class ReRepairPacket:
    source_id: str
    domain_id: str
    spec_fingerprint: str
    attempt: int
    findings: tuple[ReRepairFinding, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "source_id": self.source_id,
            "domain_id": self.domain_id,
            "spec_fingerprint": self.spec_fingerprint,
            "attempt": self.attempt,
            "findings": [
                {
                    **asdict(item),
                    "source_evidence": list(item.source_evidence),
                }
                for item in self.findings
            ],
        }

    @classmethod
    def from_json_dict(cls, value: Mapping[str, object]) -> "ReRepairPacket":
        if value.get("schema_version") != 1:
            raise ValueError("unsupported repair packet schema")
        attempt = value.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("repair packet attempt must be positive")
        raw_findings = value.get("findings")
        if not isinstance(raw_findings, list) or not raw_findings:
            raise ValueError("repair packet findings must be non-empty")
        if any(not isinstance(item, Mapping) for item in raw_findings):
            raise ValueError("repair packet finding must be an object")
        return cls(
            source_id=_required_string(value, "source_id"),
            domain_id=_required_string(value, "domain_id"),
            spec_fingerprint=_required_string(value, "spec_fingerprint"),
            attempt=attempt,
            findings=tuple(
                ReRepairFinding.from_json_dict(item) for item in raw_findings
            ),
        )


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"repair packet {key} must be a non-empty string")
    return item.strip()

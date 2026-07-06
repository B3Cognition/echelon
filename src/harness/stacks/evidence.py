from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StackEvidence:
    kind: str
    value: str
    source: str
    location: str = ""
    confidence: str = "high"

    def to_dict(self) -> dict[str, str]:
        payload = {
            "kind": self.kind,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
        }
        if self.location:
            payload["location"] = self.location
        return payload


def normalize_evidence_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")

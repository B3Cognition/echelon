"""Pinned Prosaic agent authority for RE engine protocol 2.3."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.re_v2.canonical import canonical_json_bytes, content_digest


class Protocol23AuthorityError(ValueError):
    """Raised when inspected Prosaic authority is absent or malformed."""


RE_BASELINER_AGENT_ID = "echelon.re-baseliner"
_FRONTMATTER_FIELDS = frozenset(
    {"name", "description", "execution", "tools", "color", "model_tier", "effort"}
)
_REQUIRED_VALUES = {
    "name": RE_BASELINER_AGENT_ID,
    "execution": "agent",
    "tools": "write",
    "color": "orange",
    "model_tier": "strong",
    "effort": "high",
}


@dataclass(frozen=True, slots=True)
class ProsaicAgentAuthorityV1:
    agent_id: str
    body: str
    frontmatter: Mapping[str, Any]
    schema_version: int = field(default=1, init=False)
    artifact_type: str = field(default="prosaic_agent_authority", init=False)
    loader_schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        if self.agent_id != RE_BASELINER_AGENT_ID:
            raise Protocol23AuthorityError(
                f"unsupported Prosaic agent authority: {self.agent_id!r}"
            )
        if not isinstance(self.body, str) or not self.body.strip():
            raise Protocol23AuthorityError("Prosaic agent body must be nonempty text")
        try:
            self.body.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise Protocol23AuthorityError("Prosaic agent body must be UTF-8") from exc
        if not isinstance(self.frontmatter, Mapping):
            raise Protocol23AuthorityError("Prosaic frontmatter must be an object")
        copied = dict(self.frontmatter)
        if set(copied) != _FRONTMATTER_FIELDS:
            raise Protocol23AuthorityError(
                "Prosaic frontmatter must contain exactly "
                + ", ".join(sorted(_FRONTMATTER_FIELDS))
            )
        description = copied.get("description")
        if not isinstance(description, str) or not description.strip():
            raise Protocol23AuthorityError(
                "Prosaic frontmatter description must be nonempty"
            )
        for key, expected in _REQUIRED_VALUES.items():
            if copied.get(key) != expected:
                raise Protocol23AuthorityError(
                    f"Prosaic frontmatter {key} must be {expected!r}"
                )
        object.__setattr__(self, "frontmatter", MappingProxyType(copied))

    @classmethod
    def from_artifact(
        cls, agent_id: str, artifact: ProsaicCommandArtifact
    ) -> "ProsaicAgentAuthorityV1":
        if not isinstance(artifact, ProsaicCommandArtifact):
            raise Protocol23AuthorityError(
                "Prosaic inspection returned no agent artifact"
            )
        return cls(
            agent_id=agent_id,
            body=artifact.body,
            frontmatter=artifact.frontmatter,
        )

    @property
    def body_bytes(self) -> bytes:
        return self.body.encode("utf-8")

    @property
    def body_hash(self) -> str:
        return content_digest(self.body_bytes)

    @property
    def frontmatter_hash(self) -> str:
        return content_digest(canonical_json_bytes(dict(self.frontmatter)))

    @property
    def inspection_receipt_hash(self) -> str:
        return content_digest(
            {
                "loader_schema_version": self.loader_schema_version,
                "agent_id": self.agent_id,
                "body_hash": self.body_hash,
                "frontmatter_hash": self.frontmatter_hash,
            }
        )

    @property
    def artifact_id(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "agent_id": self.agent_id,
            "body_hash": self.body_hash,
            "frontmatter_hash": self.frontmatter_hash,
            "frontmatter": dict(self.frontmatter),
            "inspection": {
                "loader_schema_version": self.loader_schema_version,
                "receipt_hash": self.inspection_receipt_hash,
            },
        }


def load_re_agent_authorities(
    project_root: Path,
    *,
    goal: str,
    loader: ProsaicPromptLoader | None = None,
) -> Mapping[str, ProsaicAgentAuthorityV1]:
    """Inspect and pin exactly the Prosaic agents required by *goal*."""
    if goal == "inventory":
        return MappingProxyType({})
    if goal != "baseline":
        raise Protocol23AuthorityError(f"unsupported RE v2 goal: {goal!r}")
    resolved_loader = loader or ProsaicPromptLoader(project_root)
    artifact = resolved_loader.load_subagent(RE_BASELINER_AGENT_ID)
    if artifact is None:
        raise Protocol23AuthorityError(
            "installed Prosaic agent echelon.re-baseliner is missing; run "
            "`echelon workspace migrate-to-prosaic` before starting RE"
        )
    authority = ProsaicAgentAuthorityV1.from_artifact(
        RE_BASELINER_AGENT_ID,
        artifact,
    )
    return MappingProxyType({RE_BASELINER_AGENT_ID: authority})

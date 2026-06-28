"""Feature metadata extraction for canonical and run-local Echelon specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
import re

import yaml

ACTIVE_STATUSES = {"active", "changed"}
LIFECYCLE_STATUSES = {"active", "changed", "deprecated", "superseded", "removed"}


def artifact_hash(path: Path) -> str:
    digest = sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def validate_lifecycle_status(status: str) -> str:
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(f"unknown lifecycle status: {status}")
    return status


@dataclass(frozen=True)
class RequirementMetadata:
    id: str
    status: str
    artifact_path: str
    artifact_hash: str
    use_cases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": validate_lifecycle_status(self.status),
            "artifact_path": self.artifact_path,
            "artifact_hash": self.artifact_hash,
            "use_cases": list(self.use_cases),
        }


@dataclass(frozen=True)
class UseCaseMetadata:
    id: str
    title: str
    status: str = "active"
    source_requirements: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": validate_lifecycle_status(self.status),
            "source_requirements": list(self.source_requirements),
            "supersedes": list(self.supersedes),
            "superseded_by": list(self.superseded_by),
        }


@dataclass(frozen=True)
class FeatureMetadata:
    schema_version: int
    feature_id: str
    spec_id: str
    slug: str
    status: str = "active"
    created_in_run: str | None = None
    last_changed_in_run: str | None = None
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    related_features: list[str] = field(default_factory=list)
    use_cases: list[UseCaseMetadata] = field(default_factory=list)
    requirements: list[RequirementMetadata] = field(default_factory=list)

    @classmethod
    def from_spec_dir(cls, spec_dir: Path, run_id: str | None = None) -> "FeatureMetadata":
        spec_id, slug = _split_spec_dir_name(spec_dir.name)
        spec_file = spec_dir / "spec.md"
        if not spec_file.exists():
            raise FileNotFoundError(spec_file)
        text = spec_file.read_text(encoding="utf-8")
        spec_hash = artifact_hash(spec_file)
        reqs = _extract_requirements(text, spec_file, spec_hash)
        use_cases = _extract_use_cases(text, reqs)
        return cls(
            schema_version=1,
            feature_id=f"{spec_id}-{slug}" if slug else spec_id,
            spec_id=spec_id,
            slug=slug,
            created_in_run=run_id,
            last_changed_in_run=run_id,
            use_cases=use_cases,
            requirements=reqs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "spec_id": self.spec_id,
            "slug": self.slug,
            "status": validate_lifecycle_status(self.status),
            "created_in_run": self.created_in_run,
            "last_changed_in_run": self.last_changed_in_run,
            "supersedes": list(self.supersedes),
            "superseded_by": list(self.superseded_by),
            "related_features": list(self.related_features),
            "use_cases": [u.to_dict() for u in self.use_cases],
            "requirements": [r.to_dict() for r in self.requirements],
        }


def write_feature_metadata(spec_dir: Path, metadata: FeatureMetadata) -> Path:
    path = spec_dir / "feature-metadata.yml"
    path.write_text(yaml.safe_dump(metadata.to_dict(), sort_keys=False), encoding="utf-8")
    return path


def read_feature_metadata(spec_dir: Path) -> FeatureMetadata | None:
    path = spec_dir / "feature-metadata.yml"
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return FeatureMetadata(
        schema_version=int(raw.get("schema_version", 1)),
        feature_id=str(raw.get("feature_id", "")),
        spec_id=str(raw.get("spec_id", "")),
        slug=str(raw.get("slug", "")),
        status=str(raw.get("status", "active")),
        created_in_run=raw.get("created_in_run"),
        last_changed_in_run=raw.get("last_changed_in_run"),
        supersedes=list(raw.get("supersedes") or []),
        superseded_by=list(raw.get("superseded_by") or []),
        related_features=list(raw.get("related_features") or []),
        use_cases=[
            UseCaseMetadata(
                id=str(u.get("id", "")),
                title=str(u.get("title", "")),
                status=str(u.get("status", "active")),
                source_requirements=list(u.get("source_requirements") or []),
                supersedes=list(u.get("supersedes") or []),
                superseded_by=list(u.get("superseded_by") or []),
            )
            for u in raw.get("use_cases", []) or []
        ],
        requirements=[
            RequirementMetadata(
                id=str(r.get("id", "")),
                status=str(r.get("status", "active")),
                artifact_path=str(r.get("artifact_path", "")),
                artifact_hash=str(r.get("artifact_hash", "")),
                use_cases=list(r.get("use_cases") or []),
            )
            for r in raw.get("requirements", []) or []
        ],
    )


def _split_spec_dir_name(name: str) -> tuple[str, str]:
    match = re.match(r"^([0-9]{3})(?:-(.*))?$", name)
    if not match:
        return name, ""
    return match.group(1), match.group(2) or ""


def _extract_requirements(
    text: str,
    spec_file: Path,
    spec_hash: str,
) -> list[RequirementMetadata]:
    ids = sorted(set(re.findall(r"\b(FR-[A-Za-z0-9_.-]+|NFR-[A-Za-z0-9_.-]+|REQ-[A-Za-z0-9_.-]+)\b", text)))
    return [
        RequirementMetadata(
            id=req_id,
            status="active",
            artifact_path=_to_artifact_relative_path(spec_file),
            artifact_hash=spec_hash,
        )
        for req_id in ids
    ]


def _extract_use_cases(
    text: str,
    reqs: list[RequirementMetadata],
) -> list[UseCaseMetadata]:
    use_cases: list[UseCaseMetadata] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.lower().startswith(("### user story", "## user story", "- user story")):
            use_cases.append(
                UseCaseMetadata(
                    id=f"UC-{len(use_cases) + 1:03d}",
                    title=stripped.lstrip("#- ").strip() or f"User story line {index}",
                    source_requirements=[r.id for r in reqs],
                )
            )
    return use_cases


def _to_artifact_relative_path(spec_file: Path) -> str:
    parts = spec_file.as_posix().split("/")
    if "runs" in parts:
        start = parts.index("runs")
        return "/".join(parts[start:])
    if "specs" in parts:
        start = parts.index("specs")
        return "/".join(parts[start:])
    return "specs/" + spec_file.parent.name + "/" + spec_file.name

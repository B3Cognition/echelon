"""Immutable data model for the generated human wiki."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WikiWarning:
    code: str
    message: str
    source_path: str | None = None


@dataclass(frozen=True)
class WikiArtifact:
    stable_id: str
    source_path: str
    projection_path: str
    title: str
    kind: str
    sha256: str
    size_bytes: int
    copy_mode: str


@dataclass(frozen=True)
class WikiSpec:
    stable_id: str
    spec_id: str
    source_path: str
    title: str
    lifecycle_status: str
    targets: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    publication_branch: str | None = None
    publication_commit: str | None = None


@dataclass(frozen=True)
class WikiSource:
    stable_id: str
    source_id: str
    path: str
    published_path: str | None


@dataclass(frozen=True)
class WikiDomain:
    stable_id: str
    source_id: str
    domain_id: str
    source_path: str
    title: str


@dataclass(frozen=True)
class WikiRelationship:
    kind: str
    source_id: str
    target_id: str
    evidence_path: str
    evidence_key: str


@dataclass(frozen=True)
class WikiRecentChange:
    commit: str
    committed_at: str
    subject: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class WikiModel:
    schema_version: int
    generated_at: str
    workspace_name: str
    workspace_root: str
    sources: tuple[WikiSource, ...]
    domains: tuple[WikiDomain, ...]
    specs: tuple[WikiSpec, ...]
    artifacts: tuple[WikiArtifact, ...]
    relationships: tuple[WikiRelationship, ...]
    recent_changes: tuple[WikiRecentChange, ...]
    warnings: tuple[WikiWarning, ...]

"""Immutable discovery snapshots and pure exact-source scope checks."""

from collections.abc import Sequence
from dataclasses import dataclass

from harness import element_identity_lifecycle as lifecycle
from harness.element_artifacts import _validate_input


SUPPORTED_ROLES = frozenset({"unknowns", "assumptions", "investigation", "evidence", "references"})


@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    path: str
    role: str
    before_text: str | None
    after_text: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryEditScope:
    writable_paths: tuple[str, ...]
    element_ids: tuple[str, ...]
    unowned_text_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    code: str
    path: str | None
    element_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class CandidateReferenceState:
    path: str
    source_sha256: str
    start: int
    end: int
    target_id: str
    relation: str
    assessed_revisions: tuple[str | None, ...]
    assessment_state: str


@dataclass(frozen=True, slots=True)
class DiscoveryCandidateCheck:
    diagnostics: tuple[CandidateDiagnostic, ...]
    references: tuple[CandidateReferenceState, ...]


def _sequence(value, name):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    return tuple(value)


def request(spec_id, artifacts, scope, changes):
    """Snapshot every caller sequence and validate before acquiring authority."""
    lifecycle.text(spec_id, "spec_id")
    artifacts = _sequence(artifacts, "artifacts")
    if not artifacts:
        raise ValueError("artifacts must be nonempty")
    for artifact in artifacts:
        if type(artifact) is not CandidateArtifact:
            raise ValueError("artifact must be an exact CandidateArtifact")
        lifecycle.text(artifact.role, "role")
        if artifact.before_text is None and artifact.after_text is None:
            raise ValueError("artifact requires at least one image")
        for image in (artifact.before_text, artifact.after_text):
            # Roles are controller assertions; unsupported strings are candidate
            # diagnostics. Reuse the adapter's path/text rules independently.
            _validate_input(path=artifact.path, role="references", text="" if image is None else image)
        artifact.path.encode("utf-8")
    paths = tuple(artifact.path for artifact in artifacts)
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate artifact path")
    if type(scope) is not DiscoveryEditScope:
        raise ValueError("scope must be an exact DiscoveryEditScope")
    writable = _sequence(scope.writable_paths, "writable_paths")
    labels = _sequence(scope.element_ids, "element_ids")
    unowned = _sequence(scope.unowned_text_paths, "unowned_text_paths")
    for path in (*writable, *unowned):
        _validate_input(path=path, role="references", text="")
        path.encode("utf-8")
    for label in labels:
        lifecycle.label(label)
        if label.split("-", 1)[0] not in {"U", "A"}:
            raise ValueError("element scope supports only U/A labels")
    if any(len(set(entries)) != len(entries) for entries in (writable, labels, unowned)):
        raise ValueError("duplicate scope entry")
    if not set(unowned) <= set(writable):
        raise ValueError("unowned_text_paths must be a subset of writable_paths")
    if not set(writable) <= set(paths):
        raise ValueError("writable_paths must be in the artifact bundle")
    changes = _sequence(changes, "changes")
    affected = ()
    if changes:
        changes, _, affected = lifecycle.request(changes)
    return artifacts, DiscoveryEditScope(writable, labels, unowned), changes, affected


def scope_diagnostics(artifact, before, after, scope):
    """Mask only exact authorized declaration spans, preserving all other text."""
    result = []
    path = artifact.path
    if artifact.before_text != artifact.after_text and path not in scope.writable_paths:
        result.append(CandidateDiagnostic("artifact_out_of_scope", path, None, "changed artifact is not writable"))
    for image, parsed, text in (("before", before, artifact.before_text), ("after", after, artifact.after_text)):
        end = 0
        for entry in sorted(parsed.declarations, key=lambda item: (item.span.start, item.span.end)):
            if not (end <= entry.span.start < entry.span.end <= len(text or "")):
                result.append(CandidateDiagnostic("overlapping_definition_spans", path, entry.element_id,
                                                  f"{image}: invalid or overlapping declaration ownership"))
            end = max(end, entry.span.end)
    if any(entry.code == "overlapping_definition_spans" for entry in result):
        return tuple(result)
    before_ids = {entry.element_id for entry in before.declarations}
    after_ids = {entry.element_id for entry in after.declarations}
    for label in before_ids | after_ids:
        old = tuple(entry.content for entry in before.declarations if entry.element_id == label)
        new = tuple(entry.content for entry in after.declarations if entry.element_id == label)
        if old != new and label not in scope.element_ids:
            result.append(CandidateDiagnostic("element_out_of_scope", path, label, "definition changed outside element scope"))

    def masked(text, parsed, other_ids):
        chunks, cursor = [], 0
        for entry in sorted(parsed.declarations, key=lambda item: item.span.start):
            if entry.element_id not in scope.element_ids:
                continue
            chunks.append(text[cursor:entry.span.start])
            # NUL is forbidden in source text and labels, so markers cannot
            # collide with user bytes or one another.
            if entry.element_id in other_ids:
                chunks.append(f"\x00{entry.element_id}\x00")
            cursor = entry.span.end
        chunks.append(text[cursor:])
        return "".join(chunks)

    if path not in scope.unowned_text_paths and (
        masked(artifact.before_text or "", before, after_ids)
        != masked(artifact.after_text or "", after, before_ids)
    ):
        result.append(CandidateDiagnostic("unowned_text_changed", path, None,
                                          "text outside authorized definition spans changed"))
    return tuple(result)

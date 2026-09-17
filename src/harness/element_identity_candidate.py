"""Immutable candidate snapshots and pure exact-source scope checks."""

from collections.abc import Sequence
from dataclasses import dataclass

from harness import element_identity_lifecycle as lifecycle
from harness.element_artifacts import _validate_input


SUPPORTED_ROLES = frozenset({"unknowns", "assumptions", "investigation", "evidence", "references"})
IDENTITY_SUPPORTED_ROLES = SUPPORTED_ROLES | frozenset({
    "requirements", "tasks", "lexicon", "lexicon_projection", "glossary",
    "evidence_inventory", "issues", "intent",
})


@dataclass(frozen=True, slots=True)
class _CandidatePolicy:
    name: str
    scope_type: type
    supported_roles: frozenset[str]
    supported_kinds: tuple[str, ...]
    preserve_caption_kinds: frozenset[str]
    nested_requirement_spans: bool


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
class IdentityEditScope:
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


@dataclass(frozen=True, slots=True)
class IdentityCandidateCheck:
    diagnostics: tuple[CandidateDiagnostic, ...]
    references: tuple[CandidateReferenceState, ...]


_DISCOVERY_POLICY = _CandidatePolicy(
    "discovery", DiscoveryEditScope, SUPPORTED_ROLES, ("U", "A"),
    frozenset({"U", "A"}), False,
)
_IDENTITY_POLICY = _CandidatePolicy(
    "identity", IdentityEditScope, IDENTITY_SUPPORTED_ROLES,
    ("U", "A", "FR", "NFR", "AC", "T", "ISS", "UI", "II"), frozenset({"U", "A"}), True,
)


def _sequence(value, name):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    return tuple(value)


def _request(spec_id, artifacts, scope, changes, *, policy):
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
    if type(scope) is not policy.scope_type:
        raise ValueError(f"scope must be an exact {policy.scope_type.__name__}")
    writable = _sequence(scope.writable_paths, "writable_paths")
    labels = _sequence(scope.element_ids, "element_ids")
    unowned = _sequence(scope.unowned_text_paths, "unowned_text_paths")
    for path in (*writable, *unowned):
        _validate_input(path=path, role="references", text="")
        path.encode("utf-8")
    for label in labels:
        lifecycle.label(label)
        if label.split("-", 1)[0] not in policy.supported_kinds:
            raise ValueError(f"element scope supports only {'/'.join(policy.supported_kinds)} labels")
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
    return artifacts, policy.scope_type(writable, labels, unowned), changes, affected


def request(spec_id, artifacts, scope, changes):
    """Normalize the strict discovery request through its fixed narrow policy."""
    return _request(spec_id, artifacts, scope, changes, policy=_DISCOVERY_POLICY)


def identity_request(spec_id, artifacts, scope, changes, projection_sources, evidence_inventories,
                     issue_reports):
    """Normalize the strict general request through its closed identity policy."""
    from harness.element_identity_bundle import _normalize
    from harness import element_identity_issue_candidate as issues

    artifacts, scope, changes, affected = _request(
        spec_id, artifacts, scope, changes, policy=_IDENTITY_POLICY)
    projection_sources, evidence_inventories = _normalize(
        projection_sources, evidence_inventories)
    issue_reports = issues._normalize(issue_reports)
    return artifacts, scope, changes, affected, projection_sources, evidence_inventories, issue_reports


def _scope_diagnostics(
        artifact, before, after, scope, *, allow_nested, preserve_image_presence=False):
    """Mask only exact authorized declaration spans, preserving all other text."""
    result = []
    path = artifact.path
    if artifact.before_text != artifact.after_text and path not in scope.writable_paths:
        result.append(CandidateDiagnostic("artifact_out_of_scope", path, None, "changed artifact is not writable"))
    for image, parsed, text in (("before", before, artifact.before_text), ("after", after, artifact.after_text)):
        stack = []
        for entry in sorted(parsed.declarations, key=lambda item: (item.span.start, -item.span.end)):
            start, end = entry.span.start, entry.span.end
            while stack and start >= stack[-1].span.end:
                stack.pop()
            valid_bounds = 0 <= start < end <= len(text or "")
            valid_relation = not stack or (
                allow_nested
                and stack[-1].span.start <= start
                and end <= stack[-1].span.end
                and (stack[-1].span.start, stack[-1].span.end) != (start, end)
            )
            if not valid_bounds or not valid_relation:
                result.append(CandidateDiagnostic("overlapping_definition_spans", path, entry.element_id,
                                                  f"{image}: invalid or overlapping declaration ownership"))
                continue
            stack.append(entry)
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
        for entry in sorted(parsed.declarations, key=lambda item: (item.span.start, -item.span.end)):
            if entry.element_id not in scope.element_ids:
                continue
            if entry.span.start < cursor:
                # An authorized outer declaration already owns this exact span.
                continue
            chunks.append(text[cursor:entry.span.start])
            # NUL is forbidden in source text and labels, so markers cannot
            # collide with user bytes or one another.
            if entry.element_id in other_ids:
                chunks.append(f"\x00{entry.element_id}\x00")
            cursor = entry.span.end
        chunks.append(text[cursor:])
        return "".join(chunks)

    before_unowned = masked(artifact.before_text or "", before, after_ids)
    after_unowned = masked(artifact.after_text or "", after, before_ids)
    presence_changed = (
        preserve_image_presence
        and (artifact.before_text is None) != (artifact.after_text is None)
    )
    if path not in scope.unowned_text_paths and (
            presence_changed or before_unowned != after_unowned):
        result.append(CandidateDiagnostic("unowned_text_changed", path, None,
                                          "text outside authorized definition spans changed"))
    return tuple(result)


def scope_diagnostics(artifact, before, after, scope):
    """Apply discovery's reviewed disjoint declaration policy."""
    return _scope_diagnostics(artifact, before, after, scope, allow_nested=False)


def _identity_scope_diagnostics(artifact, before, after, scope):
    """Apply the general policy, permitting real nested requirement declarations."""
    return _scope_diagnostics(
        artifact,
        before,
        after,
        scope,
        allow_nested=artifact.role == "requirements",
        preserve_image_presence=artifact.role in {"glossary", "evidence_inventory", "issues"},
    )

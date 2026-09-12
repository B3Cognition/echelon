"""Pure exact-source checks for proposed reference claims."""

from collections.abc import Sequence
import hashlib

from harness import element_identity_bindings as bindings
from harness import element_identity_bundle as bundle
from harness.element_artifacts import (
    ParsedIdentityArtifact,
    _validate_input,
    parse_identity_artifact,
)
from harness.element_identity_candidate import (
    CandidateArtifact,
    CandidateDiagnostic,
    IDENTITY_SUPPORTED_ROLES,
)
from harness.element_identity_lifecycle import text as validate_text


_EMPTY_CONTENT_SHA256 = hashlib.sha256(b"").hexdigest()
_INVALID_REQUEST = "invalid reference source validation request"


def _parse_image(artifact, text):
    if text is None:
        return ParsedIdentityArtifact(
            artifact.path, artifact.role, _EMPTY_CONTENT_SHA256, (), (), ())
    if artifact.role in {"glossary", "evidence_inventory"}:
        return bundle._empty_fact_image(path=artifact.path, role=artifact.role, text=text)
    return parse_identity_artifact(path=artifact.path, role=artifact.role, text=text)


def _normalize(artifacts, claims):
    try:
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise ValueError
        artifacts = tuple(artifacts)
        for artifact in artifacts:
            if type(artifact) is not CandidateArtifact:
                raise ValueError
            validate_text(artifact.role, "role")
            if artifact.before_text is None and artifact.after_text is None:
                raise ValueError
            for image in (artifact.before_text, artifact.after_text):
                _validate_input(
                    path=artifact.path,
                    role="references",
                    text="" if image is None else image,
                )
            artifact.path.encode("utf-8")
            artifact.role.encode("utf-8")
        paths = tuple(artifact.path for artifact in artifacts)
        if len(set(paths)) != len(paths):
            raise ValueError

        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            raise ValueError
        claims = tuple(claims)
        if claims:
            bindings.request(claims, bindings.ReferenceClaim)
        return artifacts, claims
    except (AttributeError, RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError(_INVALID_REQUEST) from error


def validate_reference_claim_sources(
    artifacts: Sequence[CandidateArtifact],
    claims: Sequence[bindings.ReferenceClaim],
) -> tuple[CandidateDiagnostic, ...]:
    """Match proposed claims to exact parsed references in supplied postimages.

    A clean result authenticates only source syntax and bytes. It is not target,
    semantic, completeness, freshness, storage, or publication authority.
    """
    artifacts, claims = _normalize(artifacts, claims)
    if not claims:
        return ()

    diagnostics = []
    by_path = {artifact.path: artifact for artifact in artifacts}
    claims_by_path = {}
    for claim in claims:
        claims_by_path.setdefault(claim.source_path, []).append(claim)

    for source_path, source_claims in claims_by_path.items():
        artifact = by_path.get(source_path)
        if artifact is None or artifact.after_text is None:
            for claim in source_claims:
                diagnostics.append(CandidateDiagnostic(
                    "reference_source_missing",
                    source_path,
                    claim.target_id,
                    "claim requires a present supplied after image",
                ))
            continue

        after_text = artifact.after_text
        actual_sha256 = hashlib.sha256(after_text.encode("utf-8")).hexdigest()
        for claim in source_claims:
            if claim.source_sha256 != actual_sha256:
                diagnostics.append(CandidateDiagnostic(
                    "reference_source_hash_mismatch",
                    source_path,
                    claim.target_id,
                    "claim source hash does not match supplied after image",
                ))

        if artifact.role not in IDENTITY_SUPPORTED_ROLES:
            diagnostics.append(CandidateDiagnostic(
                "unsupported_role", source_path, None,
                "claim source role is unsupported",
            ))
            continue

        parsed = _parse_image(artifact, after_text)
        for diagnostic in parsed.diagnostics:
            diagnostics.append(CandidateDiagnostic(
                diagnostic.code,
                source_path,
                None,
                f"after span:{diagnostic.span.start}:{diagnostic.span.end}: {diagnostic.detail}",
            ))

        eligible = set()
        for reference in parsed.references:
            if reference.range_end_id is not None:
                diagnostics.append(CandidateDiagnostic(
                    "unsupported_reference_range",
                    source_path,
                    reference.target_id,
                    "interval references are unsupported",
                ))
                continue
            eligible.add((
                f"span:{reference.span.start}:{reference.span.end}",
                reference.target_id,
                reference.relation,
            ))

        for claim in source_claims:
            if (claim.source_anchor, claim.target_id, claim.relation) not in eligible:
                diagnostics.append(CandidateDiagnostic(
                    "reference_source_binding_mismatch",
                    source_path,
                    claim.target_id,
                    "claim requires an exact parsed span, target and relation match",
                ))

    return tuple(sorted(
        set(diagnostics),
        key=lambda row: (row.path or "", row.element_id or "", row.code, row.detail),
    ))


__all__ = ["validate_reference_claim_sources"]

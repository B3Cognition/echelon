"""Pure normalization and checks for explicitly associated supplemental artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from harness.element_artifacts import ParsedIdentityArtifact, _validate_input
from harness.element_identity_candidate import CandidateDiagnostic
from harness.evidence_inventory import validate_evidence_inventory_text
from harness.spec_lexicon_gate import validate_spec_lexicon_texts


@dataclass(frozen=True, slots=True)
class LexiconProjectionSource:
    projection_path: str
    source_path: str
    glossary_path: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceInventoryContext:
    path: str
    required_seed_locators: tuple[str, ...] = ()


def _sequence(value, name):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    return tuple(value)


def _path(value):
    _validate_input(path=value, role="references", text="")
    value.encode("utf-8")
    return value


def _normalize(projection_sources, evidence_inventories):
    """Snapshot and validate all caller-owned descriptor structures."""
    projections = _sequence(projection_sources, "projection_sources")
    normalized_projections = []
    for descriptor in projections:
        if type(descriptor) is not LexiconProjectionSource:
            raise ValueError("projection source must be an exact LexiconProjectionSource")
        projection_path = _path(descriptor.projection_path)
        source_path = _path(descriptor.source_path)
        glossary_path = descriptor.glossary_path
        if glossary_path is not None:
            glossary_path = _path(glossary_path)
        normalized_projections.append(
            LexiconProjectionSource(projection_path, source_path, glossary_path))
    projection_paths = tuple(item.projection_path for item in normalized_projections)
    if len(set(projection_paths)) != len(projection_paths):
        raise ValueError("duplicate projection descriptor path")

    inventories = _sequence(evidence_inventories, "evidence_inventories")
    normalized_inventories = []
    for descriptor in inventories:
        if type(descriptor) is not EvidenceInventoryContext:
            raise ValueError("evidence inventory context must be an exact EvidenceInventoryContext")
        path = _path(descriptor.path)
        seeds = _sequence(descriptor.required_seed_locators, "required_seed_locators")
        for seed in seeds:
            if type(seed) is not str or not seed.strip():
                raise ValueError("required seed locator must be a nonblank string")
            if "\x00" in seed:
                raise ValueError("required seed locator contains NUL")
            seed.encode("utf-8")
        normalized_inventories.append(EvidenceInventoryContext(path, seeds))
    inventory_paths = tuple(item.path for item in normalized_inventories)
    if len(set(inventory_paths)) != len(inventory_paths):
        raise ValueError("duplicate evidence inventory descriptor path")
    return tuple(normalized_projections), tuple(normalized_inventories)


def _empty_fact_image(*, path: str, role: str, text: str) -> ParsedIdentityArtifact:
    """Represent opaque supplemental text without scanning it for identities."""
    return ParsedIdentityArtifact(
        path, role, hashlib.sha256(text.encode("utf-8")).hexdigest(), (), (), ())


def _diagnostics(images, projection_sources, evidence_inventories):
    """Validate associations and exact captured supplemental images."""
    result = []

    def diagnose(code, path, detail):
        result.append(CandidateDiagnostic(code, path, None, detail))

    by_path = {artifact.path: (artifact, before, after) for artifact, before, after in images}
    projection_by_path = {item.projection_path: item for item in projection_sources}
    inventory_by_path = {item.path: item for item in evidence_inventories}

    for artifact, _, _ in images:
        if artifact.role == "lexicon_projection" and artifact.path not in projection_by_path:
            diagnose("projection_binding_missing", artifact.path,
                     "lexicon projection requires an explicit source descriptor")
        if artifact.role == "evidence_inventory" and artifact.path not in inventory_by_path:
            diagnose("inventory_binding_missing", artifact.path,
                     "evidence inventory requires an explicit context descriptor")

    for descriptor in projection_sources:
        projection_row = by_path.get(descriptor.projection_path)
        association_valid = True
        if projection_row is None or projection_row[0].role != "lexicon_projection":
            diagnose("supplemental_binding_mismatch", descriptor.projection_path,
                     "projection descriptor path must name a captured lexicon_projection artifact")
            association_valid = False
        source_row = by_path.get(descriptor.source_path)
        if source_row is None or source_row[0].role != "requirements":
            diagnose("supplemental_binding_mismatch", descriptor.source_path,
                     "projection source path must name a captured requirements artifact")
            association_valid = False
        glossary_row = None
        if descriptor.glossary_path is not None:
            glossary_row = by_path.get(descriptor.glossary_path)
            if glossary_row is None or glossary_row[0].role != "glossary":
                diagnose("supplemental_binding_mismatch", descriptor.glossary_path,
                         "projection glossary path must name a captured glossary artifact")
                association_valid = False
        if not association_valid:
            continue

        projection_artifact, projection_before, projection_after = projection_row
        source_artifact, source_before, source_after = source_row
        for image, projection_text, projection_parsed, source_text, source_parsed in (
            ("before", projection_artifact.before_text, projection_before,
             source_artifact.before_text, source_before),
            ("after", projection_artifact.after_text, projection_after,
             source_artifact.after_text, source_after),
        ):
            if projection_text is None:
                continue
            if source_text is None:
                diagnose("supplemental_binding_mismatch", descriptor.source_path,
                         f"{image}: present projection image requires its captured source image")
                continue
            glossary_text = None
            if glossary_row is not None:
                glossary_artifact = glossary_row[0]
                glossary_text = (glossary_artifact.before_text if image == "before"
                                 else glossary_artifact.after_text)
            report = validate_spec_lexicon_texts(
                derived_text=projection_text,
                source_text=source_text,
                source_name=PurePosixPath(descriptor.source_path).name,
                glossary_text=glossary_text,
                artifact_type="SPEC",
            )
            for finding in report["findings"]:
                diagnose(
                    "invalid_lexicon_projection",
                    descriptor.projection_path,
                    f"{image}: {finding['code']}: {finding['message']} "
                    f"(line:{finding['line']}, span:{finding['span']})",
                )
            projection_labels = sorted(
                item.element_id for item in projection_parsed.declarations
                if item.kind in {"FR", "NFR", "AC"})
            source_labels = sorted(
                item.element_id for item in source_parsed.declarations
                if item.kind in {"FR", "NFR", "AC"})
            if projection_labels != source_labels:
                diagnose(
                    "projection_authority_mismatch",
                    descriptor.projection_path,
                    f"{image}: projection labels {projection_labels!r} do not match "
                    f"source labels {source_labels!r}",
                )

    for descriptor in evidence_inventories:
        inventory_row = by_path.get(descriptor.path)
        if inventory_row is None or inventory_row[0].role != "evidence_inventory":
            diagnose("supplemental_binding_mismatch", descriptor.path,
                     "inventory descriptor path must name a captured evidence_inventory artifact")
            continue
        artifact = inventory_row[0]
        for image, text in (("before", artifact.before_text), ("after", artifact.after_text)):
            if text is None:
                continue
            error = validate_evidence_inventory_text(
                text, required_seed_locators=descriptor.required_seed_locators)
            if error is not None:
                diagnose("invalid_evidence_inventory", descriptor.path, f"{image}: {error}")
    return tuple(result)


__all__ = ["EvidenceInventoryContext", "LexiconProjectionSource"]

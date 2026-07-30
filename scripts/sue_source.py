#!/usr/bin/env python3
"""Immutable source snapshots and provenance references for SUE.

This module deliberately has no provider or filesystem side effects.  Adapters
construct a bundle once; later stages use its digest and references to retain
the original source evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any


_LINE_RANGE_RE = re.compile(r"L([1-9][0-9]*)-L([1-9][0-9]*)\Z")
_LOCATOR_KINDS = frozenset({"line-range", "json-pointer", "xml-id", "page-paragraph"})


@dataclass(frozen=True)
class SourceRef:
    document_id: str
    locator_kind: str
    locator: str


@dataclass(frozen=True)
class SourceDocument:
    id: str
    source_uri: str
    media_type: str
    digest: str
    text: str

    @classmethod
    def from_text(
        cls, *, id: str, source_uri: str, media_type: str, text: str
    ) -> "SourceDocument":
        return cls(
            id=id,
            source_uri=source_uri,
            media_type=media_type,
            digest=sha256_text(text),
            text=text,
        )


@dataclass(frozen=True)
class ControlledSituation:
    given: str
    when: str
    then: str


@dataclass(frozen=True)
class DeclaredRelation:
    predicate: str
    target_unit_id: str
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True)
class SourceUnit:
    id: str
    kind: str
    text: str
    normative_level: str
    source_refs: tuple[SourceRef, ...]
    declared_relations: tuple[DeclaredRelation, ...]
    situation: ControlledSituation | None


@dataclass(frozen=True)
class GlossaryTerm:
    canonical: str
    aliases: tuple[str, ...]
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True)
class SourceAdapter:
    id: str
    version: str = "1"


@dataclass(frozen=True)
class SUESourceBundle:
    schema_version: int
    bundle_id: str
    snapshot_digest: str
    adapter: SourceAdapter
    documents: tuple[SourceDocument, ...]
    units: tuple[SourceUnit, ...]
    glossary: tuple[GlossaryTerm, ...]


def _json_value(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    """Return the stable JSON representation used for evidence digests."""
    return json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _line_bounds(locator: str) -> tuple[int, int]:
    match = _LINE_RANGE_RE.fullmatch(locator)
    if match is None:
        raise ValueError(f"invalid line-range locator: {locator!r}")
    start, end = (int(group) for group in match.groups())
    if start > end:
        raise ValueError(f"invalid line-range locator: {locator!r}")
    return start, end


def _validate_ref(documents: dict[str, SourceDocument], ref: SourceRef) -> None:
    _require_identifier(ref.document_id, "source reference document ID")
    if ref.document_id not in documents:
        raise ValueError(f"unknown document in source reference: {ref.document_id}")
    if ref.locator_kind not in _LOCATOR_KINDS:
        raise ValueError(f"unknown locator kind: {ref.locator_kind}")
    _require_identifier(ref.locator, "source reference locator")
    if ref.locator_kind == "line-range":
        start, end = _line_bounds(ref.locator)
        line_count = len(documents[ref.document_id].text.splitlines())
        if start > line_count or end > line_count:
            raise ValueError(f"line-range locator out of range: {ref.locator!r}")


def _validate_references(
    documents: dict[str, SourceDocument], refs: tuple[SourceRef, ...]
) -> None:
    for ref in refs:
        _validate_ref(documents, ref)


def make_bundle(
    *,
    bundle_id: str,
    adapter_id: str,
    documents: tuple[SourceDocument, ...],
    units: tuple[SourceUnit, ...],
    glossary: tuple[GlossaryTerm, ...] = (),
    adapter_version: str = "1",
    schema_version: int = 1,
) -> SUESourceBundle:
    """Validate immutable source records and attach their canonical digest."""
    _require_identifier(bundle_id, "bundle ID")
    _require_identifier(adapter_id, "adapter ID")
    _require_identifier(adapter_version, "adapter version")
    if schema_version < 1:
        raise ValueError("schema version must be positive")

    document_map: dict[str, SourceDocument] = {}
    for document in documents:
        _require_identifier(document.id, "document ID")
        if document.id in document_map:
            raise ValueError(f"duplicate document ID: {document.id}")
        if document.digest != sha256_text(document.text):
            raise ValueError(f"document digest does not match text: {document.id}")
        document_map[document.id] = document

    unit_ids: set[str] = set()
    for unit in units:
        _require_identifier(unit.id, "unit ID")
        if unit.id in unit_ids:
            raise ValueError(f"duplicate unit ID: {unit.id}")
        unit_ids.add(unit.id)
        _validate_references(document_map, unit.source_refs)
        for relation in unit.declared_relations:
            _require_identifier(relation.predicate, "relation predicate")
            _require_identifier(relation.target_unit_id, "relation target unit ID")
            _validate_references(document_map, relation.source_refs)

    for term in glossary:
        _require_identifier(term.canonical, "glossary canonical term")
        _validate_references(document_map, term.source_refs)

    unsigned = SUESourceBundle(
        schema_version=schema_version,
        bundle_id=bundle_id,
        snapshot_digest="",
        adapter=SourceAdapter(adapter_id, adapter_version),
        documents=documents,
        units=units,
        glossary=glossary,
    )
    return replace(unsigned, snapshot_digest=sha256_text(canonical_json(unsigned)))


def resolve_source_ref(bundle: SUESourceBundle, ref: SourceRef) -> str:
    """Resolve a supported provenance reference without changing source text."""
    documents = {document.id: document for document in bundle.documents}
    _validate_ref(documents, ref)
    if ref.locator_kind != "line-range":
        raise ValueError(f"cannot resolve locator kind: {ref.locator_kind}")
    start, end = _line_bounds(ref.locator)
    return "\n".join(documents[ref.document_id].text.splitlines()[start - 1 : end])

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
from pathlib import Path
from typing import Any


_LINE_RANGE_RE = re.compile(r"L([1-9][0-9]*)-L([1-9][0-9]*)\Z")
_LOCATOR_KINDS = frozenset({"line-range", "json-pointer", "xml-id", "page-paragraph"})
_EXPLICIT_UNIT_RE = re.compile(
    r"^\s*(?:(?:#{1,6}|[-*+])\s+)?(?:\*\*)?((?:FR|REQ|AC)[-_][A-Za-z0-9-]+)(?:\*\*)?\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_HEADING_UNIT_RE = re.compile(
    r"^\s*#+\s+((?:FR|REQ|AC)[-_][A-Za-z0-9-]+)\b", re.IGNORECASE
)
_NORMATIVE_RE = re.compile(r"\b(MUST|SHALL|SHOULD|MAY)\b", re.IGNORECASE)
_LEXICON_RE = re.compile(r"^(REQ|AC|GIVEN|WHEN|THEN):\s*(.*?)\s*$", re.IGNORECASE)


class SUESourceError(ValueError):
    """A source input cannot be represented with trustworthy provenance."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


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


def _normalize_relation(relation: DeclaredRelation) -> DeclaredRelation:
    return DeclaredRelation(
        predicate=relation.predicate,
        target_unit_id=relation.target_unit_id,
        source_refs=tuple(relation.source_refs),
    )


def _normalize_unit(unit: SourceUnit) -> SourceUnit:
    return SourceUnit(
        id=unit.id,
        kind=unit.kind,
        text=unit.text,
        normative_level=unit.normative_level,
        source_refs=tuple(unit.source_refs),
        declared_relations=tuple(
            _normalize_relation(relation) for relation in unit.declared_relations
        ),
        situation=unit.situation,
    )


def _normalize_glossary_term(term: GlossaryTerm) -> GlossaryTerm:
    return GlossaryTerm(
        canonical=term.canonical,
        aliases=tuple(term.aliases),
        source_refs=tuple(term.source_refs),
    )


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

    documents = tuple(documents)
    units = tuple(_normalize_unit(unit) for unit in units)
    glossary = tuple(_normalize_glossary_term(term) for term in glossary)

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
    return _line_range_text(documents[ref.document_id].text, start, end)


def _line_range_text(document_text: str, start: int, end: int) -> str:
    """Return a line range exactly as source-reference resolution exposes it."""
    lines = document_text.splitlines(keepends=True)
    start_offset = sum(len(line) for line in lines[: start - 1])
    selected = "".join(lines[start - 1 : end])
    if selected.endswith("\r\n"):
        selected = selected[:-2]
    elif selected.endswith(("\n", "\r")):
        selected = selected[:-1]
    return document_text[start_offset : start_offset + len(selected)]


def _read_utf8(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise SUESourceError("INPUT_ERROR", f"cannot read {path}: {error}") from error


def _media_type(path: Path) -> str:
    return "text/markdown" if path.suffix.lower() in {".md", ".markdown"} else "text/plain"


def _normative_level(text: str) -> str:
    match = _NORMATIVE_RE.search(text)
    return match.group(1).lower().replace("shall", "must") if match else "unspecified"


def load_markdown_lexicon(path: Path) -> SUESourceBundle:
    """Load the small, explicit Markdown and lexicon source subset."""
    path = Path(path)
    text = _read_utf8(path)
    document_id = path.stem
    document = SourceDocument.from_text(
        id=document_id, source_uri=str(path), media_type=_media_type(path), text=text
    )
    units: list[SourceUnit] = []
    lines = text.splitlines()
    lexicon: dict[str, tuple[str, int]] = {}

    def flush_lexicon() -> None:
        nonlocal lexicon
        if "REQ" not in lexicon and "AC" not in lexicon:
            return
        key = "REQ" if "REQ" in lexicon else "AC"
        unit_id, id_line = lexicon[key]
        end = max(line for _, line in lexicon.values())
        block_text = _line_range_text(text, id_line, end)
        situation = None
        if all(label in lexicon for label in ("GIVEN", "WHEN", "THEN")):
            situation = ControlledSituation(
                given=lexicon["GIVEN"][0], when=lexicon["WHEN"][0], then=lexicon["THEN"][0]
            )
        units.append(SourceUnit(
            id=unit_id,
            kind="requirement" if key == "REQ" else "acceptance-criterion",
            text=block_text,
            normative_level=_normative_level(block_text),
            source_refs=(SourceRef(document_id, "line-range", f"L{id_line}-L{end}"),),
            declared_relations=(), situation=situation,
        ))
        lexicon = {}

    for number, line in enumerate(lines, start=1):
        lexicon_match = _LEXICON_RE.fullmatch(line)
        if lexicon_match:
            label, value = lexicon_match.groups()
            label = label.upper()
            if label in {"REQ", "AC"} and lexicon:
                flush_lexicon()
            lexicon[label] = (value, number)
            continue
        if lexicon:
            flush_lexicon()
        explicit = _EXPLICIT_UNIT_RE.fullmatch(line)
        if explicit:
            unit_id, _ = explicit.groups()
            kind = "acceptance-criterion" if unit_id.upper().startswith("AC") else "requirement"
        else:
            heading = _HEADING_UNIT_RE.match(line)
            if heading:
                unit_id = heading.group(1)
                kind = "acceptance-criterion" if unit_id.upper().startswith("AC") else "requirement"
            else:
                bullet = re.fullmatch(r"\s*[-*+]\s+(.+?)\s*", line)
                if bullet and _NORMATIVE_RE.search(bullet.group(1)):
                    unit_id = f"{document_id}:L{number}-L{number}"
                    kind = "requirement"
                else:
                    continue
        unit_text = _line_range_text(text, number, number)
        units.append(SourceUnit(
            id=unit_id, kind=kind, text=unit_text,
            normative_level=_normative_level(unit_text),
            source_refs=(SourceRef(document_id, "line-range", f"L{number}-L{number}"),),
            declared_relations=(), situation=None,
        ))
    flush_lexicon()
    if not units:
        raise SUESourceError(
            "INCONCLUSIVE_INPUT",
            "no explicit requirement, acceptance criterion, lexicon block, or normative bullet found",
        )
    try:
        return make_bundle(bundle_id=document_id, adapter_id="markdown-lexicon", documents=(document,), units=tuple(units))
    except ValueError as error:
        raise SUESourceError("INVALID_INPUT", str(error)) from error


def _source_error(code: str, message: str) -> None:
    raise SUESourceError(code, message)


def _manifest_refs(value: object) -> tuple[SourceRef, ...]:
    if not isinstance(value, list):
        _source_error("INVALID_MANIFEST", "source_refs must be a list")
    try:
        return tuple(SourceRef(**ref) for ref in value)
    except (TypeError, ValueError) as error:
        _source_error("INVALID_MANIFEST", f"invalid source reference: {error}")


def load_generic_manifest(path: Path) -> SUESourceBundle:
    """Load a generic JSON manifest without fetching or inferring source data."""
    path = Path(path)
    try:
        data = json.loads(_read_utf8(path))
    except json.JSONDecodeError as error:
        _source_error("INVALID_MANIFEST", f"invalid JSON: {error.msg}")
    if not isinstance(data, dict):
        _source_error("INVALID_MANIFEST", "manifest root must be an object")
    directory = path.parent.resolve()
    documents: list[SourceDocument] = []
    for record in data.get("documents", []):
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "document must be an object")
        relative_path = record.get("path")
        if not isinstance(relative_path, str):
            _source_error("INVALID_MANIFEST", "document path must be a string")
        candidate = (directory / relative_path).resolve()
        try:
            candidate.relative_to(directory)
        except ValueError:
            _source_error("PATH_ESCAPE", f"document path escapes manifest directory: {relative_path}")
        if not candidate.is_file():
            _source_error("MISSING_DOCUMENT", f"document does not exist: {relative_path}")
        content = _read_utf8(candidate)
        document = SourceDocument.from_text(
            id=record.get("id"), source_uri=relative_path,
            media_type=record.get("media_type"), text=content,
        )
        supplied_digest = record.get("digest")
        if supplied_digest is not None and supplied_digest != document.digest:
            _source_error("DIGEST_MISMATCH", f"document digest does not match: {document.id}")
        documents.append(document)

    units: list[SourceUnit] = []
    for record in data.get("units", []):
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "unit must be an object")
        relations = []
        for relation in record.get("declared_relations", []):
            if not isinstance(relation, dict):
                _source_error("INVALID_MANIFEST", "declared relation must be an object")
            relations.append(DeclaredRelation(
                predicate=relation.get("predicate"), target_unit_id=relation.get("target_unit_id"),
                source_refs=_manifest_refs(relation.get("source_refs", [])),
            ))
        raw_situation = record.get("situation")
        try:
            situation = ControlledSituation(**raw_situation) if raw_situation is not None else None
            source_refs = _manifest_refs(record.get("source_refs", []))
            if not source_refs:
                _source_error("UNGROUNDED_UNIT", "manifest units require at least one source reference")
            units.append(SourceUnit(
                id=record.get("id"), kind=record.get("kind"), text=record.get("text"),
                normative_level=record.get("normative_level", "unspecified"),
                source_refs=source_refs,
                declared_relations=tuple(relations), situation=situation,
            ))
        except TypeError as error:
            _source_error("INVALID_MANIFEST", f"invalid unit: {error}")

    glossary: list[GlossaryTerm] = []
    aliases: dict[str, str] = {}
    for record in data.get("glossary", []):
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "glossary term must be an object")
        term = GlossaryTerm(record.get("canonical"), tuple(record.get("aliases", [])), _manifest_refs(record.get("source_refs", [])))
        for alias in term.aliases:
            previous = aliases.setdefault(alias.casefold(), term.canonical)
            if previous != term.canonical:
                _source_error("AMBIGUOUS_ALIAS", f"alias maps to multiple terms: {alias}")
        glossary.append(term)
    try:
        bundle = make_bundle(
            bundle_id=data.get("bundle_id"), adapter_id="manifest", schema_version=data.get("schema_version", 1),
            documents=tuple(documents), units=tuple(units), glossary=tuple(glossary),
        )
        unit_ids = {unit.id for unit in bundle.units}
        for unit in bundle.units:
            for relation in unit.declared_relations:
                if relation.target_unit_id not in unit_ids:
                    _source_error("UNRESOLVED_TARGET", f"unknown relation target: {relation.target_unit_id}")
            for ref in unit.source_refs:
                if resolve_source_ref(bundle, ref) != unit.text:
                    _source_error("SOURCE_TEXT_MISMATCH", f"unit text does not match {ref.locator}")
        return bundle
    except SUESourceError:
        raise
    except ValueError as error:
        raise SUESourceError("INVALID_MANIFEST", str(error)) from error


def load_source_bundle(path: Path, source_format: str = "auto") -> SUESourceBundle:
    """Load one supported source shape, preserving only explicit evidence."""
    path = Path(path)
    if source_format == "auto":
        source_format = "manifest" if path.name.endswith(".sue.json") else "markdown-lexicon"
    if source_format == "manifest":
        return load_generic_manifest(path)
    if source_format in {"markdown", "lexicon", "markdown-lexicon"}:
        return load_markdown_lexicon(path)
    raise SUESourceError("UNSUPPORTED_FORMAT", f"unsupported source format: {source_format}")

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
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any


_LINE_RANGE_RE = re.compile(r"L([1-9][0-9]*)-L([1-9][0-9]*)\Z")
_MEDIA_TYPE_RE = re.compile(
    r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z"
)
_UNIT_KINDS = frozenset(
    {"requirement", "acceptance-criterion", "constraint", "rule"}
)
_NORMATIVE_LEVELS = frozenset({"must", "should", "may", "unspecified"})
UNIT_FAMILIES = ("REQ", "FR", "AC", "NFR", "ERR", "SC", "U", "OQ", "A")
UNIT_ID_PATTERN = (
    rf"(?:{'|'.join(UNIT_FAMILIES)})"
    r"[-_][A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*"
)
UNIT_ID_RE = re.compile(
    rf"^(?P<family>{'|'.join(UNIT_FAMILIES)})"
    r"[-_][A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$",
    re.IGNORECASE,
)
_EXPLICIT_UNIT_RE = re.compile(
    rf"^\s*(?P<bullet>[-*+]\s+)?(?:\*\*)?"
    rf"(?P<unit_id>{UNIT_ID_PATTERN})(?:\*\*)?"
    r"(?P<colon>\s*:)?\s+(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
_HEADING_UNIT_RE = re.compile(
    rf"^\s*(#{{1,6}})\s+({UNIT_ID_PATTERN})(?=\s|:|$)(.*)$",
    re.IGNORECASE,
)
_MARKED_UNIT_CANDIDATE_RE = re.compile(
    rf"^\s*(?:[-*+]\s+|#{{1,6}}\s+)(?:\*\*)?"
    rf"((?:{'|'.join(UNIT_FAMILIES)})[-_][^\s*:]+)",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_MARKDOWN_RULE_RE = re.compile(r"^\s*(?:-{3,}|_{3,}|\*{3,})\s*$")
_NORMATIVE_RE = re.compile(r"\b(MUST|SHALL|SHOULD|MAY)\b", re.IGNORECASE)
_LEXICON_RE = re.compile(r"^(REQ|AC|GIVEN|WHEN|THEN):\s*(.*?)\s*$", re.IGNORECASE)


class SUESourceError(ValueError):
    """A source input cannot be represented with trustworthy provenance."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _source_error(code: str, message: str) -> None:
    raise SUESourceError(code, message)


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


@dataclass(frozen=True)
class SourceKnowledgeMap:
    """Deterministic, declaration-only indexes for one source bundle."""

    bundle_id: str
    units_by_id: Mapping[str, SourceUnit]
    outgoing: Mapping[str, tuple[DeclaredRelation, ...]]
    glossary_by_alias: Mapping[str, tuple[str, ...]]


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


def _normalize_glossary_label(label: str) -> str:
    normalized = " ".join(label.casefold().split())
    for article in ("a ", "an ", "the "):
        if normalized.startswith(article):
            normalized = normalized[len(article) :]
            break
    return " ".join(_singular(word) for word in normalized.split())


def _singular(word: str) -> str:
    """Apply the conservative singularization rule used by V3."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _relation_sort_key(relation: DeclaredRelation) -> tuple[object, ...]:
    return (
        relation.predicate,
        relation.target_unit_id,
        tuple(
            (ref.document_id, ref.locator_kind, ref.locator)
            for ref in relation.source_refs
        ),
    )


def build_source_knowledge_map(bundle: SUESourceBundle) -> SourceKnowledgeMap:
    """Build deterministic indexes without deriving relations from source text."""
    units_by_id = {unit.id: unit for unit in sorted(bundle.units, key=lambda unit: unit.id)}
    outgoing = {
        unit_id: tuple(sorted(unit.declared_relations, key=_relation_sort_key))
        for unit_id, unit in units_by_id.items()
    }
    aliases: dict[str, set[str]] = {}
    for term in bundle.glossary:
        for label in (term.canonical, *term.aliases):
            alias = _normalize_glossary_label(label)
            aliases.setdefault(alias, set()).add(term.canonical)
    glossary_by_alias = {
        alias: tuple(sorted(canonicals))
        for alias, canonicals in sorted(aliases.items())
    }
    return SourceKnowledgeMap(
        bundle_id=bundle.bundle_id,
        units_by_id=MappingProxyType(units_by_id),
        outgoing=MappingProxyType(outgoing),
        glossary_by_alias=MappingProxyType(glossary_by_alias),
    )


def canonical_glossary_match(knowledge_map: SourceKnowledgeMap, label: str) -> str | None:
    """Return an exact declared glossary match only when it is unambiguous."""
    matches = knowledge_map.glossary_by_alias.get(_normalize_glossary_label(label), ())
    return matches[0] if len(matches) == 1 else None


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _source_error("INVALID_IDENTIFIER", f"{label} must be a non-empty string")


def _require_string(
    value: object, label: str, *, nonempty: bool = False, code: str = "INVALID_SCHEMA"
) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        _source_error(code, f"{label} must be a {qualifier}string")
    return value


def _require_collection(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        _source_error("INVALID_COLLECTION", f"{label} must be a list or tuple")
    return tuple(value)


def _line_bounds(locator: str) -> tuple[int, int]:
    match = _LINE_RANGE_RE.fullmatch(locator)
    if match is None:
        _source_error("INVALID_LOCATOR", f"invalid line-range locator: {locator!r}")
    start, end = (int(group) for group in match.groups())
    if start > end:
        _source_error("INVALID_LOCATOR", f"invalid line-range locator: {locator!r}")
    return start, end


def _validate_ref(documents: dict[str, SourceDocument], ref: SourceRef) -> None:
    if not isinstance(ref, SourceRef):
        _source_error("INVALID_SOURCE_REF", "source reference must be a SourceRef")
    _require_identifier(ref.document_id, "source reference document ID")
    if ref.document_id not in documents:
        _source_error(
            "UNKNOWN_DOCUMENT",
            f"unknown document in source reference: {ref.document_id}",
        )
    _require_string(
        ref.locator_kind,
        "source reference locator kind",
        nonempty=True,
        code="INVALID_LOCATOR",
    )
    _require_string(
        ref.locator,
        "source reference locator",
        code="INVALID_LOCATOR",
    )
    document = documents[ref.document_id]
    if ref.locator_kind == "line-range":
        start, end = _line_bounds(ref.locator)
        line_count = len(document.text.splitlines())
        if start > line_count or end > line_count:
            _source_error(
                "INVALID_LOCATOR",
                f"line-range locator out of range: {ref.locator!r}",
            )
    elif ref.locator_kind == "json-pointer":
        _resolve_json_pointer(document, ref.locator)
    else:
        _source_error(
            "UNSUPPORTED_LOCATOR",
            f"locator kind is not implemented: {ref.locator_kind}",
        )


def _validate_references(
    documents: dict[str, SourceDocument], refs: object
) -> tuple[SourceRef, ...]:
    normalized = _require_collection(refs, "source references")
    for ref in normalized:
        _validate_ref(documents, ref)
    return normalized


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
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        _source_error(
            "UNSUPPORTED_SCHEMA",
            f"schema_version must be exactly 1, got {schema_version!r}",
        )

    raw_documents = _require_collection(documents, "documents")
    raw_units = _require_collection(units, "units")
    raw_glossary = _require_collection(glossary, "glossary")

    document_map: dict[str, SourceDocument] = {}
    normalized_documents: list[SourceDocument] = []
    for document in raw_documents:
        if not isinstance(document, SourceDocument):
            _source_error("INVALID_DOCUMENT", "document must be a SourceDocument")
        _require_identifier(document.id, "document ID")
        if document.id in document_map:
            _source_error(
                "DUPLICATE_DOCUMENT", f"duplicate document ID: {document.id}"
            )
        _require_string(
            document.source_uri,
            "document source URI",
            nonempty=True,
            code="INVALID_DOCUMENT",
        )
        media_type = _require_string(
            document.media_type,
            "document media type",
            nonempty=True,
            code="INVALID_MEDIA_TYPE",
        )
        if _MEDIA_TYPE_RE.fullmatch(media_type) is None:
            _source_error(
                "INVALID_MEDIA_TYPE",
                f"invalid document media type: {media_type!r}",
            )
        _require_string(document.text, "document text", code="INVALID_DOCUMENT")
        _require_string(document.digest, "document digest", code="INVALID_DIGEST")
        if document.digest != sha256_text(document.text):
            _source_error(
                "DIGEST_MISMATCH",
                f"document digest does not match text: {document.id}",
            )
        document_map[document.id] = document
        normalized_documents.append(document)

    unit_ids: set[str] = set()
    normalized_units: list[SourceUnit] = []
    for unit in raw_units:
        if not isinstance(unit, SourceUnit):
            _source_error("INVALID_UNIT", "unit must be a SourceUnit")
        _require_identifier(unit.id, "unit ID")
        if unit.id in unit_ids:
            _source_error("DUPLICATE_UNIT", f"duplicate unit ID: {unit.id}")
        unit_ids.add(unit.id)
        kind = _require_string(
            unit.kind, "unit kind", code="INVALID_UNIT_KIND"
        )
        if kind not in _UNIT_KINDS:
            _source_error("INVALID_UNIT_KIND", f"invalid unit kind: {kind!r}")
        _require_string(unit.text, "unit text", code="INVALID_UNIT")
        normative_level = _require_string(
            unit.normative_level,
            "unit normative level",
            code="INVALID_NORMATIVE_LEVEL",
        )
        if normative_level not in _NORMATIVE_LEVELS:
            _source_error(
                "INVALID_NORMATIVE_LEVEL",
                f"invalid normative level: {normative_level!r}",
            )
        source_refs = _validate_references(document_map, unit.source_refs)
        if not source_refs:
            _source_error(
                "UNGROUNDED_UNIT",
                f"unit {unit.id} requires at least one source reference",
            )
        raw_relations = _require_collection(
            unit.declared_relations, "declared relations"
        )
        normalized_relations: list[DeclaredRelation] = []
        for relation in raw_relations:
            if not isinstance(relation, DeclaredRelation):
                _source_error(
                    "INVALID_RELATION",
                    "declared relation must be a DeclaredRelation",
                )
            _require_identifier(relation.predicate, "relation predicate")
            _require_identifier(
                relation.target_unit_id, "relation target unit ID"
            )
            relation_refs = _validate_references(
                document_map, relation.source_refs
            )
            if not relation_refs:
                _source_error(
                    "UNGROUNDED_RELATION",
                    f"relation to {relation.target_unit_id} requires a source reference",
                )
            normalized_relations.append(
                DeclaredRelation(
                    relation.predicate,
                    relation.target_unit_id,
                    relation_refs,
                )
            )
        situation = unit.situation
        if situation is not None:
            if not isinstance(situation, ControlledSituation):
                _source_error(
                    "INVALID_SITUATION",
                    "unit situation must be a ControlledSituation or null",
                )
            for label, value in (
                ("given", situation.given),
                ("when", situation.when),
                ("then", situation.then),
            ):
                _require_string(
                    value,
                    f"situation {label}",
                    code="INVALID_SITUATION",
                )
        normalized_units.append(
            SourceUnit(
                id=unit.id,
                kind=kind,
                text=unit.text,
                normative_level=normative_level,
                source_refs=source_refs,
                declared_relations=tuple(normalized_relations),
                situation=situation,
            )
        )

    for unit in normalized_units:
        for relation in unit.declared_relations:
            if relation.target_unit_id not in unit_ids:
                _source_error(
                    "UNRESOLVED_TARGET",
                    f"unknown relation target: {relation.target_unit_id}",
                )
        for ref in unit.source_refs:
            resolved = _resolve_ref_from_documents(document_map, ref)
            if resolved != unit.text:
                _source_error(
                    "SOURCE_TEXT_MISMATCH",
                    f"unit {unit.id} text does not match {ref.locator}",
                )

    normalized_glossary: list[GlossaryTerm] = []
    for term in raw_glossary:
        if not isinstance(term, GlossaryTerm):
            _source_error(
                "INVALID_GLOSSARY", "glossary term must be a GlossaryTerm"
            )
        _require_identifier(term.canonical, "glossary canonical term")
        aliases = _require_collection(term.aliases, "glossary aliases")
        for alias in aliases:
            _require_string(
                alias,
                "glossary alias",
                nonempty=True,
                code="INVALID_GLOSSARY",
            )
        refs = _validate_references(document_map, term.source_refs)
        normalized_glossary.append(
            GlossaryTerm(term.canonical, aliases, refs)
        )

    unsigned = SUESourceBundle(
        schema_version=schema_version,
        bundle_id=bundle_id,
        snapshot_digest="",
        adapter=SourceAdapter(adapter_id, adapter_version),
        documents=tuple(normalized_documents),
        units=tuple(normalized_units),
        glossary=tuple(normalized_glossary),
    )
    return replace(unsigned, snapshot_digest=sha256_text(canonical_json(unsigned)))


def resolve_source_ref(bundle: SUESourceBundle, ref: SourceRef) -> str:
    """Resolve a supported provenance reference without changing source text."""
    documents = {document.id: document for document in bundle.documents}
    _validate_ref(documents, ref)
    return _resolve_ref_from_documents(documents, ref)


def _resolve_ref_from_documents(
    documents: dict[str, SourceDocument], ref: SourceRef
) -> str:
    document = documents[ref.document_id]
    if ref.locator_kind == "json-pointer":
        return _resolve_json_pointer(document, ref.locator)
    if ref.locator_kind != "line-range":
        _source_error(
            "UNSUPPORTED_LOCATOR",
            f"locator kind is not implemented: {ref.locator_kind}",
        )
    start, end = _line_bounds(ref.locator)
    return _line_range_text(document.text, start, end)


def _resolve_json_pointer(document: SourceDocument, pointer: str) -> str:
    media_type = document.media_type.casefold()
    if media_type != "application/json" and not media_type.endswith("+json"):
        _source_error(
            "INVALID_LOCATOR",
            f"json-pointer requires a JSON document: {document.id}",
        )
    try:
        value: object = json.loads(
            document.text, parse_constant=_reject_json_constant
        )
    except (json.JSONDecodeError, ValueError) as error:
        _source_error(
            "INVALID_JSON_DOCUMENT",
            f"document {document.id} is not valid JSON: {error}",
        )
    if pointer == "":
        tokens: list[str] = []
    elif pointer.startswith("/"):
        tokens = pointer[1:].split("/")
    else:
        _source_error(
            "INVALID_LOCATOR",
            f"JSON Pointer must be empty or begin with '/': {pointer!r}",
        )

    current = value
    for encoded_token in tokens:
        if re.search(r"~(?:[^01]|$)", encoded_token):
            _source_error(
                "INVALID_LOCATOR",
                f"invalid JSON Pointer escape in token: {encoded_token!r}",
            )
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                _source_error(
                    "INVALID_LOCATOR",
                    f"JSON Pointer object key does not exist: {token!r}",
                )
            current = current[token]
        elif isinstance(current, list):
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                _source_error(
                    "INVALID_LOCATOR",
                    f"invalid JSON Pointer array index: {token!r}",
                )
            index = int(token)
            if index >= len(current):
                _source_error(
                    "INVALID_LOCATOR",
                    f"JSON Pointer array index out of range: {index}",
                )
            current = current[index]
        else:
            _source_error(
                "INVALID_LOCATOR",
                "JSON Pointer cannot traverse through a scalar value",
            )

    if isinstance(current, (dict, list)):
        _source_error(
            "NON_SCALAR_LOCATOR",
            "JSON Pointer must resolve to a scalar value",
        )
    if isinstance(current, str):
        return current
    return json.dumps(
        current,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"invalid JSON constant: {constant}")


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


def unit_id_family(unit_id: str) -> str | None:
    """Return the exact declared family for a supported source-unit ID."""
    match = UNIT_ID_RE.fullmatch(unit_id)
    return match.group("family").upper() if match else None


def _explicit_unit_match(line: str) -> re.Match[str] | None:
    match = _EXPLICIT_UNIT_RE.fullmatch(line)
    if match is None:
        return None
    # Bare definitions retain the established ``FR-001: ...`` form. A colon
    # is optional only for a Markdown list item such as ``- **FR-EL-001**``.
    if match.group("bullet") is None and match.group("colon") is None:
        return None
    return match


def load_markdown_lexicon(path: Path) -> SUESourceBundle:
    """Load the small, explicit Markdown and lexicon source subset."""
    path = Path(path)
    text = _read_utf8(path)
    document_id = path.stem
    document = SourceDocument.from_text(
        id=document_id, source_uri=str(path), media_type=_media_type(path), text=text
    )
    lines = text.splitlines()
    located_units: list[tuple[int, SourceUnit]] = []
    lexicon: dict[str, tuple[str, int]] = {}
    heading_sites: list[tuple[int, str, str]] = []
    covered_heading_lines: set[int] = set()
    explicit_sites: list[tuple[int, str]] = []
    covered_explicit_lines: set[int] = set()

    for number, line in enumerate(lines, start=1):
        heading = _HEADING_UNIT_RE.fullmatch(line)
        if heading:
            _, unit_id, suffix = heading.groups()
            heading_sites.append((number, unit_id, suffix))

    for index, (start, unit_id, suffix) in enumerate(heading_sites):
        end = (
            heading_sites[index + 1][0] - 1
            if index + 1 < len(heading_sites)
            else len(lines)
        )
        body_has_text = any(line.strip() for line in lines[start:end])
        title_has_text = bool(suffix.strip().lstrip(":").strip())
        if not body_has_text and not title_has_text:
            _source_error(
                "INCONCLUSIVE_INPUT",
                f"requirement heading {unit_id} has no semantic title or body",
            )
        unit_text = _line_range_text(text, start, end)
        kind = (
            "acceptance-criterion"
            if unit_id.upper().startswith("AC")
            else "requirement"
        )
        located_units.append(
            (
                start,
                SourceUnit(
                    id=unit_id,
                    kind=kind,
                    text=unit_text,
                    normative_level=_normative_level(unit_text),
                    source_refs=(
                        SourceRef(
                            document_id,
                            "line-range",
                            f"L{start}-L{end}",
                        ),
                    ),
                    declared_relations=(),
                    situation=None,
                ),
            )
        )
        covered_heading_lines.update(range(start, end + 1))

    for number, line in enumerate(lines, start=1):
        if number in covered_heading_lines:
            continue
        explicit = _explicit_unit_match(line)
        if explicit:
            explicit_sites.append((number, explicit.group("unit_id")))
            continue
        candidate = _MARKED_UNIT_CANDIDATE_RE.match(line)
        if candidate and unit_id_family(candidate.group(1)) is None:
            _source_error(
                "UNSUPPORTED_UNIT_ID",
                f"cannot represent explicit unit identifier exactly on "
                f"line {number}: {candidate.group(1)!r}",
            )

    for index, (start, unit_id) in enumerate(explicit_sites):
        end = (
            explicit_sites[index + 1][0] - 1
            if index + 1 < len(explicit_sites)
            else len(lines)
        )
        for boundary in range(start + 1, end + 1):
            line = lines[boundary - 1]
            if _MARKDOWN_HEADING_RE.match(line) or _MARKDOWN_RULE_RE.fullmatch(line):
                end = boundary - 1
                break
        while end > start and not lines[end - 1].strip():
            end -= 1
        unit_text = _line_range_text(text, start, end)
        located_units.append(
            (
                start,
                SourceUnit(
                    id=unit_id,
                    kind=(
                        "acceptance-criterion"
                        if unit_id_family(unit_id) == "AC"
                        else "requirement"
                    ),
                    text=unit_text,
                    normative_level=_normative_level(unit_text),
                    source_refs=(
                        SourceRef(
                            document_id,
                            "line-range",
                            f"L{start}-L{end}",
                        ),
                    ),
                    declared_relations=(),
                    situation=None,
                ),
            )
        )
        covered_explicit_lines.update(range(start, end + 1))

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
        located_units.append(
            (
                id_line,
                SourceUnit(
                    id=unit_id,
                    kind=(
                        "requirement"
                        if key == "REQ"
                        else "acceptance-criterion"
                    ),
                    text=block_text,
                    normative_level=_normative_level(block_text),
                    source_refs=(
                        SourceRef(
                            document_id,
                            "line-range",
                            f"L{id_line}-L{end}",
                        ),
                    ),
                    declared_relations=(),
                    situation=situation,
                ),
            )
        )
        lexicon = {}

    for number, line in enumerate(lines, start=1):
        if number in covered_heading_lines or number in covered_explicit_lines:
            if lexicon:
                flush_lexicon()
            continue
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
        bullet = re.fullmatch(r"\s*[-*+]\s+(.+?)\s*", line)
        if bullet and _NORMATIVE_RE.search(bullet.group(1)):
            unit_id = f"{document_id}:L{number}-L{number}"
            kind = "requirement"
        else:
            continue
        unit_text = _line_range_text(text, number, number)
        located_units.append(
            (
                number,
                SourceUnit(
                    id=unit_id,
                    kind=kind,
                    text=unit_text,
                    normative_level=_normative_level(unit_text),
                    source_refs=(
                        SourceRef(
                            document_id,
                            "line-range",
                            f"L{number}-L{number}",
                        ),
                    ),
                    declared_relations=(),
                    situation=None,
                ),
            )
        )
    flush_lexicon()
    units = tuple(unit for _, unit in sorted(located_units, key=lambda item: item[0]))
    if not units:
        raise SUESourceError(
            "INCONCLUSIVE_INPUT",
            "no explicit requirement, acceptance criterion, lexicon block, or normative bullet found",
        )
    return make_bundle(
        bundle_id=document_id,
        adapter_id="markdown-lexicon",
        documents=(document,),
        units=units,
    )


def _manifest_refs(value: object) -> tuple[SourceRef, ...]:
    if not isinstance(value, list):
        _source_error("INVALID_MANIFEST", "source_refs must be a list")
    refs: list[SourceRef] = []
    for record in value:
        if not isinstance(record, dict):
            _source_error(
                "INVALID_MANIFEST", "source reference must be an object"
            )
        document_id = _manifest_string(record, "document_id")
        locator_kind = _manifest_string(record, "locator_kind")
        locator = _manifest_string(record, "locator", nonempty=False)
        refs.append(SourceRef(document_id, locator_kind, locator))
    return tuple(refs)


def _manifest_list(
    record: Mapping[str, object],
    key: str,
    *,
    default: object | None = None,
) -> list[object]:
    if key not in record:
        if default is None:
            _source_error("INVALID_MANIFEST", f"missing manifest field: {key}")
        value = default
    else:
        value = record[key]
    if not isinstance(value, list):
        _source_error("INVALID_MANIFEST", f"{key} must be a list")
    return value


def _manifest_string(
    record: Mapping[str, object],
    key: str,
    *,
    nonempty: bool = True,
) -> str:
    if key not in record:
        _source_error("INVALID_MANIFEST", f"missing manifest field: {key}")
    value = record[key]
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        _source_error(
            "INVALID_MANIFEST",
            f"{key} must be a {qualifier}string",
        )
    return value


def load_generic_manifest(path: Path) -> SUESourceBundle:
    """Load a generic JSON manifest without fetching or inferring source data."""
    path = Path(path)
    try:
        data = json.loads(_read_utf8(path))
    except json.JSONDecodeError as error:
        _source_error("INVALID_MANIFEST", f"invalid JSON: {error.msg}")
    if not isinstance(data, dict):
        _source_error("INVALID_MANIFEST", "manifest root must be an object")
    if data.get("schema_version") != 1 or isinstance(
        data.get("schema_version"), bool
    ):
        _source_error(
            "UNSUPPORTED_SCHEMA",
            f"schema_version must be exactly 1, got {data.get('schema_version')!r}",
        )
    bundle_id = _manifest_string(data, "bundle_id")
    document_records = _manifest_list(data, "documents")
    unit_records = _manifest_list(data, "units")
    glossary_records = _manifest_list(data, "glossary")

    directory = path.parent.resolve()
    documents: list[SourceDocument] = []
    for record in document_records:
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "document must be an object")
        document_id = _manifest_string(record, "id")
        media_type = _manifest_string(record, "media_type")
        if "path" in record:
            relative_path = _manifest_string(record, "path")
            if "text" in record:
                _source_error(
                    "INVALID_MANIFEST",
                    f"document {document_id} cannot contain both path and text",
                )
            candidate = (directory / relative_path).resolve()
            try:
                candidate.relative_to(directory)
            except ValueError:
                _source_error(
                    "PATH_ESCAPE",
                    f"document path escapes manifest directory: {relative_path}",
                )
            if not candidate.is_file():
                _source_error(
                    "MISSING_DOCUMENT",
                    f"document does not exist: {relative_path}",
                )
            content = _read_utf8(candidate)
            source_uri = relative_path
        elif "text" in record:
            content = _manifest_string(record, "text", nonempty=False)
            source_uri = _manifest_string(record, "source_uri")
            if "digest" not in record:
                _source_error(
                    "INVALID_MANIFEST",
                    f"embedded document {document_id} requires a digest",
                )
        else:
            _source_error(
                "INVALID_MANIFEST",
                f"document {document_id} requires path or embedded text",
            )
        document = SourceDocument.from_text(
            id=document_id,
            source_uri=source_uri,
            media_type=media_type,
            text=content,
        )
        supplied_digest = record.get("digest")
        if supplied_digest is not None:
            if not isinstance(supplied_digest, str):
                _source_error(
                    "INVALID_MANIFEST", "document digest must be a string"
                )
            if supplied_digest != document.digest:
                _source_error(
                    "DIGEST_MISMATCH",
                    f"document digest does not match: {document.id}",
                )
        documents.append(document)

    units: list[SourceUnit] = []
    for record in unit_records:
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "unit must be an object")
        relations: list[DeclaredRelation] = []
        for relation in _manifest_list(
            record, "declared_relations", default=[]
        ):
            if not isinstance(relation, dict):
                _source_error(
                    "INVALID_MANIFEST",
                    "declared relation must be an object",
                )
            relations.append(
                DeclaredRelation(
                    predicate=_manifest_string(relation, "predicate"),
                    target_unit_id=_manifest_string(
                        relation, "target_unit_id"
                    ),
                    source_refs=_manifest_refs(
                        _manifest_list(
                            relation, "source_refs", default=[]
                        )
                    ),
                )
            )
        raw_situation = record.get("situation")
        if raw_situation is None:
            situation = None
        elif isinstance(raw_situation, dict):
            if set(raw_situation) != {"given", "when", "then"}:
                _source_error(
                    "INVALID_MANIFEST",
                    "situation requires exactly given, when, and then",
                )
            situation = ControlledSituation(
                given=_manifest_string(
                    raw_situation, "given", nonempty=False
                ),
                when=_manifest_string(raw_situation, "when", nonempty=False),
                then=_manifest_string(raw_situation, "then", nonempty=False),
            )
        else:
            _source_error(
                "INVALID_MANIFEST", "situation must be an object or null"
            )
        units.append(
            SourceUnit(
                id=_manifest_string(record, "id"),
                kind=_manifest_string(record, "kind"),
                text=_manifest_string(record, "text", nonempty=False),
                normative_level=_manifest_string(
                    record, "normative_level"
                ),
                source_refs=_manifest_refs(
                    _manifest_list(record, "source_refs", default=[])
                ),
                declared_relations=tuple(relations),
                situation=situation,
            )
        )

    glossary: list[GlossaryTerm] = []
    aliases: dict[str, str] = {}
    for record in glossary_records:
        if not isinstance(record, dict):
            _source_error("INVALID_MANIFEST", "glossary term must be an object")
        raw_aliases = _manifest_list(record, "aliases")
        term_aliases = tuple(
            _require_string(
                alias,
                "glossary alias",
                nonempty=True,
                code="INVALID_MANIFEST",
            )
            for alias in raw_aliases
        )
        term = GlossaryTerm(
            _manifest_string(record, "canonical"),
            term_aliases,
            _manifest_refs(
                _manifest_list(record, "source_refs", default=[])
            ),
        )
        for alias in term.aliases:
            previous = aliases.setdefault(alias.casefold(), term.canonical)
            if previous != term.canonical:
                _source_error(
                    "AMBIGUOUS_ALIAS",
                    f"alias maps to multiple terms: {alias}",
                )
        glossary.append(term)
    return make_bundle(
        bundle_id=bundle_id,
        adapter_id="manifest",
        schema_version=data["schema_version"],
        documents=tuple(documents),
        units=tuple(units),
        glossary=tuple(glossary),
    )


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

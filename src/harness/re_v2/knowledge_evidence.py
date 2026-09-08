"""Opt-in safe snapshot evidence for repaired RE discovery, not legacy dispatch.

Provider projections contain untrusted data, never execution instructions. Original
evidence identities belong only in the private mapping receipt. Screening is
defense in depth: a clean result is not a semantic or universal secrecy guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import PurePosixPath
import re
import stat

from harness.secret_scan import RULES
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1, Protocol22EvidenceError
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError, nonnegative_int, safe_id, safe_relative_path,
)
from harness.re_v2.snapshot import CapturedSnapshot


_MAX_SCREEN_BYTES = 8 * 1024 * 1024
_MAX_RANGE_BYTES = 65_536
_MAX_CONTEXT_BYTES = 262_144
_EXCLUDED_NAMES = frozenset({
    "credentials", "credentials.json", "secrets.json", "secrets.yml", "secrets.yaml",
    ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
})
_EXCLUDED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")
_ASSIGNMENT = re.compile(
    r'''(?im)(?<![\w-])["']?(?:[a-z][a-z0-9_-]*[_-])?'''
    r'''(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)'''
    r'''["']?[^\S\r\n]*[:=][^\S\r\n]*(?:"(?P<double>(?:\\[^\r\n]|[^"\\\r\n])*)"|'''
    r'''\x27(?P<single>(?:\\[^\r\n]|[^\x27\\\r\n])*)\x27|(?P<bare>[^\r\n]+))''',
)


class KnowledgeEvidenceError(ValueError):
    """Sanitized closed-code evidence failure; never include untrusted values."""


def security_policy_id() -> str:
    """Bind the exact screening rules and limits, without an operator selector."""
    return content_digest({
        "contract": "re-safe-evidence-v1",
        "rules": [(r.rule_id, r.pattern.pattern, r.pattern.flags) for r in RULES],
        "assignment": (_ASSIGNMENT.pattern, _ASSIGNMENT.flags),
        "excluded_names": sorted(_EXCLUDED_NAMES),
        "excluded_suffixes": list(_EXCLUDED_SUFFIXES),
        "exclude_env_variants": True,
        "screen_bytes": _MAX_SCREEN_BYTES,
        "range_bytes": _MAX_RANGE_BYTES,
        "context_bytes": _MAX_CONTEXT_BYTES,
    })


def _secret_spans(text: str) -> tuple[tuple[int, int, str], ...]:
    spans = {(m.start(), m.end(), rule.rule_id)
             for rule in RULES for m in rule.pattern.finditer(text)}
    for match in _ASSIGNMENT.finditer(text):
        group = next(name for name in ("double", "single", "bare") if match.group(name) is not None)
        value = match.group(group)
        if value and set(value) != {"*"}:
            spans.add((*match.span(group), "credential-assignment"))
    return tuple(sorted(spans))


@dataclass(frozen=True, slots=True)
class EvidenceSelectorV1:
    source_id: str
    path: str
    byte_start: int
    byte_end: int

    def __post_init__(self) -> None:
        try:
            safe_id(self.source_id, "source")
            safe_relative_path(self.path, "path")
            self.path.encode("utf-8")
            nonnegative_int(self.byte_start, "start")
            nonnegative_int(self.byte_end, "end")
        except (Protocol22SchemaError, UnicodeError):
            raise KnowledgeEvidenceError("invalid-evidence-selector") from None
        if (self.byte_end < self.byte_start
                or self.byte_end - self.byte_start > _MAX_RANGE_BYTES
                or any(ord(char) < 32 or ord(char) == 127 for char in self.path)
                or _secret_spans(self.source_id) or _secret_spans(self.path)):
            raise KnowledgeEvidenceError("invalid-evidence-selector")

    def to_json_dict(self) -> dict[str, object]:
        return {"source_id": self.source_id, "path": self.path,
                "byte_start": self.byte_start, "byte_end": self.byte_end}


@dataclass(frozen=True, slots=True)
class SafeEvidenceProjectionV1:
    projection_id: str
    mapping_receipt_id: str
    _provider_bytes: bytes = field(repr=False)

    def provider_bytes(self) -> bytes:
        return self._provider_bytes


def _excluded(path: str) -> bool:
    parts = tuple(part.lower() for part in PurePosixPath(path).parts)
    return any(part in _EXCLUDED_NAMES or part == ".env" or part.startswith(".env.")
               or part.endswith(_EXCLUDED_SUFFIXES) for part in parts)


def _screen_source(raw: bytes) -> tuple[bytes, tuple[tuple[int, int, str], ...]]:
    text = raw.decode("utf-8")
    spans = _secret_spans(text)
    # Convert character offsets once, in order; do not rescan long prefixes for
    # every match. Ranges address original bytes even after multibyte redaction.
    positions = sorted({p for start, end, _ in spans for p in (start, end)})
    byte_offsets: dict[int, int] = {}
    previous = byte_offset = 0
    for position in positions:
        byte_offset += len(text[previous:position].encode("utf-8"))
        byte_offsets[position] = byte_offset
        previous = position
    ranges = tuple((byte_offsets[start], byte_offsets[end], reason) for start, end, reason in spans)
    safe = bytearray(raw)
    for start, end, _ in ranges:
        safe[start:end] = b"*" * (end - start)
    return bytes(safe), ranges


class SafeEvidenceBoundary:
    """Resolve only an exact selected inventory entry in the captured snapshot."""

    def __init__(
        self, snapshot: CapturedSnapshot, partition: WorkspacePartitionCatalogV1,
        selected_sources: tuple[str, ...], objects: ObjectStore,
    ) -> None:
        declared = {source.source_id for source in partition.sources}
        if (not selected_sources or len(selected_sources) != len(set(selected_sources))
                or not set(selected_sources).issubset(declared)):
            raise KnowledgeEvidenceError("invalid-evidence-selection")
        try:
            self._reader = PinnedSnapshotReaderV1(snapshot, partition)
        except (Protocol22EvidenceError, OSError):
            raise KnowledgeEvidenceError("unavailable-snapshot") from None
        self._records = {
            (source.source_id, record.source_relative_path): record
            for source in partition.sources if source.source_id in selected_sources
            for record in source.files
        }
        self._snapshot_id = snapshot.snapshot_id
        self._partition_id = partition.identity
        self._objects = objects

    def project(self, selector: EvidenceSelectorV1) -> SafeEvidenceProjectionV1:
        if not isinstance(selector, EvidenceSelectorV1):
            raise KnowledgeEvidenceError("invalid-evidence-selector")
        record = self._records.get((selector.source_id, selector.path))
        if record is None or record.object_kind != "regular":
            raise KnowledgeEvidenceError("unavailable-evidence")
        if selector.byte_end > record.byte_count:
            raise KnowledgeEvidenceError("invalid-evidence-range")
        reason = None
        if _excluded(selector.path):
            reason = "excluded-path"
        elif record.byte_count > _MAX_SCREEN_BYTES:
            reason = "local-screening-bound"
        elif record.text_status != "eligible_utf8":
            reason = "non-text-evidence"
        text = ""
        ranges: tuple[tuple[int, int, str], ...] = ()
        if reason is None:
            try:
                raw = self._reader.read_file(selector.source_id, selector.path, record)
                # Validate original boundaries before masking turns multibyte
                # credentials into ASCII and could conceal an invalid selector.
                raw[:selector.byte_start].decode("utf-8")
                raw[selector.byte_start:selector.byte_end].decode("utf-8")
                if any(r.rule_id == "private-key" and r.pattern.search(raw.decode("utf-8")) for r in RULES):
                    reason = "private-key-material"
                else:
                    safe, full_ranges = _screen_source(raw)
                    text = safe[selector.byte_start:selector.byte_end].decode("utf-8")
                    ranges = tuple((max(start, selector.byte_start), min(end, selector.byte_end), rule)
                                   for start, end, rule in full_ranges
                                   if start < selector.byte_end and end > selector.byte_start)
            except (Protocol22EvidenceError, OSError, UnicodeError):
                raise KnowledgeEvidenceError("unsafe-evidence-projection") from None
        if reason is not None:
            ranges = ((selector.byte_start, selector.byte_end, reason),) if selector.byte_end > selector.byte_start else ()
        provider = canonical_json_bytes({
            "schema_version": 1, "kind": "untrusted_snapshot_evidence",
            "security_policy_id": security_policy_id(), **selector.to_json_dict(),
            "disposition": "withheld" if reason else "redacted" if ranges else "available",
            "reason_code": reason, "text": text,
            "withheld_ranges": [{"byte_start": start, "byte_end": end, "reason_code": rule}
                                for start, end, rule in ranges],
        })
        if len(provider) > _MAX_CONTEXT_BYTES:
            raise KnowledgeEvidenceError("evidence-context-bound")
        receipt = canonical_json_bytes({
            "schema_version": 1, "kind": "private_safe_evidence_mapping",
            "snapshot_id": self._snapshot_id, "partition_id": self._partition_id,
            "file_record_id": content_digest(record.to_json_dict()),
            "original_content_id": record.content_hash,
            "selector": selector.to_json_dict(), "security_policy_id": security_policy_id(),
            "projection_id": content_digest(provider),
        })
        try:
            projection_id = self._objects.put_blob(provider)
            receipt_id = self._objects.put_blob(receipt)
        except (ReV2LedgerError, OSError):
            raise KnowledgeEvidenceError("evidence-store-failed") from None
        return SafeEvidenceProjectionV1(projection_id, receipt_id, provider)


def _quarantine_output(payload: bytes, quarantine: ObjectStore) -> None:
    """Keep unsafe bytes outside ordinary artifacts in an owner-only store."""
    object_id = content_digest(payload)
    digest = object_id.removeprefix("sha256:")
    bucket = digest[:2]
    object_path = quarantine.root / "sha256" / bucket / digest[2:]

    def check_object() -> None:
        metadata = object_path.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                or metadata.st_uid != os.getuid()):
            raise KnowledgeEvidenceError("unsafe-quarantine-store")

    try:
        for path in (quarantine.root, quarantine.root / "sha256", quarantine.root / "sha256" / bucket):
            if not path.exists() and not path.is_symlink() and path.name == bucket:
                continue
            metadata = path.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077
                    or metadata.st_uid != os.getuid()):
                raise KnowledgeEvidenceError("unsafe-quarantine-store")
        if object_path.exists() or object_path.is_symlink():
            check_object()
        quarantine.put_blob(payload)
        check_object()
    except (ReV2LedgerError, OSError):
        raise KnowledgeEvidenceError("unsafe-quarantine-store") from None


def screen_provider_output(payload: bytes, quarantine: ObjectStore) -> bytes:
    """Screen before ordinary logs/artifacts; preserve clean output for parsing.

    This does not accept a schema or certify claims. Callers must quarantine here
    before retaining raw provider output or formatting provider exception text.
    """
    if not isinstance(payload, bytes) or len(payload) > _MAX_CONTEXT_BYTES:
        raise KnowledgeEvidenceError("provider-output-bound")
    try:
        text = payload.decode("utf-8")
        unsafe = bool(_secret_spans(text))

        def screen_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            nonlocal unsafe
            # Inspect every pair before normal JSON decoding discards duplicate
            # keys. Even a superseded value must never reach ordinary retention.
            for key, value in pairs:
                unsafe = unsafe or bool(_secret_spans(json.dumps({key: value}, ensure_ascii=False)))
            return dict(pairs)

        try:
            decoded = json.loads(text, object_pairs_hook=screen_pairs)
        except json.JSONDecodeError:
            decoded = None
        if decoded is not None:
            # Reserialization removes JSON escaping of token characters and
            # preserves key/value relationships for credential assignments.
            normalized = json.dumps(decoded, ensure_ascii=False)
            unsafe = unsafe or bool(_secret_spans(normalized))
        if not unsafe:
            return payload
    except (ValueError, RecursionError):
        # Uninspectable output is not safe merely because no rule matched.
        _quarantine_output(payload, quarantine)
        raise KnowledgeEvidenceError("uninspectable-provider-output") from None
    _quarantine_output(payload, quarantine)
    raise KnowledgeEvidenceError("unsafe-provider-output")

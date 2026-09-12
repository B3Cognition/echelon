"""Explicit, inactive SQLite allocation authority; never inferred from documents.

Reservations are permanent claims, including when their caller dies. Lifecycle
storage is explicit and inactive: no producer or publication is wired here.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import UUID, uuid4

from kernel.element_ids import decimal_to_int, format_element_id, int_to_decimal
from harness import element_identity_schema as schema
from harness import element_identity_lifecycle as lifecycle
from harness import element_identity_lifecycle_store as lifecycle_store
from harness import element_identity_bindings as bindings
from harness import element_identity_binding_store as binding_store


_VERSION = 1
_BUSY_SECONDS = 10
_KINDS = frozenset({"AC", "FR", "NFR", "ISS", "U", "A", "T"})
_LABEL = re.compile(r"(AC|FR|NFR|ISS|U|A|T)-([A-Za-z0-9][A-Za-z0-9_.-]*)\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_DATABASE = "registry.sqlite3"
_MARKER = "authority.json"

class IdentityStoreError(ValueError):
    """Invalid request or unavailable authority; callers must not invent IDs."""


def _public(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except IdentityStoreError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as error:
            raise IdentityStoreError(f"{function.__name__}: {error}") from error
    return guarded


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IdentityStoreError(f"{name} must be a nonblank string without NUL")


def _kind(value):
    if not isinstance(value, str) or value not in _KINDS:
        raise IdentityStoreError("kind must be AC, FR, NFR, ISS, U, A, or T")


def _integer(value):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise IdentityStoreError("authority contains a noncanonical decimal counter")
    return decimal_to_int(value)


def _decimal(value):
    return int_to_decimal(value)


def _labels(kind, first, count):
    return tuple(format_element_id(kind, ordinal) for ordinal in range(first, first + count))


def _parse_label(label):
    if not isinstance(label, str) or (match := _LABEL.fullmatch(label)) is None:
        raise IdentityStoreError("element_id must have a recognized kind and an ASCII legacy suffix")
    kind, suffix = match.groups()
    if suffix.isascii() and suffix.isdecimal():
        ordinal = suffix.lstrip("0") or "0"
        if ordinal == "0":
            raise IdentityStoreError("numeric element ordinals must be positive")
        return kind, ordinal
    return kind, None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _safe_path(path):
    """Check before following any directory/file link, including SQLite sidecars."""
    path = Path(os.path.abspath(path))
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise IdentityStoreError(f"symlinked identity state is forbidden: {component}")
    return path


def _directory(path):
    path = _safe_path(path)
    if not path.is_dir():
        raise IdentityStoreError(f"required identity directory is missing: {path}")
    for child in path.iterdir():
        if child.is_symlink():
            raise IdentityStoreError(f"symlinked identity state is forbidden: {child}")
    return path


def _file(path):
    path = _safe_path(path)
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or not mode & 0o444:
        raise IdentityStoreError(f"required identity file is not readable and regular: {path}")
    return path


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _read_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IdentityStoreError("identity metadata contains duplicate JSON keys")
            result[key] = value
        return result
    with _file(path).open("r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique_object)


def _authority(value):
    if (not isinstance(value, dict) or set(value) != {"version", "workspace_uuid", "epoch_uuid"}
            or type(value["version"]) is not int or value["version"] != _VERSION):
        raise IdentityStoreError("missing or unsupported authority marker version")
    for key in ("workspace_uuid", "epoch_uuid"):
        if not isinstance(value[key], str) or str(UUID(value[key])) != value[key]:
            raise IdentityStoreError(f"invalid authority {key}")
    return value


@contextmanager
def _database(path, *, readonly=False):
    _file(path)
    connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, timeout=_BUSY_SECONDS, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA fullfsync=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise IdentityStoreError("unsupported authority journal mode; expected DELETE")
        yield connection
    finally:
        connection.close()


def _validate(connection, marker, *, allow_old=False):
    return schema.validate(connection, marker, allow_old=allow_old)


def _claim_directory(path):
    path = _safe_path(path)
    path.mkdir(mode=0o700)  # Any existing directory, even empty crash debris, blocks reuse.
    _sync_directory(path.parent)
    return path


def _claim_authority(workspace):
    workspace = _safe_path(workspace)
    if not workspace.is_dir():
        raise IdentityStoreError("workspace must be an existing directory")
    config = _safe_path(workspace / ".echelon")
    config.mkdir(mode=0o700, exist_ok=True)
    _sync_directory(workspace)
    return _claim_directory(config / "identity")


def _hash_file(path):
    with _file(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class IdentityStore:
    """An authority handle with no persistent connection or process-local counter."""

    def __init__(self, workspace: Path, marker: dict):
        self._workspace = workspace
        self._marker = dict(marker)

    @classmethod
    @_public
    def initialize(cls, workspace: Path) -> IdentityStore:
        """Explicitly claim fresh state; incomplete attempts remain blocking debris."""
        directory = _claim_authority(workspace)
        marker = {"version": _VERSION, "workspace_uuid": str(uuid4()), "epoch_uuid": str(uuid4())}
        _write_new(directory / _MARKER, _json(marker).encode("ascii"))
        _write_new(directory / _DATABASE, b"")
        with _database(directory / _DATABASE) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in schema.SCHEMA.values():
                    connection.execute(statement)
                connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                       [(key, str(value)) for key, value in marker.items()]
                                       + [("schema_version", schema.SCHEMA_VERSION)])
                connection.execute(f"PRAGMA user_version={_VERSION}")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        _sync_directory(directory)
        return cls.open(workspace)

    @classmethod
    @_public
    def open(cls, workspace: Path) -> IdentityStore:
        """Open established state without creating files or scanning entities."""
        workspace = _safe_path(workspace)
        directory = _directory(workspace / ".echelon/identity")
        marker = _authority(_read_json(directory / _MARKER))
        with _database(directory / _DATABASE) as connection:
            _validate(connection, marker)
        return cls(workspace, marker)

    @classmethod
    @_public
    def upgrade(cls, workspace: Path) -> IdentityStore:
        """Explicitly upgrade only recognized authority; never initialize or repair."""
        workspace = _safe_path(workspace)
        directory = _directory(workspace / ".echelon/identity")
        marker = _authority(_read_json(directory / _MARKER))
        with _database(directory / _DATABASE) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = _validate(connection, marker, allow_old=True)
                cls._audit(connection, lifecycle_state=version != "1", binding_state=version == "3")
                if version != schema.SCHEMA_VERSION:
                    schema.upgrade(connection)
                _validate(connection, marker)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return cls.open(workspace)

    @contextmanager
    def _transaction(self, *, write=False):
        directory = _directory(self._workspace / ".echelon/identity")
        marker = _authority(_read_json(directory / _MARKER))
        if marker != self._marker:
            raise IdentityStoreError("authority changed since this handle was opened")
        with _database(directory / _DATABASE) as connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                _validate(connection, marker)
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _operation(connection, operation_id, method, spec_id, digest):
        existing = connection.execute("SELECT method, spec_id, digest FROM operations WHERE operation_id=?",
                                      (operation_id,)).fetchone()
        if existing is not None:
            if tuple(existing) != (method, spec_id, digest):
                raise IdentityStoreError("operation_id was already used with different arguments")
            return True
        connection.execute("INSERT INTO operations VALUES (?, ?, ?, ?)",
                           (operation_id, method, spec_id, digest))
        return False

    @staticmethod
    def _high_water(connection, spec_id, kind):
        """Validate retained claims with indexed numeric maxima, never repair state."""
        row = connection.execute("SELECT high_water FROM counters WHERE spec_id=? AND kind=?",
                                 (spec_id, kind)).fetchone()
        counter = _integer(row[0]) if row else 0
        reservation = connection.execute(
            "SELECT last_ordinal FROM reservations WHERE spec_id=? AND kind=? "
            "ORDER BY length(last_ordinal) DESC, last_ordinal DESC LIMIT 1", (spec_id, kind),
        ).fetchone()
        entity = connection.execute(
            "SELECT ordinal FROM entities WHERE spec_id=? AND kind=? AND ordinal IS NOT NULL "
            "ORDER BY length(ordinal) DESC, ordinal DESC LIMIT 1", (spec_id, kind),
        ).fetchone()
        for claim in (reservation, entity):
            if claim is not None and (row is None or counter < _integer(claim[0])):
                raise IdentityStoreError("counter is missing or below retained numeric claims")
        return counter

    @classmethod
    def _audit_counters(cls, connection):
        """Full namespace discovery is reserved for explicit restore verification."""
        namespaces = connection.execute(
            "SELECT spec_id, kind FROM counters UNION SELECT spec_id, kind FROM reservations "
            "UNION SELECT spec_id, kind FROM entities WHERE ordinal IS NOT NULL"
        )
        for spec_id, kind in namespaces:
            cls._high_water(connection, spec_id, kind)

    @staticmethod
    def _set_high_water(connection, spec_id, kind, number):
        connection.execute("INSERT INTO counters VALUES (?, ?, ?) ON CONFLICT(spec_id, kind) "
                           "DO UPDATE SET high_water=excluded.high_water", (spec_id, kind, _decimal(number)))

    @_public
    def reserve(self, *, spec_id: str, kind: str, operation_id: str, count: int) -> tuple[str, ...]:
        """Permanently reserve a range, replaying exactly on a matching retry."""
        _identifier(spec_id, "spec_id")
        _identifier(operation_id, "operation_id")
        _kind(kind)
        if type(count) is not int or count <= 0:
            raise IdentityStoreError("count must be a positive integer")
        digest = _digest(["reserve", spec_id, kind, _decimal(count)])
        with self._transaction(write=True) as connection:
            high_water = self._high_water(connection, spec_id, kind)
            if self._operation(connection, operation_id, "reserve", spec_id, digest):
                row = connection.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
                if row is None or row["spec_id"] != spec_id or row["kind"] != kind or row["count"] != _decimal(count):
                    raise IdentityStoreError("reservation history is missing or inconsistent")
                first = _integer(row["first_ordinal"])
                if first <= 0 or _integer(row["last_ordinal"]) != first + count - 1:
                    raise IdentityStoreError("reservation range is malformed")
            else:
                first = high_water + 1
                last = first + count - 1
                first_text = _decimal(first)
                connection.execute("INSERT INTO reservations VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (operation_id, spec_id, kind, first_text, len(first_text), _decimal(last), _decimal(count)))
                self._set_high_water(connection, spec_id, kind, last)
            result = _labels(kind, first, count)
        return result

    @_public
    def import_identities(self, *, spec_id: str, operation_id: str,
                          definitions: Sequence[tuple[str, str]]) -> None:
        """Atomically bind exact legacy labels and subjects, retaining numeric claims."""
        _identifier(spec_id, "spec_id")
        _identifier(operation_id, "operation_id")
        if not isinstance(definitions, Sequence) or isinstance(definitions, (str, bytes)):
            raise IdentityStoreError("definitions must be a sequence of (element_id, subject) pairs")
        parsed, seen = [], set()
        for definition in definitions:
            if not isinstance(definition, (tuple, list)) or len(definition) != 2:
                raise IdentityStoreError("each definition must contain an element_id and subject")
            label, subject = definition
            kind, ordinal = _parse_label(label)
            _identifier(subject, "subject")
            if label in seen:
                raise IdentityStoreError("duplicate element_id in import request")
            seen.add(label)
            parsed.append((label, subject, kind, ordinal))
        digest = _digest(["import", spec_id, [(label, subject) for label, subject, _, _ in parsed]])
        with self._transaction(write=True) as connection:
            high_water_by_kind = {
                kind: self._high_water(connection, spec_id, kind)
                for kind in {definition[2] for definition in parsed}
            }
            if self._operation(connection, operation_id, "import", spec_id, digest):
                return
            maxima = {}
            for label, subject, kind, ordinal in parsed:
                existing = connection.execute("SELECT subject FROM entities WHERE spec_id=? AND element_id=?",
                                              (spec_id, label)).fetchone()
                if existing is not None:
                    if existing[0] != subject:
                        raise IdentityStoreError("element_id is already bound to a different subject")
                    self._head(connection, spec_id, label)
                    continue
                if ordinal is not None:
                    # The predecessor range can be found with one indexed seek.
                    # Canonical decimal length then text sorts without precision loss.
                    previous = connection.execute(
                        "SELECT last_ordinal FROM reservations WHERE spec_id=? AND kind=? "
                        "AND (first_length, first_ordinal) <= (?, ?) "
                        "ORDER BY first_length DESC, first_ordinal DESC LIMIT 1",
                        (spec_id, kind, len(ordinal), ordinal),
                    ).fetchone()
                    number = _integer(ordinal)
                    if previous and number <= _integer(previous[0]):
                        raise IdentityStoreError("numeric ordinal is already reserved")
                    alias = connection.execute("SELECT element_id FROM entities WHERE spec_id=? AND kind=? AND ordinal=?",
                                               (spec_id, kind, ordinal)).fetchone()
                    if alias:
                        raise IdentityStoreError("numeric ordinal already has a different exact label")
                    if kind not in maxima:
                        maxima[kind] = high_water_by_kind[kind]
                    maxima[kind] = max(maxima[kind], number)
                connection.execute("INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                                   (spec_id, label, kind, subject, ordinal))
                connection.execute("INSERT INTO lifecycle_heads (spec_id,element_id,status,revision) "
                                   "VALUES (?,?,'imported',NULL)", (spec_id, label))
            for kind, number in maxima.items():
                self._set_high_water(connection, spec_id, kind, number)

    @_public
    def lookup(self, *, spec_id: str, element_id: str) -> dict | None:
        """Copy exact allocation binding plus verified current lifecycle content."""
        _identifier(spec_id, "spec_id")
        kind, _ = _parse_label(element_id)
        with self._transaction() as connection:
            self._high_water(connection, spec_id, kind)
            return self._head(connection, spec_id, element_id)

    @staticmethod
    def _revision(connection, spec_id, element_id, revision):
        row = connection.execute("SELECT * FROM revisions WHERE spec_id=? AND element_id=? AND revision=?",
                                 (spec_id, element_id, revision)).fetchone()
        if row is None:
            return None
        lifecycle.revision(row["revision"])
        lifecycle.text(row["content"], "stored content")
        entity = connection.execute("SELECT subject FROM entities WHERE spec_id=? AND element_id=?",
                                    (spec_id, element_id)).fetchone()
        operation = connection.execute("SELECT method,spec_id FROM operations WHERE operation_id=?",
                                       (row["operation_id"],)).fetchone()
        if (entity is None or entity[0] != row["subject"]
                or operation is None or tuple(operation) != ("lifecycle", spec_id)
                or hashlib.sha256(row["content"].encode("utf-8")).hexdigest() != row["content_sha256"]
                or row["status"] not in {"active", "retired", "superseded"}):
            raise IdentityStoreError("stored revision digest or binding is inconsistent")
        if row["status"] == "active":
            if row["reason"] is not None:
                raise IdentityStoreError("active revision contains a terminal reason")
        else:
            lifecycle.text(row["reason"], "terminal reason")
            previous = connection.execute(
                "SELECT status,subject,content,content_sha256 FROM revisions "
                "WHERE spec_id=? AND element_id=? AND revision=?",
                (spec_id, element_id, _decimal(_integer(revision) - 1)),
            ).fetchone()
            if (previous is None or previous["status"] != "active"
                    or previous["subject"] != row["subject"]
                    or previous["content"] != row["content"]
                    or previous["content_sha256"] != row["content_sha256"]):
                raise IdentityStoreError("terminal revision does not retain its active predecessor content")
        return dict(row)

    @classmethod
    def _head(cls, connection, spec_id, element_id):
        entity = connection.execute("SELECT * FROM entities WHERE spec_id=? AND element_id=?",
                                    (spec_id, element_id)).fetchone()
        if entity is None:
            return None
        head = connection.execute("SELECT status,revision FROM lifecycle_heads WHERE spec_id=? AND element_id=?",
                                  (spec_id, element_id)).fetchone()
        maximum = connection.execute("SELECT revision FROM revisions WHERE spec_id=? AND element_id=? "
                                     "ORDER BY length(revision) DESC,revision DESC LIMIT 1",
                                     (spec_id, element_id)).fetchone()
        if head is None or head["revision"] != (maximum[0] if maximum else None):
            raise IdentityStoreError("lifecycle head is missing or inconsistent with retained revisions")
        if head["status"] == "imported":
            if head["revision"] is not None:
                raise IdentityStoreError("imported entity has assessed revision history")
            return dict(entity) | dict(head) | {"content": None, "content_sha256": None}
        if head["revision"] is None:
            raise IdentityStoreError("assessed entity is missing its revision binding")
        revision = cls._revision(connection, spec_id, element_id, head["revision"])
        if revision is None or revision["status"] != head["status"]:
            raise IdentityStoreError("head and revision status bindings disagree")
        return dict(entity) | {key: revision[key] for key in ("status", "revision", "content", "content_sha256")}

    @_public
    def read_revision(self, *, spec_id: str, element_id: str, revision: str) -> dict | None:
        _identifier(spec_id, "spec_id")
        kind, _ = _parse_label(element_id)
        lifecycle.revision(revision)
        with self._transaction() as connection:
            self._high_water(connection, spec_id, kind)
            self._head(connection, spec_id, element_id)
            return self._revision(connection, spec_id, element_id, revision)

    @classmethod
    def _lineage(cls, connection, spec_id, element_id):
        rows = connection.execute(
            "SELECT * FROM lifecycle_lineage WHERE spec_id=? AND predecessor_id=? UNION "
            "SELECT * FROM lifecycle_lineage WHERE spec_id=? AND successor_id=? "
            "ORDER BY predecessor_id,successor_id", (spec_id, element_id, spec_id, element_id),
        ).fetchall()
        for link in rows:
            for label in (link["predecessor_id"], link["successor_id"]):
                kind, _ = _parse_label(label)
                cls._high_water(connection, spec_id, kind)
                if cls._head(connection, spec_id, label) is None:
                    raise IdentityStoreError("lineage entity is missing")
            predecessor = cls._revision(connection, spec_id, link["predecessor_id"], link["predecessor_revision"])
            terminal = cls._revision(connection, spec_id, link["predecessor_id"],
                                     _decimal(_integer(link["predecessor_revision"]) + 1))
            successor = cls._revision(connection, spec_id, link["successor_id"], link["successor_revision"])
            if (predecessor is None or predecessor["status"] != "active" or terminal is None
                    or terminal["status"] != "superseded" or successor is None
                    or successor["revision"] != "1" or successor["status"] != "active"
                    or terminal["operation_id"] != link["operation_id"]
                    or successor["operation_id"] != link["operation_id"]
                    or terminal["reason"] != link["reason"]
                    or terminal["content"] != predecessor["content"]):
                raise IdentityStoreError("lineage revision or operation binding is inconsistent")
        return tuple(dict(row) for row in rows)

    @_public
    def lineage(self, *, spec_id: str, element_id: str) -> tuple[dict, ...]:
        _identifier(spec_id, "spec_id")
        kind, _ = _parse_label(element_id)
        with self._transaction() as connection:
            self._high_water(connection, spec_id, kind)
            self._head(connection, spec_id, element_id)
            return self._lineage(connection, spec_id, element_id)

    @classmethod
    def _receipt(cls, connection, operation_id, spec_id):
        row = connection.execute("SELECT receipt,receipt_sha256 FROM lifecycle_receipts WHERE operation_id=?",
                                 (operation_id,)).fetchone()
        if row is None or hashlib.sha256(row[0].encode("ascii")).hexdigest() != row[1]:
            raise IdentityStoreError("lifecycle receipt is missing or damaged")
        receipt = json.loads(row[0])
        if not isinstance(receipt, list) or not receipt:
            raise IdentityStoreError("invalid lifecycle receipt")
        for entry in receipt:
            if (not isinstance(entry, dict)
                    or set(entry) != {"element_id", "revision", "status", "lineage"}):
                raise IdentityStoreError("invalid lifecycle receipt entry")
            label = entry["element_id"]
            cls._head(connection, spec_id, label)
            revision = cls._revision(connection, spec_id, label, entry["revision"])
            links = [link for link in cls._lineage(connection, spec_id, label)
                     if link["operation_id"] == operation_id]
            if (revision is None or revision["operation_id"] != operation_id
                    or revision["status"] != entry["status"] or links != entry["lineage"]):
                raise IdentityStoreError("lifecycle receipt bindings are inconsistent")
        return tuple(receipt)

    @classmethod
    def _creation(cls, connection, spec_id, change):
        kind, ordinal = _parse_label(change.element_id)
        if ordinal is None or change.element_id != format_element_id(kind, _integer(ordinal)):
            raise IdentityStoreError("creation requires the exact controller-issued numeric label")
        if cls._head(connection, spec_id, change.element_id) is not None:
            raise IdentityStoreError("element_id is already materialized")
        reservation = connection.execute("SELECT * FROM reservations WHERE operation_id=?",
                                         (change.reservation_operation_id,)).fetchone()
        if reservation is None or reservation["spec_id"] != spec_id or reservation["kind"] != kind:
            raise IdentityStoreError("matching reservation is missing")
        cls._validate_reservation(connection, reservation)
        if not (_integer(reservation["first_ordinal"]) <= _integer(ordinal) <= _integer(reservation["last_ordinal"])):
            raise IdentityStoreError("element_id is outside its reservation")
        if connection.execute("SELECT 1 FROM entities WHERE spec_id=? AND kind=? AND ordinal=?",
                              (spec_id, kind, ordinal)).fetchone():
            raise IdentityStoreError("numeric ordinal is already materialized")
        return (change.element_id, "1", change.subject, change.content, "active", None, kind, ordinal)

    @classmethod
    def _existing_change(cls, connection, spec_id, label, expected, *, subject=None, content=None,
                         status="active", reason=None, adopt=False):
        head = cls._head(connection, spec_id, label)
        if head is None or head["status"] != ("imported" if adopt else "active"):
            raise IdentityStoreError("entity is not in the required lifecycle state")
        if head["revision"] != expected:
            raise IdentityStoreError("stale expected_revision")
        if subject is not None and subject != head["subject"]:
            raise IdentityStoreError("revision cannot change immutable subject")
        revision = "1" if adopt else _decimal(_integer(expected) + 1)
        return (label, revision, head["subject"], head["content"] if content is None else content,
                status, reason, None, None)

    @_public
    def apply_lifecycle(self, *, spec_id: str, operation_id: str,
                        changes: Sequence[lifecycle.LifecycleChange]) -> tuple[dict, ...]:
        """Validate a whole batch against its prestate, then atomically persist it."""
        _identifier(spec_id, "spec_id")
        _identifier(operation_id, "operation_id")
        changes, payload, labels = lifecycle.request(changes)
        digest = _digest(["lifecycle", spec_id, payload])
        with self._transaction(write=True) as connection:
            for kind in {_parse_label(label)[0] for label in labels}:
                self._high_water(connection, spec_id, kind)
            if self._operation(connection, operation_id, "lifecycle", spec_id, digest):
                return self._receipt(connection, operation_id, spec_id)
            planned, links = lifecycle_store.plan_changes(connection, self, spec_id, changes)
            for label, revision, subject, content, status, reason, kind, ordinal in planned:
                if kind is not None:
                    connection.execute("INSERT INTO entities (spec_id,element_id,kind,subject,ordinal) VALUES (?,?,?,?,?)",
                                       (spec_id, label, kind, subject, ordinal))
                connection.execute("INSERT INTO revisions "
                    "(spec_id,element_id,revision,subject,content,content_sha256,status,reason,operation_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (spec_id, label, revision, subject, content, hashlib.sha256(content.encode("utf-8")).hexdigest(), status, reason, operation_id))
                connection.execute("INSERT INTO lifecycle_heads (spec_id,element_id,status,revision) VALUES (?,?,?,?) "
                    "ON CONFLICT(spec_id,element_id) DO UPDATE SET status=excluded.status,revision=excluded.revision",
                    (spec_id, label, status, revision))
            connection.executemany("INSERT INTO lifecycle_lineage "
                "(spec_id,predecessor_id,predecessor_revision,successor_id,successor_revision,kind,reason,operation_id) "
                "VALUES (?,?,?,?,?,?,?,?)", ((*link, operation_id) for link in links))
            result = [{"element_id": row[0], "revision": row[1], "status": row[4],
                       "lineage": [link for link in self._lineage(connection, spec_id, row[0])
                                   if link["operation_id"] == operation_id]} for row in planned]
            receipt = _json(result)
            connection.execute("INSERT INTO lifecycle_receipts (operation_id,receipt,receipt_sha256) VALUES (?,?,?)",
                               (operation_id, receipt, hashlib.sha256(receipt.encode("ascii")).hexdigest()))
            return tuple(result)

    @_public
    def preview_lifecycle(self, *, spec_id: str,
                          changes: Sequence[lifecycle.LifecycleChange]) -> tuple[dict, ...]:
        """Project validated lifecycle heads from one read snapshot without writes."""
        _identifier(spec_id, "spec_id")
        with self._transaction() as connection:
            planned, _ = lifecycle_store.plan_changes(connection, self, spec_id, changes)
            result = []
            for label, revision, subject, content, status, _, _, _ in planned:
                head = self._head(connection, spec_id, label)
                result.append({
                    "element_id": label,
                    "expected_status": head["status"] if head is not None else None,
                    "expected_revision": head["revision"] if head is not None else None,
                    "subject": subject,
                    "content": content,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "revision": revision,
                    "status": status,
                })
            return tuple(result)

    @staticmethod
    def _validate_reservation(connection, row):
        first, last, count = (_integer(row[key]) for key in ("first_ordinal", "last_ordinal", "count"))
        operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                       (row["operation_id"],)).fetchone()
        if (first <= 0 or count <= 0 or last != first + count - 1
                or row["first_length"] != len(row["first_ordinal"])
                or operation is None or tuple(operation) != ("reserve", row["spec_id"],
                    _digest(["reserve", row["spec_id"], row["kind"], row["count"]]))):
            raise IdentityStoreError("reservation history is inconsistent")

    @classmethod
    def _audit(cls, connection, *, lifecycle_state, binding_state=False):
        """Full validation is restricted to explicit upgrade/restore."""
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise IdentityStoreError("database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise IdentityStoreError("database has inconsistent foreign keys")
        methods = {"reserve", "import"}
        if lifecycle_state:
            methods.add("lifecycle")
        if binding_state:
            methods.update(("reference_claims", "issue_occurrences"))
        if any(row[0] not in methods for row in connection.execute("SELECT DISTINCT method FROM operations")):
            raise IdentityStoreError("operation method is unsupported by this authority schema")
        cls._audit_counters(connection)
        if connection.execute(
            "SELECT 1 FROM operations LEFT JOIN reservations USING (operation_id) "
            "WHERE operations.method='reserve' AND reservations.operation_id IS NULL LIMIT 1"
        ).fetchone():
            raise IdentityStoreError("reservation operation is missing its retained range")
        previous = {}
        for row in connection.execute("SELECT * FROM reservations ORDER BY spec_id,kind,first_length,first_ordinal"):
            cls._validate_reservation(connection, row)
            key = (row["spec_id"], row["kind"])
            if _integer(row["first_ordinal"]) <= previous.get(key, 0):
                raise IdentityStoreError("reservation ranges overlap")
            previous[key] = _integer(row["last_ordinal"])
        for row in connection.execute("SELECT * FROM entities"):
            kind, ordinal = _parse_label(row["element_id"])
            _identifier(row["subject"], "stored subject")
            if (kind, ordinal) != (row["kind"], row["ordinal"]):
                raise IdentityStoreError("identity label, kind and ordinal binding disagree")
            if not lifecycle_state and ordinal is not None:
                claim = connection.execute(
                    "SELECT last_ordinal FROM reservations WHERE spec_id=? AND kind=? "
                    "AND (first_length,first_ordinal) <= (?,?) "
                    "ORDER BY first_length DESC,first_ordinal DESC LIMIT 1",
                    (row["spec_id"], kind, len(ordinal), ordinal),
                ).fetchone()
                if claim and _integer(ordinal) <= _integer(claim[0]):
                    raise IdentityStoreError("legacy import overlaps a retained reservation")
        if lifecycle_state:
            for row in connection.execute("SELECT spec_id,element_id FROM entities"):
                cls._head(connection, *row)
            for row in connection.execute("SELECT spec_id,element_id,revision FROM revisions"):
                cls._revision(connection, *row)
            for row in connection.execute("SELECT spec_id,predecessor_id FROM lifecycle_lineage"):
                cls._lineage(connection, *row)
            for row in connection.execute("SELECT operation_id,spec_id FROM operations WHERE method='lifecycle'"):
                cls._receipt(connection, *row)
        if binding_state:
            binding_store.audit(connection, cls)

    @_public
    def record_reference_claims(self, *, spec_id: str, operation_id: str,
                                claims: Sequence[bindings.ReferenceClaim]) -> tuple[dict, ...]:
        """Retain declared source provenance without resolving a mutable file."""
        lifecycle.text(spec_id, "spec_id")
        lifecycle.text(operation_id, "operation_id")
        payloads = bindings.request(claims, bindings.ReferenceClaim)
        with self._transaction(write=True) as connection:
            return binding_store.record(connection, self, "reference_claims", spec_id, operation_id, payloads)

    @_public
    def reference_claims(self, *, spec_id: str, source_path: str, source_sha256: str) -> tuple[dict, ...]:
        """Read original claims plus current head metadata, never a gate verdict."""
        lifecycle.text(spec_id, "spec_id")
        bindings.source_path(source_path)
        bindings.sha256(source_sha256)
        with self._transaction() as connection:
            return binding_store.read(connection, self, "reference_claims", spec_id, (source_path, source_sha256))

    @_public
    def record_issue_occurrences(self, *, spec_id: str, operation_id: str,
                                 occurrences: Sequence[bindings.IssueOccurrence]) -> tuple[dict, ...]:
        lifecycle.text(spec_id, "spec_id")
        lifecycle.text(operation_id, "operation_id")
        payloads = bindings.request(occurrences, bindings.IssueOccurrence)
        with self._transaction(write=True) as connection:
            return binding_store.record(connection, self, "issue_occurrences", spec_id, operation_id, payloads)

    @_public
    def issue_occurrences(self, *, spec_id: str, issue_id: str) -> tuple[dict, ...]:
        lifecycle.text(spec_id, "spec_id")
        bindings.issue_label(issue_id)
        with self._transaction() as connection:
            self._high_water(connection, spec_id, "ISS")
            self._head(connection, spec_id, issue_id)
            return binding_store.read(connection, self, "issue_occurrences", spec_id, (issue_id,))

    @_public
    def high_water(self, *, spec_id: str, kind: str) -> str:
        _identifier(spec_id, "spec_id")
        _kind(kind)
        with self._transaction() as connection:
            return _decimal(self._high_water(connection, spec_id, kind))

    @_public
    def backup(self, destination: Path) -> None:
        """Write a dedicated online snapshot; only the final manifest completes it."""
        with self._transaction() as source:
            destination = _claim_directory(destination)
            database = destination / _DATABASE
            _write_new(database, b"")
            with _database(database) as target:
                source.backup(target)
                _validate(target, self._marker)
            _write_new(destination / _MARKER, _json(self._marker).encode("ascii"))
            with database.open("rb") as stream:
                os.fsync(stream.fileno())
            _sync_directory(destination)
            manifest = {"version": _VERSION, "completed": True, "authority": self._marker,
                        "database_sha256": _hash_file(database)}
            _write_new(destination / "manifest.json", _json(manifest).encode("ascii"))
            _sync_directory(destination)

    @classmethod
    @_public
    def restore(cls, workspace: Path, backup: Path) -> IdentityStore:
        """Verify a completed snapshot before claiming a fresh destination authority."""
        backup = _directory(backup)
        if any((backup / (_DATABASE + suffix)).exists() for suffix in ("-journal", "-wal", "-shm")):
            raise IdentityStoreError("completed backups must not contain SQLite sidecars")
        marker = _authority(_read_json(backup / _MARKER))
        manifest = _read_json(backup / "manifest.json")
        if (not isinstance(manifest, dict)
                or set(manifest) != {"version", "completed", "authority", "database_sha256"}
                or type(manifest["version"]) is not int or manifest["version"] != _VERSION
                or manifest["completed"] is not True or _authority(manifest["authority"]) != marker):
            raise IdentityStoreError("backup is incomplete or its digest/authority is invalid")
        with _database(backup / _DATABASE, readonly=True) as source:
            source.execute("BEGIN")
            version = _validate(source, marker, allow_old=True)
            # Validate the digest while holding the same read snapshot that is
            # copied below. DELETE journaling prevents a concurrent writer from
            # committing between checksum verification and the online backup.
            if manifest["database_sha256"] != _hash_file(backup / _DATABASE):
                raise IdentityStoreError("backup database digest does not match its manifest")
            cls._audit(source, lifecycle_state=version != "1", binding_state=version == "3")
            directory = _claim_authority(workspace)
            _write_new(directory / _MARKER, _json(marker).encode("ascii"))
            _write_new(directory / _DATABASE, b"")
            with _database(directory / _DATABASE) as target:
                source.backup(target)
                if version != schema.SCHEMA_VERSION:
                    target.execute("BEGIN IMMEDIATE")
                    try:
                        schema.upgrade(target)
                        _validate(target, marker)
                        target.commit()
                    except BaseException:
                        target.rollback()
                        raise
                _validate(target, marker)
            _sync_directory(directory)
        return cls.open(workspace)

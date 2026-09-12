"""Explicit, inactive SQLite allocation authority; never inferred from documents.

Only imports materialize identities. Reservations are permanent claims, including
when their caller dies. No producer or content lifecycle is wired to this module.
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


_VERSION = 1
_BUSY_SECONDS = 10
_KINDS = frozenset({"AC", "FR", "NFR", "ISS", "U", "A", "T"})
_LABEL = re.compile(r"(AC|FR|NFR|ISS|U|A|T)-([A-Za-z0-9][A-Za-z0-9_.-]*)\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_DATABASE = "registry.sqlite3"
_MARKER = "authority.json"

# Canonical text avoids SQLite's signed-64-bit integer and floating-point limits.
_CANONICAL = "{0} NOT GLOB '*[^0-9]*' AND ({0} = '0' OR {0} GLOB '[1-9]*')"
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
    "counters": "CREATE TABLE counters (spec_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "high_water TEXT NOT NULL CHECK (" + _CANONICAL.format("high_water") + "), "
        "PRIMARY KEY (spec_id, kind)) WITHOUT ROWID",
    "operations": "CREATE TABLE operations (operation_id TEXT PRIMARY KEY, method TEXT NOT NULL, "
        "spec_id TEXT NOT NULL, digest TEXT NOT NULL) WITHOUT ROWID",
    "reservations": "CREATE TABLE reservations (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), "
        "spec_id TEXT NOT NULL, kind TEXT NOT NULL, first_ordinal TEXT NOT NULL CHECK (" +
        _CANONICAL.format("first_ordinal") + " AND first_ordinal != '0'), "
        "first_length INTEGER NOT NULL, last_ordinal TEXT NOT NULL CHECK (" +
        _CANONICAL.format("last_ordinal") + "), count TEXT NOT NULL CHECK (" +
        _CANONICAL.format("count") + " AND count != '0')) WITHOUT ROWID",
    "reservation_ranges": "CREATE UNIQUE INDEX reservation_ranges ON reservations "
        "(spec_id, kind, first_length, first_ordinal)",
    "entities": "CREATE TABLE entities (spec_id TEXT NOT NULL, element_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, subject TEXT NOT NULL, ordinal TEXT CHECK (ordinal IS NULL OR (" +
        _CANONICAL.format("ordinal") + " AND ordinal != '0')), "
        "PRIMARY KEY (spec_id, element_id)) WITHOUT ROWID",
    "entity_ordinals": "CREATE UNIQUE INDEX entity_ordinals ON entities (spec_id, kind, ordinal)",
}


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


def _validate(connection, marker):
    if connection.execute("PRAGMA user_version").fetchone()[0] != _VERSION:
        raise IdentityStoreError("unsupported identity database schema version")
    actual = {row["name"]: row["sql"] for row in connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    )}
    if actual != _SCHEMA:
        raise IdentityStoreError("identity database schema or required indexes are malformed")
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if metadata != {key: str(value) for key, value in marker.items()}:
        raise IdentityStoreError("authority marker and database identity do not match")


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
                for statement in _SCHEMA.values():
                    connection.execute(statement)
                connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                       [(key, str(value)) for key, value in marker.items()])
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
        row = connection.execute("SELECT high_water FROM counters WHERE spec_id=? AND kind=?",
                                 (spec_id, kind)).fetchone()
        return _integer(row[0]) if row else 0

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
            if self._operation(connection, operation_id, "reserve", spec_id, digest):
                row = connection.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
                if row is None or row["spec_id"] != spec_id or row["kind"] != kind or row["count"] != _decimal(count):
                    raise IdentityStoreError("reservation history is missing or inconsistent")
                first = _integer(row["first_ordinal"])
                if first <= 0 or _integer(row["last_ordinal"]) != first + count - 1:
                    raise IdentityStoreError("reservation range is malformed")
            else:
                first = self._high_water(connection, spec_id, kind) + 1
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
            if self._operation(connection, operation_id, "import", spec_id, digest):
                return
            maxima = {}
            for label, subject, kind, ordinal in parsed:
                existing = connection.execute("SELECT subject FROM entities WHERE spec_id=? AND element_id=?",
                                              (spec_id, label)).fetchone()
                if existing is not None:
                    if existing[0] != subject:
                        raise IdentityStoreError("element_id is already bound to a different subject")
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
                        maxima[kind] = self._high_water(connection, spec_id, kind)
                    maxima[kind] = max(maxima[kind], number)
                connection.execute("INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                                   (spec_id, label, kind, subject, ordinal))
            for kind, number in maxima.items():
                self._set_high_water(connection, spec_id, kind, number)

    @_public
    def lookup(self, *, spec_id: str, element_id: str) -> dict | None:
        """Copy an imported identity record; reservations are not entities."""
        _identifier(spec_id, "spec_id")
        _parse_label(element_id)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM entities WHERE spec_id=? AND element_id=?",
                                     (spec_id, element_id)).fetchone()
            return dict(row) if row else None

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
            _validate(source, marker)
            # Validate the digest while holding the same read snapshot that is
            # copied below. DELETE journaling prevents a concurrent writer from
            # committing between checksum verification and the online backup.
            if manifest["database_sha256"] != _hash_file(backup / _DATABASE):
                raise IdentityStoreError("backup database digest does not match its manifest")
            if [row[0] for row in source.execute("PRAGMA integrity_check")] != ["ok"]:
                raise IdentityStoreError("backup database integrity check failed")
            if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise IdentityStoreError("backup database has inconsistent foreign keys")
            directory = _claim_authority(workspace)
            _write_new(directory / _MARKER, _json(marker).encode("ascii"))
            _write_new(directory / _DATABASE, b"")
            with _database(directory / _DATABASE) as target:
                source.backup(target)
                _validate(target, marker)
            _sync_directory(directory)
        return cls.open(workspace)

"""Explicit administration for the inactive element identity authority."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from harness.element_identity_store import IdentityStore, IdentityStoreError


class _InputError(ValueError):
    """Malformed administration input."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m harness.element_identity_admin")
    commands = parser.add_subparsers(dest="command", required=True)

    for command in ("initialize", "audit", "upgrade"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--workspace", required=True, type=Path)

    backup = commands.add_parser("backup")
    backup.add_argument("--workspace", required=True, type=Path)
    backup.add_argument("--destination", required=True, type=Path)

    restore = commands.add_parser("restore")
    restore.add_argument("--workspace", required=True, type=Path)
    restore.add_argument("--backup", required=True, type=Path)

    import_labels = commands.add_parser("import-labels")
    import_labels.add_argument("--workspace", required=True, type=Path)
    import_labels.add_argument("--input", required=True, type=Path)
    return parser


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _InputError("import JSON contains duplicate object keys")
        value[key] = item
    return value


def _import_request(path: Path) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    with path.open("r", encoding="utf-8") as stream:
        request = json.load(stream, object_pairs_hook=_unique_object)
    if type(request) is not dict or set(request) != {
        "schema_version", "spec_id", "operation_id", "definitions",
    }:
        raise _InputError("import JSON has invalid top-level keys")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise _InputError("import schema_version must be integer 1")
    if type(request["spec_id"]) is not str or type(request["operation_id"]) is not str:
        raise _InputError("import spec_id and operation_id must be strings")
    definitions = request["definitions"]
    if type(definitions) is not list or not definitions:
        raise _InputError("import definitions must be a nonempty array")
    result = []
    for definition in definitions:
        if type(definition) is not dict or set(definition) != {"element_id", "subject"}:
            raise _InputError("each import definition must contain only element_id and subject")
        if type(definition["element_id"]) is not str or type(definition["subject"]) is not str:
            raise _InputError("import element_id and subject must be strings")
        result.append((definition["element_id"], definition["subject"]))
    return request["spec_id"], request["operation_id"], tuple(result)


def _write_result(value: dict) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicitly selected identity authority administration operation."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "initialize":
            IdentityStore.initialize(arguments.workspace)
        elif arguments.command == "audit":
            _write_result(IdentityStore.open(arguments.workspace).audit())
            return 0
        elif arguments.command == "upgrade":
            IdentityStore.upgrade(arguments.workspace)
        elif arguments.command == "backup":
            IdentityStore.open(arguments.workspace).backup(arguments.destination)
        elif arguments.command == "restore":
            IdentityStore.restore(arguments.workspace, arguments.backup)
        elif arguments.command == "import-labels":
            store = IdentityStore.open(arguments.workspace)
            spec_id, operation_id, definitions = _import_request(arguments.input)
            store.import_identities(
                spec_id=spec_id,
                operation_id=operation_id,
                definitions=definitions,
            )
    except (IdentityStoreError, OSError, UnicodeError, json.JSONDecodeError, _InputError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    _write_result({"command": arguments.command, "completed": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

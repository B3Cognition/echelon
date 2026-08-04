"""Authenticated write-ahead transactions for mutable product-input packages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping, Sequence

from echelon.product_inputs import (
    ProductInputError,
    immutable_product_input_tree_digest,
    validate_immutable_product_input_package,
    validate_product_input_contract_pointers,
)
from harness.state_transaction_namespace import (
    PENDING_EXTERNAL_PUBLICATION_KEY,
    PRODUCT_INPUT_MUTATION_KEY,
    require_product_input_mutation_publication_binding,
    validate_pending_external_publication,
    validate_product_input_mutation,
)


class ProductInputMutationError(RuntimeError):
    """Raised when a package mutation cannot prove its exact old/post image."""


_TREE_HASH = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_MAX_OWNED_PATHS = 100_000


def product_input_tree_identity(inputs_dir: Path) -> tuple[tuple[object, ...], ...]:
    """Pin every package pathname to one no-follow inode identity snapshot."""
    root = Path(inputs_dir)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_before = os.stat(root, follow_symlinks=False)
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ProductInputMutationError("product input package identity is unavailable") from exc
    records: list[tuple[object, ...]] = []

    def identity(relative: str, metadata: os.stat_result) -> tuple[object, ...]:
        return (
            relative,
            metadata.st_dev,
            metadata.st_ino,
            stat.S_IFMT(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def walk(directory_fd: int, relative: Path) -> None:
        before = os.fstat(directory_fd)
        if not stat.S_ISDIR(before.st_mode):
            raise ProductInputMutationError("product input package directory changed")
        names = sorted(os.listdir(directory_fd))
        records.append(identity(relative.as_posix() or ".", before))
        for name in names:
            child_relative = relative / name
            label = child_relative.as_posix()
            try:
                observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise ProductInputMutationError("product input package entry changed") from exc
            if stat.S_ISLNK(observed.st_mode):
                raise ProductInputMutationError("product input package contains a symlink")
            if stat.S_ISDIR(observed.st_mode):
                try:
                    child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise ProductInputMutationError("product input package directory changed") from exc
                try:
                    opened = os.fstat(child_fd)
                    if identity(label, opened)[1:5] != identity(label, observed)[1:5]:
                        raise ProductInputMutationError("product input package directory was swapped")
                    walk(child_fd, child_relative)
                    rebound = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if identity(label, rebound) != identity(label, os.fstat(child_fd)):
                        raise ProductInputMutationError("product input package directory was swapped")
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                raise ProductInputMutationError("product input package contains an unsafe file")
            try:
                child_fd = os.open(name, file_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise ProductInputMutationError("product input package file changed") from exc
            try:
                opened = os.fstat(child_fd)
                if identity(label, opened) != identity(label, observed):
                    raise ProductInputMutationError("product input package file was swapped")
                rebound = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if identity(label, rebound) != identity(label, os.fstat(child_fd)):
                    raise ProductInputMutationError("product input package file was swapped")
                records.append(identity(label, rebound))
            finally:
                os.close(child_fd)
        after = os.fstat(directory_fd)
        if sorted(os.listdir(directory_fd)) != names or identity("", after)[1:] != identity("", before)[1:]:
            raise ProductInputMutationError("product input package directory changed")

    try:
        opened_root = os.fstat(root_fd)
        if identity(".", root_before)[1:5] != identity(".", opened_root)[1:5]:
            raise ProductInputMutationError("product input package root was swapped")
        walk(root_fd, Path())
        rebound_root = os.stat(root, follow_symlinks=False)
        if identity(".", rebound_root) != identity(".", os.fstat(root_fd)):
            raise ProductInputMutationError("product input package root was swapped")
    except (OSError, TypeError) as exc:
        raise ProductInputMutationError("product input package identity changed") from exc
    finally:
        os.close(root_fd)
    return tuple(records)


def product_input_request_sha256(
    command: str,
    declarations: Sequence[object],
) -> str:
    """Bind one add-input request without persisting unbounded source text."""
    if type(command) is not str or not command or len(command.encode("utf-8")) > 4096:
        raise ProductInputMutationError("product input command is invalid")
    if len(declarations) > 128:
        raise ProductInputMutationError("too many product input declarations")
    normalized: list[dict[str, str]] = []
    for declaration in declarations:
        role = getattr(declaration, "role", None)
        location = getattr(declaration, "location", None)
        if (
            type(role) is not str
            or type(location) is not str
            or not role
            or not location
            or len(location.encode("utf-8")) > 16_384
        ):
            raise ProductInputMutationError("product input declaration is invalid")
        normalized.append({"role": role, "location": location})
    document = json.dumps(
        {"command": command, "declarations": normalized},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(document).hexdigest()


def _normalize_owned_paths(paths: Sequence[str | Path]) -> list[str]:
    if len(paths) > _MAX_OWNED_PATHS:
        raise ProductInputMutationError("product input mutation owns too many paths")
    normalized: list[str] = []
    for value in paths:
        path = Path(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ProductInputMutationError("product input mutation path is invalid")
        text = path.as_posix()
        if len(text.encode("utf-8")) > 4096:
            raise ProductInputMutationError("product input mutation path is too long")
        normalized.append(text)
    ordered = sorted(set(normalized))
    if not ordered or len(ordered) != len(normalized):
        raise ProductInputMutationError("product input mutation paths are empty or duplicate")
    return ordered


def _owned_paths_sha256(paths: Sequence[str | Path]) -> tuple[str, int]:
    normalized = _normalize_owned_paths(paths)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(normalized)


def authenticate_product_input_contract(
    project_root: Path,
    product_inputs: Mapping[str, object],
    inputs_dir: Path,
) -> str:
    """Require the current package to equal its persisted full-tree digest."""
    expected = product_inputs.get("tree_hash")
    if type(expected) is not str or _TREE_HASH.fullmatch(expected) is None:
        raise ProductInputMutationError("product input tree hash is missing or invalid")
    try:
        validate_product_input_contract_pointers(
            project_root,
            product_inputs,
            inputs_dir,
        )
        validate_immutable_product_input_package(inputs_dir, product_inputs)
    except ProductInputError as exc:
        raise ProductInputMutationError(str(exc)) from exc
    observed = immutable_product_input_tree_digest(inputs_dir)
    if observed != expected:
        raise ProductInputMutationError("product input tree hash drift")
    return expected


def _package_files(root: Path) -> dict[Path, Path]:
    files: dict[Path, Path] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ProductInputMutationError(
                f"product input package contains a symlink: {relative.as_posix()}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ProductInputMutationError(
                f"product input package contains an unsafe file: {relative.as_posix()}"
            )
        files[relative] = path
    return files


def add_complete_product_input_publication(
    transaction: object,
    project_root: Path,
    current_inputs: Path,
    staged_inputs: Path,
) -> tuple[str, ...]:
    """Bind every old/post package file into one publication manifest."""
    root = Path(project_root).resolve()
    current = Path(current_inputs).resolve()
    staged = Path(staged_inputs).resolve()
    current_files = _package_files(current)
    staged_files = _package_files(staged)
    relative_files = sorted(set(current_files) | set(staged_files))
    targets = tuple(
        (current / relative).relative_to(root).as_posix()
        for relative in relative_files
    )
    owned = {Path(target) for target in targets}
    for relative, target in zip(relative_files, targets, strict=True):
        if relative in staged_files:
            transaction.add_write(
                Path(target),
                staged_files[relative],
                owned_paths=owned,
            )
        else:
            transaction.add_delete(Path(target), owned_paths=owned)
    return targets


def build_product_input_mutation(
    *,
    kind: str,
    marker: Mapping[str, object],
    inputs_dir: str,
    old_tree_hash: str,
    new_tree_hash: str,
    owned_paths: Sequence[str | Path],
    request_sha256: str | None = None,
    attachment_id: str | None = None,
    added_count: int = 0,
    duplicate_count: int = 0,
) -> dict[str, object]:
    publication = validate_pending_external_publication(marker)
    paths_sha256, path_count = _owned_paths_sha256(owned_paths)
    value = {
        "schema_version": 1,
        "kind": kind,
        "operation_id": publication["transaction_id"],
        "manifest_sha256": publication["manifest_sha256"],
        "inputs_dir": inputs_dir,
        "old_tree_hash": old_tree_hash,
        "new_tree_hash": new_tree_hash,
        "owned_paths_sha256": paths_sha256,
        "owned_path_count": path_count,
        "request_sha256": request_sha256,
        "attachment_id": attachment_id,
        "added_count": added_count,
        "duplicate_count": duplicate_count,
    }
    return validate_product_input_mutation(value)


def _operation_targets(
    operations: object,
    *,
    package_prefix: Path,
) -> tuple[list[str], dict[str, Mapping[str, object]]]:
    if type(operations) is not list:
        raise ProductInputMutationError("product input publication operations are invalid")
    targets: list[str] = []
    by_relative: dict[str, Mapping[str, object]] = {}
    prefix_text = package_prefix.as_posix().rstrip("/") + "/"
    for operation in operations:
        if type(operation) is not dict:
            raise ProductInputMutationError("product input publication operation is invalid")
        target = operation.get("target")
        if type(target) is not str or not target.startswith(prefix_text):
            continue
        relative = target[len(prefix_text):]
        targets.append(target)
        by_relative[relative] = operation
    if len(by_relative) != len(targets):
        raise ProductInputMutationError("product input publication paths are duplicate")
    if targets != sorted(targets):
        raise ProductInputMutationError(
            "product input publication paths are not canonical"
        )
    return targets, by_relative


def _current_file_image(path: Path) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ProductInputMutationError("product input publication target is unsafe")
    return {
        "kind": "file",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": stat.S_IMODE(metadata.st_mode),
    }


def authenticate_pending_product_input_mutation(
    project_root: Path,
    state: Mapping[str, object],
    publication_marker: Mapping[str, object],
    operations: object,
    *,
    staged_inputs: Path,
) -> dict[str, object] | None:
    """Accept only one exact manifest-order crash prefix and sealed stage."""
    raw = state.get(PRODUCT_INPUT_MUTATION_KEY)
    if raw is None:
        return None
    try:
        mutation = require_product_input_mutation_publication_binding(
            raw,
            publication_marker,
        )
    except ValueError as exc:
        raise ProductInputMutationError(str(exc)) from exc
    product_inputs = state.get("product_inputs")
    if (
        type(product_inputs) is not dict
        or product_inputs.get("tree_hash") != mutation["new_tree_hash"]
        or product_inputs.get("inputs_dir") != mutation["inputs_dir"]
    ):
        raise ProductInputMutationError("product input mutation state postimage changed")
    try:
        if immutable_product_input_tree_digest(staged_inputs) != mutation["new_tree_hash"]:
            raise ProductInputMutationError("staged product input postimage changed")
        validate_immutable_product_input_package(staged_inputs, product_inputs)
    except ProductInputError as exc:
        raise ProductInputMutationError(str(exc)) from exc
    root = Path(project_root).resolve()
    inputs = Path(str(mutation["inputs_dir"]))
    if not inputs.is_absolute():
        inputs = root / inputs
    inputs = inputs.resolve()
    if not inputs.is_relative_to(root):
        raise ProductInputMutationError("product input mutation package escapes project root")
    try:
        package_prefix = inputs.relative_to(root)
    except ValueError as exc:  # pragma: no cover - guarded above
        raise ProductInputMutationError("product input mutation package escapes project root") from exc
    targets, by_relative = _operation_targets(
        operations,
        package_prefix=package_prefix,
    )
    paths_sha256, path_count = _owned_paths_sha256(targets)
    if (
        paths_sha256 != mutation["owned_paths_sha256"]
        or path_count != mutation["owned_path_count"]
    ):
        raise ProductInputMutationError("product input mutation owned paths changed")
    try:
        current_hash = immutable_product_input_tree_digest(inputs)
    except ProductInputError as exc:
        raise ProductInputMutationError(str(exc)) from exc
    if current_hash in {mutation["old_tree_hash"], mutation["new_tree_hash"]}:
        return mutation

    current_files = _package_files(inputs)
    if set(path.as_posix() for path in current_files) - set(by_relative):
        raise ProductInputMutationError("product input package has unowned drift")
    expected_directories = {
        parent.as_posix()
        for relative, operation in by_relative.items()
        if _current_file_image(inputs / relative)["kind"] == "file"
        for parent in Path(relative).parents
        if parent != Path(".")
    }
    actual_directories: set[str] = set()
    try:
        root_metadata = inputs.lstat()
    except OSError as exc:
        raise ProductInputMutationError("product input package root changed") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o755
    ):
        raise ProductInputMutationError("product input package directory mode drift")
    for path in sorted(inputs.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(inputs).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(relative)
            if stat.S_IMODE(metadata.st_mode) != 0o755:
                raise ProductInputMutationError("product input package directory mode drift")
    if actual_directories != expected_directories:
        raise ProductInputMutationError("product input package has directory topology drift")
    reached_preimage = False
    for relative, operation in by_relative.items():
        current = _current_file_image(inputs / relative)
        preimage = dict(operation["preimage"])
        postimage = dict(operation["postimage"])
        if current == preimage == postimage:
            continue
        if current == preimage:
            reached_preimage = True
            continue
        if current == postimage and not reached_preimage:
            continue
        if current != preimage and current != postimage:
            raise ProductInputMutationError("product input package has partial target drift")
        raise ProductInputMutationError("product input package is not an exact publication prefix")
    return mutation


def require_product_input_mutation_postimage(
    project_root: Path,
    state: Mapping[str, object],
    publication_marker: Mapping[str, object],
) -> str | None:
    raw = state.get(PRODUCT_INPUT_MUTATION_KEY)
    if raw is None:
        return None
    try:
        mutation = require_product_input_mutation_publication_binding(
            raw,
            publication_marker,
        )
    except ValueError as exc:
        raise ProductInputMutationError(str(exc)) from exc
    product_inputs = state.get("product_inputs")
    if type(product_inputs) is not dict:
        raise ProductInputMutationError("product input mutation state contract is missing")
    inputs = Path(str(mutation["inputs_dir"]))
    root = Path(project_root).resolve()
    if not inputs.is_absolute():
        inputs = root / inputs
    observed = immutable_product_input_tree_digest(inputs)
    if (
        observed != mutation["new_tree_hash"]
        or product_inputs.get("tree_hash") != observed
    ):
        raise ProductInputMutationError("product input mutation postimage drift")
    return observed


def pending_product_input_mutation(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    raw = state.get(PRODUCT_INPUT_MUTATION_KEY)
    publication = state.get(PENDING_EXTERNAL_PUBLICATION_KEY)
    if raw is None and publication is None:
        return None
    if raw is None or publication is None:
        raise ProductInputMutationError("product input mutation authority is incomplete")
    try:
        return require_product_input_mutation_publication_binding(raw, publication)
    except ValueError as exc:
        raise ProductInputMutationError(str(exc)) from exc

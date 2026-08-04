"""Immutable, safe product-input evidence for Phase A specification runs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from echelon import atomic_install, durable_tree
from harness.secret_scan import scan_text
from kernel.task_contract import parse_task_rows


_ROLES = frozenset({"requirement", "reference"})
_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".xml"})
_ASSET_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".svg"})
_SECRET_FILENAMES = frozenset({".env", "secrets.env", "credentials", "credentials.json", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"})
_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})
_PRODUCT_INPUT_POINTERS = (
    "inputs_dir",
    "manifest",
    "catalog",
    "input_context",
    "requirement_context",
    "reference_context",
    "traceability",
    "traceability_markdown",
)
_PRODUCT_INPUT_POINTER_RELATIVE_PATHS = {
    "inputs_dir": Path("."),
    "manifest": Path("manifest.json"),
    "catalog": Path("catalog.json"),
    "input_context": Path("input-context.md"),
    "requirement_context": Path("requirement-context.md"),
    "reference_context": Path("reference-context.md"),
    "traceability": Path("traceability.json"),
    "traceability_markdown": Path("traceability.md"),
}
_TREE_HASH_KEY = "tree_hash"


class ProductInputError(ValueError):
    """Raised when declared product input is unsafe or cannot be consumed."""


@dataclass(frozen=True)
class ProductInputTraceabilityRepair:
    """A deterministic, conservative repair plan for contextual task references."""

    removed: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ProductInputDeclaration:
    role: str
    location: str


@dataclass(frozen=True)
class ProductInputResolution:
    declarations: tuple[ProductInputDeclaration, ...]
    inputs_dir: Path
    manifest_path: Path
    catalog_path: Path
    input_context_path: Path
    requirement_context_path: Path
    reference_context_path: Path
    traceability_path: Path
    traceability_markdown_path: Path
    manifest_hash: str
    tree_hash: str | None = None

    def state_payload(self, project_root: Path) -> dict[str, object]:
        """Return JSON-safe, workspace-portable pointers for squad state."""
        tree_hash = _validated_tree_hash(
            self.tree_hash,
            label="product input resolution authenticated tree hash",
        )
        return {
            "declarations": [
                {"role": item.role, "location": item.location}
                for item in self.declarations
            ],
            "inputs_dir": _portable(self.inputs_dir, project_root),
            "manifest": _portable(self.manifest_path, project_root),
            "catalog": _portable(self.catalog_path, project_root),
            "input_context": _portable(self.input_context_path, project_root),
            "requirement_context": _portable(self.requirement_context_path, project_root),
            "reference_context": _portable(self.reference_context_path, project_root),
            "traceability": _portable(self.traceability_path, project_root),
            "traceability_markdown": _portable(self.traceability_markdown_path, project_root),
            "manifest_hash": self.manifest_hash,
            _TREE_HASH_KEY: tree_hash,
        }


@dataclass(frozen=True)
class ProductInputAttachmentResult:
    """Result of appending evidence to an existing product-input contract."""

    attachment_id: str
    inputs_dir: Path
    revision: ProductInputResolution | None
    added: tuple[dict[str, object], ...]
    duplicates: tuple[dict[str, object], ...]
    ledger_path: Path
    tree_hash: str | None = None

    def state_product_inputs(
        self,
        project_root: Path,
        current_product_inputs: Mapping[str, object],
        *,
        package_dir: Path | None = None,
    ) -> dict[str, object]:
        tree_hash = _validated_tree_hash(
            self.tree_hash,
            label="product input attachment authenticated aggregate tree hash",
        )
        package = Path(package_dir) if package_dir is not None else self.inputs_dir
        updated = dict(current_product_inputs)
        updated.update({
            "inputs_dir": _portable(self.inputs_dir, project_root),
            "manifest": _portable(self.inputs_dir / "manifest.json", project_root),
            "catalog": _portable(self.inputs_dir / "catalog.json", project_root),
            "input_context": _portable(self.inputs_dir / "input-context.md", project_root),
            "requirement_context": _portable(self.inputs_dir / "requirement-context.md", project_root),
            "reference_context": _portable(self.inputs_dir / "reference-context.md", project_root),
            "traceability": _portable(self.inputs_dir / "traceability.json", project_root),
            "traceability_markdown": _portable(self.inputs_dir / "traceability.md", project_root),
            "manifest_hash": hashlib.sha256((package / "manifest.json").read_bytes()).hexdigest(),
            _TREE_HASH_KEY: tree_hash,
        })
        return updated

    def state_attachments(
        self,
        project_root: Path,
        *,
        ledger_source_path: Path | None = None,
    ) -> list[dict[str, object]]:
        source = (
            Path(ledger_source_path)
            if ledger_source_path is not None
            else self.ledger_path
        )
        if not source.exists():
            return []
        ledger = _read_json_object(source, "product input attachment ledger")
        attachments = ledger.get("attachments")
        if not isinstance(attachments, list):
            return []
        normalized: list[dict[str, object]] = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            clone = dict(item)
            clone["ledger"] = _portable(self.ledger_path, project_root)
            normalized.append(clone)
        return normalized


def _validated_tree_hash(value: object, *, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ProductInputError(f"{label} is missing or invalid")
    return value


def parse_input_declaration(value: str) -> ProductInputDeclaration:
    """Parse one ``role:location`` CLI declaration without corrupting URL schemes."""
    role, separator, location = value.partition(":")
    role = role.strip().lower()
    location = location.strip()
    if not separator or role not in _ROLES or not location:
        raise ProductInputError(
            "--input must use requirement:<path-or-figma-url> or reference:<path-or-figma-url>"
        )
    return ProductInputDeclaration(role=role, location=location)


def resolve_product_inputs(
    project_root: Path,
    run_dir: Path,
    declarations: Sequence[ProductInputDeclaration],
) -> ProductInputResolution:
    """Resolve local declarations and write an immutable run-local evidence package."""
    return _resolve_product_inputs_to(
        project_root,
        Path(run_dir) / "inputs",
        declarations,
        replace_existing=True,
    )


def resolve_product_input_revision(
    project_root: Path,
    inputs_dir: Path,
    declarations: Sequence[ProductInputDeclaration],
    *,
    pointer_inputs_dir: Path | None = None,
) -> ProductInputResolution:
    """Write one amendment input revision without replacing prior evidence."""
    return _resolve_product_inputs_to(
        project_root,
        Path(inputs_dir),
        declarations,
        replace_existing=False,
        pointer_inputs_dir=pointer_inputs_dir,
    )


def _resolve_project_path(project_root: Path, value: str) -> Path:
    root = Path(project_root).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise ProductInputError(f"product input path must not be a symlink: {value}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ProductInputError(f"product input path is unavailable: {value}") from exc
    if not resolved.is_relative_to(root):
        raise ProductInputError(f"product input path escapes project root: {value}")
    return resolved


def _assert_regular_package_tree(inputs_dir: Path) -> None:
    try:
        root_mode = inputs_dir.lstat().st_mode
    except OSError as exc:
        raise ProductInputError(f"product input package is unavailable: {inputs_dir}") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise ProductInputError(f"product input package must be a regular directory: {inputs_dir}")
    for current, directory_names, file_names in os.walk(inputs_dir, followlinks=False):
        current_path = Path(current)
        for name in [*directory_names, *file_names]:
            path = current_path / name
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise ProductInputError(f"product input package entry is unavailable: {path}") from exc
            if stat.S_ISLNK(mode):
                raise ProductInputError(f"product input package contains a symlink: {path}")
            if name in directory_names:
                if not stat.S_ISDIR(mode):
                    raise ProductInputError(f"product input package entry is not a directory: {path}")
            elif not stat.S_ISREG(mode):
                raise ProductInputError(f"product input package entry is not a regular file: {path}")


def immutable_product_input_tree_digest(inputs_dir: Path) -> str:
    """Hash every package path, type, mode, and byte through no-follow fds."""

    root = Path(inputs_dir)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, flags)
    except OSError as exc:
        raise ProductInputError(f"cannot open immutable product input package: {root}") from exc
    digest = hashlib.sha256()

    def frame(kind: bytes, relative: str, mode: int) -> None:
        encoded = relative.encode("utf-8")
        digest.update(kind)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(stat.S_IMODE(mode).to_bytes(4, "big"))

    def walk(directory_fd: int, relative: Path) -> None:
        directory_before = os.fstat(directory_fd)
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise ProductInputError("cannot enumerate immutable product input package") from exc
        for name in names:
            child_relative = relative / name
            child_text = child_relative.as_posix()
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise ProductInputError(f"product input path changed during verification: {child_text}") from exc
            if stat.S_ISLNK(before.st_mode):
                raise ProductInputError(f"product input package contains a symlink: {child_text}")
            if stat.S_ISDIR(before.st_mode):
                try:
                    child_fd = os.open(name, flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise ProductInputError(f"product input directory changed during verification: {child_text}") from exc
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino, opened.st_mode) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_mode,
                    ):
                        raise ProductInputError(f"product input directory swapped during verification: {child_text}")
                    frame(b"D", child_text, opened.st_mode)
                    walk(child_fd, child_relative)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(before.st_mode):
                raise ProductInputError(f"product input package entry is not a regular file: {child_text}")
            if before.st_nlink != 1:
                raise ProductInputError(f"product input package contains a hardlink: {child_text}")
            file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                file_fd = os.open(name, file_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise ProductInputError(f"product input file changed during verification: {child_text}") from exc
            try:
                opened = os.fstat(file_fd)
                if (
                    (opened.st_dev, opened.st_ino, opened.st_mode) !=
                    (before.st_dev, before.st_ino, before.st_mode)
                    or opened.st_nlink != 1
                ):
                    raise ProductInputError(f"product input file swapped during verification: {child_text}")
                frame(b"F", child_text, opened.st_mode)
                while chunk := os.read(file_fd, 1024 * 1024):
                    digest.update(len(chunk).to_bytes(8, "big"))
                    digest.update(chunk)
                digest.update((0).to_bytes(8, "big"))
                after = os.fstat(file_fd)
                if (
                    after.st_size != opened.st_size
                    or after.st_mtime_ns != opened.st_mtime_ns
                    or after.st_ctime_ns != opened.st_ctime_ns
                ):
                    raise ProductInputError(f"product input source mutated during verification: {child_text}")
            finally:
                os.close(file_fd)
        directory_after = os.fstat(directory_fd)
        if (
            directory_after.st_dev != directory_before.st_dev
            or directory_after.st_ino != directory_before.st_ino
            or directory_after.st_mode != directory_before.st_mode
            or directory_after.st_mtime_ns != directory_before.st_mtime_ns
            or directory_after.st_ctime_ns != directory_before.st_ctime_ns
        ):
            label = relative.as_posix() or "."
            raise ProductInputError(
                f"product input directory mutated during verification: {label}"
            )

    try:
        root_stat = os.fstat(root_fd)
        frame(b"D", ".", root_stat.st_mode)
        walk(root_fd, Path())
    finally:
        os.close(root_fd)
    return f"sha256:{digest.hexdigest()}"


def _durably_finalize_product_input_tree(inputs_dir: Path) -> None:
    try:
        durable_tree.durably_sync_owned_tree(
            inputs_dir,
            normalize_directory_modes=True,
        )
    except (OSError, durable_tree.DurableTreeError) as exc:
        raise ProductInputError(
            f"cannot durably finalize product input package: {inputs_dir}"
        ) from exc


def _validated_package_file(inputs_dir: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ProductInputError(f"product input {label} is missing")
    relative = Path(value)
    if relative.is_absolute():
        raise ProductInputError(f"product input {label} must be package-relative")
    path = inputs_dir / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ProductInputError(f"product input {label} is unavailable: {value}") from exc
    if not resolved.is_relative_to(inputs_dir.resolve()):
        raise ProductInputError(f"product input {label} escapes the immutable package")
    if path.is_symlink() or not resolved.is_file():
        raise ProductInputError(f"product input {label} is not a regular file")
    return resolved


def _validate_snapshot_digests(
    inputs_dir: Path,
    rows: object,
    *,
    label: str,
) -> None:
    if not isinstance(rows, list):
        raise ProductInputError(f"product input {label} must be a list")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ProductInputError(f"product input {label} contains a non-object entry")
        snapshot = row.get("snapshot")
        digest = row.get("sha256")
        if not isinstance(snapshot, str) or not snapshot:
            if label == "catalog units":
                raise ProductInputError("product input catalog unit is missing its snapshot")
            continue
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ProductInputError(f"product input {label} has an invalid sha256 digest")
        path = _validated_package_file(inputs_dir, snapshot, label=f"{label} snapshot")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ProductInputError(f"product input {label} snapshot hash drift: {snapshot}")
        size_bytes = row.get("size_bytes")
        if isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes != len(content):
            raise ProductInputError(f"product input {label} snapshot size drift: {snapshot}")


def validate_immutable_product_input_package(
    inputs_dir: Path,
    product_inputs: Mapping[str, object],
) -> None:
    """Fail closed when immutable aggregate input bytes no longer match their indexes."""

    package = Path(inputs_dir).resolve()
    _assert_regular_package_tree(package)
    expected_tree_hash = product_inputs.get(_TREE_HASH_KEY)
    if expected_tree_hash is not None:
        if (
            not isinstance(expected_tree_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_tree_hash) is None
            or immutable_product_input_tree_digest(package) != expected_tree_hash
        ):
            raise ProductInputError("product input tree hash drift")
    manifest = _read_json_object(package / "manifest.json", "product input manifest")
    catalog = _read_json_object(package / "catalog.json", "product input catalog")
    expected_manifest_hash = product_inputs.get("manifest_hash")
    if (
        not isinstance(expected_manifest_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_hash) is None
        or hashlib.sha256((package / "manifest.json").read_bytes()).hexdigest()
        != expected_manifest_hash
    ):
        raise ProductInputError("product input manifest hash drift")
    _validate_snapshot_digests(
        package,
        manifest.get("resources"),
        label="manifest resources",
    )
    _validate_snapshot_digests(
        package,
        catalog.get("units"),
        label="catalog units",
    )


def validate_product_input_contract_pointers(
    project_root: Path,
    product_inputs: Mapping[str, object],
    inputs_dir: Path,
) -> None:
    """Require every persisted pointer to name its canonical package entry."""

    root = Path(project_root).resolve()
    package_candidate = Path(inputs_dir)
    if not package_candidate.is_absolute():
        package_candidate = root / package_candidate
    if package_candidate.is_symlink():
        raise ProductInputError("product input package pointer must not be a symlink")
    package = package_candidate.resolve()
    if not package.is_relative_to(root):
        raise ProductInputError("product input package pointer escapes project root")
    for key in _PRODUCT_INPUT_POINTERS:
        value = product_inputs.get(key)
        if not isinstance(value, str) or not value:
            raise ProductInputError(f"product input {key} pointer is missing")
        observed = _resolve_project_path(root, value)
        expected = (package / _PRODUCT_INPUT_POINTER_RELATIVE_PATHS[key]).resolve()
        if observed != expected:
            raise ProductInputError(
                f"product input {key} pointer does not name its canonical package entry"
            )


def clone_product_input_contract(
    project_root: Path,
    source_state: Mapping[str, object],
    replacement_run_dir: Path,
    *,
    baseline_run_dir: Path | None = None,
    contract_run_dir: Path | None = None,
) -> dict[str, object]:
    """Clone one baseline run's aggregate immutable evidence without re-resolving inputs."""

    raw = source_state.get("product_inputs")
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, Mapping):
        raise ProductInputError("baseline product input contract is malformed")
    root = Path(project_root).resolve()
    source = _resolve_project_path(root, str(raw.get("inputs_dir") or ""))
    spec_ref = source_state.get("spec_dir")
    if not isinstance(spec_ref, str) or not spec_ref:
        raise ProductInputError("baseline state is missing its run-local spec directory")
    baseline_spec_dir = _resolve_project_path(root, spec_ref)
    state_run_dir = baseline_spec_dir.parent.parent
    if baseline_spec_dir.parent.name != "specs":
        raise ProductInputError("baseline spec directory is not run-local")
    if baseline_run_dir is not None:
        verified_run_dir = _resolve_project_path(root, str(baseline_run_dir))
        if state_run_dir != verified_run_dir:
            raise ProductInputError(
                "product input package does not belong to the verified baseline run"
            )
    else:
        verified_run_dir = state_run_dir
    if source != verified_run_dir / "inputs":
        raise ProductInputError("product input package is outside the baseline run")

    source_root = source.resolve()
    validate_product_input_contract_pointers(root, raw, source_root)
    source_tree_hash = _require_authenticated_product_input_tree_hash(source, raw)
    validate_immutable_product_input_package(source, raw)
    replacement_candidate = Path(replacement_run_dir)
    if not replacement_candidate.is_absolute():
        replacement_candidate = root / replacement_candidate
    if replacement_candidate.is_symlink():
        raise ProductInputError("replacement run directory must not be a symlink")
    replacement = replacement_candidate.resolve()
    if not replacement.is_relative_to(root):
        raise ProductInputError("replacement run directory must be inside the project root")
    if contract_run_dir is not None:
        contract_root = Path(contract_run_dir).resolve()
        if not contract_root.is_relative_to(root):
            raise ProductInputError(
                "product input contract run must be inside the project root"
            )
        contract_destination = contract_root / "inputs"
    else:
        contract_destination = replacement / "inputs"
    destination = replacement / "inputs"
    replacement.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ProductInputError(f"replacement product input destination already exists: {destination}")

    temporary = Path(tempfile.mkdtemp(prefix=".inputs-clone-", dir=str(replacement)))
    temporary.rmdir()
    try:
        shutil.copytree(
            source,
            temporary,
            copy_function=shutil.copy2,
            symlinks=True,
        )
        if immutable_product_input_tree_digest(source) != source_tree_hash:
            raise ProductInputError("product input source mutated during clone")
        _durably_finalize_product_input_tree(temporary)
        if immutable_product_input_tree_digest(temporary) != source_tree_hash:
            raise ProductInputError("product input clone bytes differ from baseline")
        validate_immutable_product_input_package(temporary, raw)
        atomic_install.atomic_rename_no_replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    cloned = dict(raw)
    for key in _PRODUCT_INPUT_POINTERS:
        cloned[key] = _portable(
            contract_destination / _PRODUCT_INPUT_POINTER_RELATIVE_PATHS[key],
            root,
        )
    cloned[_TREE_HASH_KEY] = source_tree_hash
    validation_contract = dict(cloned)
    for key in _PRODUCT_INPUT_POINTERS:
        validation_contract[key] = _portable(
            destination / _PRODUCT_INPUT_POINTER_RELATIVE_PATHS[key], root
        )
    validate_product_input_contract_pointers(root, validation_contract, destination)
    validate_immutable_product_input_package(destination, validation_contract)
    return cloned


def project_cloned_product_input_contract(
    project_root: Path,
    source_state: Mapping[str, object],
    replacement_run_dir: Path,
    *,
    baseline_run_dir: Path,
) -> dict[str, object]:
    """Authenticate baseline bytes and derive the exact replacement metadata."""

    raw = source_state.get("product_inputs")
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, Mapping):
        raise ProductInputError("baseline product input contract is malformed")
    root = Path(project_root).resolve()
    source = _resolve_project_path(root, str(raw.get("inputs_dir") or ""))
    verified = _resolve_project_path(root, str(baseline_run_dir))
    if source != verified / "inputs":
        raise ProductInputError("product input package is outside the verified baseline run")
    validate_product_input_contract_pointers(root, raw, source)
    source_tree_hash = _require_authenticated_product_input_tree_hash(source, raw)
    validate_immutable_product_input_package(source, raw)
    projected = dict(raw)
    replacement = Path(replacement_run_dir).resolve()
    if not replacement.is_relative_to(root):
        raise ProductInputError("replacement run directory must be inside the project root")
    destination = replacement / "inputs"
    for key in _PRODUCT_INPUT_POINTERS:
        projected[key] = _portable(
            destination / _PRODUCT_INPUT_POINTER_RELATIVE_PATHS[key], root
        )
    projected[_TREE_HASH_KEY] = source_tree_hash
    return projected


def _require_authenticated_product_input_tree_hash(
    inputs_dir: Path,
    product_inputs: Mapping[str, object],
) -> str:
    expected = product_inputs.get(_TREE_HASH_KEY)
    if (
        type(expected) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None
    ):
        raise ProductInputError("baseline product input tree hash is missing or invalid")
    if immutable_product_input_tree_digest(inputs_dir) != expected:
        raise ProductInputError("baseline product input tree hash drift")
    return expected


def attach_product_input_revision(
    project_root: Path,
    inputs_dir: Path,
    declarations: Sequence[ProductInputDeclaration],
    *,
    command: str,
    evidence_requests: Mapping[str, object] | None = None,
    pointer_inputs_dir: Path | None = None,
) -> ProductInputAttachmentResult:
    """Append one immutable evidence revision and rebuild aggregate indexes."""
    project_root = Path(project_root).resolve()
    inputs_dir = Path(inputs_dir)
    pointer_inputs = (
        Path(pointer_inputs_dir)
        if pointer_inputs_dir is not None
        else inputs_dir
    )
    manifest_path = inputs_dir / "manifest.json"
    catalog_path = inputs_dir / "catalog.json"
    traceability_path = inputs_dir / "traceability.json"
    manifest = _read_json_object(manifest_path, "product input manifest")
    catalog = _read_json_object(catalog_path, "product input catalog")
    traceability = _read_json_object(traceability_path, "product input traceability")
    ledger_path = inputs_dir / "attachment-ledger.json"
    ledger = (
        _read_json_object(ledger_path, "product input attachment ledger")
        if ledger_path.exists()
        else {"schema_version": 1, "attachments": []}
    )
    if not isinstance(ledger.get("attachments"), list):
        raise ProductInputError("product input attachment ledger has no attachments list")

    normalized = tuple(_normalize_declaration(item) for item in declarations)
    if not normalized:
        raise ProductInputError("add-input requires at least one input declaration")
    existing_declarations = _attachment_declaration_keys(manifest, ledger)
    declaration_duplicates = [
        {
            "role": item.role,
            "location": item.location,
            "reason": "duplicate declaration",
        }
        for item in normalized
        if (item.role, item.location) in existing_declarations
    ]
    new_declarations = [
        item for item in normalized
        if (item.role, item.location) not in existing_declarations
    ]
    attachment_id = _next_attachment_id(inputs_dir, ledger)
    if not new_declarations:
        return ProductInputAttachmentResult(
            attachment_id=attachment_id,
            inputs_dir=pointer_inputs,
            revision=None,
            added=(),
            duplicates=tuple(declaration_duplicates),
            ledger_path=pointer_inputs / "attachment-ledger.json",
            tree_hash=immutable_product_input_tree_digest(inputs_dir),
        )

    revision_dir = inputs_dir / "attachments" / attachment_id
    revision = resolve_product_input_revision(
        project_root,
        revision_dir,
        new_declarations,
        pointer_inputs_dir=pointer_inputs / "attachments" / attachment_id,
    )
    revision_manifest = _read_json_object(revision.manifest_path, "attachment manifest")
    revision_catalog = _read_json_object(revision.catalog_path, "attachment catalog")
    known_hashes = _accepted_hashes(manifest, ledger)
    accepted_resources = [
        dict(item)
        for item in revision_manifest.get("resources", [])
        if isinstance(item, dict) and item.get("status") == "accepted"
    ]
    duplicate_hashes = {
        str(item.get("sha256"))
        for item in accepted_resources
        if str(item.get("sha256") or "") in known_hashes
    }
    added_resources = [
        _attachment_resource_summary(
            item,
            attachment_id=attachment_id,
            inputs_dir=pointer_inputs,
            project_root=project_root,
        )
        for item in accepted_resources
        if str(item.get("sha256") or "") not in duplicate_hashes
    ]
    content_duplicates = [
        {
            **_attachment_resource_summary(
                item,
                attachment_id=attachment_id,
                inputs_dir=pointer_inputs,
                project_root=project_root,
            ),
            "reason": "duplicate content",
        }
        for item in accepted_resources
        if str(item.get("sha256") or "") in duplicate_hashes
    ]
    duplicates = tuple([*declaration_duplicates, *content_duplicates])
    if not added_resources:
        shutil.rmtree(revision_dir, ignore_errors=True)
        return ProductInputAttachmentResult(
            attachment_id=attachment_id,
            inputs_dir=pointer_inputs,
            revision=None,
            added=(),
            duplicates=duplicates,
            ledger_path=pointer_inputs / "attachment-ledger.json",
            tree_hash=immutable_product_input_tree_digest(inputs_dir),
        )

    linked_request_ids = _linked_evidence_request_ids(
        evidence_requests,
        [*new_declarations],
        added_resources,
    )
    attachment_entry = {
        "id": attachment_id,
        "command": command,
        "attached_at": datetime.now(timezone.utc).isoformat(),
        "declarations": [
            {"role": item.role, "location": item.location}
            for item in new_declarations
        ],
        "resources": added_resources,
        "duplicates": list(duplicates),
        "linked_evidence_request_ids": linked_request_ids,
        "revision_manifest": _portable(
            pointer_inputs / "attachments" / attachment_id / "manifest.json",
            project_root,
        ),
        "revision_catalog": _portable(
            pointer_inputs / "attachments" / attachment_id / "catalog.json",
            project_root,
        ),
    }
    ledger["attachments"].append(attachment_entry)

    _write_aggregate_product_inputs(
        inputs_dir,
        manifest,
        catalog,
        traceability,
        revision_manifest,
        revision_catalog,
        duplicate_hashes=duplicate_hashes,
        attachment_id=attachment_id,
        pointer_inputs_dir=pointer_inputs,
    )
    _write_json(ledger_path, ledger)
    _durably_finalize_product_input_tree(inputs_dir)
    return ProductInputAttachmentResult(
        attachment_id=attachment_id,
        inputs_dir=pointer_inputs,
        revision=revision,
        added=tuple(added_resources),
        duplicates=duplicates,
        ledger_path=pointer_inputs / "attachment-ledger.json",
        tree_hash=immutable_product_input_tree_digest(inputs_dir),
    )


def _resolve_product_inputs_to(
    project_root: Path,
    inputs_dir: Path,
    declarations: Sequence[ProductInputDeclaration],
    *,
    replace_existing: bool,
    pointer_inputs_dir: Path | None = None,
) -> ProductInputResolution:
    """Resolve input declarations to one explicitly selected evidence directory."""
    project_root = project_root.resolve()
    rendered_inputs_dir = (
        Path(pointer_inputs_dir)
        if pointer_inputs_dir is not None
        else inputs_dir
    )
    if inputs_dir.exists():
        if not replace_existing:
            raise ProductInputError(f"product input evidence directory already exists: {inputs_dir}")
        shutil.rmtree(inputs_dir)
    inputs_dir.mkdir(parents=True, exist_ok=True)

    normalized = tuple(_normalize_declaration(item) for item in declarations)
    manifest_resources: list[dict[str, object]] = []
    catalog_units: list[dict[str, object]] = []
    declaration_rows: list[dict[str, str]] = []
    seen_locations: set[tuple[str, str]] = set()

    for index, declaration in enumerate(normalized, start=1):
        declaration_id = f"{declaration.role}-{index:03d}"
        declaration_rows.append({
            "id": declaration_id,
            "role": declaration.role,
            "location": declaration.location,
        })
        duplicate_key = (declaration.role, declaration.location)
        if duplicate_key in seen_locations:
            manifest_resources.append({
                "declaration_id": declaration_id,
                "role": declaration.role,
                "source_locator": declaration.location,
                "status": "excluded",
                "reason": "duplicate declaration",
            })
            continue
        seen_locations.add(duplicate_key)
        source_locator_base = ""
        if _is_url(declaration.location):
            source = _resolve_figma_url(declaration.location, inputs_dir, declaration_id)
            source_locator_base = declaration.location.rstrip("/")
        else:
            declared_path = Path(declaration.location).expanduser()
            source = declared_path.resolve() if declared_path.is_absolute() else (project_root / declared_path).resolve()
        if not source.exists():
            raise ProductInputError(f"input path does not exist: {declaration.location}")
        root = source if source.is_dir() else source.parent
        resources = [source] if source.is_file() or source.is_symlink() else sorted(source.rglob("*"), key=lambda path: path.as_posix())
        for resource in resources:
            if resource.is_dir():
                continue
            _assert_contained(resource, root)
            relative = resource.relative_to(root)
            locator = (
                f"{source_locator_base}/{relative.as_posix()}"
                if source_locator_base
                else _portable(resource, project_root)
            )
            status, reason = _classify(resource)
            base = {
                "declaration_id": declaration_id,
                "role": declaration.role,
                "source_locator": locator,
                "declared_relative_path": relative.as_posix(),
                "status": status,
            }
            if status == "excluded":
                manifest_resources.append({**base, "reason": reason})
                continue
            if status == "blocking":
                raise ProductInputError(f"unsupported input file {locator}; convert or remove it before running the spec")

            content = resource.read_bytes()
            text = _decode_text(resource, content)
            if text is not None and scan_text(text, path=locator):
                manifest_resources.append({**base, "status": "excluded", "reason": "secret-like content"})
                continue
            digest = hashlib.sha256(content).hexdigest()
            snapshot = inputs_dir / "snapshots" / declaration.role / declaration_id / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource, snapshot)
            media_type = _media_type(resource)
            manifest_resources.append({
                **base,
                "snapshot": snapshot.relative_to(inputs_dir).as_posix(),
                "sha256": digest,
                "size_bytes": len(content),
                "media_type": media_type,
            })
            if resource.suffix.lower() == ".pdf" and declaration.role == "requirement":
                catalog_units.extend(_unitize_requirement_pdf(
                    resource,
                    declaration_id,
                    locator,
                    snapshot.relative_to(inputs_dir).as_posix(),
                    digest,
                    media_type,
                ))
            else:
                catalog_units.extend(_unitize(
                    declaration.role,
                    declaration_id,
                    locator,
                    snapshot.relative_to(inputs_dir).as_posix(),
                    digest,
                    media_type,
                    text,
                ))

    manifest = {"schema_version": 1, "declarations": declaration_rows, "resources": manifest_resources}
    catalog = {"schema_version": 1, "units": catalog_units}
    manifest_path = inputs_dir / "manifest.json"
    catalog_path = inputs_dir / "catalog.json"
    _write_json(manifest_path, manifest)
    _write_json(catalog_path, catalog)
    requirement_context = inputs_dir / "requirement-context.md"
    reference_context = inputs_dir / "reference-context.md"
    _write_context(requirement_context, catalog_units, "requirement")
    _write_context(reference_context, catalog_units, "reference")
    input_context = inputs_dir / "input-context.md"
    input_context.write_text(
        "# Product Input Context\n\n"
        f"- Manifest: `{rendered_inputs_dir / 'manifest.json'}`\n"
        f"- Catalog: `{rendered_inputs_dir / 'catalog.json'}`\n"
        f"- Requirement units: `{rendered_inputs_dir / 'requirement-context.md'}`\n"
        f"- Reference units: `{rendered_inputs_dir / 'reference-context.md'}`\n",
        encoding="utf-8",
    )
    traceability_path = inputs_dir / "traceability.json"
    traceability = {
        "schema_version": 1,
        "requirements": [
            {
                "input_unit_id": unit["id"],
                "disposition": "open_question",
                "rationale": "Awaiting specification analysis.",
                "spec_ids": [],
                "task_ids": [],
                "targets": [],
            }
            for unit in catalog_units
            if unit["role"] == "requirement" and unit.get("traceability_required", True)
        ],
        "references": [
            {"input_unit_id": unit["id"], "state": "reviewed_unused", "rationale": "Awaiting analysis."}
            for unit in catalog_units if unit["role"] == "reference"
        ],
    }
    _write_json(traceability_path, traceability)
    traceability_markdown_path = inputs_dir / "traceability.md"
    _write_traceability_markdown(traceability_markdown_path, traceability)
    _durably_finalize_product_input_tree(inputs_dir)
    return ProductInputResolution(
        declarations=normalized,
        inputs_dir=inputs_dir,
        manifest_path=manifest_path,
        catalog_path=catalog_path,
        input_context_path=input_context,
        requirement_context_path=requirement_context,
        reference_context_path=reference_context,
        traceability_path=traceability_path,
        traceability_markdown_path=traceability_markdown_path,
        manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        tree_hash=immutable_product_input_tree_digest(inputs_dir),
    )


def validate_product_input_traceability(spec_dir: Path, declared_targets: Sequence[str]) -> list[str]:
    """Return publication blockers for requirement input traceability."""
    return validate_product_input_traceability_paths(
        spec_dir / "inputs" / "traceability.json",
        spec_dir / "tasks.md",
        declared_targets,
    )


def validate_product_input_traceability_paths(
    traceability_path: Path,
    tasks_path: Path,
    declared_targets: Sequence[str],
) -> list[str]:
    """Validate one ledger against one task artifact before publication."""
    if not traceability_path.exists():
        return ["product input traceability.json is missing"]
    try:
        ledger = json.loads(traceability_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"product input traceability.json is invalid: {exc}"]
    return _traceability_blockers(ledger, _task_metadata(tasks_path), declared_targets)


def _traceability_blockers(
    ledger: object,
    tasks: dict[str, dict[str, set[str]]],
    declared_targets: Sequence[str],
) -> list[str]:
    """Validate a traceability ledger against canonical task metadata."""
    if not isinstance(ledger, dict):
        return ["product input traceability.json is invalid"]
    blockers: list[str] = []
    declared = set(declared_targets)
    for entry in ledger.get("requirements", []):
        if not isinstance(entry, dict):
            blockers.append("product input traceability contains an invalid requirement entry")
            continue
        unit_id = str(entry.get("input_unit_id") or "(unknown input unit)")
        disposition = str(entry.get("disposition") or "")
        if disposition not in {"included", "excluded", "duplicate"}:
            blockers.append(f"{unit_id}: unresolved disposition {disposition or '(missing)'}")
            continue
        if disposition != "included":
            continue
        spec_ids = {str(value) for value in entry.get("spec_ids", []) if str(value)}
        task_ids = [str(value) for value in entry.get("task_ids", []) if str(value)]
        if not spec_ids:
            blockers.append(f"{unit_id}: included requirement has no specification IDs")
        if not task_ids:
            blockers.append(f"{unit_id}: included requirement has no task IDs")
        for task_id in task_ids:
            task = tasks.get(task_id)
            if task is None or not (spec_ids & task["requirements"]):
                blockers.append(f"{unit_id}: task {task_id} does not reference the mapped specification IDs")
                continue
            if not (task["targets"] & declared):
                blockers.append(f"{unit_id}: task {task_id} is not target-owned by a declared implementation target")
    return blockers


def repair_product_input_traceability(
    traceability_path: Path,
    tasks_path: Path,
    declared_targets: Sequence[str],
    *,
    apply: bool,
) -> ProductInputTraceabilityRepair:
    """Prune only contextual task references when direct evidence remains.

    A product-input unit may cite only tasks whose ``req=`` values intersect its
    ``spec_ids``.  Agents sometimes append context tasks (for example a decision
    spike with ``req=INFRA``) as evidence.  That is invalid, but it is safe to
    remove when the same unit still has one or more direct task mappings.  Any
    other traceability defect remains a blocker for a deliberate PLAN repair.
    """
    try:
        ledger = json.loads(traceability_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ProductInputTraceabilityRepair((), (f"product input traceability.json is invalid: {exc}",))
    requirements = ledger.get("requirements")
    if not isinstance(requirements, list):
        return ProductInputTraceabilityRepair((), ("product input traceability has no requirements list",))

    tasks = _task_metadata(tasks_path)
    declared = set(declared_targets)
    removed: list[tuple[str, str]] = []
    blockers: list[str] = []
    for entry in requirements:
        if not isinstance(entry, dict) or str(entry.get("disposition") or "") != "included":
            continue
        unit_id = str(entry.get("input_unit_id") or "(unknown input unit)")
        spec_ids = {str(value) for value in entry.get("spec_ids", []) if str(value)}
        task_ids = [str(value) for value in entry.get("task_ids", []) if str(value)]
        if not spec_ids or not task_ids:
            blockers.append(f"{unit_id}: included requirement lacks direct traceability metadata")
            continue

        direct: list[str] = []
        contextual: list[str] = []
        unsafe: list[str] = []
        for task_id in task_ids:
            task = tasks.get(task_id)
            if task is None:
                unsafe.append(task_id)
            elif not (task["targets"] & declared):
                unsafe.append(task_id)
            elif spec_ids & task["requirements"]:
                direct.append(task_id)
            else:
                contextual.append(task_id)
        if unsafe:
            blockers.append(
                f"{unit_id}: cannot safely repair task reference(s) {', '.join(unsafe)}"
            )
            continue
        if contextual and not direct:
            blockers.append(
                f"{unit_id}: cannot remove contextual task reference(s) without losing all direct evidence"
            )
            continue
        if contextual:
            entry["task_ids"] = direct
            removed.extend((unit_id, task_id) for task_id in contextual)

    result = ProductInputTraceabilityRepair(tuple(removed), tuple(blockers))
    if apply and result.removed and not result.blockers:
        _write_json(traceability_path, ledger)
        _write_traceability_markdown(traceability_path.with_suffix(".md"), ledger)
    return result


def apply_product_input_updates(
    traceability_path: Path,
    updates: Sequence[object],
    *,
    tasks_path: Path | None = None,
    declared_targets: Sequence[str] | None = None,
) -> None:
    """Apply validated agent mappings while keeping the controller as ledger writer."""
    try:
        ledger = json.loads(traceability_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductInputError(f"cannot update product input traceability: {exc}") from exc
    # Work on a copy: PLAN mapping errors must never leave a partial or invalid
    # controller-owned ledger behind for a later finalization gate to discover.
    candidate = json.loads(json.dumps(ledger))
    requirements = candidate.get("requirements")
    if not isinstance(requirements, list):
        raise ProductInputError("product input traceability has no requirements list")
    by_id = {
        str(entry.get("input_unit_id")): entry
        for entry in requirements
        if isinstance(entry, dict) and entry.get("input_unit_id")
    }
    for update in updates:
        if not isinstance(update, dict):
            raise ProductInputError("product input update must be an object")
        unit_id = str(update.get("input_unit_id") or "")
        current = by_id.get(unit_id)
        if current is None:
            raise ProductInputError(f"product input update references unknown requirement unit {unit_id!r}")
        disposition = str(update.get("disposition") or "")
        if disposition not in {"included", "excluded", "duplicate", "open_question", "conflict"}:
            raise ProductInputError(f"{unit_id}: invalid product input disposition {disposition!r}")
        rationale = str(update.get("rationale") or "").strip()
        if not rationale:
            raise ProductInputError(f"{unit_id}: product input update requires rationale")
        current.update({
            "disposition": disposition,
            "rationale": rationale,
            "spec_ids": _string_list(update.get("spec_ids")),
            "task_ids": _string_list(update.get("task_ids")),
            "targets": _string_list(update.get("targets")),
        })
    if tasks_path is not None:
        blockers = _traceability_blockers(
            candidate,
            _task_metadata(tasks_path),
            declared_targets or (),
        )
        if blockers:
            raise ProductInputError("; ".join(blockers))
    _write_json(traceability_path, candidate)
    _write_traceability_markdown(traceability_path.with_suffix(".md"), candidate)


def normalize_context_only_product_input_updates(
    updates: Sequence[object],
    catalog_path: Path,
) -> tuple[list[object], tuple[str, ...]]:
    """Drop harmless exclusions for catalog units that are not traceable.

    Product-input contexts created before the traceability filter exposed
    Markdown headings and table scaffolding with ``IN-REQ`` IDs.  Those units
    are deliberately absent from the controller-owned ledger, so an agent's
    empty ``excluded`` proposal is a harmless acknowledgement rather than a
    ledger update.  Preserve every substantive proposal for normal validation.
    """
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductInputError(f"cannot read product input catalog: {exc}") from exc
    units = catalog.get("units") if isinstance(catalog, dict) else None
    if not isinstance(units, list):
        raise ProductInputError("product input catalog has no units list")
    context_only_ids = {
        str(unit.get("id"))
        for unit in units
        if isinstance(unit, dict)
        and unit.get("role") == "requirement"
        and not unit.get("traceability_required", True)
        and unit.get("id")
    }

    normalized: list[object] = []
    ignored: list[str] = []
    for update in updates:
        if not isinstance(update, dict):
            normalized.append(update)
            continue
        unit_id = str(update.get("input_unit_id") or "")
        if unit_id not in context_only_ids:
            normalized.append(update)
            continue
        is_empty_exclusion = (
            str(update.get("disposition") or "") == "excluded"
            and not _string_list(update.get("spec_ids"))
            and not _string_list(update.get("task_ids"))
            and not _string_list(update.get("targets"))
        )
        if is_empty_exclusion:
            ignored.append(unit_id)
            continue
        raise ProductInputError(
            f"{unit_id}: context-only catalog unit is not traceable; omit it from product_input_updates"
        )
    return normalized, tuple(ignored)


def refresh_requirement_context_from_catalog(
    catalog_path: Path,
    requirement_context_path: Path,
) -> None:
    """Regenerate a derived requirement prompt from its immutable catalog."""
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductInputError(f"cannot read product input catalog: {exc}") from exc
    units = catalog.get("units") if isinstance(catalog, dict) else None
    if not isinstance(units, list):
        raise ProductInputError("product input catalog has no units list")
    _write_context(requirement_context_path, units, "requirement")


def build_product_input_mapping_repair_hints(
    updates: Sequence[object],
    tasks_path: Path,
    declared_targets: Sequence[str],
) -> dict[str, object]:
    """Return the exact direct-task choices for a rejected PLAN mapping proposal.

    This diagnostic is intentionally derived only from the canonical task rows.
    It does not infer semantic mappings or write the controller-owned ledger;
    it prevents an agent from repeatedly citing context-only ``INFRA`` tasks as
    proof for a product-input requirement.
    """
    tasks = _task_metadata(tasks_path)
    declared = set(declared_targets)
    matrix = [
        {
            "task_id": task_id,
            "requirements": sorted(metadata["requirements"]),
            "target": next(iter(sorted(metadata["targets"])), ""),
        }
        for task_id, metadata in sorted(tasks.items())
    ]
    candidates: list[dict[str, object]] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        unit_id = str(update.get("input_unit_id") or "").strip()
        if not unit_id:
            continue
        spec_ids = sorted({str(value) for value in update.get("spec_ids", []) if str(value).strip()})
        task_ids = [str(value) for value in update.get("task_ids", []) if str(value).strip()]
        direct = [
            task_id for task_id, metadata in sorted(tasks.items())
            if (metadata["requirements"] & set(spec_ids)) and (metadata["targets"] & declared)
        ]
        candidates.append({
            "input_unit_id": unit_id,
            "spec_ids": spec_ids,
            "direct_task_ids": direct,
            "invalid_task_ids": [task_id for task_id in task_ids if task_id not in direct],
        })
    return {"candidates": candidates, "task_requirement_matrix": matrix}


def repair_product_input_structural_units(
    traceability_path: Path,
    catalog_path: Path,
    *,
    apply: bool,
) -> tuple[str, ...]:
    """Exclude legacy Markdown scaffolding from a requirement traceability ledger.

    Early input packages represented every non-empty Markdown line as a
    requirement.  Heading-only, table-header, and separator lines provide
    useful context but no independently implementable product obligation.  The
    repair is deterministic and deliberately limited to those syntactic forms.
    """
    try:
        ledger = json.loads(traceability_path.read_text(encoding="utf-8"))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    requirements = ledger.get("requirements") if isinstance(ledger, dict) else None
    units = catalog.get("units") if isinstance(catalog, dict) else None
    if not isinstance(requirements, list) or not isinstance(units, list):
        return ()

    structural_ids = _structural_catalog_unit_ids(units)
    repaired: list[str] = []
    for entry in requirements:
        if not isinstance(entry, dict):
            continue
        unit_id = str(entry.get("input_unit_id") or "")
        if unit_id not in structural_ids:
            continue
        if str(entry.get("disposition") or "") == "excluded":
            continue
        entry.update({
            "disposition": "excluded",
            "rationale": "Markdown structural context; retained in the immutable input catalog but not an independently implementable requirement.",
            "spec_ids": [],
            "task_ids": [],
            "targets": [],
        })
        repaired.append(unit_id)
    if apply and repaired:
        _write_json(traceability_path, ledger)
        _write_traceability_markdown(traceability_path.with_suffix(".md"), ledger)
    return tuple(repaired)


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductInputError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProductInputError(f"{label} must be a JSON object")
    return payload


def _attachment_declaration_keys(
    manifest: Mapping[str, object],
    ledger: Mapping[str, object],
) -> set[tuple[str, str]]:
    keys = {
        (str(item.get("role") or ""), str(item.get("location") or ""))
        for item in manifest.get("declarations", [])
        if isinstance(item, dict)
    }
    attachments = ledger.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            declarations = attachment.get("declarations")
            if not isinstance(declarations, list):
                continue
            keys.update(
                (str(item.get("role") or ""), str(item.get("location") or ""))
                for item in declarations
                if isinstance(item, dict)
            )
    return {(role, location) for role, location in keys if role and location}


def _accepted_hashes(
    manifest: Mapping[str, object],
    ledger: Mapping[str, object],
) -> set[str]:
    hashes = {
        str(item.get("sha256"))
        for item in manifest.get("resources", [])
        if isinstance(item, dict)
        and item.get("status") == "accepted"
        and str(item.get("sha256") or "")
    }
    attachments = ledger.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            resources = attachment.get("resources")
            if not isinstance(resources, list):
                continue
            hashes.update(
                str(item.get("sha256"))
                for item in resources
                if isinstance(item, dict) and str(item.get("sha256") or "")
            )
    return hashes


def _next_attachment_id(
    inputs_dir: Path,
    ledger: Mapping[str, object],
) -> str:
    ids: list[int] = []
    attachments = ledger.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            raw_id = str(attachment.get("id") or "")
            if raw_id.isdigit():
                ids.append(int(raw_id))
    attachment_root = inputs_dir / "attachments"
    if attachment_root.exists():
        ids.extend(
            int(path.name)
            for path in attachment_root.iterdir()
            if path.is_dir() and path.name.isdigit()
        )
    return f"{(max(ids) if ids else 0) + 1:03d}"


def _attachment_resource_summary(
    resource: Mapping[str, object],
    *,
    attachment_id: str,
    inputs_dir: Path,
    project_root: Path,
) -> dict[str, object]:
    snapshot = str(resource.get("snapshot") or "")
    run_relative_snapshot = (
        (Path("attachments") / attachment_id / snapshot).as_posix()
        if snapshot
        else ""
    )
    return {
        "declaration_id": str(resource.get("declaration_id") or ""),
        "role": str(resource.get("role") or ""),
        "source_locator": str(resource.get("source_locator") or ""),
        "declared_relative_path": str(resource.get("declared_relative_path") or ""),
        "sha256": str(resource.get("sha256") or ""),
        "size_bytes": resource.get("size_bytes", 0),
        "media_type": str(resource.get("media_type") or ""),
        "snapshot": run_relative_snapshot,
        "snapshot_path": _portable(inputs_dir / run_relative_snapshot, project_root)
        if run_relative_snapshot
        else "",
    }


def _linked_evidence_request_ids(
    evidence_requests: Mapping[str, object] | None,
    declarations: Sequence[ProductInputDeclaration],
    resources: Sequence[Mapping[str, object]],
) -> list[str]:
    if not isinstance(evidence_requests, Mapping):
        return []
    requests = evidence_requests.get("requests")
    if not isinstance(requests, list):
        return []
    haystack = " ".join(
        [
            *(item.location for item in declarations),
            *(
                str(resource.get("source_locator") or "")
                for resource in resources
            ),
            *(
                str(resource.get("declared_relative_path") or "")
                for resource in resources
            ),
        ]
    ).lower()
    request_ids: list[str] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        request_id = str(request.get("id") or "").strip()
        if not request_id:
            continue
        question = str(request.get("question") or "").lower()
        if request_id.lower() in haystack or any(
            token and len(token) > 3 and token in haystack
            for token in re.split(r"\W+", question)
        ):
            request_ids.append(request_id)
    if request_ids:
        return request_ids
    return [
        str(request.get("id"))
        for request in requests
        if isinstance(request, dict) and str(request.get("id") or "").strip()
    ]


def _write_aggregate_product_inputs(
    inputs_dir: Path,
    base_manifest: Mapping[str, object],
    base_catalog: Mapping[str, object],
    base_traceability: Mapping[str, object],
    revision_manifest: Mapping[str, object],
    revision_catalog: Mapping[str, object],
    *,
    duplicate_hashes: set[str],
    attachment_id: str,
    pointer_inputs_dir: Path | None = None,
) -> None:
    rendered_inputs_dir = (
        Path(pointer_inputs_dir)
        if pointer_inputs_dir is not None
        else inputs_dir
    )
    aggregate_manifest = json.loads(json.dumps(base_manifest))
    aggregate_catalog = json.loads(json.dumps(base_catalog))
    aggregate_traceability = json.loads(json.dumps(base_traceability))

    aggregate_manifest.setdefault("schema_version", 1)
    aggregate_manifest.setdefault("declarations", [])
    aggregate_manifest.setdefault("resources", [])
    aggregate_catalog.setdefault("schema_version", 1)
    aggregate_catalog.setdefault("units", [])
    aggregate_traceability.setdefault("schema_version", 1)
    aggregate_traceability.setdefault("requirements", [])
    aggregate_traceability.setdefault("references", [])

    declaration_id_map: dict[str, str] = {}
    declarations = revision_manifest.get("declarations")
    if isinstance(declarations, list):
        for declaration in declarations:
            if not isinstance(declaration, dict):
                continue
            old_id = str(declaration.get("id") or "")
            new_id = f"attachment-{attachment_id}-{old_id}" if old_id else f"attachment-{attachment_id}"
            declaration_id_map[old_id] = new_id
            aggregate_manifest["declarations"].append({
                **declaration,
                "id": new_id,
                "attachment_id": attachment_id,
            })

    resources = revision_manifest.get("resources")
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            cloned = dict(resource)
            old_declaration_id = str(cloned.get("declaration_id") or "")
            if old_declaration_id in declaration_id_map:
                cloned["declaration_id"] = declaration_id_map[old_declaration_id]
            cloned["attachment_id"] = attachment_id
            if cloned.get("snapshot"):
                cloned["snapshot"] = (
                    Path("attachments") / attachment_id / str(cloned["snapshot"])
                ).as_posix()
            if (
                cloned.get("status") == "accepted"
                and str(cloned.get("sha256") or "") in duplicate_hashes
            ):
                cloned["status"] = "excluded"
                cloned["reason"] = "duplicate content"
            aggregate_manifest["resources"].append(cloned)

    units = revision_catalog.get("units")
    if isinstance(units, list):
        existing_unit_ids = {
            str(unit.get("id"))
            for unit in aggregate_catalog.get("units", [])
            if isinstance(unit, dict) and unit.get("id")
        }
        for unit in units:
            if not isinstance(unit, dict):
                continue
            if str(unit.get("sha256") or "") in duplicate_hashes:
                continue
            cloned = dict(unit)
            old_declaration_id = str(cloned.get("declaration_id") or "")
            if old_declaration_id in declaration_id_map:
                cloned["declaration_id"] = declaration_id_map[old_declaration_id]
            cloned["attachment_id"] = attachment_id
            if cloned.get("snapshot"):
                cloned["snapshot"] = (
                    Path("attachments") / attachment_id / str(cloned["snapshot"])
                ).as_posix()
            if str(cloned.get("id") or "") in existing_unit_ids:
                continue
            aggregate_catalog["units"].append(cloned)
            existing_unit_ids.add(str(cloned.get("id") or ""))
            if cloned.get("role") == "requirement" and cloned.get("traceability_required", True):
                aggregate_traceability["requirements"].append({
                    "input_unit_id": cloned["id"],
                    "disposition": "open_question",
                    "rationale": "Awaiting specification analysis.",
                    "spec_ids": [],
                    "task_ids": [],
                    "targets": [],
                })
            elif cloned.get("role") == "reference":
                aggregate_traceability["references"].append({
                    "input_unit_id": cloned["id"],
                    "state": "reviewed_unused",
                    "rationale": "Awaiting analysis.",
                })

    _write_json(inputs_dir / "manifest.json", aggregate_manifest)
    _write_json(inputs_dir / "catalog.json", aggregate_catalog)
    aggregate_units = [
        unit for unit in aggregate_catalog.get("units", [])
        if isinstance(unit, dict)
    ]
    _write_context(inputs_dir / "requirement-context.md", aggregate_units, "requirement")
    _write_context(inputs_dir / "reference-context.md", aggregate_units, "reference")
    input_context = inputs_dir / "input-context.md"
    input_context.write_text(
        "# Product Input Context\n\n"
        f"- Manifest: `{rendered_inputs_dir / 'manifest.json'}`\n"
        f"- Catalog: `{rendered_inputs_dir / 'catalog.json'}`\n"
        f"- Requirement units: `{rendered_inputs_dir / 'requirement-context.md'}`\n"
        f"- Reference units: `{rendered_inputs_dir / 'reference-context.md'}`\n",
        encoding="utf-8",
    )
    _write_json(inputs_dir / "traceability.json", aggregate_traceability)
    _write_traceability_markdown(inputs_dir / "traceability.md", aggregate_traceability)


def _normalize_declaration(declaration: ProductInputDeclaration) -> ProductInputDeclaration:
    if declaration.role not in _ROLES or not declaration.location.strip():
        raise ProductInputError("invalid product input declaration")
    return ProductInputDeclaration(declaration.role, declaration.location.strip())


def _is_url(location: str) -> bool:
    return bool(urlparse(location).scheme and urlparse(location).netloc)


def _resolve_figma_url(location: str, inputs_dir: Path, declaration_id: str) -> Path:
    """Resolve a declared Figma file URL without retaining its access token."""
    parsed = urlparse(location)
    if "figma.com" not in parsed.netloc.lower():
        raise ProductInputError("only Figma URLs are supported as remote product inputs")
    parts = [part for part in parsed.path.split("/") if part]
    try:
        marker = next(index for index, part in enumerate(parts) if part in {"file", "design"})
        file_key = parts[marker + 1]
    except (StopIteration, IndexError) as exc:
        raise ProductInputError("Figma URL must identify a file or design key") from exc
    token = os.environ.get("FIGMA_ACCESS_TOKEN", "").strip()
    if not token:
        raise ProductInputError(
            "Figma URL requires FIGMA_ACCESS_TOKEN or an offline Figma evidence bundle "
            "(manifest.json, design.json, and frame assets)."
        )
    request = Request(
        f"https://api.figma.com/v1/files/{file_key}",
        headers={"X-Figma-Token": token},
    )
    try:
        with urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ProductInputError(f"could not resolve Figma URL: {exc}") from exc
    resolved = inputs_dir / ".figma-resolved" / declaration_id
    resolved.mkdir(parents=True, exist_ok=True)
    _write_json(resolved / "manifest.json", {
        "format": "figma-rest-file",
        "source_url": location,
        "file_key": file_key,
    })
    _write_json(resolved / "design.json", document)
    return resolved


def _assert_contained(resource: Path, root: Path) -> None:
    try:
        resource.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ProductInputError(f"input symlink {resource} escapes declared input root") from exc


def _classify(path: Path) -> tuple[str, str]:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == ".ds_store":
        return "excluded", "hidden OS metadata"
    if name.startswith("."):
        return "excluded", "hidden file"
    if name in _SECRET_FILENAMES or name.endswith(".env") or suffix in _SECRET_SUFFIXES:
        return "excluded", "secret-like filename"
    if suffix in _TEXT_SUFFIXES or suffix in _ASSET_SUFFIXES:
        return "accepted", ""
    return "blocking", "unsupported file type"


def _decode_text(path: Path, content: bytes) -> str | None:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProductInputError(f"text input is not UTF-8: {path}") from exc


def _unitize_requirement_pdf(
    path: Path,
    declaration_id: str,
    locator: str,
    snapshot: str,
    digest: str,
    media_type: str,
) -> list[dict[str, object]]:
    pages = _extract_pdf_pages(path)
    if not pages:
        raise ProductInputError(f"requirement PDF has no extractable text: {locator}")
    return [
        _unit(
            "requirement",
            declaration_id,
            locator,
            snapshot,
            digest,
            media_type,
            f"page:{page_number}",
            page,
        )
        for page_number, page in enumerate(pages, start=1)
        if page.strip()
    ]


def _extract_pdf_pages(path: Path) -> list[str]:
    """Extract pages with the bundled reader, then Poppler when it adds fidelity."""
    try:
        pages = _extract_pdf_pages_with_pypdf(path)
    except ProductInputError as pypdf_error:
        return _extract_pdf_pages_with_pdftotext(path, pypdf_error)
    if pages:
        return pages
    return _extract_pdf_pages_with_pdftotext(
        path,
        ProductInputError("pypdf found no extractable text"),
    )


def _extract_pdf_pages_with_pypdf(path: Path) -> list[str]:
    """Use the Python PDF reader when Poppler is unavailable on the host."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ProductInputError(
            "requirement PDF input requires pdftotext or the pypdf package; "
            "install Echelon dependencies or provide OCR text"
        ) from exc
    try:
        reader = PdfReader(path)
        return [
            text.strip()
            for page in reader.pages
            if (text := (page.extract_text() or "")).strip()
        ]
    except Exception as exc:
        raise ProductInputError(f"could not extract requirement PDF text from {path}: {exc}") from exc


def _extract_pdf_pages_with_pdftotext(
    path: Path,
    pypdf_error: ProductInputError,
) -> list[str]:
    """Use Poppler when pypdf is unavailable or cannot read useful text."""

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProductInputError(
            f"could not extract requirement PDF text from {path}: {pypdf_error}; "
            "pdftotext (Poppler) is not installed"
        ) from exc
    if result.returncode:
        raise ProductInputError(
            f"could not extract requirement PDF text from {path}: {pypdf_error}; "
            f"pdftotext fallback failed: {result.stderr.strip()}"
        )
    return [page.strip() for page in result.stdout.split("\f") if page.strip()]


def _media_type(path: Path) -> str:
    if path.suffix.lower() == ".svg":
        return "image/svg+xml"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "text/plain"


def _unitize(role: str, declaration_id: str, locator: str, snapshot: str, digest: str, media_type: str, text: str | None) -> list[dict[str, object]]:
    if text is None:
        return [_unit(role, declaration_id, locator, snapshot, digest, media_type, "file", "binary/design evidence")]
    units: list[dict[str, object]] = []
    source_lines = text.splitlines()
    for line_number, line in enumerate(source_lines, start=1):
        statement = line.strip()
        if statement:
            units.append(_unit(
                role,
                declaration_id,
                locator,
                snapshot,
                digest,
                media_type,
                f"line:{line_number}",
                statement,
                traceability_required=not _is_markdown_scaffolding(source_lines, line_number - 1),
            ))
    return units or [_unit(role, declaration_id, locator, snapshot, digest, media_type, "file", "empty input file")]


def _unit(role: str, declaration_id: str, locator: str, snapshot: str, digest: str, media_type: str, locator_suffix: str, statement: str, *, traceability_required: bool = True) -> dict[str, object]:
    prefix = "REQ" if role == "requirement" else "REF"
    stable = f"{role}:{locator}:{locator_suffix}:{digest}".encode("utf-8")
    return {
        "id": f"IN-{prefix}-{hashlib.sha256(stable).hexdigest()[:12].upper()}",
        "role": role,
        "declaration_id": declaration_id,
        "source_locator": f"{locator}:{locator_suffix}",
        "snapshot": snapshot,
        "sha256": digest,
        "media_type": media_type,
        "statement": statement,
        "traceability_required": traceability_required,
    }


def _is_markdown_scaffolding(lines: Sequence[str], index: int) -> bool:
    """Identify Markdown structure that is useful context but not a requirement."""
    statement = lines[index].strip()
    if re.fullmatch(r"#{1,6}\s+.+", statement):
        return True
    if re.fullmatch(r"\*\*[^*]+\*\*", statement):
        return True
    if _is_markdown_table_separator(statement):
        return True
    next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
    return statement.startswith("|") and statement.endswith("|") and _is_markdown_table_separator(next_line)


def _is_markdown_table_separator(statement: str) -> bool:
    cells = [cell.strip() for cell in statement.strip("|").split("|")]
    return len(cells) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _structural_catalog_unit_ids(units: Sequence[object]) -> set[str]:
    statements = [
        str(unit.get("statement") or "") if isinstance(unit, dict) else ""
        for unit in units
    ]
    return {
        str(unit.get("id"))
        for index, unit in enumerate(units)
        if isinstance(unit, dict)
        and unit.get("role") == "requirement"
        and _is_markdown_scaffolding(statements, index)
    }


def _write_context(path: Path, units: Iterable[dict[str, object]], role: str) -> None:
    selected = [
        unit for unit in units
        if unit["role"] == role
        and (role != "requirement" or unit.get("traceability_required", True))
    ]
    lines = [f"# {role.title()} Product Inputs", ""]
    if not selected:
        lines.append("No accepted inputs.")
    for unit in selected:
        lines.extend([f"## {unit['id']}", f"- Source: `{unit['source_locator']}`", f"- Snapshot: `{unit['snapshot']}`", f"- Evidence: {unit['statement']}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_traceability_markdown(path: Path, ledger: dict[str, object]) -> None:
    lines = ["# Product Input Traceability", ""]
    for entry in ledger.get("requirements", []):
        lines.append(f"- {entry['input_unit_id']}: {entry['disposition']}; spec={entry['spec_ids']}; tasks={entry['task_ids']}")
    for entry in ledger.get("references", []):
        lines.append(f"- {entry['input_unit_id']}: reference {entry['state']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _task_metadata(tasks_path: Path) -> dict[str, dict[str, set[str]]]:
    if not tasks_path.exists():
        return {}
    markdown = tasks_path.read_text(encoding="utf-8")
    canonical_tasks = parse_task_rows(markdown)
    if canonical_tasks:
        return {
            task.task_id: {
                "requirements": set(task.requirements),
                "targets": {task.target} if task.target else set(),
            }
            for task in canonical_tasks
        }

    # Compatibility for pre-canonical task ledgers. Canonical tasks must use
    # the shared parser above so fenced examples and later prose cannot
    # overwrite their metadata.
    tasks: dict[str, dict[str, set[str]]] = {}
    for line in markdown.splitlines():
        task_match = re.search(r"\b(T-\d+)\b", line)
        if task_match is None:
            continue
        requirements = {
            requirement
            for value in re.findall(r"req=([^\]\s]+)", line)
            for requirement in value.split(",")
            if requirement
        }
        targets = set(re.findall(r"target=([^\]\s]+)", line))
        tasks[task_match.group(1)] = {"requirements": requirements, "targets": targets}
    return tasks


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _portable(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()

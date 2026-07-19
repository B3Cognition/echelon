"""Immutable, safe product-input evidence for Phase A specification runs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from harness.secret_scan import scan_text
from kernel.task_contract import parse_task_rows


_ROLES = frozenset({"requirement", "reference"})
_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".xml"})
_ASSET_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".svg"})
_SECRET_FILENAMES = frozenset({".env", "secrets.env", "credentials", "credentials.json", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"})
_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


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

    def state_payload(self, project_root: Path) -> dict[str, object]:
        """Return JSON-safe, workspace-portable pointers for squad state."""
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
        }


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
    project_root = project_root.resolve()
    inputs_dir = run_dir / "inputs"
    if inputs_dir.exists():
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
        f"- Manifest: `{manifest_path}`\n"
        f"- Catalog: `{catalog_path}`\n"
        f"- Requirement units: `{requirement_context}`\n"
        f"- Reference units: `{reference_context}`\n",
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
    selected = [unit for unit in units if unit["role"] == role]
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

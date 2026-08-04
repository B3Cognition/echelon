"""Controller-owned evidence attachment for parked Phase A spec runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
from threading import get_ident
from typing import Sequence
from uuid import uuid4

from echelon.product_inputs import (
    ProductInputDeclaration,
    attach_product_input_revision,
    immutable_product_input_tree_digest,
    parse_input_declaration,
)
from echelon.strict_json import loads_strict_json
from echelon.product_input_transaction import (
    ProductInputMutationError,
    add_complete_product_input_publication,
    authenticate_pending_product_input_mutation,
    authenticate_product_input_contract,
    build_product_input_mutation,
    pending_product_input_mutation,
    product_input_request_sha256,
    require_product_input_mutation_postimage,
    restore_product_input_directory_modes,
)
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleLocked,
    SpecRunExecutionLock,
)
from harness.squad_state import SquadStateStore
from harness.squad_publication import (
    PublicationError,
    SquadPublicationTransaction,
    load_prepared_publication,
)
from harness.state_transaction_namespace import (
    PENDING_EXTERNAL_PUBLICATION_KEY,
    is_valid_product_input_attachment_id,
)


class SpecAddInputError(RuntimeError):
    """Raised when active-run evidence cannot be appended safely."""


_COMPLETED_ADD_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "request_sha256",
        "product_input_tree_hash",
        "command",
        "operation_id",
        "attachment_ids",
        "attachment_id",
        "added_count",
        "duplicate_count",
        "original_declaration_count",
        "attached_declaration_count",
        "original_declarations",
        "attached_declarations",
        "attachment_ledger_entry",
        "attachment_ledger_entry_sha256",
        "product_input_attachments_sha256",
        "previous_blocked_reason",
        "previous_phase1_investigate_dispatch_count",
    }
)
_MAX_COMPLETION_EVIDENCE_BYTES = 4 * 1024 * 1024


def _canonical_evidence_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeError) as exc:
        raise SpecAddInputError("completed add-input evidence is invalid") from exc
    if len(encoded) > _MAX_COMPLETION_EVIDENCE_BYTES:
        raise SpecAddInputError("completed add-input evidence is too large")
    return encoded


def _evidence_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_evidence_bytes(value)).hexdigest()


def _load_attachment_ledger(path: Path) -> dict[str, object]:
    try:
        value = loads_strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SpecAddInputError("completed add-input attachment ledger is invalid") from exc
    if (
        type(value) is not dict
        or frozenset(value) != frozenset({"schema_version", "attachments"})
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or type(value.get("attachments")) is not list
        or len(value["attachments"]) > 100_000
    ):
        raise SpecAddInputError("completed add-input attachment ledger is invalid")
    return value


def _exact_attachment_entry(
    ledger: dict[str, object],
    attachment_id: str,
) -> dict[str, object]:
    matches = [
        entry
        for entry in ledger["attachments"]
        if type(entry) is dict and entry.get("id") == attachment_id
    ]
    if len(matches) != 1:
        raise SpecAddInputError("completed add-input attachment ledger entry is missing")
    entry = matches[0]
    _canonical_evidence_bytes(entry)
    return entry


@dataclass(frozen=True)
class SpecAddInputResult:
    run_dir: Path
    attachment_id: str
    added_count: int
    duplicate_count: int
    original_declarations: tuple[dict[str, str], ...]
    attached_declarations: tuple[dict[str, str], ...]
    next_command: str = "echelon spec continue"


def add_input_to_active_run(
    project_root: Path,
    input_values: Sequence[str],
    *,
    command: str = "echelon spec add-input",
) -> SpecAddInputResult:
    """Append declared evidence to the active parked investigation run."""
    root = Path(project_root).resolve()
    declarations = tuple(parse_input_declaration(value) for value in input_values)
    if not declarations:
        raise SpecAddInputError("at least one --input declaration is required")
    run_dir = _find_current_run_dir(root)
    if run_dir is None:
        raise SpecAddInputError("no active squad run found")
    operation_id = f"add-input-{os.getpid()}-{get_ident()}-{uuid4().hex}"
    try:
        with PhaseAExecutionLock.acquire(root, operation_id):
            with SpecRunExecutionLock.acquire(run_dir, operation_id):
                return _add_input_locked(
                    root,
                    run_dir,
                    declarations,
                    command=command,
                )
    except SpecLifecycleLocked as exc:
        raise SpecAddInputError(
            f"cannot add input while execution lease is owned by {exc.operation_id}"
        ) from exc


def _add_input_locked(
    project_root: Path,
    run_dir: Path,
    declarations: Sequence[object],
    *,
    command: str,
) -> SpecAddInputResult:
    store = SquadStateStore(run_dir)
    request_sha256 = product_input_request_sha256(command, declarations)
    _recover_pending_mutation(project_root, store)
    state = store.load()
    completed = _completed_add_input_result(
        run_dir,
        state,
        request_sha256=request_sha256,
    )
    if completed is not None:
        _authenticate_completed_add_input(
            project_root,
            run_dir,
            state,
            request_sha256=request_sha256,
        )
        return completed
    _ensure_eligible_state(state)
    product_inputs = state.get("product_inputs")
    if not isinstance(product_inputs, dict) or not product_inputs:
        raise SpecAddInputError("active run has no Product Input Contract")
    inputs_ref = str(product_inputs.get("inputs_dir") or "").strip()
    if not inputs_ref:
        raise SpecAddInputError("active run Product Input Contract lacks inputs_dir")
    inputs_dir = Path(inputs_ref)
    if not inputs_dir.is_absolute():
        inputs_dir = project_root / inputs_dir
    inputs_dir = inputs_dir.resolve()
    expected_inputs_dir = (run_dir / "inputs").resolve()
    if inputs_dir != expected_inputs_dir:
        raise SpecAddInputError(
            "active run Product Input Contract is not run-local"
        )

    try:
        old_tree_hash = authenticate_product_input_contract(
            project_root,
            product_inputs,
            inputs_dir,
        )
    except ProductInputMutationError as exc:
        raise SpecAddInputError(str(exc)) from exc
    snapshot = store.capture_routing_snapshot(
        expected_phase=str(state.get("phase") or "")
    )
    original_declarations = tuple(
        {
            "role": str(item.get("role") or ""),
            "location": str(item.get("location") or ""),
        }
        for item in product_inputs.get("declarations", [])
        if isinstance(item, dict)
    )
    attached_declarations = tuple(
        {"role": item.role, "location": item.location}
        for item in declarations  # type: ignore[attr-defined]
    )
    operation_id = uuid4().hex
    transaction = SquadPublicationTransaction.begin(
        project_root,
        run_dir,
        operation_id,
    )
    staged_old_inputs = transaction.build_path("work/product-inputs-old")
    staged_inputs = transaction.build_path("work/product-inputs")
    prepared = None
    try:
        shutil.copytree(
            inputs_dir,
            staged_old_inputs,
            symlinks=True,
            copy_function=shutil.copy2,
        )
        if (
            authenticate_product_input_contract(
                project_root,
                product_inputs,
                inputs_dir,
            )
            != old_tree_hash
        ):
            raise ProductInputMutationError("product input tree changed during staging")
        if immutable_product_input_tree_digest(staged_old_inputs) != old_tree_hash:
            raise ProductInputMutationError("staged product input preimage changed")
        shutil.copytree(
            staged_old_inputs,
            staged_inputs,
            symlinks=True,
            copy_function=shutil.copy2,
        )
        if immutable_product_input_tree_digest(staged_inputs) != old_tree_hash:
            raise ProductInputMutationError("staged product input preimage changed")
        attachment = attach_product_input_revision(
            project_root,
            staged_inputs,
            declarations,  # type: ignore[arg-type]
            command=command,
            evidence_requests=(
                state.get("evidence_requests")
                if isinstance(state.get("evidence_requests"), dict)
                else None
            ),
            pointer_inputs_dir=inputs_dir,
            operation_id=operation_id,
        )
        restore_product_input_directory_modes(
            staged_old_inputs,
            staged_inputs,
        )
        if not attachment.added:
            transaction.seal().discard()
            return SpecAddInputResult(
                run_dir=run_dir,
                attachment_id=attachment.attachment_id,
                added_count=0,
                duplicate_count=len(attachment.duplicates),
                original_declarations=original_declarations,
                attached_declarations=attached_declarations,
            )
        if attachment.tree_hash is None:
            raise ProductInputMutationError(
                "product input attachment has no authenticated postimage"
            )
        owned_paths = add_complete_product_input_publication(
            transaction,
            project_root,
            inputs_dir,
            staged_inputs,
        )
        post_tree_hash = immutable_product_input_tree_digest(staged_inputs)
        prepared = transaction.seal()
        marker = prepared.marker.to_dict()
        mutation = build_product_input_mutation(
            kind="add_input",
            marker=marker,
            inputs_dir=inputs_dir.relative_to(project_root).as_posix(),
            old_tree_hash=old_tree_hash,
            new_tree_hash=post_tree_hash,
            owned_paths=owned_paths,
            request_sha256=request_sha256,
            attachment_id=attachment.attachment_id,
            added_count=len(attachment.added),
            duplicate_count=len(attachment.duplicates),
        )
    except Exception as exc:
        if prepared is None:
            try:
                transaction.seal().discard()
            except Exception:
                pass
        if isinstance(exc, SpecAddInputError):
            raise
        raise SpecAddInputError(f"cannot stage product input mutation: {exc}") from exc

    previous_counts = dict(state.get("phase_dispatch_counts") or {})
    previous_investigate_count = previous_counts.pop("phase1-investigate", 0)
    updated_product_inputs = attachment.state_product_inputs(
        project_root,
        product_inputs,
        package_dir=staged_inputs,
    )
    updated_product_inputs["tree_hash"] = post_tree_hash
    product_input_attachments = attachment.state_attachments(
        project_root,
        ledger_source_path=staged_inputs / "attachment-ledger.json",
    )
    attachment_ledger = _load_attachment_ledger(
        staged_inputs / "attachment-ledger.json"
    )
    attachment_ledger_entry = _exact_attachment_entry(
        attachment_ledger,
        attachment.attachment_id,
    )
    recovery = {
        "schema_version": 3,
        "request_sha256": request_sha256,
        "product_input_tree_hash": post_tree_hash,
        "command": command,
        "operation_id": operation_id,
        "attachment_ids": [attachment.attachment_id],
        "attachment_id": attachment.attachment_id,
        "added_count": len(attachment.added),
        "duplicate_count": len(attachment.duplicates),
        "original_declaration_count": len(original_declarations),
        "attached_declaration_count": len(attached_declarations),
        "original_declarations": list(original_declarations),
        "attached_declarations": list(attached_declarations),
        "attachment_ledger_entry": attachment_ledger_entry,
        "attachment_ledger_entry_sha256": _evidence_sha256(
            attachment_ledger_entry
        ),
        "product_input_attachments_sha256": _evidence_sha256(
            product_input_attachments
        ),
        "previous_blocked_reason": state.get("blocked_reason"),
        "previous_phase1_investigate_dispatch_count": previous_investigate_count,
    }
    state_updates = {
        "phase_dispatch_counts": previous_counts,
        "product_inputs": updated_product_inputs,
        "product_input_attachments": product_input_attachments,
        "status": "running",
        "phase": "phase1-investigate",
        "blocked_reason": None,
        "escalation_question": None,
        "escalation_resolved": True,
        "escalation_resolver": command,
        "add_input_recovery": recovery,
    }
    result = SpecAddInputResult(
        run_dir=run_dir,
        attachment_id=attachment.attachment_id,
        added_count=len(attachment.added),
        duplicate_count=len(attachment.duplicates),
        original_declarations=original_declarations,
        attached_declarations=attached_declarations,
    )
    try:
        store.begin_product_input_publication(
            marker,
            mutation,
            snapshot=snapshot,
            state_updates=state_updates,
        )
    except Exception as exc:
        _discard_publication_without_authority(store, prepared)
        raise SpecAddInputError(
            f"cannot persist product input mutation intent: {exc}"
        ) from exc
    try:
        persisted = store.confirm_durable_state(store.load())
        authenticate_pending_product_input_mutation(
            project_root,
            persisted,
            marker,
            prepared._manifest.get("operations"),
            staged_inputs=prepared._transaction_root / "work/product-inputs",
        )
        prepared.publish()
        persisted = store.load()
        verified_hash = require_product_input_mutation_postimage(
            project_root,
            persisted,
            marker,
        )
        store.complete_external_publication(
            marker,
            verified_product_input_tree_hash=verified_hash,
        )
        store.confirm_durable_state(store.load())
        prepared.discard()
    except Exception as exc:
        raise SpecAddInputError(
            f"product input mutation remains pending: {exc}"
        ) from exc
    return result


def _discard_publication_without_authority(
    store: SquadStateStore,
    prepared: object,
) -> None:
    try:
        marker = prepared.marker.to_dict()
        if store.load().get(PENDING_EXTERNAL_PUBLICATION_KEY) == marker:
            return
        prepared.discard()
    except Exception:
        return


def _recover_pending_mutation(
    project_root: Path,
    store: SquadStateStore,
) -> dict[str, object] | None:
    state = store.load()
    try:
        mutation = pending_product_input_mutation(state)
    except ProductInputMutationError as exc:
        raise SpecAddInputError(str(exc)) from exc
    if mutation is None:
        return None
    marker = state[PENDING_EXTERNAL_PUBLICATION_KEY]
    try:
        durable = store.confirm_durable_state(state)
        prepared = load_prepared_publication(
            project_root,
            store.squad_dir,
            marker,
        )
        authenticate_pending_product_input_mutation(
            project_root,
            durable,
            marker,
            prepared._manifest.get("operations"),
            staged_inputs=prepared._transaction_root / "work/product-inputs",
        )
        prepared.publish()
        persisted = store.load()
        verified_hash = require_product_input_mutation_postimage(
            project_root,
            persisted,
            marker,
        )
        store.complete_external_publication(
            marker,
            verified_product_input_tree_hash=verified_hash,
        )
        store.confirm_durable_state(store.load())
        prepared.discard()
        return mutation
    except (OSError, PublicationError, ProductInputMutationError, ValueError) as exc:
        raise SpecAddInputError(
            f"product input mutation recovery failed with evidence retained: {exc}"
        ) from exc


def _completed_add_input_result(
    run_dir: Path,
    state: dict,
    *,
    request_sha256: str,
) -> SpecAddInputResult | None:
    recovery = state.get("add_input_recovery")
    if (
        type(recovery) is not dict
        or frozenset(recovery) != _COMPLETED_ADD_INPUT_KEYS
        or recovery.get("schema_version") != 3
        or recovery.get("request_sha256") != request_sha256
    ):
        return None
    original = recovery.get("original_declarations")
    attached = recovery.get("attached_declarations")
    if type(original) is not list or type(attached) is not list:
        raise SpecAddInputError("completed add-input recovery receipt is invalid")

    def declarations_tuple(value: list[object]) -> tuple[dict[str, str], ...]:
        normalized: list[dict[str, str]] = []
        for item in value:
            if (
                type(item) is not dict
                or frozenset(item) != frozenset({"role", "location"})
                or type(item.get("role")) is not str
                or type(item.get("location")) is not str
                or not item["role"]
                or not item["location"]
            ):
                raise SpecAddInputError("completed add-input declarations are invalid")
            normalized.append(
                {"role": item["role"], "location": item["location"]}
            )
        return tuple(normalized)

    attachment_id = recovery.get("attachment_id")
    added_count = recovery.get("added_count")
    duplicate_count = recovery.get("duplicate_count")
    original_count = recovery.get("original_declaration_count")
    attached_count = recovery.get("attached_declaration_count")
    operation_id = recovery.get("operation_id")
    ledger_entry = recovery.get("attachment_ledger_entry")
    ledger_entry_sha256 = recovery.get("attachment_ledger_entry_sha256")
    attachments_sha256 = recovery.get("product_input_attachments_sha256")
    normalized_original = declarations_tuple(original)
    normalized_attached = declarations_tuple(attached)
    if (
        not is_valid_product_input_attachment_id(attachment_id)
        or type(added_count) is not int
        or not 0 <= added_count <= 100_000
        or type(duplicate_count) is not int
        or not 0 <= duplicate_count <= 100_000
        or type(original_count) is not int
        or original_count != len(normalized_original)
        or type(attached_count) is not int
        or attached_count != len(normalized_attached)
        or recovery.get("attachment_ids") != [attachment_id]
        or type(recovery.get("command")) is not str
        or not recovery["command"]
        or type(operation_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
        or type(recovery.get("product_input_tree_hash")) is not str
        or type(ledger_entry) is not dict
        or type(ledger_entry_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", ledger_entry_sha256) is None
        or _evidence_sha256(ledger_entry) != ledger_entry_sha256
        or type(attachments_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", attachments_sha256) is None
    ):
        raise SpecAddInputError("completed add-input result receipt is invalid")
    return SpecAddInputResult(
        run_dir=run_dir,
        attachment_id=attachment_id,
        added_count=added_count,
        duplicate_count=duplicate_count,
        original_declarations=normalized_original,
        attached_declarations=normalized_attached,
    )


def _authenticate_completed_add_input(
    project_root: Path,
    run_dir: Path,
    state: dict,
    *,
    request_sha256: str,
) -> None:
    recovery = state.get("add_input_recovery")
    product_inputs = state.get("product_inputs")
    if type(recovery) is not dict or type(product_inputs) is not dict:
        raise SpecAddInputError("completed add-input contract is invalid")
    expected_hash = recovery.get("product_input_tree_hash")
    if (
        recovery.get("request_sha256") != request_sha256
        or product_inputs.get("tree_hash") != expected_hash
    ):
        raise SpecAddInputError("completed add-input request identity changed")
    inputs_dir = (run_dir / "inputs").resolve()
    try:
        observed = authenticate_product_input_contract(
            project_root,
            product_inputs,
            inputs_dir,
        )
    except ProductInputMutationError as exc:
        raise SpecAddInputError(str(exc)) from exc
    if observed != expected_hash:
        raise SpecAddInputError("completed add-input postimage changed")
    attached = recovery.get("attached_declarations")
    if type(attached) is not list:
        raise SpecAddInputError("completed add-input declarations are invalid")
    declarations = [
        ProductInputDeclaration(item["role"], item["location"])
        for item in attached
        if type(item) is dict
    ]
    try:
        bound_request = product_input_request_sha256(
            recovery["command"],
            declarations,
        )
    except (KeyError, ProductInputMutationError) as exc:
        raise SpecAddInputError("completed add-input request is invalid") from exc
    if (
        len(declarations) != len(attached)
        or bound_request != request_sha256
    ):
        raise SpecAddInputError("completed add-input declarations changed")
    ledger_path = inputs_dir / "attachment-ledger.json"
    ledger = _load_attachment_ledger(ledger_path)
    attachment_id = recovery["attachment_id"]
    ledger_entry = _exact_attachment_entry(ledger, attachment_id)
    if (
        _canonical_evidence_bytes(ledger_entry)
        != _canonical_evidence_bytes(recovery["attachment_ledger_entry"])
        or _evidence_sha256(ledger_entry)
        != recovery["attachment_ledger_entry_sha256"]
        or ledger_entry.get("command") != recovery["command"]
        or ledger_entry.get("operation_id") != recovery["operation_id"]
    ):
        raise SpecAddInputError("completed add-input attachment ledger entry changed")
    resources = ledger_entry.get("resources")
    duplicates = ledger_entry.get("duplicates")
    if (
        type(resources) is not list
        or len(resources) != recovery["added_count"]
        or type(duplicates) is not list
        or len(duplicates) != recovery["duplicate_count"]
    ):
        raise SpecAddInputError("completed add-input result counts changed")
    summaries = state.get("product_input_attachments")
    if type(summaries) is not list or len(summaries) > 100_000:
        raise SpecAddInputError("completed add-input state attachment summary is invalid")
    try:
        ledger_ref = ledger_path.relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        ledger_ref = str(ledger_path)
    expected_summaries: list[dict[str, object]] = []
    for entry in ledger["attachments"]:
        if type(entry) is not dict:
            raise SpecAddInputError("completed add-input attachment ledger is invalid")
        summary = dict(entry)
        summary["ledger"] = ledger_ref
        expected_summaries.append(summary)
    if (
        _canonical_evidence_bytes(summaries)
        != _canonical_evidence_bytes(expected_summaries)
        or _evidence_sha256(summaries)
        != recovery["product_input_attachments_sha256"]
    ):
        raise SpecAddInputError("completed add-input state attachment summary changed")
    original = recovery.get("original_declarations")
    if (
        _canonical_evidence_bytes(product_inputs.get("declarations"))
        != _canonical_evidence_bytes(original)
    ):
        raise SpecAddInputError("completed add-input original declarations changed")


def _ensure_eligible_state(state: dict) -> None:
    if (
        state.get("status") != "blocked"
        or state.get("phase") != "phase1-investigate"
        or state.get("blocked_reason") != "investigation_access_required"
        or state.get("evidence_resolution_status") != "access_required"
    ):
        raise SpecAddInputError(
            "add-input is only available for a parked investigation access checkpoint"
        )


def _find_current_run_dir(project_root: Path) -> Path | None:
    for base_dir in (project_root / "runs", project_root / "squad"):
        current_file = base_dir / ".current"
        if not current_file.exists():
            continue
        run_id = current_file.read_text(encoding="utf-8").strip()
        if not run_id:
            continue
        run_dir = base_dir / run_id
        if (run_dir / "state.json").is_file():
            return run_dir
    candidates = [
        path
        for base_dir in (project_root / "runs", project_root / "squad")
        if base_dir.exists()
        for path in base_dir.iterdir()
        if path.is_dir() and (path / "state.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path / "state.json").stat().st_mtime)

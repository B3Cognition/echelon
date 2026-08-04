"""Selected-spec graph invalidation and bounded final composition."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from echelon.spec_graph import (
    GRAPH_FILENAME,
    build_spec_graph,
    write_spec_graph,
)
from echelon.spec_graph_audit import (
    GRAPH_AUDIT_FILENAME,
    audit_spec_graph,
    write_spec_graph_audit,
)
from echelon.workspace_graph import (
    build_workspace_graph,
    discover_canonical_spec_dirs,
    workspace_graph_path,
    write_workspace_graph,
)
from echelon.workspace_graph_audit import (
    WORKSPACE_GRAPH_AUDIT_FILENAME,
    WorkspaceGraphAuditReport,
    audit_workspace_graph,
    write_workspace_graph_audit,
)


_CANONICAL_SPEC_ID = re.compile(
    r"^(?:[0-9]{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINDING_IDENTITY = re.compile(
    r"^[a-z][a-z0-9_]*:(?:workspace|[0-9]{3,}-[a-z0-9]+(?:-[a-z0-9]+)*)$"
)
_RECEIPT_KEYS = frozenset(
    {
        "spec_id",
        "spec_status",
        "spec_graph_hash",
        "workspace_status",
        "workspace_graph_hash",
        "workspace_finding_codes",
    }
)
_SPEC_STATUSES = frozenset({"invalidated", "pass", "warn"})
_WORKSPACE_STATUSES = frozenset(
    {"pass", "warn", "fail", "unavailable", "not_applicable_empty_workspace"}
)


class RetargetGraphError(RuntimeError):
    """Raised when retarget graph state cannot be changed safely."""


@dataclass(frozen=True)
class RetargetGraphReceipt:
    spec_id: str
    spec_status: str
    spec_graph_hash: str | None
    workspace_status: str
    workspace_graph_hash: str | None
    workspace_finding_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_receipt(self)

    def to_dict(self) -> dict[str, object]:
        _validate_receipt(self)
        return {
            "spec_id": self.spec_id,
            "spec_status": self.spec_status,
            "spec_graph_hash": self.spec_graph_hash,
            "workspace_status": self.workspace_status,
            "workspace_graph_hash": self.workspace_graph_hash,
            "workspace_finding_codes": list(self.workspace_finding_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RetargetGraphReceipt":
        if type(value) is not dict or frozenset(value) != _RECEIPT_KEYS:
            raise RetargetGraphError("invalid retarget graph receipt keys")
        findings = value["workspace_finding_codes"]
        if type(findings) is not list:
            raise RetargetGraphError("invalid retarget graph finding identities")
        return cls(
            spec_id=_require_string(value["spec_id"], "spec_id"),
            spec_status=_require_string(value["spec_status"], "spec_status"),
            spec_graph_hash=_require_optional_string(
                value["spec_graph_hash"], "spec_graph_hash"
            ),
            workspace_status=_require_string(
                value["workspace_status"], "workspace_status"
            ),
            workspace_graph_hash=_require_optional_string(
                value["workspace_graph_hash"], "workspace_graph_hash"
            ),
            workspace_finding_codes=tuple(
                _require_string(item, "workspace_finding_codes")
                for item in findings
            ),
        )


def invalidate_retarget_graphs(
    project_root: Path,
    spec_dir: Path,
) -> RetargetGraphReceipt:
    """Invalidate one selected member and compose only remaining persisted graphs."""
    try:
        root, selected = _validate_scope(project_root, spec_dir)
        spec_path = selected / "spec.md"
        if os.path.lexists(spec_path):
            raise RetargetGraphError(
                "selected canonical spec.md must already be absent before graph invalidation"
            )

        selected_graph = selected / GRAPH_FILENAME
        selected_audit = selected / GRAPH_AUDIT_FILENAME
        workspace_graph = workspace_graph_path(root)
        workspace_audit = workspace_graph.with_name(WORKSPACE_GRAPH_AUDIT_FILENAME)
        for target in (
            selected_graph,
            selected_audit,
            workspace_graph,
            workspace_audit,
        ):
            _validate_optional_regular_target(root, target)

        remaining = discover_canonical_spec_dirs(root)
        if any(path.resolve() == selected for path in remaining):
            raise RetargetGraphError("selected spec remained canonical during invalidation")

        candidate = None
        audit = None
        if remaining:
            candidate = build_workspace_graph(root)
            audit = audit_workspace_graph(root, candidate=candidate)

        _unlink_outputs((selected_graph, selected_audit))
        if candidate is None or audit is None:
            _unlink_outputs((workspace_graph, workspace_audit))
            return RetargetGraphReceipt(
                selected.name,
                "invalidated",
                None,
                "not_applicable_empty_workspace",
                None,
                (),
            )

        _unlink_outputs((workspace_audit,))
        path = write_workspace_graph(candidate.graph, root)
        _ensure_workspace_publication(path, audit)
        write_workspace_graph_audit(audit, root)
        return _workspace_receipt(selected.name, "invalidated", None, path, audit)
    except RetargetGraphError:
        raise
    except Exception as exc:
        raise RetargetGraphError(
            f"retarget graph invalidation failed: {type(exc).__name__}: {exc}"
        ) from exc


def finalize_retarget_graphs(
    project_root: Path,
    spec_dir: Path,
    baseline: RetargetGraphReceipt,
) -> RetargetGraphReceipt:
    """Publish the selected member, then compose and audit its workspace graph."""
    try:
        root, selected = _validate_scope(project_root, spec_dir)
        if type(baseline) is not RetargetGraphReceipt:
            raise RetargetGraphError("invalid retarget graph baseline receipt")
        _validate_receipt(baseline)
        if baseline.spec_id != selected.name or baseline.spec_status != "invalidated":
            raise RetargetGraphError("retarget graph baseline does not match selected spec")
        spec_path = selected / "spec.md"
        try:
            spec_metadata = spec_path.lstat()
        except FileNotFoundError as exc:
            raise RetargetGraphError(
                "replacement canonical spec.md must exist before graph finalization"
            ) from exc
        if not stat.S_ISREG(spec_metadata.st_mode):
            raise RetargetGraphError("replacement canonical spec.md must be a regular file")

        selected_graph = selected / GRAPH_FILENAME
        selected_audit_path = selected / GRAPH_AUDIT_FILENAME
        workspace_graph = workspace_graph_path(root)
        workspace_audit_path = workspace_graph.with_name(WORKSPACE_GRAPH_AUDIT_FILENAME)
        for target in (
            selected_graph,
            selected_audit_path,
            workspace_graph,
            workspace_audit_path,
        ):
            _validate_optional_regular_target(root, target)

        graph = build_spec_graph(root, selected)
        _unlink_outputs((selected_audit_path,))
        written_spec_path = write_spec_graph(graph, selected)
        spec_audit = audit_spec_graph(root, selected)
        write_spec_graph_audit(spec_audit, selected)
        spec_graph_hash = _sha256(written_spec_path.read_bytes())
        if (
            spec_audit.spec_id != selected.name
            or spec_audit.status not in {"pass", "warn"}
            or spec_audit.graph_hash != spec_graph_hash
        ):
            raise RetargetGraphError("selected spec graph audit failed")

        candidate = build_workspace_graph(root)
        selected_member = next(
            (
                member
                for member in candidate.graph.members
                if member.spec_id == selected.name
            ),
            None,
        )
        if (
            selected_member is None
            or not selected_member.included
            or selected_member.graph_hash != spec_graph_hash
            or selected_member.audit_status not in {"pass", "warn"}
        ):
            raise RetargetGraphError(
                "selected spec is not a current included workspace member"
            )

        _unlink_outputs((workspace_audit_path,))
        written_workspace_path = write_workspace_graph(candidate.graph, root)
        workspace_audit = audit_workspace_graph(root, candidate=candidate)
        _ensure_workspace_publication(written_workspace_path, workspace_audit)
        write_workspace_graph_audit(workspace_audit, root)
        _reject_retarget_attributable_findings(
            workspace_audit,
            baseline,
            selected.name,
        )
        return _workspace_receipt(
            selected.name,
            spec_audit.status,
            spec_graph_hash,
            written_workspace_path,
            workspace_audit,
        )
    except RetargetGraphError:
        raise
    except Exception as exc:
        raise RetargetGraphError(
            f"retarget graph finalization failed: {type(exc).__name__}: {exc}"
        ) from exc


def _validate_receipt(receipt: RetargetGraphReceipt) -> None:
    if (
        type(receipt.spec_id) is not str
        or _CANONICAL_SPEC_ID.fullmatch(receipt.spec_id) is None
    ):
        raise RetargetGraphError("invalid retarget graph spec_id")
    if type(receipt.spec_status) is not str or receipt.spec_status not in _SPEC_STATUSES:
        raise RetargetGraphError("invalid retarget graph spec_status")
    _validate_hash(receipt.spec_graph_hash, "spec_graph_hash")
    if (
        type(receipt.workspace_status) is not str
        or receipt.workspace_status not in _WORKSPACE_STATUSES
    ):
        raise RetargetGraphError("invalid retarget graph workspace_status")
    _validate_hash(receipt.workspace_graph_hash, "workspace_graph_hash")
    if type(receipt.workspace_finding_codes) is not tuple:
        raise RetargetGraphError("invalid retarget graph finding identities")
    for identity in receipt.workspace_finding_codes:
        if type(identity) is not str or _FINDING_IDENTITY.fullmatch(identity) is None:
            raise RetargetGraphError("invalid retarget graph finding identity")
    if tuple(sorted(set(receipt.workspace_finding_codes))) != (
        receipt.workspace_finding_codes
    ):
        raise RetargetGraphError(
            "retarget graph finding identities must be sorted and unique"
        )
    if receipt.spec_status == "invalidated":
        if receipt.spec_graph_hash is not None:
            raise RetargetGraphError("invalidated spec graph hash must be null")
    elif receipt.spec_graph_hash is None:
        raise RetargetGraphError("current spec graph hash is required")
    if receipt.workspace_status == "not_applicable_empty_workspace":
        if receipt.workspace_graph_hash is not None or receipt.workspace_finding_codes:
            raise RetargetGraphError("empty workspace receipt must not contain graph state")
    elif receipt.workspace_graph_hash is None:
        raise RetargetGraphError("workspace graph hash is required")


def _validate_hash(value: object, field: str) -> None:
    if value is not None and (
        type(value) is not str or _SHA256.fullmatch(value) is None
    ):
        raise RetargetGraphError(f"invalid retarget graph {field}")


def _require_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise RetargetGraphError(f"invalid retarget graph {field}")
    return value


def _require_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _validate_scope(project_root: Path, spec_dir: Path) -> tuple[Path, Path]:
    raw_root = Path(project_root)
    raw_spec = Path(spec_dir)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise RetargetGraphError("project root must be a real directory")
    root = raw_root.resolve()
    specs_root = root / "specs"
    if specs_root.is_symlink() or not specs_root.is_dir():
        raise RetargetGraphError("canonical specs root must be a real directory")
    if raw_spec.is_symlink() or not raw_spec.is_dir():
        raise RetargetGraphError("selected spec directory must be a real directory")
    selected = raw_spec.resolve()
    if selected.parent != specs_root or _CANONICAL_SPEC_ID.fullmatch(selected.name) is None:
        raise RetargetGraphError("selected spec directory is outside canonical specs")
    return root, selected


def _validate_optional_regular_target(root: Path, path: Path) -> None:
    resolved_parent = path.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise RetargetGraphError("graph target escapes project root") from exc
    current = root
    relative_parent = path.parent.relative_to(root)
    for part in relative_parent.parts:
        current /= part
        if os.path.lexists(current) and (
            current.is_symlink() or not current.is_dir()
        ):
            raise RetargetGraphError("graph target parent must be a real directory")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise RetargetGraphError("graph target must be a regular file")


def _unlink_outputs(paths: tuple[Path, ...]) -> None:
    for path in paths:
        unlink_error: OSError | None = None
        deleted = False
        try:
            path.unlink()
            deleted = True
        except FileNotFoundError:
            pass
        except OSError as exc:
            unlink_error = exc
        if not deleted and unlink_error is None:
            try:
                path.parent.lstat()
            except FileNotFoundError:
                continue
        try:
            _fsync_directory(path.parent)
        except OSError:
            if unlink_error is not None:
                raise unlink_error
            raise
        if unlink_error is not None:
            raise unlink_error


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _finding_identity(code: str, subject_id: str | None) -> str:
    subject = subject_id.removeprefix("spec:") if subject_id else "workspace"
    identity = f"{code}:{subject}"
    if _FINDING_IDENTITY.fullmatch(identity) is None:
        raise RetargetGraphError("workspace audit returned an invalid finding identity")
    return identity


def _reject_retarget_attributable_findings(
    audit: WorkspaceGraphAuditReport,
    baseline: RetargetGraphReceipt,
    selected_spec_id: str,
) -> None:
    baseline_identities = set(baseline.workspace_finding_codes)
    selected_subject = f"spec:{selected_spec_id}"
    for finding in audit.findings:
        if finding.severity != "error":
            continue
        identity = _finding_identity(finding.code, finding.subject_id)
        if finding.subject_id == selected_subject:
            raise RetargetGraphError(
                f"selected spec workspace graph error: {identity}"
            )
        if identity not in baseline_identities:
            raise RetargetGraphError(f"new workspace graph error: {identity}")
        if (
            finding.subject_id is None
            or not finding.subject_id.startswith("spec:")
        ):
            raise RetargetGraphError(
                f"workspace graph error is not attributable to another spec: {identity}"
            )


def _workspace_receipt(
    spec_id: str,
    spec_status: str,
    spec_graph_hash: str | None,
    path: Path,
    audit: WorkspaceGraphAuditReport,
) -> RetargetGraphReceipt:
    graph_hash = _sha256(path.read_bytes())
    findings = tuple(
        sorted(
            {
                _finding_identity(finding.code, finding.subject_id)
                for finding in audit.findings
            }
        )
    )
    return RetargetGraphReceipt(
        spec_id,
        spec_status,
        spec_graph_hash,
        audit.status,
        graph_hash,
        findings,
    )


def _ensure_workspace_publication(
    path: Path,
    audit: WorkspaceGraphAuditReport,
) -> None:
    actual_hash = _sha256(path.read_bytes())
    if audit.graph_hash != actual_hash:
        raise RetargetGraphError("workspace graph publication does not match audit")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"

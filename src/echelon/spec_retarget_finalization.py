"""Sealed completion effect for one destructive spec retarget."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.mempalace_retarget import (
    RetargetMemoryReceipt,
    _configured_mempalace_wing,
    refresh_retarget_spec_memory,
)
from echelon.mempalace_audit import audit_spec_memory
from echelon.spec_graph import GRAPH_FILENAME
from echelon.spec_graph_audit import audit_spec_graph
from echelon.spec_retarget_graph import RetargetGraphReceipt, finalize_retarget_graphs
from echelon.workspace_graph import workspace_graph_path
from echelon.workspace_graph_audit import audit_workspace_graph
from echelon.spec_retarget_history import (
    advance_retarget_revision,
    bind_completed_revision_commit,
    load_retarget_history,
)
from harness.phase_checkpoints import _commit_spec_changes
from harness.squad_completion import PreparedControllerCompletion


_RECEIPT_KEYS = frozenset(
    {
        "revision_id",
        "completion_id",
        "checkpoint_commit",
        "replacement_targets",
        "memory",
        "graph",
        "replacement_commit",
        "status",
    }
)
_PROGRESS_NAME = "retarget-progress.json"
_PROGRESS_CAP = 1_048_576
_GIT_OID = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_COMPLETION_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_TRAILER = re.compile(r"\A([A-Za-z0-9-]+): ([^\n]+)\Z")
_MEMORY_REPORTS = (
    "mempalace-audit.json",
    "mempalace-audit.md",
    "mempalace-mine.json",
)


class RetargetFinalizationError(RuntimeError):
    """The sealed retarget completion effect cannot be proven."""


def _validated_memory_receipt(value: object) -> RetargetMemoryReceipt:
    if type(value) is not dict or frozenset(value) != frozenset(
        RetargetMemoryReceipt.__dataclass_fields__
    ):
        raise RetargetFinalizationError("retarget finalization memory receipt is invalid")
    fields = dict(value)
    for name in (
        "deleted_ids",
        "remaining_owned_ids",
        "unrelated_missing_ids",
        "unrelated_changed_ids",
        "unexpected_added_ids",
    ):
        if type(fields[name]) is not list:
            raise RetargetFinalizationError("retarget finalization memory receipt is invalid")
        fields[name] = tuple(fields[name])
    try:
        return RetargetMemoryReceipt(**fields)
    except (TypeError, ValueError) as exc:
        raise RetargetFinalizationError("retarget finalization memory receipt is invalid") from exc


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _current_memory_report_records(spec_dir: Path) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for name in _MEMORY_REPORTS:
        content = (spec_dir / name).read_bytes()
        files.append(
            {
                "path": name,
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    return files


def _current_memory_report_set_digest(spec_dir: Path) -> str:
    files = _current_memory_report_records(spec_dir)
    encoded = json.dumps(
        files,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _empty_drawer_set_digest() -> str:
    return "sha256:" + hashlib.sha256(b"[]").hexdigest()


def _require_terminal_memory_receipt(
    receipt: RetargetMemoryReceipt,
    *,
    spec_id: str,
) -> None:
    if receipt.spec_id != spec_id:
        raise RetargetFinalizationError(
            "retarget finalization memory postimage drifted"
        )
    if receipt.status == "not_applicable":
        if (
            receipt.deleted_count != 0
            or receipt.deleted_ids
            or receipt.drawer_set_digest != _empty_drawer_set_digest()
            or receipt.mine_status != "not_applicable"
            or receipt.audit_status != "not_applicable"
            or receipt.adapter is not None
            or receipt.wing is not None
            or receipt.palace_path is not None
            or receipt.scanned_count != 0
            or receipt.delete_acknowledged_count is not None
            or receipt.remaining_owned_ids
            or receipt.unrelated_missing_ids
            or receipt.unrelated_changed_ids
            or receipt.unexpected_added_ids
            or receipt.report_set_digest is not None
            or receipt.failure_code is not None
        ):
            raise RetargetFinalizationError(
                "retarget finalization memory postimage drifted"
            )
        return
    if (
        receipt.status != "pass"
        or receipt.mine_status != "complete"
        or receipt.audit_status not in {"pass", "warn"}
        or not receipt.adapter
        or not receipt.wing
        or not receipt.palace_path
        or receipt.scanned_count != 0
        or receipt.delete_acknowledged_count is not None
        or receipt.remaining_owned_ids
        or receipt.unrelated_missing_ids
        or receipt.unrelated_changed_ids
        or receipt.unexpected_added_ids
        or receipt.report_set_digest is None
        or receipt.failure_code is not None
    ):
        raise RetargetFinalizationError(
            "retarget finalization memory postimage drifted"
        )


def verify_retarget_memory_postimage(
    project_root: Path,
    spec_dir: Path,
    receipt: RetargetMemoryReceipt,
) -> None:
    """Read current memory/audit evidence without mining or deleting drawers."""
    try:
        _require_terminal_memory_receipt(receipt, spec_id=spec_dir.name)
        configured_wing = _configured_mempalace_wing(project_root)
        if receipt.status == "not_applicable":
            if configured_wing is not None:
                raise ValueError
            return
        if configured_wing != receipt.wing:
            raise ValueError
        audit = audit_spec_memory(project_root, spec_dir, probe_retrieval=True)
        mine = json.loads(
            (spec_dir / "mempalace-mine.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (spec_dir / "mempalace-refresh-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        drawer_ids = mine.get("drawer_ids") if type(mine) is dict else None
        expected_ids = (
            mine.get("expected_drawer_ids") if type(mine) is dict else None
        )
        mine_count_fields = (
            "expected_count",
            "written_count",
            "adopted_count",
            "skipped_count",
            "failed_count",
            "drifted_count",
            "unavailable_count",
        )
        if (
            type(drawer_ids) is not list
            or type(expected_ids) is not list
            or drawer_ids != expected_ids
            or any(type(value) is not str or not value for value in drawer_ids)
            or drawer_ids != sorted(set(drawer_ids))
            or any(type(mine.get(field)) is not int for field in mine_count_fields)
            or mine.get("spec_id") != receipt.spec_id
            or mine.get("status") != receipt.mine_status
            or mine.get("wing") != receipt.wing
            or mine.get("palace_path") != receipt.palace_path
            or mine.get("expected_count") != len(drawer_ids)
            or mine.get("written_count", 0) + mine.get("adopted_count", 0)
            != len(drawer_ids)
            or any(
                mine.get(field) != 0
                for field in (
                    "skipped_count",
                    "failed_count",
                    "drifted_count",
                    "unavailable_count",
                )
            )
            or mine.get("errors") != []
        ):
            raise ValueError
        digest = "sha256:" + hashlib.sha256(
            json.dumps(
                drawer_ids,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        audit_anomalies = (
            "missing",
            "stale",
            "wrong_wing",
            "wrong_room",
            "duplicate",
            "non_canonical",
            "lifecycle_excluded",
            "errors",
        )
        if (
            digest != receipt.drawer_set_digest
            or getattr(audit, "spec_id", None) != receipt.spec_id
            or getattr(audit, "status", None) != receipt.audit_status
            or getattr(audit, "wing", None) != receipt.wing
            or getattr(audit, "palace_path", None) != receipt.palace_path
            or type(getattr(audit, "expected_count", None)) is not int
            or type(getattr(audit, "present_current_count", None)) is not int
            or getattr(audit, "expected_count", None) != len(drawer_ids)
            or getattr(audit, "present_current_count", None) != len(drawer_ids)
            or any(getattr(audit, field, None) != [] for field in audit_anomalies)
            or _current_memory_report_set_digest(spec_dir)
            != receipt.report_set_digest
            or type(manifest) is not dict
            or frozenset(manifest)
            != {"schema_version", "spec_id", "files", "report_set_digest"}
            or manifest.get("schema_version") != 1
            or manifest.get("spec_id") != receipt.spec_id
            or manifest.get("files") != _current_memory_report_records(spec_dir)
            or manifest.get("report_set_digest") != receipt.report_set_digest
        ):
            raise ValueError
    except RetargetFinalizationError:
        raise
    except (Exception, SystemExit) as exc:
        raise RetargetFinalizationError(
            "retarget finalization memory postimage drifted"
        ) from exc


def verify_retarget_graph_postimage(
    project_root: Path,
    spec_dir: Path,
    receipt: RetargetGraphReceipt,
) -> None:
    """Read graph bytes and current audits without publishing graph output."""
    try:
        if (
            receipt.spec_id != spec_dir.name
            or receipt.spec_status not in {"pass", "warn"}
            or receipt.workspace_status not in {"pass", "warn"}
            or receipt.spec_graph_hash is None
            or receipt.workspace_graph_hash is None
        ):
            raise RetargetFinalizationError(
                "retarget finalization graph receipt is not terminal"
            )
        if receipt.spec_graph_hash is not None:
            graph_path = spec_dir / GRAPH_FILENAME
            if _sha256_file(graph_path) != receipt.spec_graph_hash:
                raise ValueError
            spec_audit = audit_spec_graph(project_root, spec_dir)
            if (
                spec_audit.spec_id != receipt.spec_id
                or spec_audit.graph_hash != receipt.spec_graph_hash
                or spec_audit.status != receipt.spec_status
                or spec_audit.status not in {"pass", "warn"}
            ):
                raise ValueError
        if receipt.workspace_graph_hash is not None:
            workspace = workspace_graph_path(project_root)
            if _sha256_file(workspace) != receipt.workspace_graph_hash:
                raise ValueError
            workspace_audit = audit_workspace_graph(project_root)
            selected = next(
                (
                    member
                    for member in workspace_audit.members
                    if member.spec_id == receipt.spec_id
                ),
                None,
            )
            findings = tuple(
                sorted(
                    f"{finding.code}:{finding.subject_id or 'workspace'}"
                    for finding in workspace_audit.findings
                )
            )
            if (
                workspace_audit.graph_hash != receipt.workspace_graph_hash
                or workspace_audit.status != receipt.workspace_status
                or workspace_audit.status not in {"pass", "warn"}
                or findings != receipt.workspace_finding_codes
                or selected is None
                or not selected.included
                or selected.graph_hash != receipt.spec_graph_hash
                or selected.audit_status != receipt.spec_status
            ):
                raise ValueError
    except RetargetFinalizationError:
        raise
    except (Exception, SystemExit) as exc:
        raise RetargetFinalizationError(
            "retarget finalization graph postimage drifted"
        ) from exc


def require_finalizing_retarget(state: Mapping[str, object]) -> dict[str, object]:
    retarget = state.get("retarget")
    if type(retarget) is not dict or retarget.get("status") != "finalizing":
        raise RetargetFinalizationError("retarget is not finalizing")
    required = (
        "revision_id",
        "checkpoint_commit",
        "replacement_targets",
        "replacement_run_id",
        "baseline_run_id",
        "graph_invalidation",
    )
    if any(key not in retarget for key in required):
        raise RetargetFinalizationError("retarget finalization contract is incomplete")
    if (
        type(retarget["revision_id"]) is not str
        or type(retarget["checkpoint_commit"]) is not str
        or type(retarget["replacement_run_id"]) is not str
        or type(retarget["baseline_run_id"]) is not str
        or type(retarget["replacement_targets"]) is not list
        or not retarget["replacement_targets"]
        or any(type(value) is not str or not value for value in retarget["replacement_targets"])
        or type(retarget["graph_invalidation"]) is not dict
    ):
        raise RetargetFinalizationError("retarget finalization contract is invalid")
    return dict(retarget)


def validate_finalization_receipt(value: object) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != _RECEIPT_KEYS:
        raise RetargetFinalizationError("retarget finalization receipt is invalid")
    if (
        type(value["revision_id"]) is not str
        or type(value["completion_id"]) is not str
        or _COMPLETION_ID.fullmatch(value["completion_id"]) is None
        or type(value["checkpoint_commit"]) is not str
        or _GIT_OID.fullmatch(value["checkpoint_commit"]) is None
        or type(value["replacement_commit"]) is not str
        or _GIT_OID.fullmatch(value["replacement_commit"]) is None
        or type(value["replacement_targets"]) is not list
        or not value["replacement_targets"]
        or any(type(item) is not str or not item for item in value["replacement_targets"])
        or type(value["memory"]) is not dict
        or type(value["graph"]) is not dict
        or value["status"] != "complete"
    ):
        raise RetargetFinalizationError("retarget finalization receipt is invalid")
    _validated_memory_receipt(value["memory"])
    try:
        RetargetGraphReceipt.from_dict(value["graph"])
    except Exception as exc:
        raise RetargetFinalizationError("retarget finalization receipt graph is invalid") from exc
    return dict(value)


def load_retarget_effect_progress(
    prepared: PreparedControllerCompletion,
) -> dict[str, dict[str, object] | None]:
    """Load effect progress only when it is sealed to this completion attempt."""
    path = prepared._transaction_root / _PROGRESS_NAME
    if not path.exists():
        return {"memory": None, "graph": None}
    try:
        if path.is_symlink() or path.stat().st_size > _PROGRESS_CAP:
            raise ValueError
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RetargetFinalizationError("retarget finalization progress is corrupt") from exc
    if (
        type(progress) is not dict
        or frozenset(progress) != {"completion_id", "memory", "graph"}
        or progress.get("completion_id") != prepared.intent.completion_id
        or progress.get("memory") is not None and type(progress["memory"]) is not dict
        or progress.get("graph") is not None and type(progress["graph"]) is not dict
        or progress.get("graph") is not None and progress.get("memory") is None
    ):
        raise RetargetFinalizationError("retarget finalization progress is corrupt")
    memory = progress["memory"]
    graph = progress["graph"]
    if memory is not None:
        _validated_memory_receipt(memory)
    if graph is not None:
        try:
            RetargetGraphReceipt.from_dict(graph)
        except Exception as exc:
            raise RetargetFinalizationError(
                "retarget finalization progress is corrupt"
            ) from exc
    return {"memory": memory, "graph": graph}


def persist_retarget_effect_progress(
    prepared: PreparedControllerCompletion,
    step: str,
    receipt: Mapping[str, object],
) -> None:
    """Durably checkpoint one private effect step under the sealed completion ID."""
    if step not in {"memory", "graph"} or type(receipt) is not dict:
        raise RetargetFinalizationError("retarget finalization progress is invalid")
    path = prepared._transaction_root / _PROGRESS_NAME
    existing: dict[str, object] = {
        "completion_id": prepared.intent.completion_id,
        "memory": None,
        "graph": None,
    }
    if path.exists():
        try:
            if path.is_symlink() or path.stat().st_size > _PROGRESS_CAP:
                raise ValueError
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RetargetFinalizationError("retarget finalization progress is corrupt") from exc
        if (
            type(existing) is not dict
            or frozenset(existing) != {"completion_id", "memory", "graph"}
            or existing.get("completion_id") != prepared.intent.completion_id
        ):
            raise RetargetFinalizationError("retarget finalization progress is corrupt")
    current = existing.get(step)
    if current is not None and current != receipt:
        raise RetargetFinalizationError("retarget finalization progress drifted")
    existing[step] = dict(receipt)
    content = (json.dumps(existing, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(content) > _PROGRESS_CAP:
        raise RetargetFinalizationError("retarget finalization progress exceeds cap")
    temporary = path.with_name(f".{path.name}.{prepared.intent.completion_id}.tmp")
    try:
        metadata = os.lstat(temporary)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RetargetFinalizationError("retarget finalization progress is corrupt") from exc
    else:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RetargetFinalizationError("retarget finalization progress is corrupt")
        try:
            temporary.unlink()
        except OSError as exc:
            raise RetargetFinalizationError("retarget finalization progress is corrupt") from exc
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("retarget finalization progress write failed")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _published_spec_dir(project_root: Path, state: Mapping[str, object]) -> Path:
    spec_id = state.get("spec_id")
    published = state.get("published_spec_dir")
    if type(spec_id) is not str or not spec_id:
        raise RetargetFinalizationError("retarget finalization spec identity is invalid")
    expected = Path(project_root).resolve() / "specs" / spec_id
    if published is not None and published != str(expected.relative_to(project_root)):
        raise RetargetFinalizationError("retarget published spec directory drifted")
    if not expected.is_dir() or expected.is_symlink():
        raise RetargetFinalizationError("retarget published spec directory is unavailable")
    return expected


def _commit_retarget_completion(
    project_root: Path,
    spec_dir: Path,
    retarget: Mapping[str, object],
    completion_id: str,
) -> str:
    message = build_echelon_commit_message(
        "chore: finalize retargeted spec",
        EchelonCommitMetadata(
            origin="phase-a",
            action="retarget-complete",
            spec_id=spec_dir.name,
            run_id=str(retarget["replacement_run_id"]),
            completion_id=completion_id,
            checkpoint_id=str(
                retarget.get("checkpoint_id") or retarget["checkpoint_commit"]
            ),
            retarget_revision=str(retarget["revision_id"]),
            baseline_run_id=str(retarget["baseline_run_id"]),
            replacement_run_id=str(retarget["replacement_run_id"]),
        ),
    )
    commit = _commit_spec_changes(project_root, (spec_dir,), message)
    if commit is None:
        raise RetargetFinalizationError("retarget completion produced no owned commit")
    return commit


def _find_retarget_completion_commit(
    project_root: Path,
    spec_dir: Path,
    retarget: Mapping[str, object],
    completion_id: str,
) -> str | None:
    """Return the one already-created completion commit for this sealed effect."""
    commits = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "--fixed-strings",
            f"--grep=Echelon-Completion: {completion_id}",
            "--format=%H",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commits.returncode != 0:
        raise RetargetFinalizationError("retarget completion history is unavailable")
    identity = _retarget_completion_identity(spec_dir, retarget, completion_id)
    prefix = f"specs/{spec_dir.name}/"
    matches: list[str] = []
    for commit in tuple(line for line in commits.stdout.splitlines() if line):
        message = subprocess.run(
            ["git", "show", "-s", "--format=%B", commit],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        paths = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        changed = tuple(line for line in paths.stdout.splitlines() if line)
        if (
            message.returncode == 0
            and paths.returncode == 0
            and _exact_trailers_match(message.stdout, identity)
            and changed
            and all(path.startswith(prefix) for path in changed)
        ):
            matches.append(commit)
    if len(matches) > 1:
        raise RetargetFinalizationError("duplicate retarget completion commits")
    return matches[0] if matches else None


def _retarget_completion_identity(
    spec_dir: Path,
    retarget: Mapping[str, object],
    completion_id: str,
) -> dict[str, str]:
    return {
        "Echelon-Origin": "phase-a",
        "Echelon-Action": "retarget-complete",
        "Echelon-Spec": spec_dir.name,
        "Echelon-Run": str(retarget["replacement_run_id"]),
        "Echelon-Checkpoint": str(
            retarget.get("checkpoint_id") or retarget["checkpoint_commit"]
        ),
        "Echelon-Completion": completion_id,
        "Echelon-Retarget-Revision": str(retarget["revision_id"]),
        "Echelon-Baseline-Run": str(retarget["baseline_run_id"]),
        "Echelon-Replacement-Run": str(retarget["replacement_run_id"]),
    }


def _exact_trailers_match(message: str, identity: Mapping[str, str]) -> bool:
    values: dict[str, list[str]] = {}
    for line in message.splitlines():
        match = _TRAILER.fullmatch(line)
        if match is not None and match.group(1).startswith("Echelon-"):
            values.setdefault(match.group(1), []).append(match.group(2))
    return (
        frozenset(values) == frozenset(identity)
        and all(values.get(key) == [value] for key, value in identity.items())
    )


def _advance_or_verify_retarget_history(
    spec_dir: Path,
    retarget: Mapping[str, object],
    memory: RetargetMemoryReceipt,
    graph: RetargetGraphReceipt,
) -> str:
    """Advance once, or prove a completed history is the same sealed result."""
    history = load_retarget_history(spec_dir)
    if not history.revisions or history.revisions[-1].revision_id != retarget["revision_id"]:
        raise RetargetFinalizationError("retarget finalization history drifted")
    revision = history.revisions[-1]
    memory_receipt = memory.to_dict()
    graph_receipt = graph.to_dict()
    if revision.status == "finalizing":
        revision = advance_retarget_revision(
            spec_dir,
            str(retarget["revision_id"]),
            expected_status="finalizing",
            status="complete",
            updates={
                "memory_finalization": memory_receipt,
                "graph_finalization": graph_receipt,
            },
        )
    if (
        revision.status != "complete"
        or revision.memory_finalization != memory_receipt
        or revision.graph_finalization != graph_receipt
    ):
        raise RetargetFinalizationError("retarget finalization history drifted")
    return revision.revision_id


def verify_retarget_finalization_receipt(
    project_root: Path,
    state: Mapping[str, object],
    receipt: object,
) -> dict[str, object]:
    checked = validate_finalization_receipt(receipt)
    retarget = state.get("retarget")
    if type(retarget) is not dict:
        raise RetargetFinalizationError("retarget runtime state is unavailable")
    if (
        checked["revision_id"] != retarget.get("revision_id")
        or checked["checkpoint_commit"] != retarget.get("checkpoint_commit")
        or checked["replacement_targets"] != retarget.get("replacement_targets")
    ):
        raise RetargetFinalizationError("retarget finalization receipt drifted")
    spec_dir = _published_spec_dir(project_root, state)
    verify_retarget_memory_postimage(
        project_root,
        spec_dir,
        _validated_memory_receipt(checked["memory"]),
    )
    verify_retarget_graph_postimage(
        project_root,
        spec_dir,
        RetargetGraphReceipt.from_dict(checked["graph"]),
    )
    history = load_retarget_history(spec_dir)
    if not history.revisions or history.revisions[-1].revision_id != checked["revision_id"]:
        raise RetargetFinalizationError("retarget finalization history drifted")
    revision = history.revisions[-1]
    commit = str(checked["replacement_commit"])
    if (
        revision.status != "complete"
        or revision.replacement_commit != commit
        or revision.memory_finalization != checked["memory"]
        or revision.graph_finalization != checked["graph"]
    ):
        raise RetargetFinalizationError("retarget finalization history is incomplete")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    message = subprocess.run(
        ["git", "show", "-s", "--format=%B", commit],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    paths = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    committed_history = subprocess.run(
        ["git", "show", f"{commit}:specs/{spec_dir.name}/retarget-history.json"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
    )
    worktree = subprocess.run(
        ["git", "diff", "--quiet", commit, "--", f"specs/{spec_dir.name}"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", f"specs/{spec_dir.name}"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    prefix = f"specs/{spec_dir.name}/"
    identity = _retarget_completion_identity(
        spec_dir,
        retarget,
        str(checked["completion_id"]),
    )
    changed = tuple(line for line in paths.stdout.splitlines() if line)
    if (
        resolved.returncode != 0
        or resolved.stdout.strip() != commit
        or message.returncode != 0
        or paths.returncode != 0
        or committed_history.returncode != 0
        or committed_history.stdout != (spec_dir / "retarget-history.json").read_bytes()
        or worktree.returncode != 0
        or untracked.returncode != 0
        or bool(untracked.stdout.strip())
        or not changed
        or any(not path.startswith(prefix) for path in changed)
        or not _exact_trailers_match(message.stdout, identity)
    ):
        raise RetargetFinalizationError("retarget completion commit cannot be verified")
    return checked


def apply_or_verify_retarget_finalization(
    prepared: PreparedControllerCompletion,
    *,
    project_root: Path,
    state: Mapping[str, object],
    expected_receipt: object,
) -> dict[str, object]:
    """Run memory then graph finalization, sealing one receipt through completion."""

    if expected_receipt is not None:
        if (
            type(expected_receipt) is not dict
            or expected_receipt.get("completion_id")
            != prepared.intent.completion_id
        ):
            raise RetargetFinalizationError("retarget finalization receipt drifted")
        return verify_retarget_finalization_receipt(project_root, state, expected_receipt)
    retarget = require_finalizing_retarget(state)
    spec_dir = _published_spec_dir(project_root, state)
    progress = load_retarget_effect_progress(prepared)
    if progress["memory"] is None:
        memory = refresh_retarget_spec_memory(project_root, spec_dir)
        persist_retarget_effect_progress(prepared, "memory", memory.to_dict())
    else:
        memory = _validated_memory_receipt(progress["memory"])
        verify_retarget_memory_postimage(project_root, spec_dir, memory)
    if progress["graph"] is None:
        graph = finalize_retarget_graphs(
            project_root,
            spec_dir,
            RetargetGraphReceipt.from_dict(retarget["graph_invalidation"]),
        )
        persist_retarget_effect_progress(prepared, "graph", graph.to_dict())
    else:
        graph = RetargetGraphReceipt.from_dict(progress["graph"])
        verify_retarget_graph_postimage(project_root, spec_dir, graph)
    revision_id = _advance_or_verify_retarget_history(
        spec_dir,
        retarget,
        memory,
        graph,
    )
    root = Path(project_root).resolve()
    commit = _find_retarget_completion_commit(
        root,
        spec_dir,
        retarget,
        prepared.intent.completion_id,
    )
    if commit is None:
        commit = _commit_retarget_completion(
            root,
            spec_dir,
            retarget,
            prepared.intent.completion_id,
        )
    bind_completed_revision_commit(
        spec_dir,
        revision_id,
        replacement_commit=commit,
    )
    receipt = {
        "revision_id": revision_id,
        "completion_id": prepared.intent.completion_id,
        "checkpoint_commit": str(retarget["checkpoint_commit"]),
        "replacement_targets": list(retarget["replacement_targets"]),
        "memory": memory.to_dict(),
        "graph": graph.to_dict(),
        "replacement_commit": commit,
        "status": "complete",
    }
    return validate_finalization_receipt(receipt)

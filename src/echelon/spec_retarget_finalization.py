"""Sealed completion effect for one destructive spec retarget."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.mempalace_retarget import RetargetMemoryReceipt, refresh_retarget_spec_memory
from echelon.spec_retarget_graph import RetargetGraphReceipt, finalize_retarget_graphs
from echelon.spec_retarget_history import advance_retarget_revision, load_retarget_history
from harness.phase_checkpoints import _commit_spec_changes
from harness.squad_completion import PreparedControllerCompletion


_RECEIPT_KEYS = frozenset(
    {
        "revision_id",
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
        or type(value["checkpoint_commit"]) is not str
        or type(value["replacement_commit"]) is not str
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
        ["git", "log", "--all", "--max-count=256", "--format=%H"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commits.returncode != 0:
        raise RetargetFinalizationError("retarget completion history is unavailable")
    identity = (
        "Echelon-Action: retarget-complete",
        f"Echelon-Completion: {completion_id}",
        f"Echelon-Retarget-Revision: {retarget['revision_id']}",
        f"Echelon-Baseline-Run: {retarget['baseline_run_id']}",
        f"Echelon-Replacement-Run: {retarget['replacement_run_id']}",
    )
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
            and all(trailer in message.stdout for trailer in identity)
            and changed
            and all(path.startswith(prefix) for path in changed)
        ):
            matches.append(commit)
    if len(matches) > 1:
        raise RetargetFinalizationError("duplicate retarget completion commits")
    return matches[0] if matches else None


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
    history = load_retarget_history(spec_dir)
    if not history.revisions or history.revisions[-1].revision_id != checked["revision_id"]:
        raise RetargetFinalizationError("retarget finalization history drifted")
    revision = history.revisions[-1]
    if (
        revision.status != "complete"
        or revision.memory_finalization != checked["memory"]
        or revision.graph_finalization != checked["graph"]
    ):
        raise RetargetFinalizationError("retarget finalization history is incomplete")
    commit = str(checked["replacement_commit"])
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
    prefix = f"specs/{spec_dir.name}/"
    required_trailers = (
        "Echelon-Action: retarget-complete",
        f"Echelon-Retarget-Revision: {checked['revision_id']}",
        f"Echelon-Baseline-Run: {retarget.get('baseline_run_id')}",
        f"Echelon-Replacement-Run: {retarget.get('replacement_run_id')}",
    )
    changed = tuple(line for line in paths.stdout.splitlines() if line)
    if (
        message.returncode != 0
        or paths.returncode != 0
        or not changed
        or any(not path.startswith(prefix) for path in changed)
        or any(trailer not in message.stdout for trailer in required_trailers)
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
        return verify_retarget_finalization_receipt(project_root, state, expected_receipt)
    retarget = require_finalizing_retarget(state)
    spec_dir = _published_spec_dir(project_root, state)
    progress = load_retarget_effect_progress(prepared)
    if progress["memory"] is None:
        memory = refresh_retarget_spec_memory(project_root, spec_dir)
        persist_retarget_effect_progress(prepared, "memory", memory.to_dict())
    else:
        memory = _validated_memory_receipt(progress["memory"])
    if progress["graph"] is None:
        graph = finalize_retarget_graphs(
            project_root,
            spec_dir,
            RetargetGraphReceipt.from_dict(retarget["graph_invalidation"]),
        )
        persist_retarget_effect_progress(prepared, "graph", graph.to_dict())
    else:
        graph = RetargetGraphReceipt.from_dict(progress["graph"])
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
    receipt = {
        "revision_id": revision_id,
        "checkpoint_commit": str(retarget["checkpoint_commit"]),
        "replacement_targets": list(retarget["replacement_targets"]),
        "memory": memory.to_dict(),
        "graph": graph.to_dict(),
        "replacement_commit": commit,
        "status": "complete",
    }
    return validate_finalization_receipt(receipt)

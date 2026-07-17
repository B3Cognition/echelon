"""Deterministic PerlGraph evidence writer for verify-spec."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess

from .node_runtime import NodeRuntimeResolutionError, resolve_perlgraph_cli

@dataclass(frozen=True)
class PerlGraphEvidenceResult:
    analysis_path: Path
    summary_path: Path
    error_path: Path
    ok: bool


class PerlGraphEvidenceError(RuntimeError):
    """Raised after writing perlgraph-error.txt for degraded evidence."""


def write_perlgraph_evidence(
    project_root: Path,
    verify_run_dir: Path,
    spec_dir: Path,
) -> PerlGraphEvidenceResult:
    project_root = project_root.resolve()
    verify_run_dir = verify_run_dir.resolve()
    spec_dir.resolve()

    analysis_path = verify_run_dir / "perlgraph-analysis.json"
    summary_path = verify_run_dir / "perlgraph-summary.json"
    error_path = verify_run_dir / "perlgraph-error.txt"
    verify_run_dir.mkdir(parents=True, exist_ok=True)

    node = shutil.which("node")
    if node is None:
        message = "Node.js is required to run PerlGraph evidence.\n"
        _write_error(error_path, message)
        _write_degraded_summary(
            summary_path=summary_path,
            analysis_path=analysis_path,
            error_path=error_path,
            message=message,
        )
        raise PerlGraphEvidenceError(str(error_path))

    try:
        cli_path = resolve_perlgraph_cli(project_root)
    except NodeRuntimeResolutionError as exc:
        message = f"{exc}\n"
        _write_error(error_path, message)
        _write_degraded_summary(
            summary_path=summary_path,
            analysis_path=analysis_path,
            error_path=error_path,
            message=message,
        )
        raise PerlGraphEvidenceError(str(error_path))

    completed = _run_perlgraph_cli(
        node=node,
        cli_path=cli_path,
        project_root=project_root,
        analysis_path=analysis_path,
        summary_path=summary_path,
    )
    if (
        completed.returncode != 0
        or not _analysis_is_usable(analysis_path, expected_repo_path=project_root)
        or not _summary_is_usable(summary_path, expected_repo_path=project_root)
    ):
        message = _provider_failure(
            "PerlGraph CLI failed.",
            command=[
                node,
                str(cli_path),
                "analyze",
                "--repo-path",
                str(project_root),
                "--output-path",
                str(analysis_path),
                "--summary-path",
                str(summary_path),
            ],
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            output_exists=analysis_path.is_file(),
        )
        _write_error(error_path, message)
        _write_degraded_summary(
            summary_path=summary_path,
            analysis_path=analysis_path,
            error_path=error_path,
            message=message,
        )
        raise PerlGraphEvidenceError(str(error_path))

    _remove_if_exists(error_path)
    return PerlGraphEvidenceResult(
        analysis_path=analysis_path,
        summary_path=summary_path,
        error_path=error_path,
        ok=True,
    )


def _run_perlgraph_cli(
    *,
    node: str,
    cli_path: Path,
    project_root: Path,
    analysis_path: Path,
    summary_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            node,
            str(cli_path),
            "analyze",
            "--repo-path",
            str(project_root),
            "--output-path",
            str(analysis_path),
            "--summary-path",
            str(summary_path),
        ],
        cwd=str(project_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _analysis_is_usable(
    analysis_path: Path, *, expected_repo_path: Path | None = None
) -> bool:
    data = _read_json_object(analysis_path)
    if data is None:
        return False
    if data.get("tool") != "perlgraph" or not isinstance(data.get("symbols"), list):
        return False
    return _repo_path_matches(data, expected_repo_path)


def _summary_is_usable(
    summary_path: Path, *, expected_repo_path: Path | None = None
) -> bool:
    data = _read_json_object(summary_path)
    if data is None:
        return False
    if data.get("tool") != "perlgraph" or not isinstance(data.get("index_stats"), dict):
        return False
    return _repo_path_matches(data, expected_repo_path)


def _read_json_object(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _repo_path_matches(data: dict[str, object], expected_repo_path: Path | None) -> bool:
    if expected_repo_path is None:
        return True
    repo_path = data.get("repo_path")
    if not repo_path:
        return True
    try:
        actual = Path(str(repo_path)).expanduser().resolve()
        expected = expected_repo_path.expanduser().resolve()
    except OSError:
        return False
    return actual == expected


def _provider_failure(
    title: str,
    *,
    command: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    output_exists: bool,
) -> str:
    return (
        f"{title}\n\n"
        f"command: {_shell_join(command)}\n"
        f"exit_code: {exit_code}\n"
        f"output_exists: {output_exists}\n\n"
        f"stdout:\n{stdout}\n\n"
        f"stderr:\n{stderr}\n\n"
    )


def _shell_join(command: list[str]) -> str:
    return " ".join(command)


def _write_error(error_path: Path, message: str) -> None:
    error_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.write_text(message, encoding="utf-8")


def _write_degraded_summary(
    *,
    summary_path: Path,
    analysis_path: Path,
    error_path: Path,
    message: str,
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    reason = next(
        (line.strip() for line in message.splitlines() if line.strip()),
        "PerlGraph evidence degraded.",
    )
    payload = {
        "tool": "perlgraph",
        "structural_evidence": "degraded",
        "evidence_quality": "manual_fallback_required",
        "reason": reason,
        "analysis_path": str(analysis_path),
        "diagnostic_artifact": str(error_path),
        "symbol_kinds": [],
        "relationship_kinds": [],
        "top_callers": [],
        "top_callees": [],
        "dynamic_risk": {"count": 0, "patterns": []},
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass

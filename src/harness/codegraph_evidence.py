"""Deterministic CodeGraph evidence writer for verify-spec."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess


FIXED_BRIDGE_RELATIVE = Path(
    ".specify/extensions/echelon/scripts/node/re/codegraph-bridge.js"
)


@dataclass(frozen=True)
class CodeGraphEvidenceResult:
    analysis_path: Path
    summary_path: Path
    error_path: Path
    ok: bool


class CodeGraphEvidenceError(RuntimeError):
    """Raised after writing codegraph-error.txt for degraded evidence."""


def write_codegraph_evidence(
    project_root: Path,
    verify_run_dir: Path,
    spec_dir: Path,
) -> CodeGraphEvidenceResult:
    project_root = project_root.resolve()
    verify_run_dir = verify_run_dir.resolve()
    spec_dir = spec_dir.resolve()

    analysis_path = verify_run_dir / "codegraph-analysis.json"
    summary_path = verify_run_dir / "codegraph-summary.json"
    error_path = verify_run_dir / "codegraph-error.txt"
    bridge_path = project_root / FIXED_BRIDGE_RELATIVE
    codegraph_dir = project_root / ".codegraph"
    codegraph_preexisted = codegraph_dir.exists()
    diagnostics: list[str] = []

    verify_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        codegraph = shutil.which("codegraph")
        if codegraph is not None:
            completed = _run_codegraph_cli(codegraph, project_root, analysis_path)
            if completed.returncode == 0 and _analysis_is_usable(
                analysis_path, expected_repo_path=project_root
            ):
                _write_summary(analysis_path, summary_path)
                _remove_if_exists(error_path)
                return CodeGraphEvidenceResult(
                    analysis_path=analysis_path,
                    summary_path=summary_path,
                    error_path=error_path,
                    ok=True,
                )
            cli_failure_title = (
                "CodeGraph CLI produced stale or unusable output."
                if completed.returncode == 0
                else "CodeGraph CLI failed."
            )
            diagnostics.append(
                _provider_failure(
                    cli_failure_title,
                    command=[
                        codegraph,
                        "export",
                        "--format",
                        "echelon",
                        "--path",
                        str(project_root),
                        "--output",
                        str(analysis_path),
                    ],
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    output_exists=analysis_path.is_file(),
                )
            )
            _remove_if_exists(analysis_path)

        node = shutil.which("node")
        if node is None:
            message = (
                "".join(diagnostics)
                + "Node.js is required to run CodeGraph evidence.\n"
            )
            _write_error(error_path, message)
            _write_degraded_summary(
                summary_path=summary_path,
                analysis_path=analysis_path,
                error_path=error_path,
                message=message,
            )
            raise CodeGraphEvidenceError(str(error_path))

        if not bridge_path.is_file():
            message = (
                "".join(diagnostics)
                + "CodeGraph bridge missing at fixed installed extension path:\n"
                f"{bridge_path}\n"
            )
            _write_error(error_path, message)
            _write_degraded_summary(
                summary_path=summary_path,
                analysis_path=analysis_path,
                error_path=error_path,
                message=message,
            )
            raise CodeGraphEvidenceError(str(error_path))

        completed = _run_vendored_bridge(node, bridge_path, project_root, analysis_path)
        if completed.returncode != 0 or not _analysis_is_usable(
            analysis_path, expected_repo_path=project_root
        ):
            message = (
                "".join(diagnostics)
                + _provider_failure(
                    "CodeGraph bridge failed.",
                    command=[
                        node,
                        str(bridge_path),
                        "analyze",
                        "--repo-path",
                        str(project_root),
                        "--output-path",
                        str(analysis_path),
                    ],
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    output_exists=analysis_path.is_file(),
                )
            )
            _write_error(error_path, message)
            _write_degraded_summary(
                summary_path=summary_path,
                analysis_path=analysis_path,
                error_path=error_path,
                message=message,
            )
            raise CodeGraphEvidenceError(str(error_path))

        _write_summary(analysis_path, summary_path)
        _remove_if_exists(error_path)
        return CodeGraphEvidenceResult(
            analysis_path=analysis_path,
            summary_path=summary_path,
            error_path=error_path,
            ok=True,
        )
    finally:
        if not codegraph_preexisted and codegraph_dir.exists():
            if codegraph_dir.is_symlink() or codegraph_dir.is_file():
                codegraph_dir.unlink()
            else:
                shutil.rmtree(codegraph_dir)


def _run_codegraph_cli(
    codegraph: str, project_root: Path, analysis_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            codegraph,
            "export",
            "--format",
            "echelon",
            "--path",
            str(project_root),
            "--output",
            str(analysis_path),
        ],
        cwd=str(project_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_vendored_bridge(
    node: str, bridge_path: Path, project_root: Path, analysis_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            node,
            str(bridge_path),
            "analyze",
            "--repo-path",
            str(project_root),
            "--output-path",
            str(analysis_path),
        ],
        cwd=str(project_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _analysis_is_usable(
    analysis_path: Path, *, expected_repo_path: Path | None = None
) -> bool:
    if not analysis_path.is_file():
        return False
    try:
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
        return False
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
        "CodeGraph evidence degraded.",
    )
    payload = {
        "structural_evidence": "degraded",
        "evidence_quality": "manual_fallback_required",
        "reason": reason,
        "analysis_path": str(analysis_path),
        "diagnostic_artifact": str(error_path),
        "symbol_kinds": [],
        "top_callers": [],
        "top_callees": [],
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


def _write_summary(analysis_path: Path, summary_path: Path) -> None:
    data = json.loads(analysis_path.read_text(encoding="utf-8"))
    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        symbols = []
    calls = data.get("call_graph")
    if not isinstance(calls, list):
        calls = []

    symbol_kinds = Counter(
        str(symbol.get("kind") or "unknown")
        for symbol in symbols
        if isinstance(symbol, dict)
    )
    callers = Counter(
        str(edge.get("caller") or "unknown") for edge in calls if isinstance(edge, dict)
    )
    callees = Counter(
        str(edge.get("callee") or "unknown") for edge in calls if isinstance(edge, dict)
    )
    index_stats = data.get("index_stats") if isinstance(data.get("index_stats"), dict) else {}

    summary = {
        "version": data.get("version"),
        "generated_at": data.get("generated_at"),
        "repo_path": data.get("repo_path"),
        "supported": data.get("supported"),
        "index_state": index_stats.get("index_state", "unknown"),
        "index_stats": data.get("index_stats"),
        "language_coverage": data.get("language_coverage"),
        "coverage": data.get("coverage"),
        "symbol_kinds": [
            {"kind": kind, "count": count}
            for kind, count in symbol_kinds.most_common()
        ],
        "top_callers": [
            {"symbol": symbol, "outgoing_calls": count}
            for symbol, count in callers.most_common(25)
        ],
        "top_callees": [
            {"symbol": symbol, "incoming_calls": count}
            for symbol, count in callees.most_common(25)
        ],
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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

    verify_run_dir.mkdir(parents=True, exist_ok=True)

    node = shutil.which("node")
    if node is None:
        _write_error(error_path, "Node.js is required to run CodeGraph evidence.")
        raise CodeGraphEvidenceError(str(error_path))

    if not bridge_path.is_file():
        _write_error(
            error_path,
            "CodeGraph bridge missing at fixed installed extension path:\n"
            f"{bridge_path}\n",
        )
        raise CodeGraphEvidenceError(str(error_path))

    try:
        completed = subprocess.run(
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
        if completed.returncode != 0 or not analysis_path.is_file():
            _write_error(
                error_path,
                "CodeGraph bridge failed.\n\n"
                f"project_root: {project_root}\n"
                f"spec_dir: {spec_dir}\n"
                f"bridge_path: {bridge_path}\n"
                f"exit_code: {completed.returncode}\n\n"
                f"stdout:\n{completed.stdout}\n\n"
                f"stderr:\n{completed.stderr}\n",
            )
            raise CodeGraphEvidenceError(str(error_path))

        _write_summary(analysis_path, summary_path)
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


def _write_error(error_path: Path, message: str) -> None:
    error_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.write_text(message, encoding="utf-8")


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

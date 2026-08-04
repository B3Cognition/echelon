"""Deterministic CodeGraph evidence writer for verify-spec."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from .node_runtime import NodeRuntimeResolutionError, resolve_codegraph_bridge

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
    codegraph_dir = project_root / ".codegraph"
    codegraph_preexisted = codegraph_dir.exists()
    verify_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        node = shutil.which("node")
        if node is None:
            message = "Node.js is required to run CodeGraph evidence.\n"
            _write_error(error_path, message)
            _write_degraded_summary(
                summary_path=summary_path,
                analysis_path=analysis_path,
                error_path=error_path,
                message=message,
            )
            raise CodeGraphEvidenceError(str(error_path))

        try:
            bridge_path = resolve_codegraph_bridge(project_root)
        except NodeRuntimeResolutionError as exc:
            message = f"{exc}\n"
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
            message = _provider_failure(
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
    if not isinstance(data, dict):
        return False
    if (
        data.get("schema_version") != 2
        or data.get("version") != "2.0.0"
        or data.get("tool") != "codegraph"
        or data.get("tool_version") != "1.4.1"
        or data.get("provider_status") != "complete"
        or data.get("complete") is not True
    ):
        return False
    symbols = data.get("symbols")
    relationships = data.get("relationships")
    call_graph = data.get("call_graph")
    type_hierarchy = data.get("type_hierarchy")
    impact_radius = data.get("impact_radius")
    counts = data.get("counts")
    diagnostics = data.get("diagnostics")
    if not all(
        isinstance(collection, list)
        for collection in (symbols, relationships, call_graph, type_hierarchy, impact_radius)
    ):
        return False
    if not isinstance(counts, dict) or not isinstance(diagnostics, dict):
        return False
    if not isinstance(diagnostics.get("unresolved_relationships"), list):
        return False
    count_fields = (
        "discovered_symbols",
        "emitted_symbols",
        "excluded_symbols",
        "discovered_relationships",
        "emitted_relationships",
        "excluded_relationships",
    )
    if any(not isinstance(counts.get(field), int) for field in count_fields):
        return False
    if counts["emitted_symbols"] != len(symbols) or counts["emitted_relationships"] != len(relationships):
        return False
    if not all(_has_canonical_symbol_locator(symbol) for symbol in symbols):
        return False
    symbol_keys = {symbol["symbol_key"] for symbol in symbols}
    if len(symbol_keys) != len(symbols):
        return False
    if not all(
        isinstance(relationship, dict)
        and relationship.get("source_key") in symbol_keys
        and relationship.get("target_key") in symbol_keys
        for relationship in relationships
    ):
        return False
    if not all(
        isinstance(edge, dict)
        and edge.get("caller_key") in symbol_keys
        and edge.get("callee_key") in symbol_keys
        for edge in call_graph
    ):
        return False
    if not all(
        isinstance(edge, dict)
        and edge.get("child_key") in symbol_keys
        and edge.get("parent_key") in symbol_keys
        for edge in type_hierarchy
    ):
        return False
    if not all(
        isinstance(entry, dict)
        and entry.get("symbol_key") in symbol_keys
        and isinstance(entry.get("affected_keys"), list)
        and all(key in symbol_keys for key in entry["affected_keys"])
        for entry in impact_radius
    ):
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


def _is_symbol_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _has_canonical_symbol_locator(symbol: object) -> bool:
    if not isinstance(symbol, dict):
        return False
    file_path = symbol.get("file_path")
    qualified_name = symbol.get("qualified_name")
    kind = symbol.get("kind")
    signature = symbol.get("signature")
    if not (
        _is_normalized_source_path(file_path)
        and isinstance(qualified_name, str)
        and isinstance(kind, str)
        and (signature is None or isinstance(signature, str))
    ):
        return False
    locator = json.dumps(
        [file_path, qualified_name, kind, signature or ""],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    expected_key = "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()
    return symbol.get("symbol_key") == expected_key


def _is_normalized_source_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if value.startswith("/") or (len(value) >= 3 and value[0].isalpha() and value[1:3] == ":/"):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


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
    names_by_key = {
        str(symbol.get("symbol_key")): str(
            symbol.get("qualified_name") or symbol.get("name") or "unknown"
        )
        for symbol in symbols
        if isinstance(symbol, dict) and isinstance(symbol.get("symbol_key"), str)
    }
    callers = Counter(
        str(edge.get("caller_name") or names_by_key.get(str(edge.get("caller_key"))) or "unknown")
        for edge in calls
        if isinstance(edge, dict)
    )
    callees = Counter(
        str(edge.get("callee_name") or names_by_key.get(str(edge.get("callee_key"))) or "unknown")
        for edge in calls
        if isinstance(edge, dict)
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

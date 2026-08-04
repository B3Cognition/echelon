"""Landed-only promotion or recapture of delivery topology evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Mapping

from echelon.topology_registry import TopologyRegistryError, load_topology_index
from echelon.workspace_model import SourceRoot, discover_workspace
from harness.codegraph_evidence import CodeGraphEvidenceError, write_codegraph_evidence
from harness.perlgraph_evidence import PerlGraphEvidenceError, write_perlgraph_evidence
from harness.re_fingerprint import (
    SourceFingerprint,
    fingerprint_source,
    resolve_re_fingerprint_profile,
)
from harness.spec_frontmatter import find_spec_dir, read_frontmatter
from harness.topology_evidence import (
    ProviderArtifactPaths,
    TopologyEvidenceError,
    build_topology_snapshot_candidate,
    write_topology_evidence_receipt,
)
from harness.topology_publication import (
    TopologyPublicationConflict,
    TopologyPublicationError,
    publish_topology_snapshots,
)
from harness.verify_evidence_discovery import discover_verify_evidence_runs
from kernel.spec_identity import spec_identity_aliases


_GIT_HEAD = re.compile(r"[0-9a-f]{40}\Z")
_PROVIDERS = ("codegraph", "perlgraph")


@dataclass(frozen=True, slots=True)
class TopologyPromotionResult:
    status: str
    source_id: str | None
    generation: int | None = None
    recaptured: bool = False
    message: str = ""


class TopologyPromotionError(RuntimeError):
    """Raised internally when delivery evidence cannot be promoted truthfully."""


def reconcile_landed_topology(
    workspace_root: Path,
    spec_id: str,
    target_root: Path,
    default_head: str,
    *,
    evidence_run: Path | None = None,
) -> TopologyPromotionResult:
    """Publish topology only for an exact landed source snapshot."""
    workspace = Path(workspace_root).resolve()
    target = Path(target_root).resolve()
    source: SourceRoot | None = None
    try:
        matches = [
            item
            for item in discover_workspace(workspace).sources
            if _source_root(workspace, item).resolve() == target
        ]
        if not matches:
            return TopologyPromotionResult(
                "unavailable", None, message="target is not a configured source"
            )
        if len(matches) != 1:
            return TopologyPromotionResult(
                "unavailable", None, message="target has ambiguous configured source mapping"
            )
        source = matches[0]
        spec_dir = find_spec_dir(spec_id, workspace)
        if spec_dir is None:
            return _failure("unavailable", source, "spec directory is unavailable")
        status = str(read_frontmatter(spec_dir).get("status") or "").strip().lower()
        if status != "landed":
            return _failure("stale", source, f"spec is not landed (status={status or 'missing'})")
        if not isinstance(default_head, str) or not _GIT_HEAD.fullmatch(default_head):
            return _failure("unavailable", source, "landed default HEAD is invalid")

        runs = discover_verify_evidence_runs(
            workspace,
            spec_dir.name,
            required_files=("topology-receipt.json",),
        )
        selected = _select_evidence_run(runs, evidence_run)
        receipt = _load_delivery_receipt(
            workspace,
            selected,
            spec_dir.name,
            source,
        )
        if receipt["verify_scope"] != "full":
            return _failure("stale", source, "topology reconciliation requires full verify scope")
        actual_head = _git_head(target)
        if actual_head != default_head:
            return _failure("stale", source, "checked-out source is not landed default HEAD")
        current_fingerprint = fingerprint_source(
            target,
            resolve_re_fingerprint_profile(workspace),
        )
        receipt_fingerprint = SourceFingerprint.from_json_dict(
            _mapping(receipt.get("source_fingerprint"), "source fingerprint")
        )
        analyzed_commit = receipt.get("analyzed_commit")
        current_index = load_topology_index(workspace)
        expected_generation = current_index.generation if current_index else 0

        recaptured = False
        candidate_run = selected
        candidate_receipt = receipt
        if analyzed_commit == default_head:
            if current_fingerprint != receipt_fingerprint:
                return _failure("stale", source, "landed source fingerprint differs from verify receipt")
            provenance = {"kind": "delivery", "run_id": _evidence_run_id(selected)}
        else:
            if (
                current_fingerprint.kind != "git"
                or current_fingerprint.git_head != default_head
                or current_fingerprint.dirty
            ):
                return _failure("stale", source, "landed source is not a clean default HEAD snapshot")
            candidate_run = selected / f"land-reconciliation-{default_head[:12]}"
            _prepare_recapture_run(selected, candidate_run)
            _clear_capture_outputs(candidate_run)
            _write_recapture_state(
                candidate_run,
                {
                    "spec_id": spec_dir.name,
                    "verify_scope": "full",
                    "status": "in_progress",
                },
            )
            capture_delivery_topology_evidence(target, candidate_run, spec_dir)
            write_topology_evidence_receipt(
                target,
                candidate_run,
                spec_dir,
                workspace_root=workspace,
                source_id=source.id,
                source_root=target,
                provenance={
                    "kind": "land-reconciliation",
                    "evidence_run": _evidence_run_id(selected),
                },
            )
            candidate_receipt = _load_delivery_receipt(
                workspace,
                candidate_run,
                spec_dir.name,
                source,
                require_discovered=False,
            )
            recaptured_fingerprint = SourceFingerprint.from_json_dict(
                _mapping(candidate_receipt.get("source_fingerprint"), "source fingerprint")
            )
            if (
                candidate_receipt.get("analyzed_commit") != default_head
                or recaptured_fingerprint != current_fingerprint
            ):
                return _failure("stale", source, "land recapture does not match default HEAD")
            provenance = {
                "kind": "land-reconciliation",
                "evidence_run": _evidence_run_id(selected),
            }
            recaptured = True

        evidence = _candidate_from_receipt(
            source,
            candidate_run,
            candidate_receipt,
            provenance,
        )
        result = publish_topology_snapshots(
            workspace,
            (evidence.candidate,),
            owner_id=f"land-{hashlib.sha256((spec_dir.name + default_head).encode()).hexdigest()[:20]}",
            owner_run_dir=None,
            expected_generation=expected_generation,
        )
        return TopologyPromotionResult(
            "current",
            source.id,
            generation=result.generation,
            recaptured=recaptured,
            message="landed topology is current",
        )
    except TopologyPublicationConflict as exc:
        return _failure("stale", source, str(exc))
    except (TopologyPromotionError, TopologyEvidenceError, TopologyPublicationError, TopologyRegistryError, OSError, ValueError) as exc:
        return _failure("unavailable", source, str(exc))


def capture_delivery_topology_evidence(
    project_root: Path,
    verify_run_dir: Path,
    spec_dir: Path,
) -> None:
    """Run the same bounded delivery providers used during verify-spec."""
    try:
        write_codegraph_evidence(project_root, verify_run_dir, spec_dir)
    except CodeGraphEvidenceError:
        pass
    try:
        write_perlgraph_evidence(project_root, verify_run_dir, spec_dir)
    except PerlGraphEvidenceError:
        pass


def _select_evidence_run(
    runs: tuple[Path, ...],
    requested: Path | None,
) -> Path:
    if requested is None:
        if not runs:
            raise TopologyPromotionError("completed topology evidence run was not found")
        return runs[-1]
    resolved = Path(requested).resolve()
    for run in runs:
        if run.resolve() == resolved:
            return run
    raise TopologyPromotionError("requested topology evidence run is not a strict verify run")


def _load_delivery_receipt(
    workspace: Path,
    run_dir: Path,
    spec_id: str,
    source: SourceRoot,
    *,
    require_discovered: bool = True,
) -> dict[str, object]:
    if require_discovered:
        discovered = discover_verify_evidence_runs(
            workspace,
            spec_id,
            required_files=("topology-receipt.json",),
        )
        if not any(path.resolve() == run_dir.resolve() for path in discovered):
            raise TopologyPromotionError("topology receipt is outside strict verify discovery")
    try:
        document = json.loads((run_dir / "topology-receipt.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyPromotionError("topology receipt is unavailable or malformed") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "source_id",
        "source_path",
        "source_fingerprint",
        "analyzed_commit",
        "spec_id",
        "verify_scope",
        "provenance",
        "providers",
    }:
        raise TopologyPromotionError("topology receipt has an invalid schema")
    if document.get("schema_version") != 1:
        raise TopologyPromotionError("topology receipt schema version is unsupported")
    if document.get("spec_id") != spec_id:
        raise TopologyPromotionError("topology receipt spec identity mismatch")
    if document.get("source_id") != source.id or document.get("source_path") != source.path:
        raise TopologyPromotionError("topology receipt source identity mismatch")
    provenance = _mapping(document.get("provenance"), "provenance")
    if require_discovered:
        expected_provenance = {
            "kind": "delivery",
            "run_dir": run_dir.relative_to(workspace).as_posix(),
        }
        if provenance != expected_provenance:
            raise TopologyPromotionError("topology receipt provenance/run mismatch")
    elif (
        set(provenance) != {"kind", "evidence_run"}
        or provenance.get("kind") != "land-reconciliation"
        or not isinstance(provenance.get("evidence_run"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", provenance["evidence_run"])
    ):
        raise TopologyPromotionError("topology recapture provenance is malformed")
    fingerprint = SourceFingerprint.from_json_dict(
        _mapping(document.get("source_fingerprint"), "source fingerprint")
    )
    analyzed_commit = document.get("analyzed_commit")
    if fingerprint.kind == "git":
        if analyzed_commit != fingerprint.git_head or not isinstance(analyzed_commit, str):
            raise TopologyPromotionError("topology receipt commit/fingerprint mismatch")
    elif analyzed_commit is not None:
        raise TopologyPromotionError("file-tree topology receipt has an analyzed commit")
    providers = _mapping(document.get("providers"), "providers")
    if set(providers) != set(_PROVIDERS):
        raise TopologyPromotionError("topology receipt must describe both providers")
    for provider in _PROVIDERS:
        _validate_receipt_provider(run_dir, provider, providers[provider])
    return document


def _validate_receipt_provider(run_dir: Path, provider: str, raw: object) -> None:
    row = _mapping(raw, f"{provider} receipt")
    status = row.get("status")
    if status == "unavailable":
        if set(row) != {"status", "complete", "diagnostics", "artifacts"}:
            raise TopologyPromotionError(f"{provider} unavailable receipt is malformed")
        if row.get("complete") is not False or row.get("artifacts") != {}:
            raise TopologyPromotionError(f"{provider} unavailable receipt is malformed")
        return
    required = {
        "status",
        "complete",
        "artifact_schema_version",
        "tool_version",
        "capabilities",
        "counts",
        "diagnostics",
        "artifacts",
    }
    if set(row) != required or not isinstance(status, str) or not isinstance(row.get("complete"), bool):
        raise TopologyPromotionError(f"{provider} receipt is malformed")
    artifacts = _mapping(row.get("artifacts"), f"{provider} artifacts")
    if set(artifacts) != {"analysis", "summary"}:
        raise TopologyPromotionError(f"{provider} artifact receipt is malformed")
    for artifact in ("analysis", "summary"):
        item = _mapping(artifacts[artifact], f"{provider} {artifact} artifact")
        expected_name = f"{provider}-{artifact}.json"
        if set(item) != {"path", "sha256"} or item.get("path") != expected_name:
            raise TopologyPromotionError(f"{provider} artifact path is invalid")
        path = run_dir / expected_name
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise TopologyPromotionError(f"{provider} artifact is missing") from exc
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if item.get("sha256") != digest:
            raise TopologyPromotionError(f"{provider} artifact hash mismatch")


def _candidate_from_receipt(
    source: SourceRoot,
    run_dir: Path,
    receipt: Mapping[str, object],
    provenance: Mapping[str, object],
):
    providers = _mapping(receipt.get("providers"), "providers")
    paths: dict[str, ProviderArtifactPaths] = {}
    for provider in _PROVIDERS:
        row = _mapping(providers[provider], f"{provider} receipt")
        if row.get("status") == "unavailable":
            analysis = run_dir / f".__unavailable-{provider}-analysis.json"
            summary = run_dir / f".__unavailable-{provider}-summary.json"
        else:
            analysis = run_dir / f"{provider}-analysis.json"
            summary = run_dir / f"{provider}-summary.json"
        paths[provider] = ProviderArtifactPaths(run_dir, analysis, summary)
    return build_topology_snapshot_candidate(
        source.id,
        source.path,
        SourceFingerprint.from_json_dict(
            _mapping(receipt.get("source_fingerprint"), "source fingerprint")
        ),
        paths,
        provenance,
    )


def _clear_capture_outputs(run_dir: Path) -> None:
    for provider in _PROVIDERS:
        for suffix in ("analysis.json", "summary.json", "error.txt"):
            try:
                (run_dir / f"{provider}-{suffix}").unlink()
            except FileNotFoundError:
                pass
    try:
        (run_dir / "topology-receipt.json").unlink()
    except FileNotFoundError:
        pass


def _prepare_recapture_run(owner_run: Path, recapture_run: Path) -> None:
    if recapture_run.is_symlink():
        raise TopologyPromotionError("topology recapture directory is symlinked")
    recapture_run.mkdir(parents=False, exist_ok=True)
    if not recapture_run.is_dir():
        raise TopologyPromotionError("topology recapture path is not a directory")
    try:
        if recapture_run.resolve(strict=True).parent != owner_run.resolve(strict=True):
            raise TopologyPromotionError("topology recapture directory escapes its verify run")
    except OSError as exc:
        raise TopologyPromotionError("topology recapture directory is unavailable") from exc


def _write_recapture_state(run_dir: Path, state: Mapping[str, object]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=run_dir,
            prefix=".state.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(run_dir / "state.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _evidence_run_id(run_dir: Path) -> str:
    if run_dir.parent.name == "verify-spec":
        return run_dir.parent.parent.name
    return run_dir.name


def _source_root(workspace: Path, source: SourceRoot) -> Path:
    return workspace if source.path == "." else workspace / source.path


def _git_head(path: Path) -> str | None:
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    head = completed.stdout.strip()
    return head if completed.returncode == 0 and _GIT_HEAD.fullmatch(head) else None


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TopologyPromotionError(f"topology receipt {label} must be an object")
    return value


def _failure(
    status: str,
    source: SourceRoot | None,
    message: str,
) -> TopologyPromotionResult:
    return TopologyPromotionResult(
        status,
        source.id if source is not None else None,
        message=message,
    )

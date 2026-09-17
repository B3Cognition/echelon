"""Reusable verify-spec preparation operations, including their CLI state stamps.

These steps preserve legacy CLI semantics. Controlled callers must validate the
complete run binding before invoking them; they do not select or initialize runs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness.canonical_requirements import (
    CanonicalRequirementInventoryResult, RequirementAuditResult,
    write_canonical_requirements, write_requirement_audit,
)
from harness.codegraph_evidence import CodeGraphEvidenceError, CodeGraphEvidenceResult, write_codegraph_evidence
from harness.perlgraph_evidence import PerlGraphEvidenceError, PerlGraphEvidenceResult, write_perlgraph_evidence
from harness.codegraph_evidence_mapper import EvidenceMapResult, write_codegraph_evidence_map
from harness.coverage_evidence import CoverageEvidenceResult, write_coverage_evidence
from harness.coverage_observation import (
    CoverageObservationError, CoverageObservationRef, CoverageObservationResult, load_coverage_observation,
)
from harness.deferred_scope import active_entries
from harness.durable_json import write_json_atomic
from harness.product_inventory import ProductInventoryResult, write_product_inventory


def _require_preparation_state(verify_run_dir: Path) -> None:
    path = verify_run_dir / "state.json"
    if not path.is_file():
        raise FileNotFoundError(f"state.json missing for verify-spec run: {path}")


def _state(verify_run_dir: Path) -> dict[str, object]:
    _require_preparation_state(verify_run_dir)
    try:
        state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
    return state if isinstance(state, dict) else {}


def _stamp_preparation_state(verify_run_dir: Path, updates: dict[str, object]) -> None:
    state = _state(verify_run_dir)
    state.update(updates)
    write_json_atomic(verify_run_dir / "state.json", state, trusted_root=verify_run_dir)


def prepare_codegraph(*, project_root: Path, verify_run_dir: Path, spec_dir: Path) -> CodeGraphEvidenceResult:
    _require_preparation_state(verify_run_dir)
    try:
        result = write_codegraph_evidence(project_root=project_root, verify_run_dir=verify_run_dir, spec_dir=spec_dir)
    except CodeGraphEvidenceError as exc:
        _stamp_preparation_state(verify_run_dir, {
            "structural_evidence": "degraded", "codegraph_evidence_quality": "manual_fallback_required",
            "codegraph_summary_path": str(verify_run_dir / "codegraph-summary.json"), "codegraph_error_path": str(exc),
        })
        raise
    _stamp_preparation_state(verify_run_dir, {"structural_evidence": "ready"})
    return result


def prepare_perlgraph(*, project_root: Path, verify_run_dir: Path, spec_dir: Path) -> PerlGraphEvidenceResult:
    _require_preparation_state(verify_run_dir)
    try:
        result = write_perlgraph_evidence(project_root=project_root, verify_run_dir=verify_run_dir, spec_dir=spec_dir)
    except PerlGraphEvidenceError as exc:
        _stamp_preparation_state(verify_run_dir, {
            "perlgraph_evidence": "degraded", "perlgraph_evidence_quality": "manual_fallback_required",
            "perlgraph_summary_path": str(verify_run_dir / "perlgraph-summary.json"), "perlgraph_error_path": str(exc),
        })
        raise
    _stamp_preparation_state(verify_run_dir, {
        "perlgraph_evidence": "ready", "perlgraph_summary_path": str(result.summary_path),
    })
    return result


def prepare_canonical_requirements(*, spec_dir: Path, verify_run_dir: Path) -> CanonicalRequirementInventoryResult:
    _require_preparation_state(verify_run_dir)
    result = write_canonical_requirements(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
    _stamp_preparation_state(verify_run_dir, {
        "canonical_requirements": "ready", "canonical_requirements_count": result.count,
    })
    return result


def prepare_product_inventory(*, project_root: Path, verify_run_dir: Path) -> ProductInventoryResult:
    _require_preparation_state(verify_run_dir)
    result = write_product_inventory(project_root=project_root, verify_run_dir=verify_run_dir)
    _stamp_preparation_state(verify_run_dir, {
        "product_inventory": "ready", "product_inventory_count": result.entry_count,
        "product_inventory_source": result.inventory_source,
    })
    return result


def prepare_requirement_audit(*, verify_run_dir: Path) -> RequirementAuditResult:
    _require_preparation_state(verify_run_dir)
    result = write_requirement_audit(verify_run_dir=verify_run_dir)
    _stamp_preparation_state(verify_run_dir, {"requirement_audit": "ready", "requirement_audit_count": result.count})
    return result


def prepare_evidence_map(*, requirement_audit_path: Path, codegraph_analysis_path: Path,
                         tasks_path: Path, out_json_path: Path, out_md_path: Path,
                         coverage_map_path: Path | None = None) -> EvidenceMapResult | None:
    verify_run_dir = out_json_path.parent
    state = _state(verify_run_dir)
    if not codegraph_analysis_path.is_file() and state.get("structural_evidence") == "degraded":
        _write_skipped_codegraph_evidence_map(
            out_json_path=out_json_path, out_md_path=out_md_path, analysis_path=codegraph_analysis_path)
        _stamp_preparation_state(verify_run_dir, {"codegraph_evidence_map": "skipped_degraded_codegraph"})
        return None
    for path in (requirement_audit_path, codegraph_analysis_path, tasks_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing required input: {path}")
    result = write_codegraph_evidence_map(
        requirement_audit_path=requirement_audit_path, codegraph_analysis_path=codegraph_analysis_path,
        tasks_path=tasks_path, out_json_path=out_json_path, out_md_path=out_md_path,
        coverage_map_path=coverage_map_path,
    )
    _stamp_preparation_state(verify_run_dir, {"codegraph_evidence_map": "ready"})
    return result


def _write_skipped_codegraph_evidence_map(*, out_json_path: Path, out_md_path: Path, analysis_path: Path) -> None:
    payload = {
        "schema_version": 2, "status": "skipped_degraded_codegraph",
        "reason": "CodeGraph evidence was degraded and codegraph-analysis.json is absent.",
        "source_files": {"codegraph_analysis": str(analysis_path)},
        "summary": {"total_requirements": 0, "counts": {
            "high": 0, "medium": 0, "low": 0, "none": 0, "ambiguous": 0,
        }, "fallback_requirement_ids": []}, "requirements": [],
    }
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md_path.write_text(
        "# CodeGraph Evidence Map\n\n"
        "CodeGraph evidence was degraded and `codegraph-analysis.json` is absent.\n", encoding="utf-8")


class PreparationObservationError(CoverageObservationError):
    """An observation failure with the legacy CLI diagnostic kept separately."""
    def __init__(self, reason: str, diagnostic: str):
        super().__init__(reason)
        self.diagnostic = diagnostic


def load_preparation_observation(*, spec_dir: Path, verify_run_dir: Path,
                                observer_required: bool, observation_path: Path | None
                                ) -> tuple[bool, CoverageObservationResult | None]:
    if not observer_required and observation_path is None:
        context_path = verify_run_dir / "coverage-observation-context.json"
        if context_path.is_file():
            try:
                context = json.loads(context_path.read_text(encoding="utf-8"))
                raw_ref = context.get("coverage_observation") if isinstance(context, dict) else None
                ref = CoverageObservationRef.from_mapping(raw_ref or {})
                observation_path = ref.path
                observer_required = (isinstance(context, dict) and context.get("schema_version") == 1
                                     and context.get("observer_required") is True)
                if not observer_required:
                    raise CoverageObservationError("coverage observation context is malformed")
            except (CoverageObservationError, OSError, json.JSONDecodeError) as exc:
                raise PreparationObservationError(str(exc), f"coverage observation context is invalid: {exc}") from exc
    if not observer_required:
        return False, None
    if observation_path is None:
        raise PreparationObservationError(
            "selected stack requires a validated coverage observation",
            "coverage observation required but no observation path was supplied")
    try:
        observation = load_coverage_observation(observation_path)
        coverage_map_hash = hashlib.sha256((spec_dir / "coverage-map.md").read_bytes()).hexdigest()
        if observation.fingerprints.get("coverage_map_hash") != coverage_map_hash:
            raise CoverageObservationError("coverage map fingerprint does not match the observation")
    except (CoverageObservationError, OSError) as exc:
        raise PreparationObservationError(str(exc), f"coverage observation is invalid: {exc}") from exc
    return True, observation


def prepare_coverage(*, spec_dir: Path, verify_run_dir: Path, observer_required: bool = False,
                     observation_path: Path | None = None) -> CoverageEvidenceResult:
    _require_preparation_state(verify_run_dir)
    canonical_path = verify_run_dir / "canonical-requirements.json"
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical_ids = tuple(str(row.get("id") or "").strip() for row in payload.get("requirements", [])
                          if isinstance(row, dict) and str(row.get("id") or "").strip())
    deferred_ids = {item_id for entry in active_entries(spec_dir) for item_id in entry.selected_ids
                    if not item_id.startswith("T-")}
    try:
        observer_required, observation = load_preparation_observation(
            spec_dir=spec_dir, verify_run_dir=verify_run_dir,
            observer_required=observer_required, observation_path=observation_path)
    except PreparationObservationError as exc:
        _stamp_preparation_state(verify_run_dir, {"coverage_evidence": "invalid", "coverage_evidence_reason": str(exc)})
        raise
    result = write_coverage_evidence(
        spec_dir=spec_dir, verify_run_dir=verify_run_dir, canonical_ids=canonical_ids,
        deferred_ids=deferred_ids, observation=observation, observer_required=observer_required)
    _stamp_preparation_state(verify_run_dir, {"coverage_evidence": "ready"})
    return result

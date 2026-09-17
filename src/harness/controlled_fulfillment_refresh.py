"""Controlled refresh composition; policy and compatibility helpers stay in the runner."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from harness.controlled_fulfillment import (
    ControlledFulfillment, _digest, _files, _SPEC_INPUTS, _EVIDENCE_INPUTS,
    _STAGED_OUTPUTS, _read_channel, _verify_reads,
)
from harness.durable_json import write_json_atomic, write_text_atomic
from harness.fulfillment_preparation import FulfillmentPreparationContext, _validate_source_binding
from harness.fulfillment_preparation_steps import load_preparation_observation
from harness.fulfillment_recovery import FulfillmentRecovery, _load, _save, publish_fulfillment_outputs
from harness.inspection_io import _open_root_directory
from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.product_inventory import product_evidence_fingerprint
from harness.verify_spec_run import init_verify_spec_run, complete_verify_spec_run, _require_safe_label
from kernel.fulfillment import (
    read_fulfillment_metadata, stamp_fulfillment_report, validate_fulfillment_artifacts,
    validate_deferred_scope_rows,
    fulfillment_table_ids,
    _FRONTMATTER_RE,
)

CONTRACT = "controlled-fulfillment-inspection-v1"
_OUTPUT_NAMES = ("fulfillment-report.md", "fulfillment-gaps.md")


def _semantic_configuration(executor, workspace):
    roles = {step: asdict(ProsaicPromptLoader(workspace).load_subagent(f"echelon.fulfillment-{step}"))
             for step in ("mapper", "judge")}
    profile = _digest(dict(roles=roles, provider=getattr(executor, "provider_id", executor.cli),
        configuration=getattr(executor, "constrained_execution_configuration_id", None)))
    return roles, profile


def _report_matches_ledger(report, ledger_path, canonical_ids):
    from harness.verified_fulfillment_ledger import _fulfillment_rows, read_verified_ledger
    rows = _fulfillment_rows(report.read_text())
    ledger = read_verified_ledger(ledger_path)
    current = {row.requirement_id: (row.status, row.evidence) for row in rows}
    recorded = {row.requirement_id: row.status for row in ledger.rows}
    if len(current) != len(rows) or set(current) - {"TASK-PROGRESS"} != canonical_ids:
        return False
    if {key: value[0] for key, value in current.items()} != recorded:
        return False
    # Evidence edits are not covered by the metadata stamp or ID set alone.
    from harness.verified_fulfillment_ledger import _evidence_refs
    return all(tuple(_evidence_refs(current[row.requirement_id][1])) == row.evidence_refs for row in ledger.rows)


def _report_body_hash(report):
    text = report.read_bytes().decode("utf-8")
    match = _FRONTMATTER_RE.match(text)
    return hashlib.sha256((text[match.end():] if match else text).encode("utf-8")).hexdigest()


def _text(path):
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
        raise ValueError("unsafe controlled fulfillment artifact")
    return path.read_bytes().decode("utf-8") if path.exists() else None


def _publication_inputs(context):
    return _files(context.verify_run_dir, (*_EVIDENCE_INPUTS, *_STAGED_OUTPUTS))


def _run_identity(path):
    state = json.loads(_text(path))
    return {key: state.get(key) for key in ("spec_id", "project_root", "orchestration_root",
        "spec_dir", "verify_run_dir", "verify_scope", "scoped_ids", "base_full_verify_commit",
        "strict", "reconcile", "dry_run", "build", "controlled_refresh_receipt")}


def refresh_controlled_fulfillment(executor, *, worktree, spec_id, spec_dir, orchestration_root,
        scope, completed_task_ids, changed_files, reconcile, dry_run, verification_evidence,
        coverage_observation, observer_required, verify_run_dir, source_id, source_root,
        token_budget, forbidden_paths, accounted_usage=None, on_run_selected=None):
    # Import lazily to keep the legacy runner API and shared policy helpers singular.
    from harness import fulfillment_runner as shared
    usage, dispatches, operation_id = 0, 0, None
    effective_scope, cache_key = scope, None
    selected = None
    try:
        spec = shared._resolve_spec_dir(spec_id, worktree, orchestration_root, explicit_spec_dir=spec_dir)
        if spec is None or orchestration_root is None or not source_id or source_root is None:
            raise ValueError("controlled fulfillment requires explicit workspace/source/spec binding")
        worktree, spec = worktree.absolute(), spec.absolute()
        workspace, source = Path(orchestration_root).absolute(), Path(source_root).absolute()
        _require_safe_label("spec_id", spec_id)
        commit = shared._current_git_commit(worktree)
        spec_hash = shared._spec_input_hash(spec)
        product_hash = shared._implementation_input_hash(worktree)
        request = dict(worktree=str(worktree), workspace=str(workspace), source_id=source_id,
            source_root=str(source), spec_id=spec_id, spec_dir=str(spec), scope=scope,
            completed_task_ids=list(completed_task_ids), changed_files=list(changed_files),
            reconcile=reconcile, dry_run=dry_run, observer_required=observer_required,
            verification_evidence=verification_evidence,
            observation=coverage_observation.ref.as_mapping() if coverage_observation else None,
            forbidden_paths=[str(Path(path).absolute()) for path in forbidden_paths], contract=CONTRACT)
        # Reconciliation owns tasks.md mutations. Its exact bytes remain in the
        # admission binding; excluding it only from path selection prevents a
        # host-applied transition from selecting a fresh billable operation.
        selection_spec = _files(spec, tuple(name for name in _SPEC_INPUTS if not (reconcile and name == "tasks.md")))
        seed = _digest(dict(request=request, commit=commit, spec=selection_spec, product=product_hash))
        selected = Path(verify_run_dir).absolute() if verify_run_dir is not None else (
            workspace / "runs" / f"verify-spec-{spec_id}-controlled-{seed[:24]}")
        selected.relative_to(workspace / "runs")
        if selected == workspace / "runs":
            raise ValueError("selected verify run must be below runs")
        operation_id = str(selected)
        if verify_run_dir is not None and not selected.is_dir():
            usage = None
            raise ValueError("caller-owned verify run is unavailable")
        # Admit the runs directory before mkdir can follow an alias outside the
        # workspace. The same descriptor-pinned root rules protect host reads.
        workspace_fd = _open_root_directory(workspace)
        try:
            try:
                os.mkdir("runs", dir_fd=workspace_fd)
            except FileExistsError:
                pass
        finally:
            os.close(workspace_fd)
        runs_fd = _open_root_directory(workspace / "runs")
        try:
            if verify_run_dir is None:
                try:
                    os.mkdir(selected.name, dir_fd=runs_fd)
                except FileExistsError:
                    pass
        finally:
            os.close(runs_fd)
        if token_budget is not None and accounted_usage is not None:
            accounted = accounted_usage.get(operation_id, 0)
            if type(accounted) is not int or accounted < 0:
                raise ValueError("invalid accounted fulfillment usage")
            token_budget += accounted
        with FulfillmentRecovery(selected) as recovery:
            # Accounting admission precedes every fallible role/provider check.
            usage = None
            journal = recovery.load()
            if journal is not None:
                accounting = recovery.usage()
                usage = accounting["tokens"] if accounting["known"] else None
                dispatches = accounting["dispatches"]
            if verify_run_dir is not None and not (selected / "state.json").is_file():
                raise ValueError("caller-owned verify state is unavailable")
            record_path = selected / "controlled-refresh.json"
            saved = _load(record_path)
            if saved is None and journal is not None:
                raise ValueError("controlled refresh receipt is missing; reconciliation required")
            if saved is None:
                usage = 0
            elif not isinstance(saved, dict) or saved.get("schema_version") != 1 or saved.get("phase") not in {
                    "selected", "publishing", "reconciling", "finalizing", "complete"}:
                raise ValueError("invalid controlled refresh receipt")
            if saved is not None:
                effective_scope = saved["scope"]
            if dry_run and not reconcile:
                raise ValueError("dry_run requires reconcile")
            if scope not in {"full", "scoped"} or commit is None:
                raise ValueError("controlled fulfillment requires valid scope and committed source")
            if getattr(executor, "supports_inspection_turn", False) is not True:
                raise ValueError("unsupported fulfillment inspection boundary")
            evidence = shared._validated_verification_evidence(verification_evidence, worktree=worktree,
                                                               candidate_commit=commit)
            if verification_evidence is not None and evidence is None:
                raise ValueError("verification evidence is invalid or stale")
            if observer_required and coverage_observation is None:
                raise ValueError("required coverage observation is missing or invalid")
            context = FulfillmentPreparationContext(worktree, workspace, source_id, source, spec_id,
                spec, selected, observer_required=observer_required,
                observation_path=coverage_observation.ref.path if coverage_observation else None)
            _validate_source_binding(context)
            ledger_path = spec / "verified-fulfillment-ledger.json"
            _text(ledger_path)
            _, observation = load_preparation_observation(spec_dir=spec, verify_run_dir=selected,
                observer_required=observer_required, observation_path=context.observation_path)
            roles, semantic_profile = _semantic_configuration(executor, workspace)
            contract_version = f"{CONTRACT}:{semantic_profile}"
            def binding():
                return _digest(dict(request=request, commit=commit, spec=_files(spec, _SPEC_INPUTS),
                    product=product_evidence_fingerprint(worktree, excluded_roots=(spec,)),
                    roles=roles, provider=getattr(executor, "provider_id", executor.cli),
                    configuration=getattr(executor, "constrained_execution_configuration_id", None),
                    observation=_files(observation.ref.path.parent, (observation.ref.path.name,)) if observation else None))
            current_binding = binding()
            cache_key = _digest(dict(contract=CONTRACT, binding=current_binding))
            report = spec / "fulfillment-report.md"
            evidence_hash = evidence.evidence_sha256 if evidence else None
            observation_hash = observation.ref.observation_sha256 if observation else None
            if saved is None:
                originals = {name: _text(spec / name) for name in _OUTPUT_NAMES}
                ids, base_commit = (), ""
                if scope == "scoped":
                    metadata = read_fulfillment_metadata(report) if report.exists() else {}
                    canonical_ids = {item.id for item in shared.extract_canonical_requirements(spec)}
                    report_ids = fulfillment_table_ids(originals["fulfillment-report.md"] or "")
                    if (metadata.get("fulfillment_contract") != CONTRACT
                            or metadata.get("fulfillment_body_sha256") != _report_body_hash(report)
                            or metadata.get("fulfillment_semantic_profile") != semantic_profile
                            or report_ids - {"TASK-PROGRESS"} != canonical_ids
                            or reconcile or not ledger_path.is_file()
                            or validate_deferred_scope_rows(report, spec)
                            or not _report_matches_ledger(report, ledger_path, canonical_ids)):
                        effective_scope = "full"
                    else:
                        plan = shared.build_scoped_verify_plan(spec_dir=spec,
                            completed_task_ids=completed_task_ids, changed_files=changed_files)
                        ledger = shared._verified_ledger_reuse_plan(worktree, spec_dir=spec, report=report,
                            spec_input_hash=spec_hash, implementation_input_hash=product_hash,
                            verification_evidence_sha256=evidence_hash, coverage_observation_sha256=observation_hash,
                            contract_version=contract_version)
                        ids = tuple(sorted((set(plan.impacted_requirement_ids) | set(ledger.rechecked_requirement_ids))
                                           & canonical_ids))
                        base_commit = plan.base_full_verify_commit or ""
                        if not ids:
                            if (verify_run_dir is None and "TASK-PROGRESS" not in ledger.rechecked_requirement_ids
                                    and metadata.get("verified_commit") == commit
                                    and metadata.get("spec_input_hash") == spec_hash
                                    and metadata.get("implementation_input_hash") == product_hash):
                                return shared.FulfillmentRefreshResult("cached", 0, True, "scoped",
                                    "no impacted controlled requirements", report_path=str(report))
                            effective_scope = "full"
                if effective_scope == "full":
                    ids, base_commit = (), ""
                state_path = selected / "state.json"
                if not state_path.exists():
                    init_verify_spec_run(project_root=worktree, spec_id=spec_id, spec_dir=spec,
                        verify_scope=effective_scope, scoped_ids=ids, base_full_verify_commit=base_commit,
                        reconcile=reconcile, dry_run=dry_run, verify_run_dir=selected)
                state = json.loads(state_path.read_text())
                if state.get("controlled_refresh_receipt"):
                    usage = None
                    raise ValueError("controlled refresh receipt was lost; reconciliation required")
                expected = dict(spec_id=spec_id, project_root=str(worktree.resolve()),
                    orchestration_root=str(workspace.resolve()), spec_dir=str(spec.resolve()),
                    verify_run_dir=str(selected.resolve()), verify_scope=effective_scope,
                    scoped_ids=list(ids), base_full_verify_commit=base_commit,
                    reconcile=reconcile, dry_run=dry_run, status="in_progress")
                if any(state.get(key) != value for key, value in expected.items()):
                    raise ValueError("selected verify run binding does not match controlled refresh")
                state["controlled_refresh_receipt"] = record_path.name
                write_json_atomic(state_path, state, trusted_root=workspace)
                saved = dict(schema_version=1, binding=current_binding, scope=effective_scope, ids=list(ids),
                    base_commit=base_commit, originals=originals, phase="selected", outputs=None,
                    publication_inputs=None, ledger=None, run_identity=_run_identity(state_path))
                _save(record_path, saved)
            elif saved["binding"] != current_binding:
                raise ValueError("controlled refresh binding changed; reconciliation required")
            if _run_identity(selected / "state.json") != saved["run_identity"]:
                raise ValueError("controlled refresh run identity changed")
            if on_run_selected is not None:
                on_run_selected(selected)
            from dataclasses import replace
            context = replace(context, scope=effective_scope, scoped_ids=tuple(saved["ids"]),
                              base_full_verify_commit=saved["base_commit"])
            if saved["phase"] == "reconciling":
                raise ValueError("progress reconciliation completion unknown; manual reconciliation required")
            if saved["phase"] in {"finalizing", "complete"}:
                if _publication_inputs(context) != saved["publication_inputs"]:
                    raise ValueError("controlled fulfillment evidence changed")
                with _read_channel(context, forbidden_paths) as channel:
                    _verify_reads(channel, [turn["read"] for step in journal["steps"].values()
                        for turn in step["records"] if turn["read"] is not None])
            else:
                result = ControlledFulfillment(executor, workspace).run(context,
                    forbidden_paths=forbidden_paths, token_budget=token_budget, _recovery=recovery)
                usage, dispatches = result.token_usage, result.dispatch_count
                if result.exit_code:
                    return shared.FulfillmentRefreshResult("failed", result.exit_code, scope=effective_scope,
                        reason=result.reason, token_usage=usage, operation_id=operation_id, dispatch_count=dispatches)
                if saved["phase"] == "selected":
                    with tempfile.TemporaryDirectory(prefix="echelon-fulfillment-publish-") as directory:
                        candidate = Path(directory) / "fulfillment-report.md"
                        if effective_scope == "scoped":
                            base = Path(directory) / "base.md"
                            write_text_atomic(base, saved["originals"]["fulfillment-report.md"], trusted_root=Path(directory))
                            shared.merge_scoped_fulfillment_report(base_report_path=base,
                                scoped_report_path=result.report_path, output_report_path=candidate,
                                impacted_requirement_ids=saved["ids"], spec_id=spec_id, commit=commit,
                                base_full_verify_commit=saved["base_commit"])
                        else:
                            write_text_atomic(candidate, result.report_path.read_text(), trusted_root=Path(directory))
                        validation = validate_fulfillment_artifacts(requirement_audit_path=selected / "requirement-audit.md",
                            fulfillment_report_path=candidate, canonical_inventory_path=selected / "canonical-requirements.json")
                        if not validation.ok or validate_deferred_scope_rows(candidate, spec):
                            raise ValueError("invalid full/merged controlled fulfillment report")
                        stamp_fulfillment_report(candidate, spec_id=spec_id, commit=commit, run_id=selected.name,
                            extra_metadata=dict(verify_scope=effective_scope, fulfillment_contract=CONTRACT,
                                fulfillment_body_sha256=_report_body_hash(candidate),
                                fulfillment_semantic_profile=semantic_profile,
                                verify_cache_key=cache_key, spec_input_hash=spec_hash, implementation_input_hash=product_hash,
                                verification_evidence_sha256=evidence_hash, coverage_observation_sha256=observation_hash))
                        saved["outputs"] = {"fulfillment-report.md": candidate.read_text(),
                            "fulfillment-gaps.md": result.gaps_path.read_text()}
                    saved.update(phase="publishing", publication_inputs=_publication_inputs(context))
                    _save(record_path, saved)
            for name in _OUTPUT_NAMES:
                if _text(spec / name) not in (saved["originals"][name], saved["outputs"][name]):
                    raise ValueError("controlled publication destination conflict")
            if saved["phase"] == "complete":
                if any(_text(spec / name) != saved["outputs"][name] for name in _OUTPUT_NAMES):
                    raise ValueError("completed controlled publication changed")
                state = json.loads((selected / "state.json").read_text())
                if state.get("status") != "complete":
                    raise ValueError("completed controlled lifecycle changed")
                return shared.FulfillmentRefreshResult("cached", 0, True, effective_scope,
                    "completed controlled operation reused", cache_key, str(report), saved["ledger"],
                    usage, operation_id, dispatches)
            publish_fulfillment_outputs(selected, spec, saved["outputs"])
            policy = shared.VerifySpecArtifactWritePolicy(workspace, spec, spec_id, selected)
            if saved["phase"] == "publishing":
                if reconcile:
                    saved["phase"] = "reconciling"
                    _save(record_path, saved)
                    error = shared._complete_requested_progress_reconciliation(policy)
                    if error:
                        raise ValueError(f"controlled progress reconciliation failed: {error}")
                    saved["binding"] = binding()
                saved["phase"] = "finalizing"
                _save(record_path, saved)
            state_path = selected / "state.json"
            state = json.loads(state_path.read_text())
            state["fulfillment_artifacts"] = "valid"
            write_json_atomic(state_path, state, trusted_root=workspace)
            previous_ledger = _text(ledger_path)
            with tempfile.TemporaryDirectory(prefix="echelon-fulfillment-ledger-") as directory:
                staged_ledger = Path(directory) / "ledger.json"
                saved["ledger"] = shared._write_verified_fulfillment_ledger(worktree, spec_dir=spec, report=report,
                    spec_input_hash=shared._spec_input_hash(spec), implementation_input_hash=product_hash,
                    verification_evidence_sha256=evidence_hash, verification_evidence=evidence,
                    coverage_observation_sha256=observation_hash, contract_version=contract_version,
                    output_path=staged_ledger)
                write_text_atomic(ledger_path, staged_ledger.read_text(), trusted_root=workspace,
                                  expected_text=previous_ledger)
            complete_verify_spec_run(selected)
            saved["phase"] = "complete"
            _save(record_path, saved)
            return shared.FulfillmentRefreshResult("refreshed", 0, scope=effective_scope,
                reason="controlled fulfillment completed", cache_key=cache_key, report_path=str(report),
                verified_ledger=saved["ledger"], token_usage=usage, operation_id=operation_id, dispatch_count=dispatches)
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
        return shared.FulfillmentRefreshResult("failed", 2, scope=effective_scope, reason=str(exc),
            cache_key=cache_key, token_usage=usage, operation_id=operation_id, dispatch_count=dispatches)

"""Inactive host-owned fulfillment semantics, staged in an explicitly bound run."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import tempfile
import time
from uuid import uuid4

from harness.deferred_scope import active_entries
from harness.canonical_requirements import _category_for
from harness.codegraph_evidence_mapper import RequirementRow, _is_runtime_threshold
from harness.durable_json import write_json_atomic, write_text_atomic
from harness.fulfillment_preparation import (
    FulfillmentPreparationContext, PreparedFulfillmentInputs, _validate_context, prepare_fulfillment_inputs,
)
from harness.fulfillment_recovery import FulfillmentRecovery
from harness.fulfillment_preparation_steps import load_preparation_observation
from harness.fulfillment_semantics import (
    FulfillmentAssignment, parse_semantic_reply, render_fallback_report, render_implementation_map,
)
from harness.inspection_io import BoundedReadChannel
from harness.judgment_prepass import assemble_fulfillment_report, write_judgment_prepass
from harness.product_inventory import CONTROL_PATHS, CONTROL_ROOTS, product_evidence_fingerprint
from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.task_progress import summarize_task_progress
from kernel.fulfillment import validate_deferred_scope_rows, validate_fulfillment_artifacts


@dataclass(frozen=True)
class ControlledFulfillmentResult:
    exit_code: int
    reason: str
    report_path: Path | None = None
    gaps_path: Path | None = None
    token_usage: int | None = 0
    dispatch_count: int = 0


_SPEC_INPUTS = ("spec.md", "plan.md", "tasks.md", "coverage-map.md", "user-clarifications.md",
                "deferred-scope.json", "test-strategy.md", "research.md", "data-model.md")
_EVIDENCE_INPUTS = ("canonical-requirements.json", "requirement-audit.md", "product-inventory.json",
                    "codegraph-analysis.json", "codegraph-summary.json", "codegraph-evidence-map.json",
                    "perlgraph-analysis.json", "perlgraph-summary.json", "coverage-evidence.json",
                    "coverage-observation-context.json", "topology-receipt.json")
_MAPPER_FIELDS = {"id": "exact assigned ID", "verified_implementation_evidence": "inspected root:path:line citations or empty",
    "verified_test_evidence": "inspected root:path:line citations or empty", "codegraph_candidates": "host-supplied leads",
    "candidate_disposition": "accepted|candidate_only|contradicted|unrelated|none",
    "evidence_kind": "source_and_test|source_only|test_only|measured_runtime|assertion_only|missing|meta",
    "evidence_strength": "strong|medium|weak|none", "runtime_threshold": "boolean",
    "confidence": "high|medium|low|none", "notes": "literal single-line text"}
_JUDGE_FIELDS = {"id": "exact assigned ID", "status": "IMPLEMENTED|PARTIAL|UNVERIFIED|MISSING|DEVIATED|OBSOLETE_SPEC",
                 "evidence": "nonempty concrete evidence with task/case context"}
_STAGED_OUTPUTS = ("implementation-map.md", "judgment-prepass.json", "judgment-prepass.md",
                   "fulfillment-report.fallback.md", "progress-integrity.json",
                   "fulfillment-report.staged.md", "fulfillment-gaps.staged.md")


def _safe_outputs(run: Path) -> None:
    for name in _STAGED_OUTPUTS:
        try:
            info = (run / name).lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"unsafe fulfillment stage destination: {name}")


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _files(root: Path, names) -> dict[str, str | None]:
    values = {}
    for name in names:
        path = root / name
        if path.is_symlink():
            raise ValueError(f"symlinked fulfillment input: {name}")
        values[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return values


def _inputs(context) -> str:
    state = _json(context.verify_run_dir / "state.json")
    _, observation = load_preparation_observation(
        spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir,
        observer_required=context.observer_required, observation_path=context.observation_path)
    return _digest({"product": product_evidence_fingerprint(context.project_root, excluded_roots=(context.spec_dir,)),
                    "observation": (_files(observation.ref.path.parent, (observation.ref.path.name,))
                                    if observation is not None else None),
                    "spec": _files(context.spec_dir, _SPEC_INPUTS),
                    "evidence": _files(context.verify_run_dir, _EVIDENCE_INPUTS),
                    "run": {key: state.get(key) for key in (
                        "spec_id", "project_root", "orchestration_root", "spec_dir", "verify_run_dir",
                        "verify_scope", "scoped_ids", "base_full_verify_commit", "status", "strict",
                        "reconcile", "dry_run", "build")}})


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_channel(context, forbidden_paths):
    run = context.verify_run_dir
    roots = {"worktree": context.project_root, "spec": context.spec_dir, "evidence": run}
    denied = (*forbidden_paths, *(context.project_root / name for name in CONTROL_ROOTS | CONTROL_PATHS),
              run / "state.json", run / "controlled-fulfillment.json", run / "controlled-fulfillment.lock",
              run / "fulfillment-publication.json", run / "controlled-refresh.json",
              *(run / name for name in (
                  "task-requirement-map.candidates.json", "task-requirement-map-plan.json", "task-requirement-map-plan.md",
                  "task-requirement-map-applied.json", "task-requirement-map-applied.md",
                  "progress-reconciliation-candidates.json", "progress-reconciliation-plan.json", "progress-reconciliation-plan.md",
                  "progress-reconciliation-applied.json", "progress-reconciliation-applied.md")),
              *(run / name for name in _STAGED_OUTPUTS),
              context.spec_dir / "verified-fulfillment-ledger.json",
              context.spec_dir / "fulfillment-report.md", context.spec_dir / "fulfillment-gaps.md")
    return BoundedReadChannel(roots, forbidden_paths=denied)


class ControlledFulfillment:
    """Stage a full/scoped semantic result; no canonical writes or active callers."""

    def __init__(self, executor, project_dir: Path):
        self._executor = executor
        self._project_dir = Path(project_dir)

    def run(self, context: FulfillmentPreparationContext, *, forbidden_paths: tuple[Path, ...] = (),
            token_budget: float | None = None, _recovery: FulfillmentRecovery | None = None) -> ControlledFulfillmentResult:
        usage = {"tokens": 0, "known": True, "dispatches": 0}
        stack = ExitStack()
        try:
            try:
                recovery = _recovery or stack.enter_context(FulfillmentRecovery(context.verify_run_dir))
                saved = recovery.load()
                if saved is not None:
                    usage.update(recovery.usage())
                elif _json(context.verify_run_dir / "state.json").get("controlled_fulfillment_journal"):
                    raise ValueError("fulfillment reconciliation required: expected journal is missing")
            except (ValueError, OSError, TypeError, KeyError):
                usage["known"] = False
                raise
            if getattr(self._executor, "supports_inspection_turn", False) is not True:
                raise ValueError("unsupported fulfillment inspection boundary")
            if token_budget is not None and (type(token_budget) not in {int, float}
                    or not math.isfinite(token_budget) or token_budget < 0):
                raise ValueError("invalid fulfillment token budget")
            roles = {}
            loader = ProsaicPromptLoader(self._project_dir)
            for step in ("mapper", "judge"):
                name = f"echelon.fulfillment-{step}"
                role = loader.load_subagent(name)
                if role is None or role.frontmatter.get("name") != name or not role.body.strip():
                    raise ValueError(f"missing or invalid fulfillment role: {name}")
                roles[step] = role
            _safe_outputs(context.verify_run_dir)
            operation_binding = _digest({
                "context": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(context).items()},
                "roles": {step: asdict(role) for step, role in roles.items()},
                "forbidden_paths": [str(Path(path).absolute()) for path in forbidden_paths],
                "provider": getattr(self._executor, "provider_id", self._executor.cli),
                "configuration": getattr(self._executor, "constrained_execution_configuration_id", None),
                "contract": "controlled-fulfillment-inspection-v1",
            })
            if saved is None:
                state_path = context.verify_run_dir / "state.json"
                state = _json(state_path)
                _validate_context(context)
                state["controlled_fulfillment_journal"] = recovery.path.name
                write_json_atomic(state_path, state, trusted_root=context.verify_run_dir)
                recovery.data = {"schema_version": 1, "binding": operation_binding, "phase": "preparing",
                                 "inputs": None, "budget_limit": token_budget, "steps": {}, "outputs": {}}
                recovery.save()
                prepared = prepare_fulfillment_inputs(context)
                recovery.data.update(phase="prepared", inputs=_inputs(context))
                recovery.save()
            else:
                if saved["binding"] != operation_binding:
                    raise ValueError("fulfillment reconciliation required: operation binding changed")
                if saved["phase"] == "preparing":
                    raise ValueError("fulfillment reconciliation required: preparation completion unknown")
                if _inputs(context) != saved["inputs"]:
                    raise ValueError("fulfillment reconciliation required: inputs changed")
                ceilings = [value for value in (token_budget, saved["budget_limit"]) if value is not None]
                token_budget = min(ceilings) if ceilings else None
                saved["budget_limit"] = token_budget
                recovery.save()
                prepared = PreparedFulfillmentInputs(context.verify_run_dir,
                    tuple(row["id"] for row in _json(context.verify_run_dir / "canonical-requirements.json")["requirements"]),
                    context.scoped_ids, str(_json(context.verify_run_dir / "state.json").get("topology_evidence")))
            run = prepared.verify_run_dir
            binding = _inputs(context)
            canonical = _json(run / "canonical-requirements.json")["requirements"]
            deterministic_path = run / "codegraph-evidence-map.json"
            deterministic = _json(deterministic_path) if deterministic_path.exists() else {"requirements": []}
            leads = {row["id"]: row for row in deterministic["requirements"]}
            thresholds = {row["id"]: _is_runtime_threshold(RequirementRow(
                row["id"], _category_for(row["id"]), row["source_file"], row["source_text"], ""))
                for row in canonical}
            deferred = {item for entry in active_entries(context.spec_dir) for item in entry.selected_ids}
            scope = prepared.scoped_ids if context.scope == "scoped" else prepared.canonical_ids
            assigned = tuple(item for item in scope if item not in deferred)
            data = {"canonical_requirements": [row for row in canonical if row["id"] in scope],
                    "deterministic_map": deterministic, "coverage": _json(run / "coverage-evidence.json"),
                    "evidence_files": list(_EVIDENCE_INPUTS), "spec_files": list(_SPEC_INPUTS)}
            with _read_channel(context, forbidden_paths) as channel:
                if recovery.data["phase"] == "staged":
                    if _files(run, _STAGED_OUTPUTS) != recovery.data["outputs"]:
                        raise ValueError("fulfillment reconciliation required: staged artifacts changed")
                    _verify_reads(channel, [record["read"] for step in recovery.data["steps"].values()
                                           for record in step["records"] if record["read"] is not None])
                    return ControlledFulfillmentResult(0, "staged", run / "fulfillment-report.staged.md",
                        run / "fulfillment-gaps.staged.md", usage["tokens"] if usage["known"] else None, usage["dispatches"])
                rows = []
                all_reads = []
                if assigned:
                    mapped, reads = self._dispatch("mapper", assigned, roles["mapper"], context, binding,
                                                   data, channel, usage, token_budget, recovery)
                    rows = mapped["rows"]
                    all_reads.extend(reads)
                    _verify_citations(rows, reads)
                    for row in rows:
                        lead = leads.get(row["id"])
                        if lead is not None:
                            row["codegraph_candidates"] = "; ".join(
                                f"{item['file']}::{item['symbol']}" for item in lead["codegraph_candidates"])
                            for key in ("evidence_kind", "evidence_strength", "runtime_threshold"):
                                row[key] = lead[key]
                        # Threshold classification is deterministic even when
                        # the graph tool degrades and cannot produce map rows.
                        row["runtime_threshold"] = thresholds[row["id"]]
                _safe_outputs(run)
                write_text_atomic(run / "implementation-map.md", render_implementation_map(rows), trusted_root=run)
                write_judgment_prepass(spec_dir=context.spec_dir, verify_run_dir=run,
                                       observer_required=context.observer_required)
                prepass = _json(run / "judgment-prepass.json")
                fallback_ids = tuple(row["id"] for row in prepass["rows"]
                                     if not row["mechanical"] and row["id"] in scope)
                fallback = []
                if fallback_ids:
                    judged, reads = self._dispatch("judge", fallback_ids, roles["judge"], context, binding,
                        {**data, "implementation_map": rows, "judgment_prepass": prepass, "mapper_reads": all_reads},
                        channel, usage, token_budget, recovery)
                    fallback = judged["rows"]
                    all_reads.extend(reads)
                    for row in fallback:
                        _verify_citation_text(row["evidence"], all_reads, required=row["status"] == "IMPLEMENTED")
                _verify_reads(channel, all_reads)
                _safe_outputs(run)
                fallback_path = run / "fulfillment-report.fallback.md"
                write_text_atomic(fallback_path, render_fallback_report(fallback), trusted_root=run)
                progress = summarize_task_progress((context.spec_dir / "tasks.md").read_text(),
                                                  _json(run / "state.json").get("build", {}))
                write_json_atomic(run / "progress-integrity.json", asdict(progress), trusted_root=run)
                if context.scope == "full" and (not progress.valid or progress.terminal_tasks < progress.total_tasks):
                    detail = "; ".join(progress.errors) if progress.errors else "Task progress is incomplete"
                    detail = detail.replace("|", "/").replace("\n", " ").replace("\r", " ")
                    write_text_atomic(fallback_path, fallback_path.read_text() + f"| TASK-PROGRESS | PARTIAL | {detail} |\n",
                                      trusted_root=run)
                report = run / "fulfillment-report.staged.md"
                assemble_fulfillment_report(canonical_inventory_path=run / "canonical-requirements.json",
                    judgment_prepass_path=run / "judgment-prepass.json", fallback_report_path=fallback_path,
                    output_report_path=report, state_path=run / "state.json")
                validation = validate_fulfillment_artifacts(requirement_audit_path=run / "requirement-audit.md",
                    fulfillment_report_path=report, canonical_inventory_path=run / "canonical-requirements.json")
                expected_missing = set(prepared.canonical_ids) - set(scope)
                if (set(validation.missing_in_report) != expected_missing or validation.extra_in_report
                        or validation.summary_count_mismatches):
                    raise ValueError(f"invalid staged fulfillment artifacts: {validation}")
                errors = validate_deferred_scope_rows(report, context.spec_dir)
                if errors:
                    raise ValueError(f"invalid deferred fulfillment rows: {errors}")
                if _inputs(context) != binding:
                    raise ValueError("fulfillment inputs changed during inspection")
                gaps = run / "fulfillment-gaps.staged.md"
                tasks = (context.spec_dir / "tasks.md").read_text()
                nonpassing = [line for line in report.read_text().splitlines() if line.startswith("| ")
                              and any(f"| {status} |" in line for status in
                                      ("PARTIAL", "UNVERIFIED", "MISSING", "DEVIATED", "OBSOLETE_SPEC"))]
                write_text_atomic(gaps, "# Fulfillment Gaps\n\n" + "\n".join(nonpassing) +
                                  ("\n\n## Task repair context\n\n" + tasks +
                                   "\n\n## Coverage repair context\n\n" + json.dumps(
                                       {key: value for key, value in data["coverage"]["requirements"].items() if key in scope},
                                       indent=2, sort_keys=True)
                                   if nonpassing else "\nNo actionable gaps.\n"),
                                  trusted_root=run)
                recovery.data.update(phase="staged", outputs=_files(run, _STAGED_OUTPUTS))
                recovery.save()
            return ControlledFulfillmentResult(0, "staged", report, gaps,
                usage["tokens"] if usage["known"] else None, usage["dispatches"])
        except (ValueError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
            return ControlledFulfillmentResult(2, str(exc), token_usage=usage["tokens"] if usage["known"] else None,
                                                dispatch_count=usage["dispatches"])
        finally:
            stack.close()

    def _dispatch(self, step, ids, role, context, binding, data, channel, usage, budget, recovery):
        assignment = FulfillmentAssignment(context.verify_run_dir.name, step, uuid4().hex,
                                            _digest({"inputs": binding, "role": asdict(role), "data": data}), ids)
        stored = recovery.data["steps"].get(step)
        if stored is None:
            stored = {"assignment": assignment.identity(), "deadline": time.time() + 300, "records": []}
            recovery.data["steps"][step] = stored
            recovery.save()
        else:
            identity = stored["assignment"]
            if {**identity, "dispatch_id": assignment.dispatch_id} != assignment.identity():
                raise ValueError("fulfillment reconciliation required: semantic assignment changed")
            assignment = FulfillmentAssignment(**{key: value for key, value in identity.items() if key != "schema_version"})
        reads = []
        deadline = stored["deadline"]
        cursor = 0
        while True:
            if cursor < len(stored["records"]):
                record = stored["records"][cursor]
                cursor += 1
                if record["error"]:
                    raise ValueError(record["error"])
                if record["reply"] is None:
                    raise ValueError("fulfillment reconciliation required: external completion unknown")
                accepted = record["reply"]
                if accepted["action"] == "final":
                    _verify_reads(channel, reads)
                    return accepted, reads
                if accepted["action"] == "blocked":
                    raise ValueError(f"fulfillment {step} blocked: {accepted['reason']}")
                if record["read"] is None:
                    raise ValueError("fulfillment reconciliation required: read completion unknown")
                reads.append(record["read"])
                _verify_reads(channel, reads)
                continue
            _check_budget(usage, budget)
            if time.time() >= deadline:
                raise ValueError("fulfillment inspection deadline exhausted")
            if _inputs(context) != binding:
                raise ValueError("fulfillment inputs changed during inspection")
            _verify_reads(channel, reads)
            payload = {"assignment": assignment.identity(), "context": data, "reads": reads,
                "reply_contract": {"actions": {"read": "request: closed read_file/list_directory request",
                    "blocked": "reason: nonempty single-line text", "final": "rows and unmapped_candidates"},
                    "row_fields": _MAPPER_FIELDS if step == "mapper" else _JUDGE_FIELDS,
                    "roots": ["worktree", "spec", "evidence"],
                    "read_file": {"op": "read_file", "root": "evidence", "path": "requirement-audit.md",
                                  "start_line": 1, "line_count": 200},
                    "list_directory": {"op": "list_directory", "root": "worktree", "path": "."},
                    "instruction": "Repeat every assignment field exactly at top level, then action and its fields only."}}
            prompt = role.body + "\nHOST_INPUT_JSON\n" + json.dumps(payload, allow_nan=False)
            if len(prompt.encode()) > 1024 * 1024:
                raise ValueError("fulfillment inspection input exceeds provider limit")
            record = {"reply": None, "read": None, "token_usage": None, "error": None}
            stored["records"].append(record)
            recovery.save()  # Durable intent before external execution.
            cursor += 1
            with tempfile.TemporaryDirectory(prefix="echelon-fulfillment-inspection-") as private:
                usage["dispatches"] += 1
                try:
                    result = self._executor.run_inspection_turn(private, prompt,
                        frontmatter={key: role.frontmatter[key] for key in ("model_tier", "effort")},
                        timeout_ms=max(1, int((deadline - time.time()) * 1000)))
                except BaseException:
                    usage["known"] = False
                    raise
            known = type(result.token_usage) is int and result.token_usage >= 0
            usage["known"] = usage["known"] and known
            usage["tokens"] += result.token_usage if known else 0
            record["token_usage"] = result.token_usage if known else None
            try:
                if result.exit_code != 0:
                    raise ValueError(f"fulfillment {step} provider failed: {result.stderr}")
                _check_budget(usage, budget)
                if time.time() >= deadline:
                    raise ValueError("fulfillment inspection deadline exhausted")
                if _inputs(context) != binding:
                    raise ValueError("fulfillment inputs changed during inspection")
                _verify_reads(channel, reads)
                accepted = parse_semantic_reply(result.stdout, assignment)
                record["reply"] = accepted
                if accepted["action"] == "blocked":
                    raise ValueError(f"fulfillment {step} blocked: {accepted['reason']}")
                if accepted["action"] == "read":
                    if len(reads) >= 32:
                        raise ValueError("fulfillment inspection read limit exhausted")
                    request = accepted["request"]
                    record["read"] = {"request": request, "response": channel.request(request)}
                    reads.append(record["read"])
                recovery.save()
                if accepted["action"] == "final":
                    return accepted, reads
            except (ValueError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
                record["error"] = str(exc) or type(exc).__name__
                recovery.save()
                raise


def _check_budget(usage, budget):
    if budget is not None and not usage["known"]:
        raise ValueError("fulfillment usage unknown with finite budget")
    if budget is not None and usage["tokens"] >= budget:
        raise ValueError("fulfillment token budget exhausted")


def _verify_reads(channel, reads):
    for read in reads:
        if channel.request(read["request"]) != read["response"]:
            raise ValueError("fulfillment inspected evidence changed")


def _verify_citations(rows, reads):
    for row in rows:
        for key in ("verified_implementation_evidence", "verified_test_evidence"):
            value = row[key]
            if not value:
                continue
            _verify_citation_text(value, reads, required=True)


def _verify_citation_text(value, reads, *, required):
    citations = re.findall(r"(worktree|spec|evidence):([^\s;]+):(\d+)", value)
    if required and not citations:
        raise ValueError("verified evidence requires inspected root:path:line citations")
    for root, path, line in citations:
        if not any(read["request"].get("op") == "read_file" and read["request"]["root"] == root
            and read["request"]["path"] == path and read["response"].get("status") == "ok"
            and read["request"]["start_line"] <= int(line) < read["request"]["start_line"] +
                len(read["response"]["text"].splitlines()) for read in reads):
                raise ValueError("verified evidence cites unread source")

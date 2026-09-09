"""Phase executors for SquadController — one class per definition.yaml type."""
from __future__ import annotations

import hashlib
import json
import re
import inspect
import shutil
import stat
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from echelon.spec_authoring import PERFECTIONIST_MODE, normalize_spec_authoring_mode
from harness.controller_state_contracts import ControllerStateContractViolation
from harness.governance_structural_gate import (
    GovernanceStructuralGateResult,
    run_governance_structural_gate,
)
from harness.prompt_companions import append_prompt_companions, prompt_package_roots
from harness.prompt_markdown import read_prompt_markdown
from harness.phase_display import color_phase_id
from harness.quality_scores import (
    normalize_why_quality_scores,
    render_quality_gate_context,
    resolve_quality_gate_thresholds,
)
from harness.agent_context import (
    RenderedSection,
    build_context_budget_report,
    compact_state_projection,
    parse_context_pack_item,
    policy_for_context,
    render_context_path,
    resolve_context_render_mode,
    write_context_budget_report,
)
from harness.spec_lexicon_gate import run_spec_lexicon_gate
from harness.stack_contract import render_stack_contract
from harness.state_transaction_namespace import store_owned_update_keys
from harness.stacks.context import build_stack_context
from harness.tasks_lexicon_gate import run_tasks_lexicon_gate
from harness.understanding_gate import run_understanding_gate

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad_provider import SquadAgentResult, SquadCliProvider
    from harness.squad_state import SquadStateStore


_STAGED_VERDICT_STATE_KEYS = {
    "WHY3": "why3_verdict",
    "ASSESS2": "assess2_verdict",
}
_EXECUTOR_BLOCK_REASONS = frozenset(
    {
        "invalid_evidence_inventory",
        "missing_consensus_prerequisite",
        "repair_review_stale",
        "repair_review_missing",
        "repair_context_incomplete",
        "repair_action_unclassified",
        "repair_no_progress",
        "missing_phase_outputs",
        "invalid_phase_outputs",
    }
)
_JOURNAL_CONTEXT_MAX_BYTES = 24 * 1024
_DEFAULT_AGENT_TIMEOUT_SECONDS = 60 * 60
_DECLARED_OUTPUT_FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_.-]*\.(?:md|json|yaml|yml))(?![A-Za-z0-9_.-])"
)
_SAGE_REVIEW_OUTPUTS = ("issues.md", "quality-gates.md")
_WHY_STATE_CONTEXT_KEYS = (
    "run_id",
    "spec_id",
    "phase",
    "iteration",
    "max_iterations",
    "autonomy_mode",
    "implementation_targets",
    "user_message",
    "quality_gate_remediation",
    "selected_issue_resolution",
)


@dataclass(frozen=True)
class ExecutorBlockedResult:
    """Trusted executor recovery produced after provider validation."""

    reason: str
    result: "SquadAgentResult"

    def __post_init__(self) -> None:
        from harness.prepared_phase_result import detach_squad_agent_result
        from harness.squad_provider import SquadAgentResult

        if self.reason not in _EXECUTOR_BLOCK_REASONS:
            raise ControllerStateContractViolation(
                "unsupported executor block reason",
                contract="executor",
                json_path="$.executor_block.reason",
                validator="provenance",
            )
        if type(self.result) is not SquadAgentResult:
            raise ControllerStateContractViolation(
                "executor block result has an invalid type",
                contract="executor",
                json_path="$.executor_block.result",
                validator="provenance",
            )
        detached = detach_squad_agent_result(self.result)
        if detached.verdict != "BLOCKED":
            raise ControllerStateContractViolation(
                "executor block result must have a BLOCKED verdict",
                contract="executor",
                json_path="$.executor_block.result.verdict",
                validator="provenance",
            )
        if detached.state_updates.get("blocked_reason") != self.reason:
            raise ControllerStateContractViolation(
                "executor block reason does not match result state",
                contract="executor",
                json_path="$.executor_block.result.state_updates.blocked_reason",
                validator="provenance",
            )
        object.__setattr__(self, "result", detached)


def _shared_agent_contract() -> str:
    """Static cross-agent instructions injected before role-specific prompt text."""
    return (
        "You were dispatched as a subagent to execute a specific task.\n"
        "You are operating inside an Echelon squad phase, not a general interactive "
        "assistant session.\n"
        "Do NOT ask the user what they want to do next. Execute the assigned phase "
        "contract with the provided context and return `echelon_result`.\n\n"
        "## Shared Agent Contract\n"
        "### Endocrine Context\n"
        "- ALWAYS read any `[ENDOCRINE]` block in your dispatched context pack before "
        "producing output.\n"
        "- ALWAYS treat hormone levels and role-specific interpretation as behavior "
        "modulation for risk, confidence, pacing, and tone.\n"
        "- NEVER ignore endocrine state when it changes execution risk, confidence, "
        "or tone.\n"
        "### Published Reverse Engineering First\n"
        "- ALWAYS inspect the Published Reverse Engineering Context block when it is present.\n"
        "- NEVER ignore Published Reverse Engineering Context and rely only on memory or broad source search.\n"
        "- ALWAYS read the workspace RE briefing when `PUBLISHED_RE_STATUS=attached`.\n"
        "- NEVER skip the workspace RE briefing during brownfield Phase A or architecture/planning phases.\n"
        "- ALWAYS read matched source RE briefings before answering source-specific architecture, dependency, data-flow, domain, or implementation-location questions.\n"
        "- NEVER answer those questions from raw source search alone when matched source RE is attached.\n"
        "- ALWAYS consult CodeGraph summaries before raw source search for symbol, entry-point, dependency, or implementation-location questions.\n"
        "- NEVER jump directly to full source spelunking when CodeGraph summary evidence is available.\n"
        "- ALWAYS use only the run-local RE snapshot under `PUBLISHED_RE_SNAPSHOT_ROOT`.\n"
        "- NEVER read or mutate the canonical `re/` tree from a spec run.\n\n"
        "### Output And Journal Ownership\n"
        "- ALWAYS end your response with an `echelon_result` block using the "
        "agent-specific or phase-specific schema in your prompt.\n"
        "- ALWAYS put journal entries and state updates in `echelon_result`; the "
        "commander/harness reads that block and performs the writes.\n"
        "- NEVER write to `reasoning-journal.jsonl` directly.\n\n"
        "### Journal Single-Writer Guard\n"
        "- ALWAYS express any journal record as an item in "
        "`echelon_result.journal_entries`.\n"
        "- NEVER use Write, Edit, Bash redirection, `cat >>`, `tee`, or any other "
        "filesystem operation to modify `reasoning-journal.jsonl`.\n"
        "- NEVER repair, append, truncate, or normalize `reasoning-journal.jsonl`; "
        "the harness is the sole writer and will persist your returned entries.\n\n"
        "### Decision Escalation Boundary\n"
        "- Before returning `STOP_AND_ASK`, distinguish a missing human-owned "
        "decision from a reversible, internal product choice.\n"
        "- For a reversible, internal product choice, prefer resolving it within "
        "the phase. If a question must remain, include one concrete bounded "
        "`escalation_recommended_answer` and `escalation_risk_level: low | medium` "
        "supported by the supplied request and artifacts.\n"
        "- Preserving existing behavior, satisfying explicit requirements, internal "
        "consistency, simplicity, and reversibility are valid decision evidence; "
        "an external source is not required for an ordinary product default.\n"
        "- Leave a question without a recommendation only when it requires a "
        "user-owned fact or authorization, an unavailable external fact or access, "
        "a security/privacy/safety/legal/compliance policy, an irreversible or "
        "high-impact commitment, or resolution of contradictory explicit user "
        "requirements with no safe preserving choice.\n"
        "- Never invent an external fact or silently weaken an explicit requirement. "
        "The controller, not the provider, decides whether to apply a recommendation "
        "under Banzai, semi, or guided policy.\n\n"
        "### Belief Registers\n"
        "- ALWAYS read your agent-specific belief register when present at "
        "`${PROJECT_ROOT}/.echelon/runtime/config/"
        "belief-registers/<agent-slug>.yaml` before threshold, scoring, "
        "quality, or confidence decisions.\n"
        "- NEVER treat calibration priors as optional when a matching belief "
        "register exists.\n\n"
    )


def _read_prompt_body(path: Path) -> str:
    """Read a prompt markdown file and strip runtime frontmatter metadata."""
    return append_prompt_companions(
        read_prompt_markdown(path).body,
        prompt_package_roots(path),
    )


def _read_prompt_metadata(path: Path) -> dict[str, object]:
    """Read runtime frontmatter metadata from a prompt markdown file."""
    return dict(read_prompt_markdown(path).metadata)


_FALLBACK_ECHELON_RESULT_TEMPLATE = """# Echelon result contract template.
# The harness appends this template to every squad-agent prompt.
# Agents fill values, but must keep the unfenced YAML root shape.
#
# Rules:
# - ALWAYS include state_updates; use {} when no state changes are needed.
# - ALWAYS include journal_entries; use [] when no journal entries are needed.
# - Registered journal-entry types require `data` with all required fields from
#   .echelon/runtime/workflow/journal-entry-types.yaml.
# - NEVER wrap this block in markdown fences such as ```yaml or ```echelon_result.
# - NEVER emit `<echelon_result>` XML, JSON, or prose-only summaries as the contract.
# - NEVER put summaries, bullets, or sign-off text after the echelon_result block.
# - Include product_input_updates only when the Product Input Contract is present
#   and this agent proposes a ledger change. Its keys are a strict API contract:
#   input_unit_id, disposition, rationale, spec_ids, task_ids, targets.
# - NEVER use aliases such as unit, adopted, or mapped in product_input_updates.
# - YAML safety: double-quote every free-text scalar (for example rationale,
#   reasoning, and section), especially when it contains `:`, `#`, or quotes.

echelon_result:
  verdict: <DONE|COMPLETE|PASS|FAIL|BLOCKED|KILL|DEFER>
  output_files:
    - <path/to/artifact.md>
  state_updates: {}
  # Omit this section when there is no Product Input Contract or no ledger change.
  product_input_updates:
    - input_unit_id: <traceable IN-REQ-* ID from PRODUCT_INPUT_TRACEABILITY>
      disposition: <included|excluded|duplicate|open_question|conflict>
      rationale: "<evidence-backed reason for this disposition>"
      spec_ids: [FR-001, AC-001]
      task_ids: []
      targets: []
  journal_entries:
    - type: insight
      data:
        artifact: <artifact-or-file>
        section: <section-or-topic>
        reasoning: <grounded reason for this entry>
        confidence: <0.0-1.0>
        evidence_grade: <A|B|C|D|E>"""


def _canonical_echelon_result_contract(ext_dir: Path) -> str:
    """Return the final cross-agent output contract appended to every prompt."""
    template_path = ext_dir / "templates" / "echelon-result-template.yaml"
    template = (
        template_path.read_text(encoding="utf-8").strip()
        if template_path.exists()
        else _FALLBACK_ECHELON_RESULT_TEMPLATE
    )
    return (
        "\n\n---\n"
        "## Canonical echelon_result contract — REQUIRED FINAL BLOCK\n"
        "Use the template below exactly as the final response shape. Fill values, "
        "but do not change the root key or wrapper.\n\n"
        f"{template}"
    )


def _allowed_state_updates_contract(
    allowed_state_updates: object,
    *,
    required_state_updates: object = None,
    state_update_types: object = None,
    state_update_enums: object = None,
    allowed_verdicts: object = None,
) -> str:
    """Render the deterministic dispatch-scoped result contract."""
    required = {str(key) for key in (required_state_updates or [])}
    value_types = {
        str(key): str(value_type)
        for key, value_type in (state_update_types or {}).items()
    }
    value_enums = {
        str(key): list(values)
        for key, values in (state_update_enums or {}).items()
    }
    lines = [
        "\n\n---",
        "## Allowed state_updates for this dispatch",
        "The harness validates `echelon_result.state_updates` before mutating state.",
        "Return only the keys listed here; use `state_updates: {}` when no state",
        "changes are needed. Undeclared reporting-only keys are quarantined and",
        "never written to state. Missing or invalid required routing keys block.",
        "Put task counts, report summaries, evidence, and diagnostics in journal_entries, never state_updates.",
        "",
    ]
    if allowed_state_updates is None:
        lines.extend(
            [
                "Allowed keys: not declared for this phase.",
                "Prefer:",
                "```yaml",
                "state_updates: {}",
                "```",
            ]
        )
    else:
        keys = [str(key) for key in allowed_state_updates]
        if keys:
            lines.append("Allowed keys:")
            for key in keys:
                annotations = []
                if key in value_types:
                    annotations.append(value_types[key])
                if key in required:
                    annotations.append("required")
                if key in value_enums:
                    annotations.append(
                        "one of " + "|".join(str(value) for value in value_enums[key])
                    )
                suffix = f" ({', '.join(annotations)})" if annotations else ""
                lines.append(f"- `{key}`{suffix}")
        else:
            lines.extend(
                [
                    "Allowed keys: none.",
                    "```yaml",
                    "state_updates: {}",
                    "```",
                ]
            )
    if allowed_verdicts is not None:
        verdicts = [f"`{verdict}`" for verdict in allowed_verdicts]
        lines.extend(["", "Allowed verdicts: " + ", ".join(verdicts)])
    return "\n".join(lines)


def _workspace_source_roots_context(project_root: Path) -> str:
    """Render source-root boundaries for agent codebase operations."""
    try:
        from echelon.workspace_model import discover_workspace

        manifest = discover_workspace(project_root)
    except Exception:
        return (
            "## Workspace Source Roots\n"
            f"WORKSPACE_ROOT={project_root}\n"
            "- Source roots could not be resolved from workspace metadata.\n"
            "- Treat PROJECT_ROOT as orchestration context; inspect manifests before broad source-code searches.\n\n"
        )

    lines = [
        "## Workspace Source Roots",
        f"WORKSPACE_ROOT={manifest.workspace.root}",
        f"WORKSPACE_GIT_ROLE={manifest.workspace.git_role}",
    ]
    if manifest.sources:
        for source in manifest.sources:
            source_path = manifest.workspace.root if source.path == "." else manifest.workspace.root / source.path
            lines.append(f"SOURCE_ROOT[{source.id}]={source_path.resolve()}")
    else:
        lines.append("SOURCE_ROOTS=none")
    lines.extend(
        [
            "- PROJECT_ROOT is the Echelon orchestration workspace for runs, specs, config, and source-root manifests.",
            "- ALWAYS perform source-code reads, searches, edits, and tests inside SOURCE_ROOT paths.",
            "- NEVER treat PROJECT_ROOT as the source tree unless a SOURCE_ROOT entry points to PROJECT_ROOT.",
            "- NEVER search sibling directories outside WORKSPACE_ROOT for implementation source unless a phase explicitly provides that path.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_implementation_target_context(state: dict) -> str:
    """Render the immutable Phase A implementation boundary."""
    targets = [
        str(value).strip()
        for value in (state.get("implementation_targets") or [])
        if str(value).strip()
    ]
    if not targets:
        return ""
    lines = [
        "## Implementation Target Contract",
        "IMPLEMENTATION_TARGETS:",
        *(f"- {target}" for target in targets),
        "- Only these repositories are writable implementation destinations for this specification.",
        "- Other workspace sources are read-only evidence and reference context.",
        "- Do not infer or add another implementation target from source similarity, RE artifacts, file paths, or architecture preferences.",
        "- If required work cannot be assigned to one declared target, return BLOCKED and identify the missing target instead of changing scope.",
        "- Architecture, contracts, plans, tests, estimates, and tasks must use these targets consistently.",
        "",
    ]
    return "\n".join(lines)


def _render_spec_authoring_mode_context(state: dict, phase_id: str) -> str:
    """Render the controller-selected Cartographer strategy for WHAT only."""
    if phase_id != "phase1-what":
        return ""
    mode = normalize_spec_authoring_mode(state.get("spec_authoring_mode"))
    if mode == PERFECTIONIST_MODE:
        strategy = (
            "- Perform a systematic applicability review of every evidence-backed behavior "
            "and quality dimension before authoring. Cover materially distinct actors, paths, "
            "states, boundaries, integrations, quality constraints, uncertainty, scope, and "
            "traceability. An inapplicable dimension produces no requirement; insufficient "
            "evidence remains an explicit question, assumption, or evidence request."
        )
    else:
        strategy = (
            "- Produce the smallest complete evidence-backed specification. Classify the "
            "feature's discovered complexity and add scenarios, requirements, quality "
            "dimensions, and optional sections only when they materially apply."
        )
    return "\n".join(
        [
            "## Specification Authoring Mode",
            f"Mode: {mode}",
            strategy,
            "- One canonical requirement per distinct observable obligation; acceptance criteria are verification paths, not duplicate obligations.",
            "- Keep every requirement grounded, atomic, testable, and technology-neutral. Preserve unresolved facts instead of guessing.",
            "- Do not invent product behavior, entities, thresholds, or quality constraints, and do not use document-volume quotas as a proxy for rigor.",
            "",
        ]
    )


def _render_product_input_context(state: dict) -> str:
    """Render immutable product evidence pointers without embedding the corpus."""
    inputs = state.get("product_inputs")
    if not isinstance(inputs, dict) or not inputs:
        return ""
    required = ("manifest", "catalog", "traceability", "requirement_context", "reference_context")
    if not all(str(inputs.get(key) or "").strip() for key in required):
        return ""
    lines = [
        "## Product Input Contract",
        f"PRODUCT_INPUT_MANIFEST={inputs['manifest']}",
        f"PRODUCT_INPUT_CATALOG={inputs['catalog']}",
        f"PRODUCT_INPUT_TRACEABILITY={inputs['traceability']}",
        f"REQUIREMENT_INPUTS={inputs['requirement_context']}",
        f"REFERENCE_INPUTS={inputs['reference_context']}",
        "- Requirement inputs are normative; reference inputs are informative and cannot override them.",
        "- Read only immutable snapshot paths named by the manifest and catalog. Do not add undeclared inputs.",
        "- Cite only traceable requirement IDs listed in REQUIREMENT_INPUTS / PRODUCT_INPUT_TRACEABILITY when proposing ledger updates.",
        "- Catalog units absent from PRODUCT_INPUT_TRACEABILITY are context-only; never return them in product_input_updates.",
        "- Propose ledger changes only in echelon_result.product_input_updates; the controller validates and writes the canonical ledger.",
        "- Each product_input_updates item must contain exactly: input_unit_id, disposition, rationale, spec_ids, task_ids, targets.",
        "- disposition is exactly one of: included, excluded, duplicate, open_question, conflict. Never use aliases such as unit, adopted, or mapped.",
        "- YAML safety: double-quote every free-text scalar, especially rationale values containing ':', '#', or quotes.",
        "- In Phase 1, use spec_ids for FR/AC mappings and return task_ids: [] and targets: []. Later planning phases fill task_ids and targets.",
        "- Required item shape:",
        "  input_unit_id: <traceable IN-REQ-* ID from PRODUCT_INPUT_TRACEABILITY>",
        "  disposition: <included|excluded|duplicate|open_question|conflict>",
        '  rationale: "<evidence-backed reason for this disposition>"',
        "  spec_ids: [FR-001, AC-001]",
        "  task_ids: []",
        "  targets: []",
    ]
    attachments = state.get("product_input_attachments")
    if isinstance(attachments, list) and attachments:
        lines.extend([
            "",
            "## Added Reference Material",
            "- Preserve and extend prior investigation artifacts; do not restart evidence collection from scratch.",
        ])
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("id") or "").strip() or "(unknown)"
            request_ids = [
                str(item).strip()
                for item in attachment.get("linked_evidence_request_ids", [])
                if str(item).strip()
            ]
            intended_for = ", ".join(request_ids) if request_ids else "outstanding evidence requests"
            lines.append(f"- Attachment {attachment_id}: intended for {intended_for}.")
            declarations = attachment.get("declarations")
            if isinstance(declarations, list):
                for declaration in declarations:
                    if not isinstance(declaration, dict):
                        continue
                    role = str(declaration.get("role") or "").strip()
                    location = str(declaration.get("location") or "").strip()
                    if role or location:
                        lines.append(f"  - {role or 'input'}: {location}")
            resources = attachment.get("resources")
            if isinstance(resources, list):
                for resource in resources[:10]:
                    if not isinstance(resource, dict):
                        continue
                    snapshot = str(resource.get("snapshot") or "").strip()
                    if snapshot:
                        lines.append(f"  - snapshot: {snapshot}")
    repair = state.get("product_input_mapping_repair")
    if isinstance(repair, dict):
        blockers = repair.get("blockers")
        if isinstance(blockers, list) and blockers:
            is_phase_one_id_repair = repair.get("phase") == "phase1-what"
            lines.extend([
                "",
                "## Product Input Mapping Repair (Controller-Enforced)",
                "The prior result did not resolve these ledger entries:",
                *[f"- {str(blocker)}" for blocker in blockers],
            ])
            if is_phase_one_id_repair:
                invalid_ids = [
                    str(value) for value in repair.get("invalid_input_unit_ids", [])
                    if str(value).strip()
                ]
                valid_ids = [
                    str(value) for value in repair.get("valid_requirement_ids", [])
                    if str(value).strip()
                ]
                if invalid_ids:
                    lines.append(f"Invalid IDs from the prior result: {', '.join(invalid_ids)}")
                if valid_ids:
                    lines.append(f"Only these canonical IDs may be used: {', '.join(valid_ids)}")
                lines.extend([
                    "Never derive an ID from a requirement label; copy it exactly from the allowlist above.",
                    "Return only Phase 1 product_input_updates: use spec_ids for FR/AC mappings, with task_ids: [] and targets: [].",
                ])
            else:
                lines.extend([
                    "Read PRODUCT_INPUT_TRACEABILITY before editing tasks.",
                    "Return one canonical product_input_updates entry for every unresolved unit, "
                    "with task_ids whose req= values intersect that unit's spec_ids.",
                    "Do not return COMPLETE while any listed unit remains open_question or conflict.",
                ])
        candidates = repair.get("candidates")
        task_matrix = repair.get("task_requirement_matrix")
        if isinstance(candidates, list) or isinstance(task_matrix, list):
            lines.extend([
                "",
                "### Deterministic Mapping Worksheet",
                "The controller derived this worksheet from canonical task rows after rejecting the prior proposal.",
                "Do not repeat any task ID in an Invalid list. Use only a Direct list for its matching spec_ids.",
                "If a requirement has no direct task, first edit the existing tasks.md canonical row(s) so their req= values honestly cover it; only then return its mapping.",
                "For a structural/context-only input unit, return disposition: excluded with an evidence-backed rationale and empty spec_ids, task_ids, and targets.",
                "Do not use Write on an existing planning artifact: Read it, then use Edit.",
            ])
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                unit_id = str(candidate.get("input_unit_id") or "(unknown)")
                spec_ids = ", ".join(str(value) for value in candidate.get("spec_ids", []) if str(value)) or "(none)"
                direct = ", ".join(str(value) for value in candidate.get("direct_task_ids", []) if str(value)) or "(none)"
                invalid = ", ".join(str(value) for value in candidate.get("invalid_task_ids", []) if str(value)) or "(none)"
                lines.append(f"- {unit_id}: spec_ids=[{spec_ids}]; Direct task IDs=[{direct}]; Invalid task IDs=[{invalid}]")
        if isinstance(task_matrix, list):
            lines.append("Current canonical task requirement matrix:")
            for task in task_matrix:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id") or "(unknown)")
                requirements = ", ".join(str(value) for value in task.get("requirements", []) if str(value)) or "(none)"
                target = str(task.get("target") or "(none)")
                lines.append(f"- {task_id}: req=[{requirements}]; target={target}")
    if state.get("tasks_lexicon_pass") is False:
        report = str(
            state.get("tasks_lexicon_report")
            or "{spec_dir}/tasks-lexicon-report.json"
        )
        lines.extend([
            "",
            "## Tasks Lexicon Repair (Controller-Enforced)",
            "The previous PLAN result failed the tasks hard gate.",
            f"Read the controller finding report at `{report}` and repair every listed finding.",
            "Repair tasks.md and glossary.md so the controller-owned tasks validator can certify the artifact after dispatch.",
            "Do not report tasks_lexicon_pass yourself; the controller writes that verdict.",
        ])
    lines.append("")
    return "\n".join(lines)


def _render_controller_owned_prompt_context(state: dict) -> str:
    """Render immutable run inputs shared by every provider dispatch."""
    stack_context = render_stack_contract(state.get("stack_contract"))
    staging_dir = state.get("staging_dir")
    if not isinstance(staging_dir, str) or not staging_dir:
        return stack_context
    receipt_path = Path(staging_dir) / "user-clarifications.md"
    try:
        receipt = receipt_path.read_text(encoding="utf-8")
    except OSError:
        return stack_context
    if not receipt.strip():
        return stack_context
    return (
        stack_context
        + "## Resolved Clarifications\n\n"
        + receipt.strip()
        + "\n\n"
    )


def _render_banzai_evidence_reassessment_context(
    state: dict,
    phase_id: str,
) -> str:
    """Bind a WHY2 retry to its immutable, controller-recorded evidence."""
    if phase_id != "phase1-why2":
        return ""
    from harness.squad_state import (
        StateAdvanceError,
        validate_banzai_evidence_reassessment_record,
    )

    try:
        record = validate_banzai_evidence_reassessment_record(
            state.get("banzai_evidence_reassessment")
        )
    except StateAdvanceError as exc:
        raise ControllerStateContractViolation(
            "Banzai evidence reassessment ledger is invalid",
            contract="phase1-why2",
            json_path="$.banzai_evidence_reassessment",
            validator="evidence_binding",
        ) from exc
    if record is None or record["schema_version"] != 2:
        return ""
    squad_dir = Path(str(state.get("squad_dir") or ""))
    if not squad_dir.is_absolute():
        raise ControllerStateContractViolation(
            "Banzai evidence root is invalid",
            contract="phase1-why2",
            json_path="$.squad_dir",
            validator="evidence_binding",
        )
    sections: list[str] = []
    armed = [attempt for attempt in record["attempts"] if attempt["status"] == "armed"]
    if not armed:
        return ""
    for attempt in armed:
        candidate = squad_dir / str(attempt["evidence_path"])
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(squad_dir.resolve(strict=True))
            metadata = candidate.lstat()
            content = candidate.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ControllerStateContractViolation(
                "Banzai evidence snapshot is unavailable or escapes its run",
                contract="phase1-why2",
                json_path="$.banzai_evidence_reassessment.attempts",
                validator="evidence_binding",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or candidate.is_symlink()
            or len(content) > 262_144
            or hashlib.sha256(content).hexdigest() != attempt["evidence_sha256"]
        ):
            raise ControllerStateContractViolation(
                "Banzai evidence snapshot failed provenance validation",
                contract="phase1-why2",
                json_path="$.banzai_evidence_reassessment.attempts",
                validator="evidence_binding",
            )
        sections.append(content.decode("utf-8"))
    if not sections:
        return ""
    return (
        "## Controller-bound decision evidence\n\n"
        "The controller retrieved and sealed this evidence for the exact "
        "question that triggered the retry. Reassess the decision against it.\n\n"
        + "\n\n---\n\n".join(section.strip() for section in sections)
        + "\n\n"
    )


def _render_phase3_planning_mode_context(phase_id: str) -> str:
    """Disambiguate PLAN from staged PLAN2 without inspecting old artifacts."""
    if phase_id != "phase3-plan":
        return ""
    return (
        "## Controller Planning Invocation\n\n"
        "Operate in **first-pass** planning mode. This controller phase owns PLAN "
        "authoring or repair reconciliation; it is not staged PLAN2. An existing "
        "`implementability-report.md` can be evidence from an earlier consensus "
        "attempt and must not change the invocation mode.\n\n"
    )


def _render_controller_repair_context(state: dict) -> str:
    """Render controller-owned artifact findings for the next repair dispatch."""
    gates = (
        (
            "feasibility_structural_pass",
            "feasibility_structural_report",
            "feasibility.md",
        ),
        (
            "intent_alignment_check_structural_pass",
            "intent_alignment_check_structural_report",
            "intent-alignment-check.md",
        ),
    )
    sections: list[str] = []
    quality_remediation = state.get("quality_gate_remediation")
    if isinstance(quality_remediation, dict):
        evidence = quality_remediation.get("evidence")
        report = evidence.get("path") if isinstance(evidence, dict) else ""
        failed_gates: list[str] = []
        weak_requirements: dict[str, list[str]] = {}
        validated_issue_ids = sorted(
            str(issue_id)
            for issue_id, entry in (state.get("issue_resolution_ledger") or {}).items()
            if isinstance(entry, dict) and entry.get("status") == "validated"
        )
        if validated_issue_ids:
            stale_issue_instruction = (
                "This controller instruction OVERRIDES any stale `issues.md`, "
                "journal, or state text that tells you to resolve "
                + ", ".join(f"`{issue_id}`" for issue_id in validated_issue_ids)
                + ". Those decisions are already validated."
            )
        else:
            stale_issue_instruction = (
                "This controller instruction OVERRIDES any stale `issues.md`, "
                "journal, or state text that tries to reopen already validated "
                "issue decisions."
            )
        if isinstance(report, str) and report:
            try:
                payload = json.loads(Path(report).read_text(encoding="utf-8"))
                gates_payload = payload.get("gates")
                if isinstance(gates_payload, dict):
                    for name, gate in gates_payload.items():
                        if not isinstance(gate, dict) or gate.get("pass") is True:
                            continue
                        score = gate.get("score")
                        threshold = gate.get("threshold")
                        failed_gates.append(
                            f"{name} ({score} < required {threshold})"
                        )
                        if name == "overall":
                            continue
                        weak_requirements[str(name)] = []
                    per_requirement = payload.get("per_requirement")
                    if isinstance(per_requirement, list):
                        for item in per_requirement:
                            if not isinstance(item, dict):
                                continue
                            requirement_id = str(
                                item.get("requirement_id") or ""
                            ).strip()
                            metrics = item.get("metrics")
                            categories = (
                                metrics.get("category_averages")
                                if isinstance(metrics, dict)
                                else None
                            )
                            if not requirement_id or not isinstance(categories, dict):
                                continue
                            for category in weak_requirements:
                                gate = gates_payload.get(category)
                                threshold = (
                                    gate.get("threshold")
                                    if isinstance(gate, dict)
                                    else None
                                )
                                score = categories.get(category)
                                if (
                                    isinstance(threshold, (int, float))
                                    and isinstance(score, (int, float))
                                    and score < threshold
                                ):
                                    weak_requirements[category].append(requirement_id)
            except (OSError, ValueError, TypeError):
                # The evidence path is advisory context. The deterministic
                # gate remains the source of truth if an old report is gone.
                pass
        qualitative_findings = quality_remediation.get("qualitative_findings")
        rendered_qualitative_findings: list[str] = []
        if isinstance(qualitative_findings, list):
            for finding in qualitative_findings:
                if not isinstance(finding, dict):
                    continue
                issue_id = str(finding.get("issue_id") or "unknown").strip()
                route = str(finding.get("route") or "unknown").strip()
                rationale = str(finding.get("rationale") or "").strip()
                rendered = f"- `{issue_id}` (`{route}`)"
                if rationale:
                    rendered += f": {rationale}"
                rendered_qualitative_findings.append(rendered)
        sections.extend([
            "## Controller Quality-Gate Remediation",
            "All previously named issue resolutions are complete, but the certified "
            "Understanding review still fails. This is a fresh remediation cycle, "
            "not a request to repeat stale ISS findings.",
            stale_issue_instruction,
            "Do NOT invoke any `echelon spec resolve`, `echelon spec continue`, "
            "or other Echelon CLI command. You are the authoring agent; edit the "
            "active spec directly.",
            f"Read the certified report at `{report}` before editing." if report else "Read the current certified Understanding report before editing.",
            "Certified failing gates: " + ", ".join(failed_gates)
            if failed_gates
            else (
                "Certified numeric failing gates: none; use the current SAGE "
                "qualitative findings below as the repair checklist."
                if rendered_qualitative_findings
                else "Use the failing gates in the certified report as the repair checklist."
            ),
            "The Understanding gate scores only formal AC/FR/NFR requirement "
            "statements. Do not append diagrams, narrative, matrices, or test "
            "appendices as a substitute for editing those scored statements.",
            "Rewrite the affected requirements into atomic, independently testable "
            "statements with explicit actor, trigger, action, observable outcome, "
            "and measurable acceptance criteria. Add explicit conditional/error "
            "flows where the behavioral gate requires them.",
            "Edit `spec.md` during this phase. The controller compares its SHA-256 "
            "with the remediation baseline and rejects a DONE result with no spec "
            "change; a review-only response is invalid.",
            "For each compound requirement, split independently verifiable behavior "
            "into separately identified formal requirements or acceptance criteria. "
            "State explicit exclusions and invalid-combination behavior where relevant.",
            "Do not merely inspect, summarize, or confirm the existing ISS repairs. "
            "The required deliverable is an actual rewrite of the failing formal "
            "requirements for the certified metric families.",
            "Preserve the already-recorded issue decisions and do not re-open them. "
            "Return the normal required phase state updates after completing the "
            "specification remediation.",
            "",
        ])
        if rendered_qualitative_findings:
            sections.extend([
                "## Current SAGE Qualitative Findings",
                "Repair these current SAGE findings even when the certified numeric "
                "Understanding gates pass; they are logical contradictions or "
                "cross-artifact issues that metric-only evidence may not list.",
                *rendered_qualitative_findings,
                "",
            ])
        for category, requirement_ids in weak_requirements.items():
            if requirement_ids:
                sections.append(
                    "Certified weak requirement IDs for "
                    f"`{category}`: {', '.join(requirement_ids)}."
                )
        if weak_requirements:
            sections.append("")
    for pass_key, report_key, artifact in gates:
        if state.get(pass_key) is not False:
            continue
        report = str(state.get(report_key) or "").strip()
        if not report:
            continue
        sections.extend([
            "## Controller Structural Repair",
            f"The previous `{artifact}` failed the controller-owned structural gate.",
            f"Read `{report}` and repair every listed finding in `{artifact}`.",
            "Preserve sections that already pass and keep the artifact aligned with its template.",
            f"Do not report `{pass_key}` or run a validator; the controller certifies the file after dispatch.",
            "",
        ])
    output_recovery = state.get("phase_output_recovery")
    if isinstance(output_recovery, dict):
        phase = str(output_recovery.get("phase") or "").strip()
        missing = output_recovery.get("missing_outputs")
        invalid = output_recovery.get("invalid_outputs")
        prior_updates = output_recovery.get("prior_state_updates")
        if phase and state.get("phase", phase) == phase and (
            (isinstance(missing, list) and missing)
            or (isinstance(invalid, list) and invalid)
        ):
            rendered_missing = ", ".join(
                str(item) for item in missing if isinstance(item, str) and item
            ) if isinstance(missing, list) else ""
            rendered_invalid = ", ".join(
                f"{item.get('path')}: {item.get('reason')}"
                for item in invalid
                if isinstance(item, dict) and item.get("path") and item.get("reason")
            ) if isinstance(invalid, list) else ""
            sections.extend([
                "## Phase Output Repair",
                f"The prior `{phase}` result was valid except for required artifacts needing repair. Missing: {rendered_missing or '(none)'}. Invalid: {rendered_invalid or '(none)'}.",
                "Read the existing phase artifacts and repair only the named artifacts. Do not repeat external retrieval or discard established evidence unless the existing artifacts are contradictory or cannot support the required repair.",
                "Before returning, verify every required phase output exists. Return the prior routing state updates again after the artifacts are complete.",
            ])
            if rendered_invalid and phase == "phase1-investigate":
                sections.extend([
                    "### Non-negotiable invalid-artifact repair",
                    "The invalid artifact is not evidence and must not be treated as a completed result.",
                    "Do NOT respond that the prior investigation is already complete. Write a replacement for every invalid artifact, using the declared source seeds and the required schema. If the prior evidence cannot establish its source frontier, perform the necessary bounded source expansion before answering.",
                    "This retry intentionally excludes stale evidence reports and journal entries from its context. Use tools to inspect the declared inputs and create the replacement artifact on disk before returning `echelon_result`.",
                ])
            if isinstance(prior_updates, dict) and prior_updates:
                sections.extend([
                    "Prior routing state updates to preserve:",
                    "```json",
                    json.dumps(prior_updates, indent=2, sort_keys=True),
                    "```",
                ])
            sections.append("")
    return "\n".join(sections)


def _render_issue_resolution_context(state: dict) -> str:
    """Render the one issue decision a repair is authorized to apply or validate."""
    selected = str(state.get("selected_issue_resolution") or "").strip()
    ledger = state.get("issue_resolution_ledger")
    if not selected or not isinstance(ledger, dict):
        return ""
    entry = ledger.get(selected)
    if not isinstance(entry, dict) or entry.get("status") not in {"selected", "repaired"}:
        return ""
    status = str(entry.get("status") or "")
    if (status == "repaired" and entry.get("repair_phase") in {
            "phase3-how", "phase3-sentinel", "phase3-plan"}
            and str(state.get("phase", "")).startswith("phase3-")):
        return ""
    action = entry.get("repair_action")
    if isinstance(action, dict):
        if state.get("phase") != entry.get("repair_phase"):
            return ""
        return ("## Selected Technical Work (Controller-Owned; not a user decision)\n"
            f"Issue: {selected} — {entry.get('title', '')}\n"
            f"Action: {action.get('action', '')}\n"
            f"Owned artifacts: {', '.join(action.get('affected_artifacts', []))}\n"
            f"Read evidence: {', '.join(action.get('evidence_refs', []))}\n"
            f"Constraints: {'; '.join(action.get('constraints', []))}\n"
            "Preserve requirements and acceptance strength. Derive evidence or propose technical mechanisms; "
            "never present an unevidenced answer as fact. Do not edit spec.md or protected policy. "
            "Handoff cross-owner changes. Submission requires independent SAGE review.\n")
    validation_rules = ""
    if status == "repaired":
        validation_rules = (
            "- This repair is now under targeted validation. Compare the current "
            "affected artifacts with the exact guidance and decision above.\n"
            "- If the current affected artifacts implement that decision, OMIT this "
            "issue from `finding_routes` even when the aggregate Understanding "
            "gate still fails. Those aggregate failures may be caused by other "
            "issues.\n"
            "- Re-list this issue only when you can identify a concrete missing or "
            "contradictory part of its decision in the affected artifacts, citing the "
            "affected section and the missing detail. Never re-list it merely "
            "because it appeared in a prior issues.md or prior score report.\n"
        )
    return (
        "## Selected Issue Resolution (Controller-Owned)\n"
        f"- Issue: {selected} — {entry.get('title', '')}\n"
        f"- SAGE guidance: {entry.get('guidance', '')}\n"
        f"- User decision: {entry.get('decision', '')}\n"
        "- You MUST implement this named repair in the affected canonical artifacts "
        "identified by the current issues.md and decision above. Amend spec.md only "
        "when the named repair requires a specification change; a repair to discovery "
        "artifacts such as mental-model.md does not require an unrelated spec.md edit. "
        "Do not declare the issue advisory, defer it, or claim design readiness instead.\n"
        "- If the repair cannot be completed from the declared evidence, return FAIL "
        "with the exact missing evidence or user decision; do not advance.\n"
        "- Apply this decision only to the named issue. Do not claim that any "
        "other issue is resolved; the controller retains them in the ledger.\n\n"
        "- Your completion report MUST discuss only this selected issue. Never "
        "state or imply that all issues are resolved.\n\n"
        + validation_rules
    )


def _render_spec_lexicon_context(
    state: dict,
    dispatch: str,
    resolved_config: dict[str, object],
) -> str:
    """Render authoritative spec Lexicon configuration and repair evidence."""
    if dispatch != "phase1-lexicon-derive":
        return ""
    gate = resolved_config.get("lexicon_gate")
    gate = gate if isinstance(gate, dict) else {}
    artifacts = gate.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    spec_gate = artifacts.get("spec")
    spec_gate = spec_gate if isinstance(spec_gate, dict) else {}
    enabled = bool(gate.get("enabled", False)) and spec_gate.get("enabled", True) is not False
    artifact_type = str(spec_gate.get("type") or "spec")
    artifact_path = str(spec_gate.get("path") or "requirements.lexicon.md")
    source_path = str(spec_gate.get("source_ref") or "spec.md")
    glossary_path = str(
        spec_gate.get("glossary_file")
        or gate.get("glossary_file")
        or "glossary.md"
    )
    try:
        repair_limit = int(gate.get("max_repair_attempts", 3))
    except (TypeError, ValueError):
        repair_limit = 3
    lines = [
        "# Controller Configuration",
        "The Echelon harness resolved this phase-specific configuration before dispatch.",
        "Treat values inside `<controller_configuration>` as authoritative data. Do not discover or override these values.",
        "<controller_configuration>",
        "lexicon_gate:",
        f"  enabled: {str(enabled).lower()}",
        f"  artifact_type: {artifact_type}",
        f"  mode: {str(spec_gate.get('mode') or 'derived')}",
        f"  artifact_path: {artifact_path}",
        f"  source_path: {source_path}",
        f"  glossary_path: {glossary_path}",
        f"  max_repair_attempts: {repair_limit}",
        "</controller_configuration>",
        "When enabled, author the derived artifact using the declared paths and grammar. The provider-free phase1-lexicon node validates it after dispatch.",
        "When disabled, do not create or amend a derived Lexicon artifact.",
        "",
    ]
    report = str(state.get("lexicon_report") or "").strip()
    if state.get("lexicon_evaluation") == "failed" and report:
        try:
            attempt = max(0, int(state.get("lexicon_attempts", 0)))
        except (TypeError, ValueError):
            attempt = 0
        lines.extend([
            "# Spec Lexicon Repair (Controller-Enforced)",
            "The previous derived requirements artifact failed the controller-owned hard gate.",
            f"- Report: `{report}`",
            f"- Attempt: `{attempt}` of `{repair_limit}`",
            f"- Artifact: `{artifact_path}`",
            "Read the report and repair every listed finding in the configured artifact.",
            f"This dispatch is a Lexicon repair pass: update the configured artifact and return `{artifact_path}` in `output_files`.",
            "Do not edit spec.md or any other canonical source artifact.",
            "Do not declare specification quality, design readiness, spec completion, or downstream phase readiness.",
            "Preserve source IDs and sections that already satisfy the grammar.",
            "Validation execution and deterministic verdict reporting are controller-owned.",
            "",
        ])
        lines.extend(_render_spec_lexicon_repair_findings(report))
        lines.append("")
    return "\n".join(lines)


def _render_spec_lexicon_repair_findings(report: str) -> list[str]:
    """Render compact, actionable findings from a controller report."""
    report_path = Path(report)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return [
            "The report could not be read by the prompt renderer; the path above remains authoritative.",
        ]
    findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings, list):
        return ["The report does not contain a readable `findings[]` list."]
    counts: dict[str, int] = {}
    normalized: list[dict[str, object]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "unknown").strip() or "unknown"
        counts[code] = counts.get(code, 0) + 1
        normalized.append(item)
    lines = [f"- Finding count: `{len(normalized)}`"]
    if counts:
        lines.append("- Findings by code:")
        for code, count in sorted(counts.items()):
            lines.append(f"  - `{code}`: {count}")
    if normalized:
        lines.append("- First concrete findings:")
        for item in normalized[:8]:
            code = str(item.get("code") or "unknown").strip() or "unknown"
            message = str(item.get("message") or "").strip()
            span = str(item.get("span") or "").strip()
            line = item.get("line")
            try:
                line_text = f"line {int(line)}"
            except (TypeError, ValueError):
                line_text = "line unknown"
            detail = f"  - `{code}` at {line_text}"
            if span:
                detail += f", span `{span}`"
            if message:
                detail += f": {message}"
            lines.append(detail)
    return lines


def _render_certified_understanding_context(state: dict, dispatch: str) -> str:
    """Render concise controller evidence for SAGE validation dispatches."""
    expected_phase = {
        "phase1-why2": "phase1-why2",
        "WHY3": "phase3-consensus",
    }.get(dispatch)
    evidence = state.get("understanding_evidence")
    if expected_phase is None or not isinstance(evidence, dict):
        return ""
    if (
        evidence.get("phase") != expected_phase
        or evidence.get("status") != "completed"
    ):
        return ""
    failing = evidence.get("failing_gates")
    failing_gates = failing if isinstance(failing, list) else []
    rendered_failing = ", ".join(f"`{gate}`" for gate in failing_gates) or "none"
    certified_pass = str(bool(evidence.get("pass"))).lower()
    scores_line = ""
    overall_basis_line = ""
    report_ref = str(evidence.get("path") or "").strip()
    if report_ref:
        try:
            payload = json.loads(Path(report_ref).read_text(encoding="utf-8"))
            scores = payload.get("scores")
            if isinstance(scores, dict):
                scores_line = "- Certified scores: " + ", ".join(
                    f"{name}={value}"
                    for name, value in sorted(scores.items())
                    if isinstance(value, (int, float))
                ) + "\n"
            gates = payload.get("gates")
            overall = gates.get("overall") if isinstance(gates, dict) else None
            if isinstance(overall, dict):
                basis = str(overall.get("pass_basis") or "").strip()
                if basis:
                    overall_basis_line = f"- Overall pass basis: `{basis}`\n"
        except (OSError, ValueError, TypeError):
            pass
    return (
        "# Certified Understanding Evidence\n"
        "The Echelon controller produced this report before provider dispatch. "
        "Interpret it; do not recalculate or override its scores. These are the "
        "only current scores; never quote older scores from state.json, issues.md, "
        "or the reasoning journal.\n"
        f"- Report: `{evidence.get('path')}`\n"
        f"- Digest: `{evidence.get('digest')}`\n"
        f"- Iteration: `{evidence.get('iteration')}`\n"
        f"- Certified pass: `{certified_pass}`\n"
        f"- Failing gates: {rendered_failing}\n\n"
        f"{scores_line}{overall_basis_line}\n"
    )


def _render_published_re_context(state: dict) -> str:
    """Render the immutable published RE snapshot attached to this spec run."""
    context = state.get("published_re_context")
    if not isinstance(context, dict):
        return ""
    status = str(context.get("status") or "absent")
    lines = [
        "## Published Reverse Engineering Context",
        f"PUBLISHED_RE_STATUS={status}",
        f"PUBLISHED_RE_GENERATION={context.get('generation', 0)}",
    ]
    snapshot_root = str(context.get("snapshot_root") or "").strip()
    if snapshot_root:
        lines.append(f"PUBLISHED_RE_SNAPSHOT_ROOT={snapshot_root}")
    quality = context.get("synthesis_quality")
    if isinstance(quality, dict):
        lines.extend(
            [
                f"PUBLISHED_RE_INPUT_QUALITY={quality.get('input_quality', 'unknown')}",
                f"PUBLISHED_RE_FULL_QUALITY_CLAIM={quality.get('full_quality_claim', 'unavailable')}",
                "PUBLISHED_RE_DEBT_MANIFEST_HASHES="
                + ",".join(
                    str(item)
                    for item in quality.get("debt_manifest_hashes", [])
                    if isinstance(item, str)
                ),
            ]
        )
    artifacts = context.get("artifacts")
    if status == "attached" and isinstance(artifacts, dict):
        lines.extend(_render_published_re_briefings(context))
        lines.extend(
            [
                "PUBLISHED_RE_ARTIFACTS:",
                "```json",
                json.dumps(artifacts, indent=2, sort_keys=True),
                "```",
                "- Treat these run-local files as read-only evidence.",
                "- Do not run reverse engineering or read the mutable canonical re/ tree.",
            ]
        )
    elif status == "ignored":
        lines.append("- RE context was explicitly ignored for this run.")
    else:
        lines.append("- No published RE context was available when this run started.")
    lines.append("")
    return "\n".join(lines)


def _render_published_re_briefings(context: dict) -> list[str]:
    """Inline deterministic RE briefings generated in the run-local snapshot."""
    rendered = context.get("rendered_briefings")
    if not isinstance(rendered, dict):
        artifacts = context.get("artifacts")
        rendered = (
            artifacts.get("rendered_briefings")
            if isinstance(artifacts, dict)
            else None
        )
    if not isinstance(rendered, dict):
        return []

    lines: list[str] = []
    workspace = rendered.get("workspace")
    workspace_text = _read_re_briefing(workspace)
    if workspace_text:
        lines.extend(["## Published RE Workspace Briefing", workspace_text])

    sources = rendered.get("sources")
    if isinstance(sources, dict):
        for source_id in sorted(sources):
            source_text = _read_re_briefing(sources[source_id])
            if source_text:
                lines.extend([f"## Published RE Source Briefing: {source_id}", source_text])
    return lines


def _read_re_briefing(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    path = Path(value)
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


_MANDATORY_PHASE_OUTPUTS: dict[str, tuple[str, ...]] = {
    "phase1-what": ("spec.md", "requirements-overview.md"),
    "phase1-lexicon-derive": ("requirements.lexicon.md",),
    "phase1-investigate": (
        "evidence-resolution.md",
        "evidence-grades.md",
        "evidence-inventory.json",
    ),
    "phase3-how": ("plan.md", "research.md", "data-model.md", "contracts"),
    "phase3-sentinel": ("test-strategy.md", "test-architecture.md", "coverage-map.md"),
    "phase3-plan": ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"),
}


def _reference_url_seeds(state: dict) -> tuple[str, ...]:
    """Return declared URL entry points, without treating credentials as seeds."""
    inputs = state.get("product_inputs")
    if not isinstance(inputs, dict):
        return ()
    reference_context = Path(str(inputs.get("reference_context") or ""))
    try:
        text = reference_context.read_text(encoding="utf-8")
    except OSError:
        return ()
    # The reference context is controller-produced.  URLs are safe locators to
    # require in the inventory; never extract arbitrary text, which may include
    # access material supplied alongside a URL.
    return tuple(dict.fromkeys(re.findall(r"https?://[^\s<>()]+", text)))


def _validate_evidence_inventory(
    path: Path, *, required_seed_locators: tuple[str, ...] = ()
) -> str | None:
    """Return a structural error for an evidence inventory, or ``None`` when valid."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return "root must be an object"
    if payload.get("schema_version") != 1:
        return "schema_version must equal 1"
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return "missing required list: sources"
    if not sources:
        return "sources must not be empty"
    required_source_fields = (
        "id",
        "locator",
        "kind",
        "status",
        "disposition",
        "discovered_from",
        "discovery_method",
    )
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            return f"sources[{index}] must be an object"
        for field in required_source_fields:
            if not isinstance(source.get(field), str) or not source[field].strip():
                return f"sources[{index}].{field} must be a non-empty string"
    frontier = payload.get("frontier")
    if not isinstance(frontier, dict):
        return "missing required object: frontier"
    if not isinstance(frontier.get("disposition"), str) or not frontier["disposition"].strip():
        return "frontier.disposition must be a non-empty string"
    unvisited = frontier.get("unvisited_relevant_sources")
    if not isinstance(unvisited, list) or not all(
        isinstance(source, str) and source.strip() for source in unvisited
    ):
        return "frontier.unvisited_relevant_sources must be a list of non-empty strings"
    expanded_seeds = frontier.get("expanded_seed_locators")
    if not isinstance(expanded_seeds, list) or not all(
        isinstance(source, str) and source.strip() for source in expanded_seeds
    ):
        return "frontier.expanded_seed_locators must be a list of non-empty strings"
    inventory_locators = {str(source["locator"]).strip() for source in sources}
    missing_seeds = [seed for seed in required_seed_locators if seed not in inventory_locators]
    if missing_seeds:
        return "missing declared source seed(s): " + ", ".join(missing_seeds)
    missing_expanded_seeds = [
        seed for seed in required_seed_locators if seed not in expanded_seeds
    ]
    if missing_expanded_seeds:
        return "frontier does not account for declared source seed(s): " + ", ".join(
            missing_expanded_seeds
        )
    return None


def _normalize_spec_dir_ref(spec_dir_ref: str, project_root: Path) -> str:
    """Return a robust repo-relative/absolute spec_dir reference.

    During squad phases, spec_dir is allowed to point at the active run copy
    under runs/<run>/specs/<spec>. Do not rewrite it back to PROJECT_ROOT/specs;
    the published project specs directory is a separate target/build artifact.
    """
    ref = (spec_dir_ref or "").strip()
    if not ref:
        return ""

    candidate = Path(ref)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(project_root))
        except ValueError:
            return str(candidate)

    return ref


def _spec_search_bases(spec_dir_ref: str, project_root: Path, staging_dir: str) -> list[Path]:
    bases: list[Path] = []
    if spec_dir_ref:
        spec_dir = Path(spec_dir_ref)
        if not spec_dir.is_absolute():
            spec_dir = project_root / spec_dir
        bases.append(spec_dir)
    bases.extend([Path(staging_dir), project_root])
    return bases


def _render_active_spec_roots_context(
    spec_dir_ref: str,
    state: dict,
    project_root: Path,
) -> str:
    """Render the authoritative active and published spec artifact roots."""
    if not spec_dir_ref:
        return ""

    spec_dir_path = Path(spec_dir_ref)
    if not spec_dir_path.is_absolute():
        spec_dir_path = project_root / spec_dir_path
    spec_dir_path = spec_dir_path.resolve()

    published_ref = str(state.get("published_spec_dir") or "").strip()
    if not published_ref:
        published_ref = f"specs/{spec_dir_path.name}" if spec_dir_path.name else ""
    if not published_ref:
        return ""

    published_path = Path(published_ref)
    if not published_path.is_absolute():
        published_path = project_root / published_path
    published_path = published_path.resolve()

    return (
        "## Active Spec Artifact Roots\n"
        f"ACTIVE_SPEC_DIR={spec_dir_path}\n"
        f"PUBLISHED_SPEC_DIR={published_path}\n"
        "- ALWAYS read and write squad phase artifacts under ACTIVE_SPEC_DIR / `{spec_dir}`.\n"
        "- NEVER switch to PUBLISHED_SPEC_DIR during squad phase execution unless a phase explicitly asks for publication.\n"
        "- PUBLISHED_SPEC_DIR is the final project target used by build/harness after publication.\n"
        "- Every injected artifact heading below is the resolved filesystem path that was read.\n\n"
    )


def _context_pack_filters(item: str) -> dict[str, str]:
    """Parse the optional ``[key=value]`` selector on a context-pack item."""
    match = re.search(r"\[([^\]]+)\]", item)
    if match is None:
        return {}
    filters: dict[str, str] = {}
    for part in match.group(1).split(","):
        key, separator, value = part.partition("=")
        if separator and key.strip() and value.strip():
            filters[key.strip()] = value.strip()
    return filters


def _render_reasoning_journal_context(
    candidate: Path,
    filters: dict[str, str],
) -> str:
    """Render only the requested, bounded journal evidence for an agent."""
    resolved = candidate.resolve()
    try:
        entries = [
            json.loads(line)
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError):
        return f"\n---\n# {resolved}\n[Journal unavailable or malformed]"

    requested_type = filters.get("type")
    # ``routing_decision`` is the historic context-pack selector for durable
    # decision records, whose canonical journal type is ``decision``.
    if requested_type == "routing_decision":
        requested_type = "decision"
    selected = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and (not requested_type or entry.get("type") == requested_type)
        and (not filters.get("phase") or entry.get("phase") == filters["phase"])
    ]
    rendered: list[str] = []
    used = 0
    for entry in reversed(selected):
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        line_bytes = len(line.encode("utf-8")) + 1
        if line_bytes > _JOURNAL_CONTEXT_MAX_BYTES:
            # A single verbose historical entry must not consume the entire
            # SAGE budget or hide the rest of the current decision trail.
            continue
        if rendered and used + line_bytes > _JOURNAL_CONTEXT_MAX_BYTES:
            break
        rendered.append(line)
        used += line_bytes
    rendered.reverse()
    selector = ", ".join(f"{key}={value}" for key, value in sorted(filters.items()))
    header = (
        f"\n---\n# {resolved}\n"
        f"[Journal context: {len(rendered)}/{len(selected)} matching entries"
        f"{f'; {selector}' if selector else ''}; newest entries retained]"
    )
    return header + ("\n" + "\n".join(rendered) if rendered else "\n[No matching entries]")


def _render_why_state_context(state: dict) -> str:
    """Give SAGE current routing facts without injecting stale run history."""
    projection = {
        key: state[key]
        for key in _WHY_STATE_CONTEXT_KEYS
        if key in state
    }
    ledger = state.get("issue_resolution_ledger")
    if isinstance(ledger, dict):
        projection["issue_resolution_statuses"] = {
            str(issue_id): str(entry.get("status") or "unknown")
            for issue_id, entry in ledger.items()
            if isinstance(entry, dict)
        }
    return "\n---\n# Current controller state (WHY projection)\n" + json.dumps(
        projection, indent=2, ensure_ascii=False, sort_keys=True
    )


def _render_context_candidate(
    file_ref: str,
    candidate: Path,
    *,
    filters: dict[str, str] | None = None,
) -> str:
    """Render a context-pack file or directory into deterministic prompt text."""
    if candidate.name == "reasoning-journal.jsonl":
        return _render_reasoning_journal_context(candidate, filters or {})
    resolved_candidate = candidate.resolve()
    if candidate.is_dir():
        chunks = [f"\n---\n# {resolved_candidate.as_posix().rstrip('/')}/"]
        for path in sorted(p for p in candidate.rglob("*") if p.is_file()):
            rel = path.relative_to(candidate)
            display = f"{resolved_candidate.as_posix().rstrip('/')}/{rel.as_posix()}"
            chunks.append(
                f"\n## {display}\n"
                f"{path.read_text(encoding='utf-8', errors='replace')}"
            )
        return "\n".join(chunks)
    return (
        f"\n---\n# {resolved_candidate.as_posix()}\n"
        f"{candidate.read_text(encoding='utf-8', errors='replace')}"
    )


def _render_user_request_context(state: dict) -> RenderedSection:
    """Render the controller-owned original request for declared consumers."""
    user_request = state.get("user_message")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ControllerStateContractViolation(
            "declared user request is missing from controller state",
            contract="user_request_context",
            json_path="$.user_message",
            validator="required",
        )
    text = (
        "\n---\n# Original user request (immutable run input)\n"
        "Explicit user requirements are authoritative. Preserve every distinct "
        "requested outcome unless a controller-recorded user decision changes it.\n"
        "<user_request>\n"
        f"{user_request.strip()}\n"
        "</user_request>"
    )
    return RenderedSection(
        "Original user request (immutable run input)",
        text,
        len(text.encode("utf-8")),
        {"source": "controller_state.user_message"},
    )


def _routing_contract(node: "PhaseNode") -> str:
    """Build a compact echelon_result contract from the phase's transition conditions.

    Scans condition expressions to derive which state_updates fields the harness
    reads for routing, then returns a hint block to append at the end of the prompt.
    Returns empty string when no agent-written fields are needed.
    """
    condition_text = " ".join(t.get("condition", "") for t in (node.transitions or []))
    if not condition_text.strip():
        return ""

    fields: list[tuple[str, str]] = []

    if "quality_gates" in condition_text or "CRITICAL_issues" in condition_text:
        if node.id == "phase1-why2":
            fields.append((
                "quality_scores",
                "\n      - pass: <true|false>"
                "\n        pass_id: \"WHY2-iter-{N}\""
                "\n        overall: <float|null>"
                "\n        structure: <float|null>"
                "\n        readability: <float|null>"
                "\n        cognitive: <float|null>"
                "\n        semantic: <float|null>"
                "\n        testability: <float|null>"
                "\n        behavioral: <float|null>"
                "\n        depth: <float|null>",
            ))
        else:
            fields.append((
                "quality_scores",
                "[{pass: true}]  # true=PASS, false=FAIL",
            ))

    # phase-specific verdict fields e.g. why3-verdict, assess2-verdict
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*-verdict)\b", condition_text):
        key = m.group(1).replace("-", "_")
        if not any(f[0] == key for f in fields):
            fields.append((key, "PASS | FAIL | REJECTED"))

    if re.search(r"\balignment\s*=", condition_text):
        fields.append(("alignment", "ALIGNED | DRIFT | STOP_AND_ASK"))

    if re.search(r"\blexicon_(?:pass|evaluation)\b", condition_text):
        if node.id != "phase1-what":
            fields.append(("lexicon_pass", "true | false  # required when the spec Lexicon gate is enabled"))
            fields.append(("lexicon_attempts", "<integer>"))
            fields.append(("lexicon_findings", "<integer>"))

    if "tasks_lexicon_pass" in condition_text:
        if node.id != "phase3-plan":
            fields.append(("tasks_lexicon_pass", "true | false  # required when the tasks Lexicon gate is enabled"))
        fields.append(("tasks_lexicon_attempts", "<integer>"))

    if not fields:
        return ""

    lines = [
        "\n\n---",
        "## Harness routing contract — REQUIRED",
        "The harness reads these `echelon_result.state_updates` fields to route to the",
        "next phase. Missing or absent fields prevent correct routing.",
        "",
        "```yaml",
        "echelon_result:",
        "  verdict: <DONE|FAIL|BLOCKED|COMPLETE|...>  # always required",
        "  state_updates:",
    ]
    for field, hint in fields:
        if hint.startswith("\n"):
            lines.append(f"    {field}:{hint}")
        else:
            lines.append(f"    {field}: {hint}")
    lines.append("```")
    return "\n".join(lines)


class PhaseExecutor(ABC):
    def __init__(
        self,
        provider: "SquadCliProvider",
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._provider = provider
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        from harness.paths import runs_dir as _runs_dir
        self._squad_dir = squad_dir if squad_dir is not None else _runs_dir(project_root)

    def _phase_prompt_metadata(
        self,
        node: "PhaseNode",
        state: dict,
        prompt_metadata: dict[str, object],
        *,
        agent_id: str | None = None,
        outputs: object | None = None,
    ) -> dict[str, object]:
        """Attach a narrow provider write scope for a review-only SAGE pass.

        WHY2 and WHY3 review existing artifacts. The role may publish its own
        reports, but must never mutate the artifact it certifies. Enforcing that
        boundary in the provider prevents an unauthorized spec edit from
        invalidating Understanding evidence after the deterministic gate runs.
        """
        metadata = dict(prompt_metadata)
        resolved_agent = str(agent_id or node.agent or "").strip()
        if resolved_agent != "echelon.sage" or node.id not in {
            "phase1-why2",
            "phase3-consensus",
        }:
            return metadata

        spec_dir_ref = _normalize_spec_dir_ref(
            str(state.get("spec_dir") or "").strip(), self._project_root
        )
        if not spec_dir_ref:
            return metadata
        spec_dir = Path(spec_dir_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir

        declared_outputs = (
            outputs if outputs is not None else getattr(node, "outputs", [])
        )
        filenames = set(_SAGE_REVIEW_OUTPUTS)
        if isinstance(declared_outputs, list):
            for declared in declared_outputs:
                if isinstance(declared, str):
                    filenames.update(_DECLARED_OUTPUT_FILE_RE.findall(declared))

        metadata["tool_write_paths"] = [
            str((spec_dir / filename).resolve(strict=False))
            for filename in sorted(filenames)
        ]
        # `:workspace` is normally writable. Codex consumes this explicit flag
        # to make the declared reports the only writable product paths.
        metadata["tool_write_scope_exclusive"] = True
        return metadata

    def _result_contract(self, node: "PhaseNode", agent_entry: dict | None = None):
        """Resolve the narrowest contract for this concrete agent dispatch."""
        from harness.echelon_result_schema import EchelonResultContract

        if hasattr(node, "result_contract"):
            return node.result_contract(agent_entry)
        entry = agent_entry or {}
        allowed = entry.get(
            "allowed_state_updates", getattr(node, "allowed_state_updates", None)
        )
        required = entry.get(
            "required_state_updates", getattr(node, "required_state_updates", [])
        )
        value_types = entry.get(
            "state_update_types", getattr(node, "state_update_types", {})
        )
        value_enums = entry.get(
            "state_update_enums", getattr(node, "state_update_enums", {})
        )
        verdicts = entry.get(
            "allowed_verdicts", getattr(node, "allowed_verdicts", None)
        )
        unexpected = entry.get(
            "unexpected_state_updates",
            getattr(node, "unexpected_state_updates", "quarantine"),
        )
        evidence_routing = entry.get(
            "evidence_routing", getattr(node, "evidence_routing", "none")
        )
        return EchelonResultContract(
            allowed_state_update_keys=(
                frozenset(str(key) for key in allowed)
                if allowed is not None
                else None
            ),
            required_state_update_keys=frozenset(str(key) for key in (required or [])),
            state_update_types={
                str(key): str(value_type)
                for key, value_type in (value_types or {}).items()
            },
            state_update_enums={
                str(key): frozenset(values)
                for key, values in (value_enums or {}).items()
            },
            allowed_verdicts=(
                frozenset(str(verdict) for verdict in verdicts)
                if verdicts is not None
                else None
            ),
            unexpected_state_updates=str(unexpected),
            evidence_routing=str(evidence_routing),
        )

    def _exec_agent_with_contract(
        self,
        prompt: str,
        result_contract,
        prompt_metadata: dict[str, object] | None = None,
    ):
        """Use provider-side result-only repair when the provider supports it."""
        kwargs: dict[str, object] = {}
        execution = self._resolved_config().get("execution", {})
        timeout_seconds = (
            execution.get("agent_timeout_seconds")
            if isinstance(execution, dict)
            else None
        )
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            timeout_seconds = _DEFAULT_AGENT_TIMEOUT_SECONDS
        kwargs["timeout_ms"] = int(timeout_seconds * 1000)
        if getattr(self._provider, "supports_result_contract", False):
            kwargs["result_contract"] = result_contract
        try:
            parameters = inspect.signature(self._provider.exec_agent).parameters.values()
            accepts_prompt_metadata = any(
                parameter.name == "prompt_metadata"
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_prompt_metadata = False
        accepts_prompt_metadata = bool(
            getattr(
                self._provider,
                "accepts_prompt_metadata",
                accepts_prompt_metadata,
            )
        )
        if getattr(self._provider, "supports_prompt_metadata", False) or (
            prompt_metadata and accepts_prompt_metadata
        ):
            kwargs["prompt_metadata"] = prompt_metadata or {}
        raw_result = self._provider.exec_agent(
            str(self._project_root),
            prompt,
            **kwargs,
        )
        from harness.prepared_phase_result import detach_squad_agent_result

        return detach_squad_agent_result(raw_result)

    def _project_config_path(self) -> Path:
        return self._project_root / ".echelon" / "config.yml"

    def _quality_gate_thresholds(self) -> dict:
        return resolve_quality_gate_thresholds(
            self._project_root,
        )

    def _resolved_config(self) -> dict[str, object]:
        from harness.config import get_full_resolved_config

        return get_full_resolved_config(self._project_root)

    def _normalize_why_result_quality_scores(
        self,
        node: "PhaseNode",
        result: "SquadAgentResult",
    ) -> None:
        if node.id not in {"phase1-why1", "phase1-why2"}:
            return
        updates = result.state_updates
        if "quality_scores" not in updates:
            return
        updates["quality_scores"] = normalize_why_quality_scores(
            updates["quality_scores"],
            verdict=result.verdict,
            gates=self._quality_gate_thresholds(),
        )

    def _validate_result_state_updates(
        self,
        node: "PhaseNode",
        result: "SquadAgentResult",
        allowed_state_updates: object = None,
        result_contract=None,
        *,
        direct_state_write: bool = False,
    ) -> "SquadAgentResult":
        """Validate result state updates before executor-side direct state writes."""
        if result.echelon_result is None:
            return result

        from harness.echelon_result_schema import (
            EchelonResultContract,
            EchelonResultValidationError,
            validate_echelon_result,
            validate_echelon_result_contract,
        )
        from harness.squad_provider import SquadAgentResult

        verdict = (result.verdict or "").upper()
        blocking_verdict = verdict in {"BLOCKED", "STOP_AND_ASK"}
        if direct_state_write and not blocking_verdict:
            reserved_updates = store_owned_update_keys(result.state_updates)
            if reserved_updates:
                key = sorted(reserved_updates)[0]
                raise ControllerStateContractViolation(
                    "provider attempted a transaction-owned state update",
                    contract="provider",
                    json_path=f"$.state_updates.{key}",
                    validator="ownership",
                )

        try:
            self._normalize_why_result_quality_scores(node, result)
            if verdict == "BLOCKED" or (direct_state_write and blocking_verdict):
                # BLOCKED results are consumed by the controller as harness-owned
                # blocked-state metadata, not applied through phase state_updates.
                result.echelon_result = validate_echelon_result(result.echelon_result)
                return result
            contract = result_contract or self._result_contract(node)
            if allowed_state_updates is not None:
                contract = EchelonResultContract(
                    allowed_state_update_keys=frozenset(allowed_state_updates),
                    required_state_update_keys=contract.required_state_update_keys,
                    state_update_types=contract.state_update_types,
                    state_update_enums=contract.state_update_enums,
                    allowed_verdicts=contract.allowed_verdicts,
                    unexpected_state_updates=contract.unexpected_state_updates,
                    evidence_routing=contract.evidence_routing,
                )
            outcome = validate_echelon_result_contract(
                result.echelon_result,
                contract,
            )
            result.echelon_result = outcome.result
            if outcome.quarantined_state_updates:
                result.quarantined_state_updates.update(
                    outcome.quarantined_state_updates
                )
            return result
        except EchelonResultValidationError as exc:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {
                        "blocked_reason": (
                            f"echelon_result validation failed: {exc}"
                        ),
                    },
                    "journal_entries": [],
                },
                raw_output=result.raw_output,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
                cost_usd=result.cost_usd,
            )

    @abstractmethod
    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult | ExecutorBlockedResult":
        ...

    def _write_journal_entries(
        self, result: "SquadAgentResult", phase_id: str
    ) -> None:
        """Append agent journal entries through the shared durable store."""
        from harness.journal_entry_validator import (
            append_reasoning_journal_entries,
        )

        entries = list((result.echelon_result or {}).get("journal_entries", []))
        if result.quarantined_state_updates:
            entries.insert(
                0,
                {
                    "type": "state_contract_warning",
                    "agent": "echelon-commander",
                    "data": {
                        "dropped_keys": sorted(result.quarantined_state_updates),
                        "action": "quarantined",
                        "reason": (
                            "undeclared reporting fields were excluded from the "
                            "state mutation control plane"
                        ),
                    },
                },
            )
        if not entries:
            return
        append_reasoning_journal_entries(
            self._squad_dir,
            entries,
            phase_id=phase_id,
            schema_path=self._ext_dir / "workflow/journal-entry-types.yaml",
            invalid_registered_policy="quarantine",
        )

    def _extension_path_context(self) -> str:
        return (
            f"RUNTIME_DIR={self._ext_dir}\n"
            f"RUNTIME_TEMPLATES_DIR={self._ext_dir / 'templates'}\n"
            "\n"
            "## Runtime Path Resolution\n"
            "- `.echelon/runtime/templates/foo.md` resolves to `${RUNTIME_TEMPLATES_DIR}/foo.md`.\n"
            "- Use only explicit `.echelon/runtime/...` paths for deployed runtime assets.\n\n"
        )

    def _stack_context(self, spec_dir_ref: str) -> str:
        """Resolve explicit project stacks before every Phase A agent dispatch."""
        from harness.config import load_config

        config = load_config(self._project_root, squad_only=True)
        spec_dir = Path(spec_dir_ref) if spec_dir_ref else None
        if spec_dir is not None and not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        return build_stack_context(
            self._project_root,
            selected_stacks=config.stacks.selected,
            target_archetypes=config.stacks.target_archetypes,
            spec_dir=spec_dir,
        )

    def _render_context_pack_item(
        self,
        *,
        item: str,
        node_id: str,
        agent_id: str,
        mode: str,
        state: dict,
        search_bases: list[Path],
        translate_ref,
    ) -> RenderedSection | None:
        selector = parse_context_pack_item(item)
        if not selector.path_ref or selector.path_ref.startswith("#"):
            return None
        resolved = translate_ref(selector.path_ref)
        candidates = [Path(resolved)] if resolved.startswith("/") else [
            base / resolved for base in search_bases
        ]
        for candidate in candidates:
            if candidate.exists():
                policy = policy_for_context(
                    phase_id=node_id,
                    agent_id=agent_id,
                    mode=mode,
                    path_ref=selector.path_ref,
                )
                return render_context_path(
                    selector.path_ref,
                    candidate,
                    policy,
                    selector.filters,
                    state=state,
                    phase_id=node_id,
                )
        return None

    def _assemble_prompt(self, node: "PhaseNode", state: dict) -> str:
        static_parts: list[str] = []
        selected_dynamic_parts: list[str] = []
        legacy_sections: list[RenderedSection] = []
        bounded_sections: list[RenderedSection] = []
        selected_render_mode = resolve_context_render_mode()
        output_recovery = state.get("phase_output_recovery")
        isolated_invalid_inventory_repair = (
            node.id == "phase1-investigate"
            and isinstance(output_recovery, dict)
            and output_recovery.get("phase") == node.id
            and isinstance(output_recovery.get("invalid_outputs"), list)
            and bool(output_recovery["invalid_outputs"])
        )

        # Resolve run dirs early — needed for both context pack file reads and
        # the text-level translation applied to agent/spec file content below.
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))

        def _translate_context_ref(ref: str) -> str:
            return (
                ref.replace("{spec_dir}", spec_dir_ref)
                .replace("{squad_dir}", squad_dir_str)
                .replace("{context_dir}", context_dir_str)
                .replace("{staging_dir}", staging_dir_str)
            )

        # 1. Agent file (role + instructions)
        if node.agent:
            rel = self._graph.agent_file(node.agent)
            if rel:
                agent_path = self._ext_dir / rel
                if agent_path.exists():
                    static_parts.append(_read_prompt_body(agent_path))

        # 2. Phase spec file (context pack assembly instructions + echelon_result schema)
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                static_parts.append(_read_prompt_body(spec_path))

        # 3. Context pack files (read each that exists on disk).
        spec_dir_ref = _normalize_spec_dir_ref(
            str(state.get("spec_dir") or "").strip(),
            self._project_root,
        )
        search_bases = _spec_search_bases(spec_dir_ref, self._project_root, staging_dir_str)
        for item in node.context_pack:
            if isolated_invalid_inventory_repair and (
                item.startswith("{spec_dir}/evidence-resolution.md")
                or item.startswith("{spec_dir}/investigation/")
                or item.startswith("{spec_dir}/evidence-inventory.json")
                or item.startswith("{squad_dir}/reasoning-journal.jsonl")
            ):
                continue
            if str(item).strip() == "user_request":
                request_section = _render_user_request_context(state)
                legacy_sections.append(request_section)
                bounded_sections.append(request_section)
                selected_dynamic_parts.append(request_section.text)
                continue
            selector = parse_context_pack_item(item)
            file_ref = selector.path_ref
            if not file_ref or file_ref.startswith("#"):
                continue
            resolved = _translate_context_ref(file_ref)
            if resolved.startswith("/"):
                candidates = [Path(resolved)]
            else:
                candidates = [base / resolved for base in search_bases]
            legacy_section = None
            for candidate in candidates:
                if candidate.exists():
                    legacy_text = _render_context_candidate(
                        file_ref,
                        candidate,
                        filters=selector.filters,
                    )
                    legacy_section = RenderedSection(
                        str(candidate.resolve()),
                        legacy_text,
                        len(legacy_text.encode("utf-8")),
                        {},
                    )
                    legacy_sections.append(legacy_section)
                    break
            bounded_section = self._render_context_pack_item(
                item=item,
                node_id=node.id,
                agent_id=str(node.agent or ""),
                mode=str(getattr(node, "mode", "") or node.id),
                state=state,
                search_bases=search_bases,
                translate_ref=_translate_context_ref,
            )
            if bounded_section is not None:
                bounded_sections.append(bounded_section)
            if selected_render_mode == "legacy":
                if legacy_section is not None:
                    selected_dynamic_parts.append(legacy_section.text)
            elif bounded_section is not None:
                selected_dynamic_parts.append(bounded_section.text)

        # 4. Current state.json for context
        state_path = self._squad_dir / "state.json"
        legacy_state_text = ""
        if node.id in {"phase1-why1", "phase1-why2"}:
            legacy_state_text = _render_why_state_context(state)
        elif state_path.exists():
            legacy_state_text = f"\n---\n# Current state.json\n{state_path.read_text()}"
        if legacy_state_text:
            legacy_sections.append(
                RenderedSection(
                    "Current state.json",
                    legacy_state_text,
                    len(legacy_state_text.encode("utf-8")),
                    {},
                )
            )
        bounded_state = dict(state)
        if state_path.exists():
            try:
                persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                persisted_state = {}
            if isinstance(persisted_state, dict):
                bounded_state = {**persisted_state, **state}
        state_projection = compact_state_projection(
            bounded_state,
            node.id,
            getattr(node, "allowed_state_updates", None),
        )
        if (
            isinstance(state_projection.get("understanding_evidence"), dict)
            and state_projection["understanding_evidence"].get("phase") == node.id
        ):
            state_projection.pop("understanding_evidence", None)
        state_text = json.dumps(state_projection, indent=2, ensure_ascii=False, sort_keys=True)
        bounded_state_text = "\n---\n# Current controller state (compact projection)\n" + state_text
        bounded_state_section = RenderedSection(
            "Current controller state (compact projection)",
            bounded_state_text,
            len(bounded_state_text.encode("utf-8")),
            {"projection": "compact"},
        )
        bounded_sections.append(bounded_state_section)
        if selected_render_mode == "legacy":
            if legacy_state_text:
                selected_dynamic_parts.append(legacy_state_text)
        else:
            selected_dynamic_parts.append(bounded_state_text)
        # Inject squad run context so agents know where to write
        context_preamble = (
            f"# Squad Run Context\n"
            f"SQUAD_DIR={squad_dir_str}\n"
            f"STAGING_DIR={staging_dir_str}\n"
            f"CONTEXT_DIR={context_dir_str}\n"
            f"PROJECT_ROOT={self._project_root}\n"
            f"{self._stack_context(spec_dir_ref)}"
            f"{_render_controller_owned_prompt_context(state)}"
            f"{_render_banzai_evidence_reassessment_context(state, node.id)}"
            f"{_render_phase3_planning_mode_context(node.id)}"
            f"{_workspace_source_roots_context(self._project_root)}"
            f"{_render_implementation_target_context(state)}"
            f"{_render_spec_authoring_mode_context(state, node.id)}"
            f"{_render_product_input_context(state)}"
            f"{_render_controller_repair_context(state)}"
            f"{_render_issue_resolution_context(state)}"
            f"{_render_spec_lexicon_context(state, node.id, self._resolved_config())}"
            f"{_render_published_re_context(state)}"
            f"{_render_certified_understanding_context(state, node.id)}"
            f"{_render_active_spec_roots_context(spec_dir_ref, state, self._project_root)}"
            f"{self._extension_path_context()}"
            f"{render_quality_gate_context(self._quality_gate_thresholds())}"
        )
        resumable_spec = False
        if node.id == "phase1-what" and state.get("cartographer_resume_existing_spec"):
            candidate = Path(str(state.get("spec_dir") or ""))
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            resumable_spec = (candidate / "spec.md").is_file()
        if resumable_spec:
            spec_dir = state.get("spec_dir", "")
            feature_branch = state.get("feature_branch", "")
            context_preamble += (
                "## CARTOGRAPHER Resume Guard\n"
                "This is a resumed/amendment pass for the controller-owned Phase A spec.\n"
                f"Existing spec_dir: {spec_dir}\n"
                f"Existing feature_branch: {feature_branch}\n"
                "Do NOT create, switch, rename, or discover a branch or spec directory. "
                "Reuse the existing spec_dir and amend spec.md and requirements-overview.md "
                "in place.\n\n"
            )

        prompt = "\n\n".join(static_parts + [context_preamble] + selected_dynamic_parts)
        prompt = prompt.replace("{spec_dir}", spec_dir_ref)
        prompt = prompt.replace("{squad_dir}", squad_dir_str)
        prompt = prompt.replace("{context_dir}", context_dir_str)
        prompt = prompt.replace("{staging_dir}", staging_dir_str)
        prompt += getattr(node, "controller_context", "")

        # Append harness routing contract so agents know exactly what
        # state_updates fields the harness needs for transition evaluation.
        prompt = (
            prompt
            + _routing_contract(node)
            + _allowed_state_updates_contract(
                node.allowed_state_updates,
                required_state_updates=getattr(node, "required_state_updates", []),
                state_update_types=getattr(node, "state_update_types", {}),
                state_update_enums=getattr(node, "state_update_enums", {}),
                allowed_verdicts=getattr(node, "allowed_verdicts", None),
            )
            + _canonical_echelon_result_contract(self._ext_dir)
        )

        feasibility_repair = (
            node.id in {"phase3-how", "phase3-sentinel", "phase3-plan"}
            and state.get("assess2_verdict") == "REJECTED"
        )
        if (feasibility_repair or (node.id in {"phase3-how", "phase3-sentinel", "phase3-plan"}
                and state.get("why3_verdict") == "FAIL"
                and state.get("why3_repair_phase") == node.id)):
            from harness.phase3_repair_context import capture_repair_context
            current_spec = Path(spec_dir_ref)
            if not current_spec.is_absolute():
                current_spec = self._project_root / current_spec
            repair_text = capture_repair_context(current_spec, project_root=self._project_root,
                                                require_implementability=feasibility_repair)
            prompt += repair_text
            repair_section = RenderedSection("Current Phase 3 repair handoff", repair_text,
                len(repair_text.encode()), {"truncated": "false"})
            legacy_sections.append(repair_section)
            bounded_sections.append(repair_section)

        report = build_context_budget_report(
            phase_id=node.id,
            agent_id=str(node.agent or ""),
            mode=str(getattr(node, "mode", "") or node.id),
            selected_render_mode=selected_render_mode,
            legacy_sections=legacy_sections,
            bounded_sections=bounded_sections,
            strict=False,
        )
        try:
            report_path = write_context_budget_report(self._squad_dir, report)
        except OSError as exc:
            print(f"[squad] context budget report unavailable for {node.id}: {exc}", flush=True)
        else:
            if report["bounded"]["bytes"] < report["legacy"]["bytes"]:
                print(
                    "[squad] context bounded for "
                    f"{color_phase_id(node, self._graph, self._ext_dir)}; "
                    f"report={report_path}",
                    flush=True,
                )

        return _shared_agent_contract() + prompt

    def _run_pre_dispatch(
        self, node: "PhaseNode", state: dict, state_store: "SquadStateStore"
    ) -> Optional["SquadAgentResult"]:
        """Execute conditional pre_dispatch entries before the main agent."""
        from harness.condition_evaluator import ConditionEvaluator
        ev = ConditionEvaluator()
        for entry in node.pre_dispatch:
            state = state_store.load()
            condition = entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            pre_agent = entry.get("agent", "").split(" ")[0]
            if not pre_agent:
                continue
            rel = self._graph.agent_file(pre_agent)
            if rel:
                pre_path = self._ext_dir / rel
                if pre_path.exists():
                    result_contract = self._result_contract(node, entry)
                    prompt = self._assemble_pre_dispatch_prompt(
                        pre_path,
                        entry,
                        state_store.load(),
                        result_contract,
                    )
                    prompt_metadata = self._phase_prompt_metadata(
                        node,
                        state,
                        _read_prompt_metadata(pre_path),
                        agent_id=pre_agent,
                        outputs=entry.get("outputs", getattr(node, "outputs", [])),
                    )
                    result = self._exec_agent_with_contract(
                        prompt,
                        result_contract,
                        prompt_metadata,
                    )
                    result = self._validate_result_state_updates(
                        node,
                        result,
                        result_contract=result_contract,
                        direct_state_write=True,
                    )
                    if result.blocked:
                        return result
                    self._write_journal_entries(result, node.id)
                    for k, v in result.state_updates.items():
                        s = state_store.load()
                        s[k] = v
                        state_store.save(s)
        return None

    def _assemble_pre_dispatch_prompt(
        self,
        agent_path: Path,
        entry: dict,
        state: dict,
        result_contract=None,
    ) -> str:
        """Build a real prompt for a generic pre-dispatch agent."""
        if not hasattr(result_contract, "allowed_state_update_keys"):
            from harness.echelon_result_schema import EchelonResultContract

            result_contract = EchelonResultContract(
                allowed_state_update_keys=frozenset(result_contract or [])
            )
        agent_text = _read_prompt_body(agent_path)
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))
        spec_dir_ref = _normalize_spec_dir_ref(
            str(state.get("spec_dir") or "").strip(),
            self._project_root,
        )
        return (
            _shared_agent_contract()
            + agent_text
            + "\n\n"
            + "# Squad Run Context\n"
            + f"SQUAD_DIR={squad_dir_str}\n"
            + f"STAGING_DIR={staging_dir_str}\n"
            + f"CONTEXT_DIR={context_dir_str}\n"
            + f"PROJECT_ROOT={self._project_root}\n"
            + self._stack_context(spec_dir_ref)
            + _workspace_source_roots_context(self._project_root)
            + _render_implementation_target_context(state)
            + _render_product_input_context(state)
            + _render_controller_repair_context(state)
            + _render_published_re_context(state)
            + self._extension_path_context()
            + _allowed_state_updates_contract(
                result_contract.allowed_state_update_keys,
                required_state_updates=result_contract.required_state_update_keys,
                state_update_types=result_contract.state_update_types,
                state_update_enums=result_contract.state_update_enums,
                allowed_verdicts=result_contract.allowed_verdicts,
            )
            + _canonical_echelon_result_contract(self._ext_dir)
        )

class AgentExecutor(PhaseExecutor):
    """Handles type: agent phases — the common case."""

    def _canonical_spec_dir(self, state: dict) -> Path | None:
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        if not spec_dir_ref:
            return None
        spec_dir = Path(spec_dir_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        return spec_dir

    def _run_local_shadow_spec_dir(self, spec_dir: Path) -> Path:
        return self._squad_dir / spec_dir.parent.name / spec_dir.name

    def _claimed_required_phase_outputs(self, node: "PhaseNode", state: dict, result: "SquadAgentResult") -> set[str]:
        required = _MANDATORY_PHASE_OUTPUTS.get(node.id, ())
        if not required:
            return set()
        spec_dir = self._canonical_spec_dir(state)
        if spec_dir is None:
            return set()
        payload = result.echelon_result or {}
        output_files = payload.get("output_files")
        if not isinstance(output_files, list):
            return set()
        claimed: set[Path] = set()
        for item in output_files:
            if not isinstance(item, str) or not item.strip():
                continue
            candidate = Path(item.strip().rstrip("/"))
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            claimed.add(candidate.resolve())

        matched: set[str] = set()
        for rel in required:
            expected = (spec_dir / rel.rstrip("/")).resolve()
            if expected in claimed:
                matched.add(rel)
        return matched

    def _recover_required_phase_outputs_from_shadow(self, node: "PhaseNode", state: dict, result: "SquadAgentResult") -> list[str]:
        required = _MANDATORY_PHASE_OUTPUTS.get(node.id, ())
        if not required:
            return []
        spec_dir = self._canonical_spec_dir(state)
        if spec_dir is None:
            return []
        claimed = self._claimed_required_phase_outputs(node, state, result)
        if not claimed:
            return []
        shadow_dir = self._run_local_shadow_spec_dir(spec_dir)
        if not shadow_dir.exists():
            return []
        recovered: list[str] = []
        for rel in required:
            if rel not in claimed:
                continue
            src = shadow_dir / rel
            dst = spec_dir / rel
            if rel == "contracts":
                if src.is_dir() and not dst.exists():
                    shutil.copytree(src, dst)
                    recovered.append(f"{rel}/")
            elif src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                recovered.append(rel)
        return recovered

    def _required_phase_outputs_missing(self, node: "PhaseNode", state: dict) -> list[str]:
        required = _MANDATORY_PHASE_OUTPUTS.get(node.id, ())
        if not required:
            return []
        spec_dir = self._canonical_spec_dir(state)
        if spec_dir is None:
            return list(required)
        missing: list[str] = []
        for rel in required:
            path = spec_dir / rel
            if rel == "contracts":
                if not path.is_dir():
                    missing.append(f"{rel}/")
            elif not path.exists():
                missing.append(rel)
        return missing

    def _required_phase_outputs_invalid(
        self,
        node: "PhaseNode",
        state: dict,
    ) -> list[dict[str, str]]:
        """Validate semantic contracts owned by the phase that wrote them."""
        if node.id != "phase3-sentinel":
            return []
        spec_dir = self._canonical_spec_dir(state)
        if spec_dir is None:
            return []
        from harness.phase_a_readiness import coverage_contract_error

        # Initial SENTINEL precedes task generation. Later repairs must still
        # reconcile existing task ownership; final readiness always requires it.
        error = coverage_contract_error(
            spec_dir, check_task_ownership=(spec_dir / "tasks.md").exists()
        )
        if error is None:
            return []
        return [{"path": "coverage-map.md", "reason": error}]

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult | ExecutorBlockedResult":
        from harness.squad_provider import SquadAgentResult

        state = state_store.load()
        self._quarantine_invalid_recovery_outputs(node, state, state_store)
        state = state_store.load()
        pre_dispatch_result = self._run_pre_dispatch(node, state, state_store)
        if pre_dispatch_result is not None and pre_dispatch_result.blocked:
            return pre_dispatch_result
        state = state_store.load()  # re-load after pre_dispatch
        from harness.phase3_repair import RepairContractError
        try:
            prompt = self._assemble_prompt(node, state)
        except (RepairContractError, UnicodeError) as exc:
            from harness.squad_provider import SquadAgentResult
            return ExecutorBlockedResult(reason="repair_context_incomplete", result=SquadAgentResult(
                exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_context_incomplete"}},
                raw_output=str(exc), duration_ms=0, timed_out=False))
        result_contract = self._result_contract(node)
        prompt_metadata: dict[str, object] = {}
        if node.agent:
            rel = self._graph.agent_file(node.agent)
            if rel:
                agent_path = self._ext_dir / rel
                if agent_path.exists():
                    prompt_metadata = _read_prompt_metadata(agent_path)
        prompt_metadata = self._phase_prompt_metadata(node, state, prompt_metadata)
        if node.id == "phase1-why2":
            reassessment = state.get("banzai_evidence_reassessment")
            armed = (
                [
                    attempt
                    for attempt in reassessment.get("attempts", [])
                    if isinstance(attempt, dict) and attempt.get("status") == "armed"
                ]
                if isinstance(reassessment, dict)
                and reassessment.get("schema_version") == 2
                else []
            )
            if armed:
                if len(armed) != 1:
                    raise ControllerStateContractViolation(
                        "WHY2 dispatch has multiple armed evidence attempts",
                        contract="phase1-why2",
                        json_path="$.banzai_evidence_reassessment.attempts",
                        validator="evidence_binding",
                    )
                state_store.consume_armed_banzai_evidence_reassessment(
                    expected_state_revision=int(state["state_revision"]),
                    expected_evidence_sha256=str(armed[0]["evidence_sha256"]),
                )
        result = self._exec_agent_with_contract(
            prompt,
            result_contract,
            prompt_metadata,
        )
        result = self._validate_result_state_updates(
            node, result, result_contract=result_contract
        )
        if result.blocked:
            return result
        self._write_journal_entries(result, node.id)
        state_store.increment_cost(result.cost_usd)
        if result.echelon_result is not None:
            recovered = self._recover_required_phase_outputs_from_shadow(node, state, result)
            if recovered:
                updates = (result.echelon_result.setdefault("state_updates", {}))
                existing = updates.get("shadow_output_recovered")
                if isinstance(existing, list):
                    updates["shadow_output_recovered"] = [*existing, *recovered]
                else:
                    updates["shadow_output_recovered"] = recovered
            missing_outputs = self._required_phase_outputs_missing(node, state)
            invalid_outputs = (
                self._required_phase_outputs_invalid(node, state)
                if not missing_outputs
                else []
            )
            if missing_outputs or invalid_outputs:
                output_reason = "missing_phase_outputs" if missing_outputs else "invalid_phase_outputs"
                recovery_state_updates = dict(result.state_updates)
                prior_recovery = state.get("phase_output_recovery")
                prior_invalid_outputs = (
                    prior_recovery.get("invalid_outputs")
                    if isinstance(prior_recovery, dict)
                    else None
                )
                recovery_updates: dict[str, object] = {
                    "blocked_reason": output_reason,
                    "missing_outputs": missing_outputs,
                    "recovery_state_updates": recovery_state_updates,
                }
                if invalid_outputs:
                    recovery_updates["invalid_outputs"] = invalid_outputs
                elif isinstance(prior_invalid_outputs, list) and prior_invalid_outputs:
                    recovery_updates["invalid_outputs"] = prior_invalid_outputs
                blocked_result = SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "BLOCKED",
                        "state_updates": recovery_updates,
                    },
                    raw_output=result.raw_output,
                    duration_ms=result.duration_ms,
                    timed_out=result.timed_out,
                    cost_usd=result.cost_usd,
                )
                return ExecutorBlockedResult(
                    reason=output_reason,
                    result=blocked_result,
                )
            elif node.id == "phase1-investigate":
                spec_dir = self._canonical_spec_dir(state)
                inventory_error = (
                    _validate_evidence_inventory(
                        spec_dir / "evidence-inventory.json",
                        required_seed_locators=_reference_url_seeds(state),
                    )
                    if spec_dir is not None
                    else "spec_dir is unavailable"
                )
                if inventory_error:
                    recovery_state_updates = dict(result.state_updates)
                    blocked_result = SquadAgentResult(
                        exit_code=0,
                        echelon_result={
                            "verdict": "BLOCKED",
                            "state_updates": {
                                "blocked_reason": "invalid_evidence_inventory",
                                "invalid_outputs": [{
                                    "path": "evidence-inventory.json",
                                    "reason": inventory_error,
                                }],
                                "recovery_state_updates": recovery_state_updates,
                            },
                        },
                        raw_output=result.raw_output,
                        duration_ms=result.duration_ms,
                        timed_out=result.timed_out,
                        cost_usd=result.cost_usd,
                    )
                    return ExecutorBlockedResult(
                        reason="invalid_evidence_inventory",
                        result=blocked_result,
                    )
        return result

    def _quarantine_invalid_recovery_outputs(
        self,
        node: "PhaseNode",
        state: dict,
        state_store: "SquadStateStore",
    ) -> None:
        """Move rejected outputs aside so an agent cannot mistake them for evidence."""
        recovery = state.get("phase_output_recovery")
        if not isinstance(recovery, dict) or recovery.get("phase") != node.id:
            return
        invalid = recovery.get("invalid_outputs")
        if not isinstance(invalid, list) or not invalid:
            return
        spec_dir = self._canonical_spec_dir(state)
        if spec_dir is None:
            return
        quarantined: list[str] = []
        for item in invalid:
            if not isinstance(item, dict):
                continue
            relative = str(item.get("path") or "").strip()
            candidate = spec_dir / relative
            if not relative or candidate.parent != spec_dir or not candidate.is_file():
                continue
            archived = candidate.with_name(f"{candidate.stem}.invalid{candidate.suffix}")
            index = 1
            while archived.exists():
                archived = candidate.with_name(
                    f"{candidate.stem}.invalid-{index}{candidate.suffix}"
                )
                index += 1
            candidate.replace(archived)
            quarantined.append(archived.name)
        if quarantined:
            refreshed = state_store.load()
            refreshed_recovery = refreshed.get("phase_output_recovery")
            if isinstance(refreshed_recovery, dict):
                refreshed_recovery["quarantined_invalid_outputs"] = quarantined
                refreshed["phase_output_recovery"] = refreshed_recovery
                state_store.save(refreshed)


class CommanderInternalExecutor(PhaseExecutor):
    """Handles type: commander_internal phases in the harness path.

    These spec files are markdown instructions for COMMANDER (the LLM) — not
    bash scripts. Running them as bash causes a stdin hang: markdown fenced
    code blocks contain triple-backticks which bash interprets as command
    substitutions that spawn child bash processes reading from the terminal.

    In the harness path these phases are no-ops: the harness already performed
    the equivalent init work (SquadStateStore.initialize, cli.py config checks),
    and any LLM-specific steps (KB reads, constitution authoring) only run in the
    interactive COMMANDER path.
    """

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        print("[squad]   (commander_internal — harness no-op)", flush=True)
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class DeterministicUnderstandingExecutor(PhaseExecutor):
    """Certify Understanding evidence without invoking an AI provider."""

    def __init__(
        self,
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        from harness.paths import runs_dir as _runs_dir

        self._squad_dir = squad_dir if squad_dir is not None else _runs_dir(project_root)

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult | ExecutorBlockedResult":
        from harness.config import get_full_resolved_config
        from harness.squad_provider import SquadAgentResult

        state = state_store.load()
        target = str(getattr(node, "understanding_target", "") or "").strip()
        if not target:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {
                        "blocked_reason": (
                            f"deterministic Understanding node {node.id!r} has no target"
                        )
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        gate = run_understanding_gate(
            project_root=self._project_root,
            squad_dir=state_store.squad_dir,
            phase=target,
            iteration=int(state.get("iteration") or 0),
            spec_dir=str(state.get("spec_dir") or ""),
            config=get_full_resolved_config(self._project_root),
        )
        updates = gate.state_updates(state.get("quality_scores"))
        if gate.operational_error:
            updates["blocked_reason"] = gate.operational_error
            return SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "BLOCKED", "state_updates": updates},
                raw_output=str(gate.report_path or ""),
                duration_ms=0,
                timed_out=False,
            )
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": updates},
            raw_output=str(gate.report_path or ""),
            duration_ms=0,
            timed_out=False,
        )


class DeterministicLexiconExecutor(PhaseExecutor):
    """Certify a Lexicon artifact without invoking an AI provider."""

    def __init__(
        self,
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        from harness.paths import runs_dir as _runs_dir

        self._squad_dir = squad_dir if squad_dir is not None else _runs_dir(project_root)

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.config import get_full_resolved_config
        from harness.squad_provider import SquadAgentResult

        artifact = str(getattr(node, "lexicon_artifact", "") or "")
        if artifact not in {"spec", "tasks"}:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {
                        "blocked_reason": (
                            f"deterministic Lexicon node {node.id!r} has "
                            f"unsupported artifact {artifact!r}"
                        )
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        state = state_store.load()
        config = get_full_resolved_config(self._project_root)
        if artifact == "spec":
            gate = run_spec_lexicon_gate(
                project_root=self._project_root,
                spec_dir_ref=str(state.get("spec_dir") or ""),
                config=config,
                previous_attempts=state.get("lexicon_attempts", 0),
            )
            updates = gate.state_updates()
            marker = (
                "✓" if gate.passed is True else "~" if gate.passed is None else "✗"
            )
            label = f"spec Lexicon {gate.evaluation}: {gate.detail}"
            raw_output = str(gate.report_path or gate.detail)
        else:
            gate = run_tasks_lexicon_gate(
                project_root=self._project_root,
                spec_dir_ref=str(state.get("spec_dir") or ""),
                config=config,
                previous_attempts=state.get("tasks_lexicon_attempts", 0),
                workflow_iteration=state.get("iteration", 0),
                max_workflow_iterations=state.get("max_iterations", 0),
            )
            updates = gate.state_updates()
            marker = (
                "✓"
                if gate.action == "proceed"
                else "~"
                if gate.action in {"repair", "proceed_with_warning"}
                else "✗"
            )
            label = f"tasks Lexicon {gate.action}: {gate.detail}"
            raw_output = str(gate.report_path or gate.detail)
        print(
            f"[squad] {marker} {label}",
            flush=True,
        )
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": (
                    "BLOCKED"
                    if artifact == "tasks" and gate.action == "block"
                    else "DONE"
                ),
                "state_updates": updates,
            },
            raw_output=raw_output,
            duration_ms=0,
            timed_out=False,
        )


class DeterministicStructuralExecutor(PhaseExecutor):
    """Certify one governance artifact without invoking an AI provider."""

    def __init__(
        self,
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._squad_dir = squad_dir

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.config import get_full_resolved_config
        from harness.squad_provider import SquadAgentResult

        artifact = str(getattr(node, "structural_artifact", "") or "")
        prefixes = {
            "feasibility": (
                "feasibility_verdict",
                "feasibility_structural_attempts",
            ),
            "intent-alignment-check": (
                "intent_alignment_verdict",
                "intent_alignment_check_structural_attempts",
            ),
        }
        state = state_store.load()
        if artifact not in prefixes:
            gate = GovernanceStructuralGateResult(
                artifact_key=artifact,
                action="block",
                passed=False,
                attempts=0,
                findings=0,
                report_path=None,
                exhausted_artifact=None,
                blocked_reason="governance_structural_artifact_unknown",
                detail=f"unsupported structural artifact for {node.id}",
            )
            updates: dict[str, object] = {"structural_action": "block"}
        else:
            verdict_key, attempts_key = prefixes[artifact]
            if state.get(verdict_key) is None:
                gate = GovernanceStructuralGateResult(
                    artifact_key=artifact,
                    action="block",
                    passed=False,
                    attempts=_normalized_attempts(state.get(attempts_key)),
                    findings=0,
                    report_path=None,
                    exhausted_artifact=None,
                    blocked_reason=(
                        "governance_structural_authoring_verdict_missing"
                    ),
                    detail=f"run the owner phase before {node.id}",
                )
            else:
                spec_ref = str(state.get("spec_dir") or "").strip()
                spec_dir = Path(spec_ref) if spec_ref else None
                if spec_dir is not None and not spec_dir.is_absolute():
                    spec_dir = self._project_root / spec_dir
                gate = run_governance_structural_gate(
                    artifact_key=artifact,
                    spec_dir=spec_dir,
                    extension_root=self._ext_dir,
                    governance_config=get_full_resolved_config(self._project_root),
                    previous_attempts=state.get(attempts_key, 0),
                    iteration=state.get("iteration", 0),
                    max_iterations=state.get("max_iterations", 0),
                )
            updates = gate.state_updates()
        verdict = {
            "proceed": "PASS",
            "repair": "REPAIR",
            "proceed_with_warning": "WARN",
            "block": "FAIL",
        }[gate.action]
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": verdict, "state_updates": updates},
            raw_output=str(gate.report_path or gate.detail),
            duration_ms=0,
            timed_out=False,
        )


def _normalized_attempts(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class StagedParallelExecutor(PhaseExecutor):
    """Handles type: staged_parallel — phase3-consensus (WHY3+ASSESS2 then PLAN2).

    This is the phase that was previously skipped via EVOI fabrication.
    Python threading enforces both stage-1 agents run; there is no code path
    that bypasses Stage 1.
    """

    _FINAL_REPORTS = ("issues.md", "quality-gates.md", "implementability-report.md")

    def _final_review_inputs(self, node, state, spec_dir):
        """Fingerprint full inputs, not bounded model renderings or report revisions.

        The journal is an append-only execution history, not candidate content.
        Reports are checked separately at round entry and may only be rewritten
        by the reviewers inside that round. Every other declared context input
        (including estimates and role/template files) remains authoritative.
        """
        from harness.phase3_repair_context import review_input_paths
        from harness.phase3_repair import RepairContractError
        paths = set(review_input_paths(spec_dir, project_root=self._project_root))
        paths.update(spec_dir / name for name in ("estimates.md", "mvp-scope.md"))
        paths.update(self._project_root / ".echelon" / name for name in ("constitution.md", "config.yml"))
        replacements = {"{spec_dir}": str(spec_dir), "{squad_dir}": str(state.get("squad_dir") or self._squad_dir),
            "{context_dir}": str(state.get("context_dir") or self._squad_dir / "context"),
            "{staging_dir}": str(state.get("staging_dir") or self._squad_dir / "staging")}
        bases = _spec_search_bases(str(spec_dir), self._project_root, replacements["{staging_dir}"])
        for agent in node.agents:
            role = self._graph.agent_file(str(agent.get("id") or agent.get("agent", "")).split(" ")[0])
            if role:
                paths.add(self._ext_dir / role)
            for item in agent.get("context_pack", []):
                ref = parse_context_pack_item(item).path_ref
                if not ref or ref.startswith("#"):
                    continue
                for key, value in replacements.items():
                    ref = ref.replace(key, value)
                candidates = [Path(ref)] if Path(ref).is_absolute() else [base / ref for base in bases]
                paths.add(next((path for path in candidates if path.exists()), candidates[0]))
        excluded = {(spec_dir / name).resolve() for name in self._FINAL_REPORTS}
        excluded.add((self._squad_dir / "reasoning-journal.jsonl").resolve())
        content = {}
        for path in sorted(paths):
            if path.is_symlink():
                raise RepairContractError(f"unsafe final-review input: {path}")
            descendants = sorted(path.rglob("*")) if path.is_dir() else [path]
            for candidate in descendants:
                if candidate.resolve() in excluded:
                    continue
                if candidate.is_symlink():
                    raise RepairContractError(f"unsafe final-review input: {candidate}")
                if not candidate.is_dir():
                    content[str(candidate.resolve())] = (hashlib.sha256(candidate.read_bytes()).hexdigest()
                                                         if candidate.exists() else None)
        context = (_render_product_input_context(state) + _render_implementation_target_context(state)
                   + self._stack_context(str(spec_dir)) + render_quality_gate_context(self._quality_gate_thresholds())
                   + _workspace_source_roots_context(self._project_root)
                   + _render_active_spec_roots_context(str(spec_dir), state, self._project_root)
                   + _render_certified_understanding_context(state, "WHY3")
                   + _shared_agent_contract() + _canonical_echelon_result_contract(self._ext_dir)
                   + getattr(node, "controller_context", ""))
        for agent in node.agents:
            contract = self._result_contract(node, agent)
            context += _allowed_state_updates_contract(contract.allowed_state_update_keys,
                required_state_updates=contract.required_state_update_keys,
                state_update_types=contract.state_update_types, state_update_enums=contract.state_update_enums,
                allowed_verdicts=contract.allowed_verdicts)
        return {"schema_version": 1, "run_id": state.get("run_id"), "inputs": content,
                "agents": node.agents, "context_sha256": hashlib.sha256(context.encode()).hexdigest()}

    def _final_review_reports(self, spec_dir):
        return {name: hashlib.sha256((spec_dir / name).read_bytes()).hexdigest()
                if (spec_dir / name).is_file() else None for name in self._FINAL_REPORTS}

    def _record_final_review(self, node, state_store, receipt):
        from harness.phase3_repair import RepairContractError
        snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
        recorded = dict(snapshot.state)
        recorded.pop("phase3_plan2_completion", None)
        if receipt is None:
            recorded.pop("phase3_final_review", None)
        else:
            recorded["phase3_final_review"] = receipt
        if not state_store.commit_routing_snapshot_state(snapshot, recorded):
            raise RepairContractError("state changed while recording final review")

    @staticmethod
    def _issue_review_context(envelope: dict, inputs: str) -> str:
        return ("\n## Phase 3 selected-issue review envelope\n```json\n"
            + json.dumps(envelope, sort_keys=True) + "\n```\n"
            "Review this selected issue independently of the overall gate against these current inputs. "
            "Return exactly one top-level phase3_issue_review object in echelon_result: schema_version: 2, "
            "selected_issue matching this envelope, outcome: resolved|unresolved|unverifiable, "
            "evidence_refs as a nonempty list of input paths (optional #anchor), and a concrete rationale. "
            "The harness binds identity and hashes: never copy identity, input_manifest or reviewed_artifacts "
            "into the response. Missing issues alone do not prove closure. "
            "Keep all other findings and the overall WHY3 verdict honest. Do not edit these inputs.\n" + inputs)

    @staticmethod
    def _repair_block(reason: str, detail: str):
        from harness.squad_provider import SquadAgentResult
        return ExecutorBlockedResult(reason=reason, result=SquadAgentResult(exit_code=0,
            echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": reason}},
            raw_output=detail, duration_ms=0, timed_out=False))

    def _assess_phase3_work(self, node, state_store):
        """One content-bound SAGE classification, never an answer-adoption grant."""
        from dataclasses import asdict
        from harness.issue_identity import issue_fingerprint, matching_issue_resolution
        from harness.phase3_repair import RepairIdentity, RepairContractError, validate_repair_action
        from harness.phase3_repair_context import capture_review_inputs, capture_repair_context, read_repair_issues
        from harness.phase3_repair_routing import OWNER_FILES, owned_artifacts
        state = state_store.load()
        if (node.id == "phase3-consensus" and state.get("phase3_pending_action")
                and state.get("why3_verdict") != "FAIL"):
            snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
            retired = dict(snapshot.state)
            retired["phase3_pending_action"] = None
            if not state_store.commit_routing_snapshot_state(snapshot, retired):
                return self._repair_block("repair_action_unclassified", "state changed while retiring superseded work")
            state = state_store.load()
        if (node.id != "phase3-consensus" or state.get("autonomy_mode") != "banzai"
                or state.get("why3_verdict") != "FAIL" or state.get("selected_issue_resolution")):
            return None
        if any(isinstance(item, dict) and item.get("review_revalidation_required")
               for item in (state.get("issue_resolution_ledger") or {}).values()):
            return None
        spec = Path(_normalize_spec_dir_ref(str(state.get("spec_dir") or ""), self._project_root))
        if not spec.is_absolute():
            spec = self._project_root / spec
        try:
            # Keep existing eligible-option handling intact. Only contradictory
            # legacy work guidance needs this bounded classification call.
            issues = read_repair_issues(spec, project_root=self._project_root)
            candidate = None
            blocks = re.findall(r"^### (ISS-[A-Za-z0-9-]+):\s*([^\n]+)\n(.*?)(?=^### ISS-|\Z)", issues, re.M | re.S)
            for issue_id, title, body in blocks:
                if not re.search(r"\*\*Banzai eligible:\*\*\s*no\b", body, re.I):
                    continue
                owner = self._why3_repair_phase_from_issues(body)
                fingerprint = issue_fingerprint(title, body)
                previous = matching_issue_resolution(state.get("issue_resolution_ledger"), fingerprint)
                if owner in OWNER_FILES and previous.get("status") != "validated":
                    candidate = (issue_id, title, fingerprint, owner)
                    break
            if candidate is None:
                if state.get("phase3_pending_action"):
                    snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                    retired = dict(snapshot.state)
                    retired["phase3_pending_action"] = None
                    if not state_store.commit_routing_snapshot_state(snapshot, retired):
                        raise RepairContractError("state changed while retiring superseded finding")
                return None
            manifest, _ = capture_review_inputs(spec, project_root=self._project_root)
            context = capture_repair_context(spec, project_root=self._project_root)
            issue_id, title, fingerprint, owner = candidate
            key = hashlib.sha256(json.dumps({"run": state.get("run_id"), "issue": fingerprint,
                "inputs": manifest}, sort_keys=True).encode()).hexdigest()
            snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
            state = dict(snapshot.state)
            attempts = dict(state.get("phase3_action_assessments") or {})
            existing = attempts.get(key)
            if existing:
                if existing.get("status") != "complete":
                    raise RepairContractError("SAGE work classification already attempted for these inputs; inspect its evidence before retrying")
                state["phase3_pending_action"] = {**existing["receipt"], "issue_id": issue_id}
                if not state_store.commit_routing_snapshot_state(snapshot, state):
                    raise RepairContractError("work classification state changed")
                return None
            identity = RepairIdentity(str(state.get("run_id")), fingerprint, snapshot.state_revision)
            envelope = {"identity": asdict(identity), "issue_id": issue_id, "title": title,
                "owner_phase": owner, "allowed_artifacts": sorted(owned_artifacts(owner, manifest)), "input_manifest": manifest}
            attempts[key] = {"status": "attempted", "identity": asdict(identity)}
            state["phase3_action_assessments"] = attempts
            if not state_store.commit_routing_snapshot_state(snapshot, state):
                raise RepairContractError("work classification state changed before dispatch")
            sage = next(a for a in node.agents if a.get("id") == "echelon.sage" and a.get("mode") == "WHY3")
            contract = self._result_contract(node, sage)
            required = ("## Phase 3 work assessment envelope\n```json\n" + json.dumps(envelope, sort_keys=True)
                + "\n```\nClassify only; do not edit any artifact or change the gate verdict. Return a top-level "
                "phase3_repair_action object: schema_version: 1, identity from the envelope, kind: "
                "investigate_or_design|apply_evidenced_resolution|human_decision|external_prerequisite, "
                "owner_phase from the envelope, affected_artifacts within allowed_artifacts, evidence_refs "
                "as manifest paths with optional anchors, action as concrete work, and constraints as a nonempty list. "
                "Missing technical mechanisms may require owner investigation/design, not a human answer. "
                "Banzai eligible:no still prohibits adopting an unevidenced answer. Preserve scope, behavior and "
                "acceptance strength; no policy waiver, invented external fact or irreversible commitment.\n" + context)
            from harness.phase3_repair_context import planner_handoff_context
            required += planner_handoff_context(state_store.load(), manifest)
            prompt = self._build_agent_prompt(sage, state_store.load(), phase_id=node.id,
                allowed_state_updates=contract.allowed_state_update_keys, allowed_verdicts=contract.allowed_verdicts,
                required_context=required)
            metadata = self._phase_prompt_metadata(node, state_store.load(), {}, agent_id="echelon.sage", outputs=[])
            result = self._validate_result_state_updates(node,
                self._exec_agent_with_contract(prompt, contract, metadata), result_contract=contract, direct_state_write=True)
            if isinstance(result, ExecutorBlockedResult):
                return result
            state_store.increment_cost(result.cost_usd)
            self._write_journal_entries(result, node.id)
            action_payload = (result.echelon_result or {}).get("phase3_repair_action")
            validate_repair_action(action_payload, expected=identity, allowed_owner_phases=frozenset({owner}),
                allowed_artifacts=owned_artifacts(owner, manifest))
            current, _ = capture_review_inputs(spec, project_root=self._project_root)
            if current != manifest or read_repair_issues(spec, project_root=self._project_root) != issues:
                raise RepairContractError("work classification inputs changed during assessment")
            receipt = {"identity": asdict(identity), "issue_id": issue_id, "title": title,
                "input_manifest": manifest, "assessment": action_payload}
            snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
            state = dict(snapshot.state)
            attempts = dict(state.get("phase3_action_assessments") or {})
            attempts[key] = {"status": "complete", "receipt": receipt}
            state.update(phase3_action_assessments=attempts, phase3_pending_action=receipt)
            if not state_store.commit_routing_snapshot_state(snapshot, state):
                raise RepairContractError("work classification state changed after assessment")
            return None
        except (OSError, UnicodeError, RepairContractError, StopIteration, TypeError, KeyError) as exc:
            return self._repair_block("repair_action_unclassified", str(exc))

    def _reconcile_final_reviews(self, node, state_store):
        """PLAN2 may regenerate dependencies even without an active selection."""
        from harness.phase3_repair import RepairContractError
        from harness.phase3_repair_context import capture_review_inputs
        state = state_store.load()
        from harness.phase3_repair_routing import has_phase3_repairs
        if node.id != "phase3-consensus" or not has_phase3_repairs(state):
            return None
        try:
            spec = Path(_normalize_spec_dir_ref(str(state.get("spec_dir") or ""), self._project_root))
            if not spec.is_absolute():
                spec = self._project_root / spec
            manifest, _ = capture_review_inputs(spec, project_root=self._project_root)
            if not state_store.reconcile_phase3_review_inputs(
                    snapshot=state_store.capture_routing_snapshot(expected_phase=node.id), input_manifest=manifest):
                raise RepairContractError("state changed during final input reconciliation")
        except (OSError, UnicodeError, RepairContractError) as exc:
            return self._repair_block("repair_review_stale", str(exc))
        return None

    @staticmethod
    def _why3_repair_phase_from_issues(issues_text: str) -> str:
        """Choose the earliest phase capable of repairing WHY3-owned issues."""
        phase_order = (
            "phase1-discover",
            "phase1-what",
            "phase3-how",
            "phase3-sentinel",
            "phase3-plan",
        )
        owner_phases = {
            "DISCOVER": "phase1-discover",
            "SCOUT": "phase1-discover",
            "WHAT": "phase1-what",
            "CARTOGRAPHER": "phase1-what",
            "HOW": "phase3-how",
            "ARCHITECT": "phase3-how",
            "SENTINEL": "phase3-sentinel",
            "PLAN": "phase3-plan",
            "ORCHESTRATOR": "phase3-plan",
        }
        from harness.phase3_repair_routing import OWNER_FILES

        artifact_phases: set[str] = set()
        phase1_files = {
            "phase1-discover": frozenset({
                "mental-model.md", "codebase-map.md", "assumptions.md", "unknowns.md",
            }),
            "phase1-what": frozenset({"spec.md", "requirements-overview.md"}),
        }
        affected_artifacts = re.findall(
            r"^- \*\*Affected artifacts?:\*\*[ \t]*(.+?)[ \t]*$",
            issues_text,
            re.MULTILINE | re.IGNORECASE,
        )
        for field in affected_artifacts:
            candidates = re.findall(r"`([^`]+)`", field) or re.split(r"[,;]", field)
            for candidate in candidates:
                path = candidate.strip().split("#", 1)[0].replace("\\", "/")
                basename = path.rsplit("/", 1)[-1]
                for phase, files in phase1_files.items():
                    if basename in files:
                        artifact_phases.add(phase)
                for phase, files in OWNER_FILES.items():
                    if basename in files or (
                        phase == "phase3-how"
                        and path.lstrip("./").startswith(("contracts/", "adr/"))
                    ):
                        artifact_phases.add(phase)
        if artifact_phases:
            for phase in phase_order:
                if phase in artifact_phases:
                    return phase

        responsible_agents = re.findall(
            r"^- \*\*Responsible agent:\*\*[ \t]*(.*?)[ \t]*$",
            issues_text,
            re.MULTILINE | re.IGNORECASE,
        )
        normalized_agents = tuple(
            agent.strip().upper() for agent in responsible_agents
        )
        if normalized_agents:
            if any(agent not in owner_phases for agent in normalized_agents):
                return "phase1-what"
            responsible_phases = {
                owner_phases[agent] for agent in normalized_agents
            }
            for phase in phase_order:
                if phase in responsible_phases:
                    return phase
            return "phase1-what"

        action_fields = re.findall(
            r"^- \*\*Action Required:\*\*[ \t]*(.+?)\s*$",
            issues_text,
            re.MULTILINE | re.IGNORECASE,
        )
        action_text = "\n".join(action_fields).upper()
        for phase, agents in (
            ("phase1-discover", ("DISCOVER", "SCOUT")),
            ("phase1-what", ("CARTOGRAPHER",)),
            ("phase3-how", ("ARCHITECT",)),
            ("phase3-sentinel", ("SENTINEL",)),
            ("phase3-plan", ("ORCHESTRATOR",)),
        ):
            if any(
                re.search(rf"\b{re.escape(agent)}\b", action_text)
                for agent in agents
            ):
                return phase
        return "phase1-what"

    def _persist_why3_repair_phase(
        self,
        state_store: "SquadStateStore",
    ) -> None:
        """Persist the controller-owned owner route for a completed WHY3 review.

        WHY3 reports ownership in ``issues.md``; the reviewing agent is not
        permitted to write controller routing state.  Resolve that report only
        after the parallel stage has completed so the following deterministic
        gate can dispatch the smallest capable repair phase.
        """
        state = state_store.load()
        if str(state.get("why3_verdict") or "").upper() != "FAIL":
            if "why3_repair_phase" in state:
                state.pop("why3_repair_phase", None)
                state_store.save(state)
            return

        spec_dir_ref = _normalize_spec_dir_ref(
            str(state.get("spec_dir") or "").strip(),
            self._project_root,
        )
        issues_text = ""
        if spec_dir_ref:
            spec_dir = Path(spec_dir_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            issues_path = spec_dir / "issues.md"
            try:
                issues_text = issues_path.read_text(encoding="utf-8")
            except OSError:
                pass
        state["why3_repair_phase"] = self._why3_repair_phase_from_issues(
            issues_text
        )
        state_store.save(state)

    @staticmethod
    def _normalize_completed_assess2_rejection(
        label: str,
        result: "SquadAgentResult",
    ) -> "SquadAgentResult":
        """Keep a completed ASSESS2 rejection distinct from executor failure.

        Legacy GATEKEEPER prompts can report ``BLOCKED`` for both an incomplete
        invocation and a completed feasibility rejection.  The latter carries
        the controller-owned negative decision and repair target, so normalize
        it before generic blocked-result handling can discard that outcome.
        """
        if (
            label.strip().upper() != "ASSESS2"
            or result.exit_code != 0
            or result.timed_out
            or result.verdict != "BLOCKED"
        ):
            return result
        updates = result.state_updates
        if (
            updates.get("gate_decision") != "REJECTED"
            or updates.get("phase_recommendation") != "phase3-how"
            or not isinstance(updates.get("implementability_metrics"), dict)
        ):
            return result
        payload = dict(result.echelon_result or {})
        payload["verdict"] = "REJECTED"
        result.echelon_result = payload
        return result

    def _build_agent_prompt(
        self,
        agent_entry: dict,
        state: dict,
        extra_files: Optional[list] = None,
        allowed_state_updates: object = None,
        required_state_updates: object = None,
        state_update_types: object = None,
        state_update_enums: object = None,
        allowed_verdicts: object = None,
        phase_id: str = "phase3-consensus",
        controller_context: str = "",
        required_context: str = "",
        omit_context_paths: frozenset[Path] = frozenset(),
        record_context_budget: bool = True,
    ) -> str:
        """Build a prompt for a single staged agent.

        Mirrors AgentExecutor._assemble_prompt logic but uses the per-agent
        context_pack from the agent entry rather than the phase node's context_pack.
        The phase spec_file is intentionally excluded: phase3-consensus.md is
        COMMANDER dispatch instructions, not agent task instructions — including
        it caused agents to receive confusing COMMANDER-oriented text and respond
        with 'Ready. What would you like to work on?'
        """
        agent_id = str(
            agent_entry.get("id") or agent_entry.get("agent", "")
        ).split(" ")[0]
        mode_label = str(agent_entry.get("mode", agent_id))

        static_parts: list[str] = []
        dynamic_parts: list[str] = []
        legacy_sections: list[RenderedSection] = []
        bounded_sections: list[RenderedSection] = []
        selected_render_mode = resolve_context_render_mode()

        # 1. Agent role file (protocol + identity)
        rel = self._graph.agent_file(agent_id)
        if rel:
            agent_path = self._ext_dir / rel
            if agent_path.exists():
                static_parts.append(_read_prompt_body(agent_path))

        # 2. Per-agent context_pack files.
        # state.spec_dir is authoritative for spec artifacts. Do not scan every
        # specs/* directory for bare names: older runs can satisfy spec.md/tasks.md
        # and contaminate staged consensus prompts.
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        search_bases = _spec_search_bases(spec_dir_ref, self._project_root, staging_dir_str)

        def _translate_context_ref(ref: str) -> str:
            return (
                ref.replace("{spec_dir}", spec_dir_ref)
                .replace("{squad_dir}", squad_dir_str)
                .replace("{context_dir}", context_dir_str)
                .replace("{staging_dir}", staging_dir_str)
            )

        for item in agent_entry.get("context_pack", []):
            selector = parse_context_pack_item(item)
            file_ref = selector.path_ref
            if not file_ref or file_ref.startswith("#"):
                continue
            resolved_ref = _translate_context_ref(file_ref)
            if resolved_ref.startswith("/"):
                candidates = [Path(resolved_ref)]
            else:
                candidates = [base / resolved_ref for base in search_bases]
            resolved_candidate = next((candidate for candidate in candidates if candidate.exists()), None)
            if resolved_candidate is not None and resolved_candidate.resolve() in omit_context_paths:
                continue
            legacy_section = None
            for candidate in candidates:
                if candidate.exists():
                    legacy_text = _render_context_candidate(
                        file_ref,
                        candidate,
                        filters=selector.filters,
                    )
                    legacy_section = RenderedSection(
                        str(candidate.resolve()),
                        legacy_text,
                        len(legacy_text.encode("utf-8")),
                        {},
                    )
                    legacy_sections.append(legacy_section)
                    break
            bounded_section = self._render_context_pack_item(
                item=item,
                node_id=phase_id,
                agent_id=agent_id,
                mode=mode_label,
                state=state,
                search_bases=search_bases,
                translate_ref=_translate_context_ref,
            )
            if bounded_section is not None:
                bounded_sections.append(bounded_section)
            if selected_render_mode == "legacy":
                if legacy_section is not None:
                    dynamic_parts.append(legacy_section.text)
            elif bounded_section is not None:
                dynamic_parts.append(bounded_section.text)

        # 3. Any extra files (e.g. implementability-report.md for PLAN2)
        for extra_path in (extra_files or []):
            if extra_path and extra_path.exists():
                dynamic_parts.append(
                    f"\n---\n# {extra_path.name}\n{extra_path.read_text()}"
                )
        # 4. Squad run context preamble + mode instruction
        preamble = (
            f"# Squad Run Context\n"
            f"SQUAD_DIR={squad_dir_str}\n"
            f"STAGING_DIR={staging_dir_str}\n"
            f"CONTEXT_DIR={context_dir_str}\n"
            f"PROJECT_ROOT={self._project_root}\n\n"
            f"{self._stack_context(spec_dir_ref)}"
            f"{_workspace_source_roots_context(self._project_root)}"
            f"{_render_implementation_target_context(state)}"
            f"{_render_product_input_context(state)}"
            f"{_render_controller_repair_context(state)}"
            f"{_render_certified_understanding_context(state, mode_label)}"
            f"{_render_active_spec_roots_context(spec_dir_ref, state, self._project_root)}"
            f"{render_quality_gate_context(self._quality_gate_thresholds())}"
            f"Operate in **{mode_label}** mode.\n\n"
        )

        if required_context:
            dynamic_parts.append(required_context)
            section = RenderedSection("Required Phase 3 review context", required_context,
                len(required_context.encode()), {"truncated": "false"})
            legacy_sections.append(section)
            bounded_sections.append(section)
        prompt = "\n\n".join(static_parts + [preamble] + dynamic_parts)
        prompt = prompt.replace("{spec_dir}", spec_dir_ref)
        prompt = prompt.replace("{squad_dir}", squad_dir_str)
        prompt = prompt.replace("{context_dir}", context_dir_str)
        prompt = prompt.replace("{staging_dir}", staging_dir_str)
        prompt += controller_context

        report = build_context_budget_report(
            phase_id=phase_id,
            agent_id=agent_id,
            mode=mode_label,
            selected_render_mode=selected_render_mode,
            legacy_sections=legacy_sections,
            bounded_sections=bounded_sections,
            strict=False,
        )
        try:
            report_path = write_context_budget_report(self._squad_dir, report) if record_context_budget else None
        except OSError as exc:
            print(
                f"[squad] context budget report unavailable for {phase_id}/{agent_id}: {exc}",
                flush=True,
            )
        else:
            if report_path is not None and report["bounded"]["bytes"] < report["legacy"]["bytes"]:
                print(
                    f"[squad] context bounded for {phase_id}/{agent_id}; report={report_path}",
                    flush=True,
                )

        return (
            _shared_agent_contract()
            + prompt
            + _allowed_state_updates_contract(
                allowed_state_updates,
                required_state_updates=required_state_updates,
                state_update_types=state_update_types,
                state_update_enums=state_update_enums,
                allowed_verdicts=allowed_verdicts,
            )
            + _canonical_echelon_result_contract(self._ext_dir)
        )

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult | ExecutorBlockedResult":
        from harness.squad_provider import SquadAgentResult

        stage1_agents = [a for a in node.agents if a.get("stage", 1) == 1]
        stage2_agents = [a for a in node.agents if a.get("stage", 1) == 2]

        stage1_results: dict[str, SquadAgentResult] = {}
        product_input_updates: list[dict] = []
        state = state_store.load()

        # A review submission is not closure. Give SAGE the exact selected
        # instance and content manifest, then persist its independent verdict
        # before PLAN2 can return BLOCKED.
        from dataclasses import asdict
        from harness.phase3_repair import RepairIdentity, RepairContractError, review_from_result
        from harness.phase3_repair_context import capture_review_inputs
        from harness.phase3_repair_routing import has_phase3_repairs
        roles = {(str(a.get("id") or a.get("agent", "")).split(" ")[0], a.get("mode")) for a in stage1_agents}
        final_enabled = (node.id == "phase3-consensus"
                         and roles == {("echelon.sage", "WHY3"), ("echelon.gatekeeper", "ASSESS2")}
                         and len(stage2_agents) == 1 and stage2_agents[0].get("mode") == "PLAN2")
        final_round = None
        if final_enabled:
            spec_dir = Path(_normalize_spec_dir_ref(str(state.get("spec_dir") or ""), self._project_root))
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            try:
                final_inputs = self._final_review_inputs(node, state, spec_dir)
                candidate_round = state.get("phase3_final_review")
                if candidate_round:
                    if candidate_round == {"candidate": final_inputs, "reports": self._final_review_reports(spec_dir)}:
                        final_round = candidate_round
                    else:
                        self._record_final_review(node, state_store, None)
            except (RepairContractError, OSError, UnicodeError) as exc:
                return self._repair_block("repair_context_incomplete", str(exc))
        if has_phase3_repairs(state):
            try:
                prior_spec = Path(_normalize_spec_dir_ref(str(state.get("spec_dir") or ""), self._project_root))
                if not prior_spec.is_absolute():
                    prior_spec = self._project_root / prior_spec
                manifest, _ = capture_review_inputs(prior_spec, project_root=self._project_root)
                if not state_store.reconcile_phase3_review_inputs(
                        snapshot=state_store.capture_routing_snapshot(expected_phase=node.id), input_manifest=manifest):
                    raise RepairContractError("state changed before stale review reconciliation")
                state = state_store.load()
            except (RepairContractError, OSError, UnicodeError) as exc:
                return self._repair_block("repair_context_incomplete", str(exc))
        selected = state.get("selected_issue_resolution")
        entry = (state.get("issue_resolution_ledger") or {}).get(selected)
        review_only_dispatch = isinstance(entry, dict) and bool(entry.get("review_revalidation_required"))
        ordered_repair_review = node.id == "phase3-consensus" and state.get("autonomy_mode") == "banzai"
        review_envelope = None
        reviewer_dispatch = None
        review_inputs = ""
        planner_context = ""
        if (isinstance(entry, dict) and entry.get("status") == "repaired"
                and entry.get("repair_phase") in {"phase3-how", "phase3-sentinel", "phase3-plan"}):
            snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
            if not entry.get("repair_identity"):
                from harness.issue_identity import issue_fingerprint
                try:
                    entry["repair_identity"] = asdict(RepairIdentity(
                        str(state.get("run_id")),
                        entry.get("issue_fingerprint") or issue_fingerprint(str(entry.get("title", "")), str(entry.get("decision", ""))),
                        snapshot.state_revision,
                    ))
                except (RepairContractError, TypeError) as exc:
                    return self._repair_block("repair_review_stale", str(exc))
                if not state_store.commit_routing_snapshot_state(snapshot, state):
                    return ExecutorBlockedResult(reason="repair_review_stale", result=SquadAgentResult(
                        exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_review_stale"}}, raw_output="selection changed before review", duration_ms=0, timed_out=False))
                state = state_store.load()
            try:
                review_identity = RepairIdentity(**entry["repair_identity"])
            except (RepairContractError, TypeError) as exc:
                return self._repair_block("repair_review_stale", str(exc))
            spec_path = Path(_normalize_spec_dir_ref(str(state.get("spec_dir", "")), self._project_root))
            if not spec_path.is_absolute():
                spec_path = self._project_root / spec_path
            try:
                review_manifest, review_inputs = capture_review_inputs(spec_path, project_root=self._project_root)
            except (RepairContractError, OSError, UnicodeError) as exc:
                return ExecutorBlockedResult(reason="repair_context_incomplete", result=SquadAgentResult(
                    exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_context_incomplete"}}, raw_output=str(exc), duration_ms=0, timed_out=False))
            review_envelope = {"identity": asdict(review_identity), "input_manifest": review_manifest,
                               "selected_issue": selected, "title": entry.get("title"), "decision": entry.get("decision"),
                               "repair_action": entry.get("repair_action")}
            from harness.phase3_repair_context import planner_handoff_context
            planner_context = planner_handoff_context(state, review_manifest)

        # Stage 1: run in parallel
        with ThreadPoolExecutor(max_workers=max(len(stage1_agents), 1)) as pool:
            futures: dict = {}
            for agent_entry in stage1_agents:
                agent_id = str(
                    agent_entry.get("id") or agent_entry.get("agent", "")
                ).split(" ")[0]
                mode_label = str(
                    agent_entry.get("mode")
                    or agent_entry.get("id")
                    or agent_entry.get("agent", "")
                )
                result_contract = self._result_contract(node, agent_entry)
                required_review = (
                    self._issue_review_context(review_envelope, review_inputs)
                    if review_envelope and agent_id == "echelon.sage" and mode_label == "WHY3" else ""
                )
                if agent_id == "echelon.sage" and mode_label == "WHY3":
                    required_review += planner_context
                if final_round:
                    required_review += ("\n## Fixed-candidate final review\n"
                        "PLAN2 has completed. Independently review this final candidate; all existing gates apply. "
                        "ALWAYS write findings only to issues.md, quality-gates.md or implementability-report.md "
                        "and return the usual verdict and journal entries. NEVER rewrite candidate inputs, "
                        "including estimates.md, scope, requirements, contracts or planning artifacts. "
                        "If any input needs repair, return a failing gate and concrete owner-directed findings. "
                        "A report revision alone is not a request for PLAN2.\n")
                prompt = self._build_agent_prompt(
                    agent_entry,
                    state,
                    allowed_state_updates=result_contract.allowed_state_update_keys,
                    required_state_updates=result_contract.required_state_update_keys,
                    state_update_types=result_contract.state_update_types,
                    state_update_enums=result_contract.state_update_enums,
                    allowed_verdicts=result_contract.allowed_verdicts,
                    phase_id=node.id,
                    controller_context=getattr(node, "controller_context", ""),
                    required_context=required_review,
                )
                prompt_metadata: dict[str, object] = {}
                if agent_id == "echelon.sage":
                    rel = self._graph.agent_file(agent_id)
                    if rel:
                        agent_path = self._ext_dir / rel
                        if agent_path.exists():
                            prompt_metadata = _read_prompt_metadata(agent_path)
                prompt_metadata = self._phase_prompt_metadata(
                    node,
                    state,
                    prompt_metadata,
                    agent_id=agent_id,
                    outputs=agent_entry.get(
                        "outputs", getattr(node, "outputs", [])
                    ),
                )
                if review_envelope and agent_id == "echelon.sage" and mode_label == "WHY3":
                    reviewer_dispatch = (agent_entry, result_contract, prompt_metadata)
                futures[pool.submit(
                    self._exec_agent_with_contract,
                    prompt,
                    result_contract,
                    prompt_metadata,
                )] = (mode_label, result_contract, agent_id)

            for future in as_completed(futures):
                label, result_contract, agent_id = futures[future]
                raw_result = self._normalize_completed_assess2_rejection(
                    label,
                    future.result(),
                )
                result = self._validate_result_state_updates(
                    node,
                    raw_result,
                    result_contract=result_contract,
                    direct_state_write=True,
                )
                if result.blocked and not (
                    review_envelope and agent_id == "echelon.sage" and label == "WHY3"
                    and not isinstance(result, ExecutorBlockedResult)
                ):
                    return result
                if "phase3_issue_review" in (result.echelon_result or {}):
                    if not review_envelope or agent_id != "echelon.sage" or label != "WHY3":
                        return ExecutorBlockedResult(reason="invalid_phase_outputs", result=SquadAgentResult(
                            exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "invalid_phase_outputs"}}, raw_output="unsolicited or non-SAGE issue review", duration_ms=0, timed_out=False))
                stage1_results[label] = result
                payload = result.echelon_result or {}
                product_input_updates.extend(payload.get("product_input_updates") or [])

        # Write stage-1 verdicts, journal entries, and cost to state (serial — after join)
        for label, result in stage1_results.items():
            self._write_journal_entries(result, node.id)
            state_store.increment_cost(result.cost_usd)
            state = state_store.load()
            verdict_state_key = _STAGED_VERDICT_STATE_KEYS.get(
                label.strip().upper()
            )
            if verdict_state_key is not None:
                state[verdict_state_key] = result.verdict
            for k, v in result.state_updates.items():
                state[k] = v
            state_store.save(state)

        self._persist_why3_repair_phase(state_store)

        if final_round:
            try:
                if not (spec_dir / "implementability-report.md").is_file():
                    self._record_final_review(node, state_store, None)
                    return self._repair_block("missing_consensus_prerequisite", "final ASSESS2 report is missing")
                if self._final_review_inputs(node, state_store.load(), spec_dir) != final_round["candidate"]:
                    self._record_final_review(node, state_store, None)
                    raise RepairContractError("final candidate inputs changed during review")
            except (RepairContractError, OSError, UnicodeError) as exc:
                return self._repair_block("repair_review_stale", str(exc))

        if review_envelope and "WHY3" in stage1_results:
            try:
                review = review_from_result(stage1_results["WHY3"].echelon_result or {},
                    agent_id="echelon.sage", mode="WHY3", expected=review_identity, expected_manifest=review_manifest,
                    expected_selection=review_envelope["selected_issue"],
                    expected_spec_dir=spec_path, project_root=self._project_root)
                if review is None:
                    return ExecutorBlockedResult(reason="repair_review_missing", result=SquadAgentResult(
                        exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_review_missing"}},
                        raw_output="SAGE did not assess the selected issue; fresh explicit review is required", duration_ms=0, timed_out=False))
                current_manifest, _ = capture_review_inputs(spec_path, project_root=self._project_root)
                if current_manifest != review_manifest:
                    raise RepairContractError("reviewed inputs changed during review")
                if review is not None:
                    snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                    review_id = hashlib.sha256(json.dumps({"envelope": review_envelope,
                        "dispatch": state.get("last_dispatch"), "revision": snapshot.state_revision}, sort_keys=True).encode()).hexdigest()
                    if not state_store.commit_phase3_issue_review(snapshot=snapshot,
                            review_dispatch_id=review_id, review=review, input_manifest=current_manifest):
                        raise RepairContractError("selected issue changed during review")
            except (RepairContractError, OSError, UnicodeError) as exc:
                return ExecutorBlockedResult(reason="repair_review_stale", result=SquadAgentResult(
                    exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_review_stale"}}, raw_output=str(exc), duration_ms=0, timed_out=False))

        # A valid issue assessment survives even a reviewer-owned gate BLOCKED.
        # It is not permission to dispatch dependent stages or advance the gate.
        if review_envelope and stage1_results.get("WHY3") and stage1_results["WHY3"].blocked:
            return stage1_results["WHY3"]

        if final_round:
            all_pass = all(r.verdict in ("PASS", "DONE") for r in stage1_results.values())
            reconciliation_error = self._reconcile_final_reviews(node, state_store)
            if reconciliation_error is not None:
                return reconciliation_error
            current = state_store.load()
            pending = bool(current.get("selected_issue_resolution"))
            selected_entry = (current.get("issue_resolution_ledger") or {}).get(current.get("selected_issue_resolution"), {})
            unperformed_review = pending and selected_entry.get("review_revalidation_required")
            if pending and not unperformed_review:
                # An explicit negative selected-issue assessment cannot be
                # hidden by an aggregate PASS or sent around as another review.
                all_pass = False
                current["why3_verdict"] = "FAIL"
                state_store.save(current)
            try:
                self._record_final_review(node, state_store,
                    {**final_round, "reports": self._final_review_reports(spec_dir)} if all_pass and unperformed_review else None)
            except RepairContractError as exc:
                return self._repair_block("repair_review_stale", str(exc))
            assessment_error = self._assess_phase3_work(node, state_store)
            if assessment_error is not None:
                return assessment_error
            return SquadAgentResult(exit_code=0, echelon_result={
                "verdict": "PASS" if all_pass and not pending else "FAIL", "state_updates": {},
                "product_input_updates": product_input_updates}, raw_output="Final candidate reviewed",
                duration_ms=0, timed_out=False)

        if ordered_repair_review:
            # Drain independent reviews on the same candidate before allowing
            # PLAN2 to regenerate their dependencies. Classify remaining work
            # before dispatching that dependent consumer, not after it blocks.
            reconciliation_error = self._reconcile_final_reviews(node, state_store)
            if reconciliation_error is not None:
                return reconciliation_error
            assessment_error = self._assess_phase3_work(node, state_store)
            if assessment_error is not None:
                return assessment_error
            current = state_store.load()
            if (current.get("why3_verdict") == "FAIL"
                    or current.get("selected_issue_resolution") or current.get("phase3_pending_action")):
                return SquadAgentResult(exit_code=0, echelon_result={
                    "verdict": "FAIL", "state_updates": {}, "product_input_updates": product_input_updates,
                }, raw_output="PLAN2 deferred until prerequisite reviews and repairs complete",
                    duration_ms=0, timed_out=False)

        # Stage 2: PLAN2 requires the exact run-local ASSESS2 report.
        impl_report_path: Optional[Path] = None
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        if spec_dir_ref:
            spec_dir = Path(spec_dir_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            impl_report_path = spec_dir / "implementability-report.md"

        if stage2_agents and (
            impl_report_path is None or not impl_report_path.is_file()
        ):
            expected = (
                impl_report_path
                if impl_report_path is not None
                else Path(spec_dir_ref or "{spec_dir}") / "implementability-report.md"
            )
            return ExecutorBlockedResult(
                reason="missing_consensus_prerequisite",
                result=SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "BLOCKED",
                        "state_updates": {
                            "blocked_reason": "missing_consensus_prerequisite",
                            "missing_outputs": [str(expected)],
                        },
                        "journal_entries": [],
                    },
                    raw_output=f"required PLAN2 input is missing: {expected}",
                    duration_ms=0,
                    timed_out=False,
                ),
            )

        state = state_store.load()
        accepted_risk = (state.get("gate_decision") == "accept_with_risk"
                         or state.get("phase_recommendation") == "advance_past_consensus_to_delivery")
        if (node.id == "phase3-consensus" and stage1_results.get("ASSESS2")
                and stage1_results["ASSESS2"].verdict == "REJECTED"
                and not accepted_risk):
            # A completed producer rejection is actionable review evidence.
            # Do not require its dependent planner to succeed before the normal
            # tasks-recertification/architecture-repair route can consume it.
            # Keep both verdicts: selected closure never waives feasibility.
            return SquadAgentResult(exit_code=0, echelon_result={
                "verdict": "FAIL", "state_updates": {}, "product_input_updates": product_input_updates,
            }, raw_output="ASSESS2 rejected the candidate; PLAN2 deferred to the existing repair route",
                duration_ms=0, timed_out=False)
        for agent_entry in stage2_agents:
            agent_id = str(
                agent_entry.get("id") or agent_entry.get("agent", "")
            ).split(" ")[0]
            result_contract = self._result_contract(node, agent_entry)
            prompt = self._build_agent_prompt(
                agent_entry,
                state,
                extra_files=[impl_report_path],
                allowed_state_updates=result_contract.allowed_state_update_keys,
                required_state_updates=result_contract.required_state_update_keys,
                state_update_types=result_contract.state_update_types,
                state_update_enums=result_contract.state_update_enums,
                allowed_verdicts=result_contract.allowed_verdicts,
                phase_id=node.id,
                controller_context=getattr(node, "controller_context", ""),
            )
            # Only reuse a successful PLAN2 during its final review handoff.
            # Bind both full review inputs and the rendered planner contract:
            # reports, constitution, role instructions and context changes all
            # invalidate reuse. Legacy/missing receipts simply rerun planning.
            plan2_receipt = None
            cache_plan2 = (not final_enabled and ordered_repair_review and has_phase3_repairs(state)
                          and len(stage2_agents) == 1 and agent_entry.get("mode") == "PLAN2")
            if cache_plan2:
                try:
                    plan_manifest, _ = capture_review_inputs(spec_dir, project_root=self._project_root)
                except (RepairContractError, OSError, UnicodeError) as exc:
                    return self._repair_block("repair_context_incomplete", str(exc))
                plan2_receipt = {"schema_version": 1, "run_id": state.get("run_id"),
                    "input_manifest": plan_manifest, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "agent_contract": agent_entry}
                if (review_only_dispatch and all(r.verdict in ("PASS", "DONE") for r in stage1_results.values())
                        and state.get("phase3_plan2_completion") == plan2_receipt):
                    continue
                # Starting another attempt retires previous success even if
                # this provider call later fails or the process is interrupted.
                snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                recorded = dict(snapshot.state)
                recorded.pop("phase3_plan2_completion", None)
                if not state_store.commit_routing_snapshot_state(snapshot, recorded):
                    return self._repair_block("repair_review_stale", "state changed before PLAN2 attempt")
                from harness.phase3_repair_routing import OWNER_FILES
                planner_outputs = OWNER_FILES["phase3-plan"]
                stable_prompt_kwargs = dict(
                    extra_files=[impl_report_path],
                    allowed_state_updates=result_contract.allowed_state_update_keys,
                    required_state_updates=result_contract.required_state_update_keys,
                    state_update_types=result_contract.state_update_types,
                    state_update_enums=result_contract.state_update_enums,
                    allowed_verdicts=result_contract.allowed_verdicts, phase_id=node.id,
                    controller_context=getattr(node, "controller_context", ""),
                    omit_context_paths=frozenset((spec_dir / name).resolve() for name in planner_outputs),
                    record_context_budget=False,
                )
                stable_prompt = self._build_agent_prompt(agent_entry, state, **stable_prompt_kwargs)
                stable_manifest = {name: digest for name, digest in plan_manifest.items() if name not in planner_outputs}
            prompt_metadata: dict[str, object] = {}
            if agent_id == "echelon.sage":
                rel = self._graph.agent_file(agent_id)
                if rel:
                    agent_path = self._ext_dir / rel
                    if agent_path.exists():
                        prompt_metadata = _read_prompt_metadata(agent_path)
            prompt_metadata = self._phase_prompt_metadata(
                node,
                state,
                prompt_metadata,
                agent_id=agent_id,
                outputs=agent_entry.get("outputs", getattr(node, "outputs", [])),
            )
            if final_enabled:
                # Retire previous success before an attempt, and capture its
                # consumed inputs so PLAN2 cannot silently change prerequisites.
                try:
                    self._record_final_review(node, state_store, None)
                    plan_inputs = self._final_review_inputs(node, state_store.load(), spec_dir)
                    plan_reports = self._final_review_reports(spec_dir)
                except (RepairContractError, OSError, UnicodeError) as exc:
                    return self._repair_block("repair_context_incomplete", str(exc))
            stage2_result = self._exec_agent_with_contract(
                prompt, result_contract, prompt_metadata
            )
            stage2_result = self._validate_result_state_updates(
                node,
                stage2_result,
                result_contract=result_contract,
                direct_state_write=True,
            )
            if cache_plan2 and not stage2_result.blocked and stage2_result.verdict in ("PASS", "DONE", "COMPLETE"):
                # Capture the output candidate before final reviews can modify
                # their reports. A later changed report must invalidate reuse.
                try:
                    plan_manifest, _ = capture_review_inputs(spec_dir, project_root=self._project_root)
                    output_prompt = self._build_agent_prompt(agent_entry, state_store.load(),
                        extra_files=[impl_report_path],
                        allowed_state_updates=result_contract.allowed_state_update_keys,
                        required_state_updates=result_contract.required_state_update_keys,
                        state_update_types=result_contract.state_update_types,
                        state_update_enums=result_contract.state_update_enums,
                        allowed_verdicts=result_contract.allowed_verdicts, phase_id=node.id,
                        controller_context=getattr(node, "controller_context", ""), record_context_budget=False)
                    # Only owned outputs may be rebound to the output candidate.
                    # Never certify newly changed instructions or prerequisites
                    # that were not consumed by the successful dispatch.
                    if (stable_manifest != {name: digest for name, digest in plan_manifest.items() if name not in planner_outputs}
                            or stable_prompt != self._build_agent_prompt(agent_entry, state_store.load(), **stable_prompt_kwargs)):
                        plan2_receipt = None
                    else:
                        plan2_receipt = {**plan2_receipt, "input_manifest": plan_manifest,
                            "prompt_sha256": hashlib.sha256(output_prompt.encode()).hexdigest()}
                except (RepairContractError, OSError, UnicodeError) as exc:
                    return self._repair_block("repair_context_incomplete", str(exc))
            else:
                plan2_receipt = None
            if review_envelope and (not final_enabled or stage2_result.blocked):
                try:
                    final_manifest, _ = capture_review_inputs(spec_path, project_root=self._project_root)
                except (RepairContractError, OSError, UnicodeError):
                    final_manifest = {}
                if final_manifest != review_manifest:
                    invalidated = state_store.invalidate_phase3_issue_review(
                        snapshot=state_store.capture_routing_snapshot(expected_phase=node.id),
                        review_dispatch_id=review_id,
                    )
                    try:
                        if not invalidated or reviewer_dispatch is None:
                            raise RepairContractError("selection changed before final-candidate review")
                        review_manifest, review_inputs = capture_review_inputs(spec_path, project_root=self._project_root)
                        if not state_store.claim_phase3_revalidation(
                                snapshot=state_store.capture_routing_snapshot(expected_phase=node.id),
                                identity=review_identity, input_manifest=review_manifest):
                            raise RepairContractError("final-candidate review already attempted for these inputs")
                        sage_entry, sage_contract, sage_metadata = reviewer_dispatch
                        fresh_state = state_store.load()
                        fresh_envelope = {**review_envelope, "input_manifest": review_manifest}
                        fresh_prompt = self._build_agent_prompt(sage_entry, fresh_state,
                            allowed_state_updates=sage_contract.allowed_state_update_keys,
                            required_state_updates=sage_contract.required_state_update_keys,
                            state_update_types=sage_contract.state_update_types,
                            state_update_enums=sage_contract.state_update_enums,
                            allowed_verdicts=sage_contract.allowed_verdicts, phase_id=node.id,
                            controller_context=getattr(node, "controller_context", ""),
                            required_context=self._issue_review_context(fresh_envelope, review_inputs))
                        fresh_result = self._validate_result_state_updates(node,
                            self._exec_agent_with_contract(fresh_prompt, sage_contract, sage_metadata),
                            result_contract=sage_contract, direct_state_write=True)
                        if isinstance(fresh_result, ExecutorBlockedResult):
                            return fresh_result
                        state_store.increment_cost(fresh_result.cost_usd)
                        self._write_journal_entries(fresh_result, node.id)
                        fresh_review = review_from_result(fresh_result.echelon_result or {},
                            agent_id="echelon.sage", mode="WHY3", expected=review_identity, expected_manifest=review_manifest,
                            expected_selection=fresh_envelope["selected_issue"],
                            expected_spec_dir=spec_path, project_root=self._project_root)
                        if fresh_review is None:
                            raise RepairContractError("final-candidate review omitted the selected issue")
                        current_manifest, _ = capture_review_inputs(spec_path, project_root=self._project_root)
                        if current_manifest != review_manifest:
                            raise RepairContractError("final candidate changed again during revalidation")
                        snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                        fresh_id = hashlib.sha256(json.dumps({"envelope": fresh_envelope,
                            "revision": snapshot.state_revision}, sort_keys=True).encode()).hexdigest()
                        if not state_store.commit_phase3_issue_review(snapshot=snapshot,
                                review_dispatch_id=fresh_id, review=fresh_review, input_manifest=current_manifest):
                            raise RepairContractError("selection changed during final-candidate review")
                        stage1_results["WHY3"] = fresh_result
                        state = state_store.load()
                        state["why3_verdict"] = fresh_result.verdict
                        state_store.save(state)
                    except (RepairContractError, OSError, UnicodeError) as exc:
                        return ExecutorBlockedResult(reason="repair_review_stale", result=SquadAgentResult(
                            exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {"blocked_reason": "repair_review_stale"}},
                            raw_output=str(exc), duration_ms=0, timed_out=False))
            reconciliation_error = self._reconcile_final_reviews(node, state_store)
            if reconciliation_error is not None:
                return reconciliation_error
            if stage2_result.blocked:
                if not isinstance(stage2_result, ExecutorBlockedResult):
                    summary = (stage2_result.echelon_result or {}).get("phase3_blocker")
                    if (isinstance(summary, dict) and set(summary) == {"issue_id", "owner_phase", "detail", "next_action"}
                            and all(isinstance(value, str) and 0 < len(value.strip()) <= 2000 for value in summary.values())):
                        snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                        recorded = dict(snapshot.state)
                        recorded["phase3_last_blocker"] = {"producer": "PLAN2", **summary}
                        if not state_store.commit_routing_snapshot_state(snapshot, recorded):
                            return self._repair_block("repair_review_stale", "state changed while preserving PLAN2 handoff")
                assessment_error = self._assess_phase3_work(node, state_store)
                if assessment_error is not None:
                    return assessment_error
                return stage2_result
            stage2_payload = stage2_result.echelon_result or {}
            product_input_updates.extend(stage2_payload.get("product_input_updates") or [])
            self._write_journal_entries(stage2_result, node.id)
            state_store.increment_cost(stage2_result.cost_usd)
            state = state_store.load()
            for k, v in stage2_result.state_updates.items():
                state[k] = v
            state_store.save(state)
            if plan2_receipt is not None:
                snapshot = state_store.capture_routing_snapshot(expected_phase=node.id)
                recorded = dict(snapshot.state)
                recorded["phase3_plan2_completion"] = plan2_receipt
                if not state_store.commit_routing_snapshot_state(snapshot, recorded):
                    return self._repair_block("repair_review_stale", "state changed while recording completed PLAN2")

            if (final_enabled and stage2_result.verdict in ("PASS", "DONE", "COMPLETE")
                    and all(r.verdict in ("PASS", "DONE") for r in stage1_results.values())):
                from harness.phase3_repair_routing import OWNER_FILES
                try:
                    output_inputs = self._final_review_inputs(node, state_store.load(), spec_dir)
                    outputs = {str((spec_dir / name).resolve()) for name in OWNER_FILES["phase3-plan"]}
                    def prerequisites(receipt):
                        return {**receipt, "inputs": {name: value for name, value in receipt["inputs"].items()
                                                       if name not in outputs}}
                    if (prerequisites(output_inputs) != prerequisites(plan_inputs)
                            or self._final_review_reports(spec_dir) != plan_reports):
                        return self._repair_block("repair_review_stale", "PLAN2 changed inputs outside its owned outputs")
                    self._record_final_review(node, state_store,
                        {"candidate": output_inputs, "reports": self._final_review_reports(spec_dir)})
                except (RepairContractError, OSError, UnicodeError) as exc:
                    return self._repair_block("repair_review_stale", str(exc))
                return SquadAgentResult(exit_code=0, echelon_result={"verdict": "FAIL", "state_updates": {},
                    "product_input_updates": product_input_updates}, raw_output="PLAN2 complete; final review pending",
                    duration_ms=0, timed_out=False)

        all_pass = all(
            r.verdict in ("PASS", "DONE") for r in stage1_results.values()
        )
        assessment_error = self._assess_phase3_work(node, state_store)
        if assessment_error is not None:
            return assessment_error
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS" if all_pass else "FAIL",
                "state_updates": {},
                "product_input_updates": product_input_updates,
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class ConditionalSequentialExecutor(PhaseExecutor):
    """Handles type: conditional_sequential — dispatches agents based on state conditions."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.condition_evaluator import ConditionEvaluator
        from harness.squad_provider import SquadAgentResult
        ev = ConditionEvaluator()
        state = state_store.load()

        for agent_entry in node.agents:
            condition = agent_entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            agent_id = str(
                agent_entry.get("id") or agent_entry.get("agent", "")
            ).split(" ")[0]
            rel = self._graph.agent_file(agent_id)
            if rel:
                path = self._ext_dir / rel
                if path.exists():
                    result_contract = self._result_contract(node, agent_entry)
                    squad_dir_str = str(
                        state.get("squad_dir") or self._squad_dir
                    )
                    staging_dir_str = str(
                        state.get("staging_dir")
                        or self._squad_dir / "staging"
                    )
                    context_dir_str = str(
                        state.get("context_dir")
                        or self._squad_dir / "context"
                    )
                    spec_dir_ref = _normalize_spec_dir_ref(
                        str(state.get("spec_dir") or "").strip(),
                        self._project_root,
                    )
                    prompt = (
                        _shared_agent_contract()
                        + path.read_text()
                        + _render_product_input_context(state)
                        + _render_controller_repair_context(state)
                    )
                    prompt = prompt.replace("{spec_dir}", spec_dir_ref)
                    prompt = prompt.replace("{squad_dir}", squad_dir_str)
                    prompt = prompt.replace("{context_dir}", context_dir_str)
                    prompt = prompt.replace("{staging_dir}", staging_dir_str)
                    prompt = (
                        prompt
                        + getattr(node, "controller_context", "")
                        + _allowed_state_updates_contract(
                            result_contract.allowed_state_update_keys,
                            required_state_updates=result_contract.required_state_update_keys,
                            state_update_types=result_contract.state_update_types,
                            state_update_enums=result_contract.state_update_enums,
                            allowed_verdicts=result_contract.allowed_verdicts,
                        )
                        + _canonical_echelon_result_contract(self._ext_dir)
                    )
                    prompt_metadata = self._phase_prompt_metadata(
                        node,
                        state,
                        _read_prompt_metadata(path)
                        if agent_id == "echelon.sage"
                        else {},
                        agent_id=agent_id,
                        outputs=agent_entry.get(
                            "outputs", getattr(node, "outputs", [])
                        ),
                    )
                    result = self._exec_agent_with_contract(
                        prompt, result_contract, prompt_metadata
                    )
                    result = self._validate_result_state_updates(
                        node,
                        result,
                        result_contract=result_contract,
                        direct_state_write=True,
                    )
                    if result.blocked:
                        return result
                    self._write_journal_entries(result, node.id)
                    state = state_store.load()
                    for k, v in result.state_updates.items():
                        state[k] = v
                    state_store.save(state)

        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

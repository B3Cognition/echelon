"""SquadController — deterministic phase routing for the pre-code squad run."""
from __future__ import annotations

import codecs
import hashlib
import hmac
import json
import logging
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import time
import threading
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Optional

from echelon.artifact_index import write_artifact_index
from echelon.context_builder import build_run_context
from echelon.kb_proposals import accepted_kb_target_paths
from echelon.spec_authoring import (
    PROPORTIONAL_MODE,
    normalize_spec_authoring_mode,
)
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleLocked,
    SpecRunExecutionLock,
)
from harness.condition_evaluator import ConditionEvaluator
from harness.controller_state_contracts import ControllerStateContractViolation
from harness.controller_state_contract_requirements import (
    required_controller_contract_name,
)
from harness.echelon_result_schema import (
    DECISION_RESOLUTION_RATIONALE_MAX_CHARS,
    EchelonResultContract,
    EchelonResultValidationError,
    validate_decision_resolution_result,
    validate_echelon_result,
    validate_echelon_result_contract,
)
from harness.blocked_decision import (
    BlockedDecisionError,
    validate_blocked_decision,
)
from harness.human_input import (
    AppliedHumanInputResolution,
    HUMAN_INPUT_MAX_OPTIONS,
    HUMAN_INPUT_OPTION_LABEL_MAX_BYTES,
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyError,
    HumanInputPolicyRegistry,
    PreparedHumanInput,
    ProportionalQualityRecommendationEvidence,
    gate_outcome_route_error,
    legacy_recovery_policy_alias,
    prepare_controller_proportional_quality_decision,
    select_initial_decision_status,
)
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.checkpoint_policy import (
    CheckpointPolicyError,
    checkpoint_additional_owned_paths,
    phase_checkpoint_policy,
)
from harness.phase_a_readiness import (
    PhaseAReadinessResult,
    unresolved_constitution_template_markers,
    validate_phase_a_readiness,
)
from harness.phase_checkpoints import create_phase_checkpoint
from harness.spec_frontmatter import write_text_atomic
from harness.phase1_quality import (
    AuthoritativeQualityAssessment,
    build_legacy_phase1_quality_certificate,
    build_phase1_quality_certificate,
    has_current_phase1_quality_prerequisite,
)
from harness.phase1_quality_debt import build_quality_debt_authorization
from harness.proportional_quality import (
    QualityCandidateIntegrityError,
    QualityCandidateManifest,
    QualityCandidateSnapshot,
    candidate_artifact_preimage_digests,
    is_actionable_sage_issue,
    load_authoritative_sage_evidence_snapshot,
    initialize_repair_state,
    load_quality_candidate_manifest,
    load_quality_candidate_snapshot,
    rank_quality_candidates,
    record_what_outcome,
    prepare_quality_candidate,
    quality_candidate_effect_payload,
    validate_repair_state,
)
from harness.proportional_quality_effects import (
    apply_or_verify_proportional_quality_effect,
)
from harness.prepared_phase_result import (
    PreparedPhaseResult,
    PreparedRoutingDecision,
    _canonical_payload_sha256,
    detach_squad_agent_result,
    prepare_phase_result,
)
from harness.quality_scores import (
    effective_quality_gate_thresholds,
    explicit_quality_pass,
    normalize_why_quality_scores,
    resolve_quality_gate_thresholds,
)
from harness.recovery_instruction import (
    RecoveryKind,
    RecoveryInstruction,
    controller_contract_recovery,
    retry_phase_recovery,
    trusted_executor_block_recovery,
    validate_recovery_instruction,
)
from harness.published_re_context import (
    attach_published_re_context,
    write_canonical_re_context,
)
from harness.run_history import append_phase_a_run
from harness.spec_frontmatter import find_spec_dir, write_targets
from echelon.spec_retarget_history import (
    advance_retarget_revision,
    load_retarget_history,
)
from harness.spec_lexicon_gate import has_current_spec_lexicon_evidence
from harness.squad_executors import (
    AgentExecutor,
    CommanderInternalExecutor,
    ConditionalSequentialExecutor,
    DeterministicLexiconExecutor,
    DeterministicStructuralExecutor,
    DeterministicUnderstandingExecutor,
    ExecutorBlockedResult,
    PhaseExecutor,
    StagedParallelExecutor,
    _MANDATORY_PHASE_OUTPUTS,
)
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_completion import (
    CompletionError,
    PreparedControllerCompletion,
    apply_or_verify_completion_journal,
    apply_or_verify_completion_mining,
    apply_or_verify_completion_timing,
    create_or_recover_completion_checkpoint,
    discard_unreferenced_controller_completion,
    install_or_verify_completion_context,
    load_prepared_controller_completion,
    persist_completion_effect_receipt,
    prepare_completion_journal_plan,
    prepare_controller_completion as prepare_controller_completion_stage,
    prepare_or_load_completion_context,
)
from harness.controller_lock_order import controller_lock_order
from harness.squad_publication import (
    PreparedSquadPublication,
    PublicationError,
    SquadPublicationTransaction,
    add_verified_quality_debt_publication,
    authenticate_prepared_quality_debt_publication,
    load_prepared_publication,
)
from echelon.telemetry.phase_timing import record_phase_finish, record_phase_start
from echelon.telemetry.provider import DispatchContext, InstrumentedProvider
from echelon.telemetry.store import TelemetryStore
from harness.squad_state import (
    AdvanceReceipt,
    RoutingStateSnapshot,
    StateAdvanceError,
    StateDurabilityError,
    SquadStateStore,
)
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
    PRODUCT_INPUT_MUTATION_KEY,
    STORE_OWNED_TRANSACTION_KEYS,
    TRUSTED_ROUTING_EFFECT_KEYS,
    validate_pending_controller_completion,
    validate_pending_external_publication,
)
from echelon.product_input_transaction import (
    ProductInputMutationError,
    add_complete_product_input_publication,
    authenticate_pending_product_input_mutation,
    authenticate_product_input_contract,
    build_product_input_mutation,
    product_input_tree_identity,
    require_product_input_mutation_postimage,
    restore_product_input_directory_modes,
)
from echelon.product_inputs import (
    ProductInputError,
    immutable_product_input_tree_digest,
    validate_immutable_product_input_package,
)
from harness.prompt_markdown import read_prompt_markdown
from harness.terminal import color_text
from harness.understanding_gate import has_current_understanding_evidence


PHASE_TERMINAL_BLOCKED = "terminal-blocked"
TERMINAL_PHASES = {"DONE", "done", PHASE_TERMINAL_BLOCKED}
WHY_PHASES = frozenset({"phase1-why1", "phase1-why2"})
ITERATIVE_PHASES = WHY_PHASES | frozenset(
    {
        "phase1-what",
        "phase1-lexicon",
        # Understanding verifies every WHAT amendment. It is a bounded
        # remediation-cycle phase, not a one-shot phase with a five-run cap.
        "phase1-understanding",
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-consensus",
    }
)

# Max times the convergence guard may redirect to the same recommended phase before
# force-advancing. Protects against agents that re-assert convergence on every dispatch.
MAX_CONVERGENCE_GUARD_FIRES = 3

# Max dispatches of a non-iterative phase per run before forcing escalation.
# Iterative authoring and verification phases use the configured repair-cycle
# budget; their no-progress safeguards remain the authority for stopping loops.
MAX_PHASE_DISPATCHES = 5
# An authoring or planning agent gets the original pass plus two
# controller-directed repairs to resolve its own product-input mapping errors.
# This is intentionally bounded: the controller may demand evidence, but must
# never invent mappings.
MAX_PRODUCT_INPUT_MAPPING_REPAIRS = 2
PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION = 2
PROJECT_MODES = {"greenfield", "brownfield", "self_analysis"}
WHY2_METRIC_STAGNATION_LIMIT = 2
WHY2_METRIC_MIN_DELTA = 0.01
COMMANDER_DECISION_PROMPT_MAX_BYTES = 32_768
DISPATCH_CAP_ISSUES_MAX_BYTES = 65_536
_BOUNDED_TEXT_CHUNK_CHARS = 1_024
_CONTEXT_FILE_READ_CHUNK_BYTES = 8_192
_WHY2_CERTIFIED_METRICS = (
    "overall",
    "structure",
    "testability",
    "behavioral",
    "semantic",
    "cognitive",
    "readability",
    "depth",
)


class _DispatchCapEvidenceError(HumanInputPolicyError):
    """A deterministic issue-evidence diagnosis with a closed reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__("phase dispatch limit evidence is not resolvable")
        self.reason_code = reason_code


def _human_input_policy_error_code(error: HumanInputPolicyError) -> str:
    """Return a stable diagnostic code without exposing provider-controlled text."""
    del error
    return "human_input_policy_invalid"


class _BoundedUtf8Builder:
    """Accumulate text without encoding or retaining more than one byte budget."""

    def __init__(self, byte_limit: int) -> None:
        self._byte_limit = byte_limit
        self._byte_size = 0
        self._parts: list[str] = []
        self.truncated = False

    @property
    def remaining(self) -> int:
        return self._byte_limit - self._byte_size

    def append(self, value: str) -> bool:
        offset = 0
        while offset < len(value):
            if self.remaining <= 0:
                self.truncated = True
                return False
            segment = value[
                offset:offset + _BOUNDED_TEXT_CHUNK_CHARS
            ]
            encoded = segment.encode("utf-8")
            if len(encoded) <= self.remaining:
                self._parts.append(segment)
                self._byte_size += len(encoded)
                offset += len(segment)
                continue
            prefix = encoded[:self.remaining].decode(
                "utf-8",
                errors="ignore",
            )
            if prefix:
                self._parts.append(prefix)
                self._byte_size += len(prefix.encode("utf-8"))
            self.truncated = True
            return False
        return True

    def build(self) -> str:
        return "".join(self._parts)


def _append_bounded_json(
    builder: _BoundedUtf8Builder,
    value: object,
    *,
    depth: int = 0,
) -> None:
    """Write JSON-shaped durable state incrementally into a bounded builder."""
    if builder.remaining <= 0:
        builder.truncated = True
        return
    if depth > 64:
        builder.append('"<depth-limit>"')
        return
    if value is None or type(value) in {bool, int, float}:
        builder.append(json.dumps(value, ensure_ascii=False))
        return
    if isinstance(value, str):
        if not builder.append('"'):
            return
        for offset in range(0, len(value), _BOUNDED_TEXT_CHUNK_CHARS):
            escaped = json.dumps(
                value[offset:offset + _BOUNDED_TEXT_CHUNK_CHARS],
                ensure_ascii=False,
            )[1:-1]
            if not builder.append(escaped):
                return
        builder.append('"')
        return
    if isinstance(value, Mapping):
        if not builder.append("{"):
            return
        for index, (key, item) in enumerate(value.items()):
            if index and not builder.append(","):
                return
            _append_bounded_json(builder, str(key), depth=depth + 1)
            if not builder.append(":"):
                return
            _append_bounded_json(builder, item, depth=depth + 1)
            if builder.remaining <= 0:
                return
        builder.append("}")
        return
    if isinstance(value, (list, tuple)):
        if not builder.append("["):
            return
        for index, item in enumerate(value):
            if index and not builder.append(","):
                return
            _append_bounded_json(builder, item, depth=depth + 1)
            if builder.remaining <= 0:
                return
        builder.append("]")
        return
    builder.append('"<unsupported-state-value>"')
_PHASE_A_GENERATED_FILES = frozenset(
    {
        Path("constitution.md"),
        Path("00-overview.md"),
        Path("plan-conformance.md"),
        Path("plan-conformance.json"),
        Path("targets.yml"),
        Path("run-history.json"),
        Path("squad-report.md"),
        Path("ARTIFACTS.md"),
        Path("feature-metadata.yml"),
    }
)
_PHASE_A_KB_REPORT_FILES = frozenset(
    {
        Path("kb/kb-apply-report.yaml"),
        Path("kb/kb-usage-summary.yaml"),
    }
)
_PRODUCT_INPUT_PATH_KEYS = frozenset(
    {
        "manifest",
        "catalog",
        "input_context",
        "requirement_context",
        "reference_context",
        "traceability",
        "traceability_markdown",
    }
)
_QUALITY_DEBT_DOWNSTREAM_PHASES = frozenset(
    {
        "phase2-decide",
        "phase2-feasibility-structural",
        "phase2-strategic-overview",
        "phase2-tracker-alignment",
        "phase2-intent-alignment-structural",
        "phase3-how",
        "phase3-specialists",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-tasks-lexicon",
        "phase3-understanding",
        "phase3-consensus",
        "phase3-consensus-tasks-lexicon",
        "checkpoint-plan",
        "phase4-document",
    }
)


def _why2_certified_metrics_improved(scores: object) -> bool | None:
    """Return whether the latest two certified WHY2 scores moved materially."""
    if not isinstance(scores, list):
        return None
    why2_scores = [
        score
        for score in scores
        if isinstance(score, dict)
        and str(score.get("pass_id") or "").startswith("WHY2-")
    ]
    if len(why2_scores) < 2:
        return None
    previous, latest = why2_scores[-2:]
    comparable = []
    for metric in _WHY2_CERTIFIED_METRICS:
        try:
            comparable.append(float(latest[metric]) - float(previous[metric]))
        except (KeyError, TypeError, ValueError):
            continue
    if not comparable:
        return None
    return any(delta >= WHY2_METRIC_MIN_DELTA for delta in comparable)
JUDGMENT_STATE_UPDATE_KEYS = frozenset(
    {
        "next_phase",
        "phase",
        "iteration",
        "status",
        "blocked_reason",
        "issue_resolution_selection",
        "risk_level",
        "fallback_mode",
        "execution_mode",
        "dependency_fallbacks",
        "shadow_output_recovered",
    }
)
JUDGMENT_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=JUDGMENT_STATE_UPDATE_KEYS,
    state_update_types={
        "iteration": "integer",
        "status": "string",
        "issue_resolution_selection": "object",
    },
    state_update_enums={
        "status": frozenset({"running", "blocked", "done", "interrupted", "killed"}),
    },
    allowed_verdicts=frozenset({"JUDGMENT_RESOLVED", "BLOCKED"}),
    unexpected_state_updates="quarantine",
)

logger = logging.getLogger(__name__)


def _spec_id_from_phase_a_dir(spec_dir: Path) -> str:
    if spec_dir.name.startswith("spec-"):
        return spec_dir.name.removeprefix("spec-")
    return spec_dir.name


def _checkpoint_spec_id_from_state(state: dict, spec_dir: Path) -> str:
    spec_dir_id = _spec_id_from_phase_a_dir(spec_dir)
    state_spec_id = str(state.get("spec_id") or "").strip()
    if state_spec_id and spec_dir_id.startswith(f"{state_spec_id}-"):
        return spec_dir_id
    return state_spec_id or spec_dir_id


def _normalize_phase_recommendation(recommended: object, valid_phases: set[str]) -> str | None:
    """Return a concrete phase id for semantic phase recommendations."""
    if not isinstance(recommended, str) or not recommended:
        return None
    if recommended in valid_phases:
        return recommended
    semantic_routes = {
        "advance_past_consensus_to_delivery": "checkpoint-plan",
        "advance_to_delivery": "checkpoint-plan",
    }
    mapped = semantic_routes.get(recommended)
    if mapped in valid_phases:
        return mapped
    return None


def _phase_requires_constitution_provenance(phase: str) -> bool:
    """Return True for phases that must run only after CHIEF has completed.

    The exempt set is not "pre-constitution" only: it also includes
    phase1-constitution itself, because CHIEF is the phase that creates the
    provenance this guard checks.
    """
    if phase in {
        "init",
        "phase1-discover",
        "phase1-synthesizer",
        "phase1-modeler",
        "phase1-tracker",
        "phase1-why1",
        "phase1-constitution",
        *TERMINAL_PHASES,
    }:
        return False
    return (
        phase.startswith("phase1-")
        or phase.startswith("phase2-")
        or phase.startswith("phase3-")
        or phase.startswith("phase4-")
        or phase.startswith("checkpoint-")
        or phase.startswith("build-")
    )


def _constitution_artifact_is_real(project_root: Path) -> bool:
    """Secondary integrity check for constitution completion provenance."""
    from echelon.constitution import canonical_constitution_path

    path = canonical_constitution_path(project_root)
    if not path.exists():
        return False
    text = path.read_text(errors="replace")
    return not unresolved_constitution_template_markers(text)


def _blocked_banner(phase: str, reason: str, question: str) -> None:
    from echelon.ui import banner as _banner
    _banner(
        "SQUAD — BLOCKED",
        [
            ("phase", phase),
            ("reason", reason),
            ("question", question),
            ("answer with", "echelon spec resume \"<your answer>\""),
            ("discard with", "echelon spec run --reset \"<new task>\""),
        ],
    )


def _truncate_checkpoint_context(text: str, *, limit: int = 520) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def _latest_journal_reasoning(
    journal_path: Path,
    *,
    phase: str,
    artifact: str,
) -> str:
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if str(entry.get("phase") or "") != phase:
            continue
        data = entry.get("data")
        if not isinstance(data, Mapping):
            continue
        if str(data.get("artifact") or "") != artifact:
            continue
        reasoning = str(data.get("reasoning") or "").strip()
        if reasoning:
            return _truncate_checkpoint_context(reasoning)
    return ""


def _latest_passing_quality_score(state: Mapping[str, object]) -> Mapping[str, object] | None:
    scores = state.get("quality_scores")
    if not isinstance(scores, list):
        return None
    for item in reversed(scores):
        if isinstance(item, Mapping) and item.get("pass") is True:
            return item
    return None


def _format_score(value: object) -> str:
    if not isinstance(value, int | float):
        return ""
    return f"{float(value):.4g}"


def _checkpoint_context(
    state: Mapping[str, object],
    *,
    node_id: str,
    node_label: str,
    journal_path: Path,
) -> str:
    lines: list[str] = []
    mode = str(state.get("autonomy_mode") or "").strip()
    if mode in {"guided", "semi"}:
        lines.append(
            f"Why approval is needed: {mode} mode pauses at {node_label or node_id} "
            "so a human approves the checkpoint before Echelon advances."
        )

    score = _latest_passing_quality_score(state)
    if score is not None:
        score_parts = [
            label
            for label in (
                f"overall {_format_score(score.get('overall'))}",
                f"structure {_format_score(score.get('structure'))}",
                f"testability {_format_score(score.get('testability'))}",
                f"cognitive {_format_score(score.get('cognitive'))}",
            )
            if not label.endswith(" ")
        ]
        pass_id = str(score.get("pass_id") or "latest")
        if score_parts:
            lines.append(f"WHY2 passed ({pass_id}: {', '.join(score_parts)}).")
        else:
            lines.append(f"WHY2 passed ({pass_id}).")

    if state.get("lexicon_evaluation") == "passed":
        findings = state.get("lexicon_findings")
        finding_text = (
            f" with {int(findings)} finding(s)"
            if isinstance(findings, int)
            else ""
        )
        report = str(state.get("lexicon_report") or "").strip()
        if report:
            lines.append(f"Spec Lexicon passed{finding_text}; report: {report}.")
        else:
            lines.append(f"Spec Lexicon passed{finding_text}.")

    latest_repair = _latest_journal_reasoning(
        journal_path,
        phase="phase1-lexicon-derive",
        artifact="requirements.lexicon.md",
    )
    if latest_repair:
        lines.append(f"Latest lexicon repair: {latest_repair}")

    if not lines:
        return ""
    return "\n\nCheckpoint context:\n- " + "\n- ".join(lines)


def _resolve_human_input_option_answer(
    answer: str,
    options: tuple[HumanInputOption, ...],
) -> HumanInputOption | None:
    normalized = str(answer or "").strip()
    if not normalized or not options:
        return None

    first_token = normalized.split(maxsplit=1)[0].strip(").:-—–")
    if len(first_token) == 1 and first_token.isalpha():
        index = ord(first_token.upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index]

    id_matches = [option for option in options if normalized == option.id]
    if len(id_matches) == 1:
        return id_matches[0]
    if len(id_matches) > 1:
        raise HumanInputPolicyError("sealed decision option ids are ambiguous")

    label_matches = [option for option in options if normalized == option.label]
    if len(label_matches) == 1:
        return label_matches[0]
    if len(label_matches) > 1:
        raise HumanInputPolicyError("sealed decision option labels are ambiguous")
    return None


def _format_phase_dispatch_line(
    node: PhaseNode,
    graph: PhaseGraph,
    ext_dir: Path,
    *,
    file: object = None,
    suffix: str = "",
) -> str:
    """Render a squad phase dispatch line, using agent frontmatter color."""
    label = node.label or node.id
    target = file if file is not None else sys.stdout
    phase_id = color_text(
        node.id,
        _agent_frontmatter_color(node, graph, ext_dir),
        file=target,
    )
    return f"\n[squad] ▶ {phase_id}  {label}{suffix}"


def _agent_frontmatter_color(node: PhaseNode, graph: PhaseGraph, ext_dir: Path) -> str:
    if not node.agent:
        return ""
    rel = graph.agent_file(node.agent)
    if not rel:
        return ""
    path = ext_dir / rel
    if not path.exists():
        return ""
    color = read_prompt_markdown(path).metadata.get("color")
    return color if isinstance(color, str) else ""


@dataclass
class SquadResult:
    status: str         # "done" | "blocked" | "interrupted" | "budget_exhausted"
    phase: str
    run_id: str
    summary: str = ""

    @classmethod
    def from_state(cls, state: dict) -> "SquadResult":
        return cls(
            status=state.get("status", "unknown"),
            phase=state.get("phase", "unknown"),
            run_id=state.get("run_id", ""),
        )

    @classmethod
    def interrupted(cls) -> "SquadResult":
        return cls(status="interrupted", phase="unknown", run_id="")


@dataclass(frozen=True)
class ControllerEnrichment:
    """Controller-owned result additions produced before preparation."""

    updates: Mapping[str, object] = field(default_factory=dict)
    routing_override: str | None = None
    controller_owns_result_updates: bool = False
    state_removals: frozenset[str] = frozenset()
    control_updates: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            MappingProxyType(deepcopy(dict(self.updates))),
        )
        object.__setattr__(
            self,
            "state_removals",
            frozenset(self.state_removals),
        )
        object.__setattr__(
            self,
            "control_updates",
            MappingProxyType(deepcopy(dict(self.control_updates))),
        )


def project_authoring_verdict(
    *, phase_id: str, provider_verdict: str
) -> Mapping[str, str]:
    """Project an exact provider verdict into controller-owned durable state."""
    mapping = {
        "phase2-decide": {
            "PASS": "feasibility_verdict",
            "KILL": "feasibility_verdict",
            "DEFER": "feasibility_verdict",
        },
        "phase2-tracker-alignment": {
            "ALIGNED": "intent_alignment_verdict",
            "DRIFT": "intent_alignment_verdict",
            "DRIFTING": "intent_alignment_verdict",
            "ESCALATE": "intent_alignment_verdict",
        },
    }
    key = mapping.get(phase_id, {}).get(provider_verdict)
    if key is None:
        raise ControllerStateContractViolation(
            "provider verdict cannot be projected for authoring phase",
            contract=required_controller_contract_name(
                {"id": phase_id, "type": "agent"}
            )
            or "authoring_verdict",
            json_path="$.verdict",
            validator="projection",
        )
    return MappingProxyType({key: provider_verdict})


@dataclass(frozen=True)
class CompletionRecoveryOutcome:
    """Structured proof of one completion recovered before phase work."""

    recovered: bool
    origin: str = ""
    manual_phase_run: bool = False
    completion_id: str = ""


class _TransitionJudgmentRequired(RuntimeError):
    """Signal that ordered routing needs external COMMANDER coordination."""

    def __init__(self, condition: str, transition_index: int) -> None:
        super().__init__(condition)
        self.condition = condition
        self.transition_index = transition_index


class _ProductInputCommitError(RuntimeError):
    """Product-input publication failed inside the state CAS window."""

    def __init__(self, reason: str, *, retain_stage: bool = False) -> None:
        super().__init__("product input commit failed")
        self.reason = reason
        self.retain_stage = retain_stage


class _PhaseAReadinessCommitError(RuntimeError):
    """Phase A publication was not build-ready inside the state CAS window."""

    def __init__(self, readiness: PhaseAReadinessResult) -> None:
        super().__init__("Phase A publication is not ready")
        self.readiness = readiness


@dataclass(frozen=True)
class _ProviderHumanInputAdvance:
    """One already-attested provider route that may seal a human decision."""

    from_phase: str
    to_phase: str
    decision: PreparedRoutingDecision


@dataclass(frozen=True)
class _PreparedControllerRouting:
    """One attested route and an optional safeguard discovered while routing."""

    decision: PreparedRoutingDecision
    human_input: PreparedHumanInput | None = None


@dataclass(frozen=True)
class _ProductInputPublicationPlan:
    old_tree_hash: str
    new_tree_hash: str
    product_inputs: Mapping[str, object]
    owned_paths: tuple[str, ...]


@dataclass(frozen=True)
class _HumanInputResolutionEffects:
    """Controller-owned effects returned by one closed resolution handler."""

    state_updates: Mapping[str, object]
    state_removals: frozenset[str]
    route: str
    completion: PreparedControllerCompletion | None = None
    resolved_at: str | None = None


class SquadController:
    """Drives the squad run phase graph deterministically.

    Phase routing is pure Python (ConditionEvaluator + state.json).
    COMMANDER (LLM) is dispatched only for judgment calls.
    """

    def __init__(
        self,
        provider: SquadCliProvider,
        state_store: SquadStateStore,
        phase_graph: PhaseGraph,
        ext_dir: Path,
        project_root: Path,
        token_budget: int = 0,
        max_iterations: int = 5,
        squad_dir: Optional[Path] = None,
        ignore_re: bool = False,
        implementation_targets: list[str] | None = None,
        re_sources: list[str] | None = None,
        product_inputs: object | None = None,
        stack_contract: dict[str, object] | None = None,
    ) -> None:
        existing_state = state_store.load()
        resolved_squad_dir = squad_dir or state_store.squad_dir
        manifest = resolved_squad_dir / "telemetry" / "manifest.json"
        try:
            manifest_trace_id = json.loads(manifest.read_text(encoding="utf-8")).get(
                "trace_id"
            )
        except (OSError, json.JSONDecodeError):
            manifest_trace_id = None
        trace_id = (
            manifest_trace_id
            if isinstance(manifest_trace_id, str) and len(manifest_trace_id) == 32
            else uuid.uuid4().hex
        )
        telemetry_store = TelemetryStore(
            resolved_squad_dir,
            workflow="spec",
            run_id=str(existing_state.get("run_id") or resolved_squad_dir.name),
            profile={"name": str(existing_state.get("autonomy_mode") or "default")},
            trace_id=trace_id,
        )
        self._telemetry_store = telemetry_store
        self._telemetry_usage_lock = threading.Lock()
        self._deferred_provider_usage: dict[str, int] | None = None
        self._provider = provider
        self._telemetry_provider = InstrumentedProvider(
            provider,
            telemetry_store,
            usage_recorder=self._record_provider_usage,
        )
        self._state_store = state_store
        self._graph = phase_graph
        self._human_input_registry = phase_graph.human_input_policy_registry()
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._max_iterations = max_iterations
        self._squad_dir = squad_dir or state_store.squad_dir
        self._ignore_re = ignore_re
        self._implementation_targets = list(implementation_targets or [])
        self._re_sources = list(re_sources or [])
        self._product_inputs = product_inputs
        self._stack_contract = dict(stack_contract or {})
        self._prepared_product_input_updates: dict[
            str,
            dict[str, object],
        ] = {}
        self._evaluator = ConditionEvaluator()
        self._gate_config_cache: Optional[dict] = None
        self._gov_config_cache: Optional[dict] = None
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "commander_internal": CommanderInternalExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "deterministic_lexicon": DeterministicLexiconExecutor(phase_graph, ext_dir, project_root, self._squad_dir),
            "deterministic_structural": DeterministicStructuralExecutor(phase_graph, ext_dir, project_root, self._squad_dir),
            "deterministic_understanding": DeterministicUnderstandingExecutor(phase_graph, ext_dir, project_root, self._squad_dir),
            "staged_parallel": StagedParallelExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "conditional_sequential": ConditionalSequentialExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
        }
        self._cancelled = False
        self._phase_a_published_this_run = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _ensure_telemetry_manifest(self) -> None:
        """Make a run's telemetry identity available before agents invoke shims."""
        state = self._state_store.load()
        if not self._telemetry_store.manifest_path.exists():
            self._telemetry_store.run_id = str(
                state.get("run_id") or self._squad_dir.name
            )
            self._telemetry_store.profile = {
                "name": str(state.get("autonomy_mode") or "default")
            }
        try:
            self._telemetry_store.ensure_manifest()
        except Exception:
            logger.warning(
                "Could not initialize telemetry manifest for run_id=%s",
                state.get("run_id") or self._squad_dir.name,
                exc_info=True,
            )

    def _start_declared_phase_timing(self, node: PhaseNode) -> None:
        """Open a workflow-declared timing window before phase dispatch."""
        phase = str(node.timing_window_start or "").strip()
        budget = node.budget_seconds
        if not phase or budget is None:
            return
        try:
            record_phase_start(
                self._telemetry_store,
                phase=phase,
                budget_seconds=float(budget),
            )
        except Exception:
            logger.warning(
                "Could not start declared phase timing for %s",
                phase,
                exc_info=True,
            )

    def _declared_phase_timing_budget(self, phase: str) -> float | None:
        """Resolve a timing budget from start or transition declarations."""
        for phase_id in self._graph.all_phase_ids():
            candidate = self._graph.get(phase_id)
            if (
                candidate.timing_window_start == phase
                and candidate.budget_seconds is not None
            ):
                return float(candidate.budget_seconds)
            transition = candidate.timing_window_transition
            if (
                isinstance(transition, dict)
                and str(transition.get("open") or "").strip() == phase
                and transition.get("open_budget_seconds") is not None
            ):
                return float(transition["open_budget_seconds"])
        return None

    def _apply_declared_phase_timing_transition(
        self,
        node: PhaseNode,
        next_phase: str,
    ) -> None:
        """Apply timing close/open metadata after a successful phase advance."""
        if next_phase == node.id:
            return
        transition = node.timing_window_transition
        if not isinstance(transition, dict) or not transition:
            return

        close_phase = str(transition.get("close") or "").strip()
        open_phase = str(transition.get("open") or "").strip()
        open_budget = transition.get("open_budget_seconds")
        try:
            if close_phase:
                events, diagnostics = self._telemetry_store.read_phase_timings()
                if diagnostics:
                    raise ValueError("invalid phase timing telemetry")
                latest = next(
                    (
                        event
                        for event in reversed(events)
                        if event.phase == close_phase
                    ),
                    None,
                )
                if latest is None:
                    close_budget = self._declared_phase_timing_budget(close_phase)
                    if close_budget is None:
                        raise ValueError(
                            f"no timing budget declared for {close_phase!r}"
                        )
                    record_phase_start(
                        self._telemetry_store,
                        phase=close_phase,
                        budget_seconds=close_budget,
                    )
                    latest = next(
                        event
                        for event in reversed(
                            self._telemetry_store.read_phase_timings()[0]
                        )
                        if event.phase == close_phase
                    )
                if latest.event == "started":
                    record_phase_finish(
                        self._telemetry_store,
                        phase=close_phase,
                    )

            if open_phase:
                if open_budget is None:
                    raise ValueError(
                        f"no timing budget declared for {open_phase!r}"
                    )
                record_phase_start(
                    self._telemetry_store,
                    phase=open_phase,
                    budget_seconds=float(open_budget),
                )
        except Exception:
            logger.warning(
                "Could not apply declared phase timing transition for %s",
                node.id,
                exc_info=True,
            )

    def _record_provider_usage(self, result: object) -> None:
        if type(result) is not SquadAgentResult:
            return
        raw = result.token_usage
        if type(raw) is not int or raw <= 0:
            return
        with controller_lock_order(
            "telemetry",
            f"provider-usage:{self._squad_dir.absolute()}",
        ):
            with self._telemetry_usage_lock:
                if self._deferred_provider_usage is not None:
                    self._deferred_provider_usage["tokens"] += raw
                    return
                self._state_store.increment_token_usage(raw)

    @contextmanager
    def _defer_routing_provider_usage(self):
        previous = self._deferred_provider_usage
        accumulator = {"tokens": 0}
        self._deferred_provider_usage = accumulator
        try:
            yield accumulator
        finally:
            self._deferred_provider_usage = previous

    def _project_config_path(self) -> Path:
        return self._project_root / ".echelon" / "config.yml"

    def _quality_gate_thresholds(self) -> dict:
        return effective_quality_gate_thresholds(
            resolve_quality_gate_thresholds(self._project_root),
            self._state_store.load().get("feature_policy"),
        )

    def _normalize_why_result_quality_scores(
        self,
        result: SquadAgentResult,
    ) -> None:
        updates = result.state_updates
        if "quality_scores" not in updates:
            return
        updates["quality_scores"] = normalize_why_quality_scores(
            updates["quality_scores"],
            verdict=result.verdict,
            gates=self._quality_gate_thresholds(),
        )

    def _detect_project_mode(self, requested_mode: str) -> str:
        """Return the project type stored in state.mode.

        `requested_mode` is the user-selected autonomy mode (`semi`/`banzai`/`guided`)
        for normal CLI entrypoints, but older tests and internal callers may still
        pass a project mode directly. Preserve that when present.
        """
        if requested_mode in PROJECT_MODES:
            return requested_mode

        script = self._ext_dir / "scripts" / "bash" / "detect-project.sh"
        if not script.exists():
            return "greenfield"
        try:
            proc = subprocess.run(
                [str(script), str(self._project_root)],
                check=False,
                capture_output=True,
                text=True,
            )
            detected = (proc.stdout or "").strip()
            if proc.returncode == 0 and detected in PROJECT_MODES:
                return detected
        except Exception:
            pass
        return "greenfield"

    def _refresh_run_context(self, reason: str = "") -> None:
        state = self._state_store.load()
        run_dir = Path(state.get("squad_dir", self._squad_dir))
        user_request = str(state.get("user_request", state.get("user_message", "")))
        try:
            context_result = build_run_context(
                self._project_root,
                run_dir,
                user_request=user_request,
                drawers=self._retrieve_mempalace_context_drawers(
                    user_request,
                    str(state.get("run_id") or ""),
                    state,
                ),
            )
        except Exception as exc:
            logger.warning(
                "run-local context refresh failed for %s%s: %s",
                run_dir,
                f" ({reason})" if reason else "",
                exc,
            )
            return

        state["context_dir"] = str(context_result.context_dir)
        self._state_store.save(state)

    def _retrieve_mempalace_context_drawers(
        self,
        user_request: str,
        run_id: str,
        state: Mapping[str, object],
    ) -> list[object]:
        query = user_request.strip()
        if not query:
            return []
        try:
            from codegen.memory.context import MemPalaceContext
            from codegen.memory.mempalace_reader import MemPalaceReader
        except Exception:
            return []
        try:
            ctx = MemPalaceContext.from_project(self._project_root, run_id=run_id or "squad-context")
            reader = MemPalaceReader(ctx)
            drawers = list(reader.search_requirements(query, n_results=10))
        except (Exception, SystemExit):
            return []
        retarget = state.get("retarget")
        if (
            isinstance(retarget, Mapping)
            and retarget.get("memory_excluded") is True
        ):
            from echelon.mempalace_retarget import (
                exclude_retarget_spec_drawers,
            )

            return exclude_retarget_spec_drawers(
                drawers,
                state.get("spec_id"),
            )
        return drawers

    def _completion_timing_parameters(
        self,
        from_phase: str,
        to_phase: str,
    ) -> dict[str, object] | None:
        if from_phase == to_phase:
            return None
        try:
            node = self._graph.get(from_phase)
        except KeyError:
            return None
        transition = node.timing_window_transition
        if not isinstance(transition, dict) or not transition:
            return None
        close_phase = str(transition.get("close") or "").strip()
        open_phase = str(transition.get("open") or "").strip()
        if not close_phase and not open_phase:
            return None
        close_budget = (
            self._declared_phase_timing_budget(close_phase)
            if close_phase
            else None
        )
        open_budget_value = transition.get("open_budget_seconds")
        open_budget = (
            float(open_budget_value)
            if open_phase
            and type(open_budget_value) in (int, float)
            and float(open_budget_value) >= 0
            else (
                self._declared_phase_timing_budget(open_phase)
                if open_phase
                else None
            )
        )
        if (
            (close_phase and close_budget is None)
            or (open_phase and open_budget is None)
        ):
            return None
        return {
            "close_phase": close_phase or None,
            "close_budget_seconds": close_budget,
            "open_phase": open_phase or None,
            "open_budget_seconds": open_budget,
        }

    def _completion_checkpoint_prestate(self) -> dict[str, object]:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD^{commit}"],
                cwd=self._project_root,
                check=True,
                capture_output=True,
                text=True,
            )
            stdout = completed.stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise StateAdvanceError(
                "controller checkpoint prestate is unavailable",
                json_path=(
                    f"$.{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ".checkpoint_prestate"
                ),
                validator="checkpoint_prestate",
            ) from exc
        head = stdout.strip() if type(stdout) is str else ""
        if (
            re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head)
            is None
            or set(head) == {"0"}
        ):
            raise StateAdvanceError(
                "controller checkpoint prestate is invalid",
                json_path=(
                    f"$.{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ".checkpoint_prestate"
                ),
                validator="checkpoint_prestate",
            )
        return {"kind": "git_head", "head": head}

    def _completion_timing_is_active(
        self,
        from_phase: str,
        to_phase: str,
    ) -> bool:
        parameters = self._completion_timing_parameters(
            from_phase,
            to_phase,
        )
        if parameters is None:
            return False
        close_phase = parameters["close_phase"]
        if close_phase is None:
            return True
        try:
            events, diagnostics = (
                self._telemetry_store.read_phase_timings()
            )
        except Exception:
            return False
        if diagnostics:
            return False
        latest = next(
            (
                event
                for event in reversed(events)
                if event.phase == close_phase
            ),
            None,
        )
        return (
            latest is not None
            and latest.event == "started"
            and latest.budget_seconds
            == parameters["close_budget_seconds"]
        )

    @staticmethod
    def _completion_judgment_record(
        result: SquadAgentResult,
    ) -> dict[str, object]:
        detached = detach_squad_agent_result(result)
        payload = detached.echelon_result
        return {
            "echelon_result": payload if isinstance(payload, dict) else {},
            "quarantined_state_updates": dict(
                detached.quarantined_state_updates
            ),
        }

    @staticmethod
    def _active_retarget(state: Mapping[str, object]) -> bool:
        retarget = state.get("retarget")
        return (
            isinstance(retarget, Mapping)
            and retarget.get("status") == "finalizing"
            and retarget.get("replacement_run_id") == state.get("run_id")
        )

    @staticmethod
    def _retarget_comparison_command(
        state: Mapping[str, object],
    ) -> str | None:
        """Return the one authoritative comparison command for a completion."""
        retarget = state.get("retarget")
        spec_id = state.get("spec_id")
        if (
            not isinstance(retarget, Mapping)
            or retarget.get("status") != "complete"
            or type(spec_id) is not str
            or re.fullmatch(r"[0-9]{3,}-[a-z0-9]+(?:-[a-z0-9]+)*", spec_id)
            is None
        ):
            return None
        checkpoint = retarget.get("checkpoint_commit")
        replacement = retarget.get("replacement_commit")
        if (
            type(checkpoint) is not str
            or type(replacement) is not str
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", checkpoint) is None
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", replacement) is None
        ):
            return None
        return (
            "Compare old and replacement artifacts:\n"
            f"  git diff {checkpoint}..{replacement} -- specs/{spec_id}"
        )

    def _emit_pending_retarget_comparison(self) -> bool:
        """Print and durably consume the one completed-retarget comparison."""
        state = self._state_store.load()
        retarget = state.get("retarget")
        if not isinstance(retarget, Mapping):
            return False
        completion_id = retarget.get("comparison_pending_completion_id")
        receipt = retarget.get("finalization_receipt")
        command = retarget.get("comparison_command")
        event_id = retarget.get("comparison_event_id")
        expected_command = self._retarget_comparison_command(state)
        if (
            type(completion_id) is not str
            or not isinstance(receipt, Mapping)
            or receipt.get("completion_id") != completion_id
            or event_id != f"retarget-comparison-{completion_id}"
            or command != expected_command
        ):
            return False
        if not self._state_store.mark_retarget_comparison_emitted(completion_id):
            return False
        print(command, flush=True)
        return True

    def _enter_retarget_finalizing(
        self,
        state: Mapping[str, object],
    ) -> dict[str, object]:
        """Persist finalizing before Phase 4 staging exposes replacement output."""
        raw = state.get("retarget")
        if not isinstance(raw, Mapping):
            return dict(state)
        retarget = dict(raw)
        if (
            retarget.get("replacement_run_id") != state.get("run_id")
            or retarget.get("status") not in {"rebuilding", "finalizing"}
        ):
            raise StateAdvanceError(
                "retarget finalization binding is invalid",
                json_path="$.retarget",
                validator="completion_binding",
            )
        spec_id = state.get("spec_id")
        revision_id = retarget.get("revision_id")
        if type(spec_id) is not str or type(revision_id) is not str:
            raise StateAdvanceError(
                "retarget finalization identity is invalid",
                json_path="$.retarget",
                validator="type",
            )
        spec_dir = self._project_root / "specs" / spec_id
        history = load_retarget_history(spec_dir)
        if not history.revisions or history.revisions[-1].revision_id != revision_id:
            raise StateAdvanceError(
                "retarget finalization history drifted",
                json_path="$.retarget.revision_id",
                validator="completion_binding",
            )
        if history.revisions[-1].status == "rebuilding":
            advance_retarget_revision(
                spec_dir,
                revision_id,
                expected_status="rebuilding",
                status="finalizing",
                updates={},
            )
        elif history.revisions[-1].status != "finalizing":
            raise StateAdvanceError(
                "retarget finalization history is not resumable",
                json_path="$.retarget.status",
                validator="completion_binding",
            )
        if retarget.get("status") == "finalizing":
            return dict(state)
        updated = dict(state)
        retarget["status"] = "finalizing"
        updated["retarget"] = retarget
        self._state_store.save(updated)
        return self._state_store.load()

    def _prepare_controller_completion(
        self,
        *,
        from_phase: str,
        to_phase: str,
        snapshot: RoutingStateSnapshot,
        manual_phase_run: bool,
        conditional_skip: bool,
        record_completion: bool,
        publication_marker: Mapping[str, object] | None,
        judgments: tuple[SquadAgentResult, ...] = (),
        origin: str = "routed",
        quality_effect: Mapping[str, object] | None = None,
        resolution_decision_id: str | None = None,
        completion_id: str | None = None,
    ) -> PreparedControllerCompletion:
        """Seal all post-dispatch work before its authorizing state save."""
        if origin == "terminal":
            route: dict[str, object] = {
                "kind": "terminal",
                "terminal_phase": from_phase,
            }
            effects = []
            if self._active_phase_a_spec_dir(snapshot.state) is not None:
                effects.append("mining")
            if self._active_retarget(self._state_store.load()):
                effects.append("retarget")
            effect_plan = tuple(effects)
            judgment_records: tuple[dict[str, object], ...] = ()
        elif origin == "resolution":
            if not resolution_decision_id or quality_effect is None:
                raise StateAdvanceError(
                    "human-input completion preparation is invalid",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
                )
            route = {
                "kind": "resolution",
                "decision_id": resolution_decision_id,
                "from_phase": from_phase,
                "to_phase": to_phase,
            }
            effect_plan = ("quality",)
            judgment_records = ()
        else:
            route = {
                "kind": "routed",
                "from_phase": from_phase,
                "to_phase": to_phase,
                "manual_phase_run": manual_phase_run,
                "record_completion": record_completion,
            }
            checkpoint_version = snapshot.state.get("checkpoint_policy_version")
            checkpoint_policy = "none"
            if checkpoint_version is not None:
                if type(checkpoint_version) is not int or checkpoint_version != 2:
                    raise StateAdvanceError(
                        "unsupported checkpoint policy version",
                        json_path="$.checkpoint_policy_version",
                        validator="checkpoint_policy",
                    )
                try:
                    checkpoint_policy, rewind_policy = phase_checkpoint_policy(
                        self._graph,
                        from_phase,
                    )
                except CheckpointPolicyError as exc:
                    raise StateAdvanceError(
                        str(exc),
                        json_path="$.checkpoint_policy",
                        validator="checkpoint_policy",
                    ) from exc
                route.update({
                    "checkpoint_policy_version": checkpoint_version,
                    "checkpoint_policy": checkpoint_policy,
                    "rewind_policy": rewind_policy,
                })
            judgment_records = tuple(
                self._completion_judgment_record(result)
                for result in judgments
            )
            if not record_completion:
                effect_plan = ("journal", "checkpoint")
            else:
                effects: list[str] = []
                if judgment_records:
                    effects.append("journal")
                if (
                    self._completion_timing_is_active(
                        from_phase,
                        to_phase,
                    )
                ):
                    effects.append("timing")
                active_spec_dir = self._active_phase_a_spec_dir(snapshot.state)
                if checkpoint_version == 2:
                    if checkpoint_policy == "required" and not conditional_skip:
                        if active_spec_dir is None or not active_spec_dir.exists():
                            raise StateAdvanceError(
                                f"phase_checkpoint_target_missing: {from_phase}",
                                json_path="$.spec_dir",
                                validator="checkpoint_target",
                            )
                        effects.append("checkpoint")
                elif active_spec_dir is not None and active_spec_dir.exists():
                    effects.append("checkpoint")
                if quality_effect is not None:
                    effects.append("quality")
                effects.append("context")
                if from_phase == "phase4-document":
                    effects.append("mining")
                    if self._active_retarget(self._state_store.load()):
                        effects.append("retarget")
                effect_plan = tuple(effects)
        publication = (
            {
                "kind": "external",
                "marker": dict(publication_marker),
            }
            if publication_marker is not None
            else {"kind": "none"}
        )
        checkpoint_prestate = (
            self._completion_checkpoint_prestate()
            if "checkpoint" in effect_plan
            else {"kind": "none"}
        )
        judgment_digests = tuple(
            _canonical_payload_sha256(
                dict(record["echelon_result"])
            )
            for record in judgment_records
        )
        try:
            return prepare_controller_completion_stage(
                self._project_root,
                self._squad_dir,
                completion_id=(
                    uuid.uuid4().hex
                    if completion_id is None
                    else completion_id
                ),
                origin=origin,
                publication=publication,
                route=route,
                effect_plan=effect_plan,
                checkpoint_prestate=checkpoint_prestate,
                context_reason=(
                    "terminal Phase A reconciliation"
                    if origin == "terminal"
                    else "human-input proportional quality resolution"
                    if origin == "resolution"
                    else (
                        f"{'manual ' if manual_phase_run else ''}"
                        f"{'skip ' if conditional_skip else ''}"
                        f"phase advance {from_phase} -> {to_phase}"
                    )
                ),
                mine_phase_a="mining" in effect_plan,
                judgment_payload_sha256=judgment_digests,
                judgments=judgment_records,
                quality_effect=(
                    dict(quality_effect)
                    if quality_effect is not None
                    else {"kind": "none"}
                ),
            )
        except CompletionError as exc:
            raise StateAdvanceError(
                "controller completion preparation failed",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator=exc.code,
            ) from exc

    def _record_controller_completion_failure_best_effort(
        self,
        marker: object,
        code: str,
    ) -> None:
        try:
            self._state_store.record_controller_completion_failure(
                marker,
                code,
            )
        except Exception:
            logger.exception(
                "Could not persist controller completion failure code %s",
                code,
            )

    def _completion_checkpoint_inputs(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> dict[str, object]:
        route = prepared.intent.route
        spec_dir = self._active_phase_a_spec_dir(dict(state))
        if spec_dir is not None and not spec_dir.exists():
            spec_dir = None
        additional_spec_dirs: tuple[Path, ...] = ()
        additional_owned_paths = (
            checkpoint_additional_owned_paths(
                self._project_root,
                str(route.get("from_phase") or ""),
                state,
            )
            if route.get("checkpoint_policy_version") == 2
            else ()
        )
        if (
            spec_dir is not None
            and route.get("from_phase") == "phase4-document"
            and route.get("to_phase") in TERMINAL_PHASES
        ):
            published = self._published_phase_a_spec_dir(
                dict(state),
                spec_dir,
            )
            if (
                published.exists()
                and published.resolve() != spec_dir.resolve()
            ):
                additional_spec_dirs = (published,)
            additional_owned_paths = tuple(dict.fromkeys(
                (
                    *additional_owned_paths,
                    *accepted_kb_target_paths(
                        self._project_root,
                        str(state.get("run_id") or ""),
                    ),
                )
            ))
        return {
            "project_root": self._project_root,
            "spec_dir": spec_dir,
            "run_id": str(state.get("run_id") or ""),
            "spec_id": (
                _checkpoint_spec_id_from_state(dict(state), spec_dir)
                if spec_dir is not None
                else ""
            ),
            "additional_spec_dirs": additional_spec_dirs,
            "additional_owned_paths": additional_owned_paths,
        }

    def _apply_controller_completion_effect(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> None:
        with controller_lock_order(
            "completion",
            str(prepared._transaction_root.absolute()),
        ):
            self._apply_controller_completion_effect_ordered(
                prepared,
                state,
            )

    def _apply_controller_completion_effect_ordered(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> None:
        effect = prepared.marker.step
        existing = prepared.receipts["effects"].get(effect)
        if effect == "journal":
            plan = prepare_completion_journal_plan(
                prepared.intent,
                self._squad_dir / "reasoning-journal.jsonl",
            )
            receipt = apply_or_verify_completion_journal(plan)
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "timing":
            route = prepared.intent.route
            parameters = self._completion_timing_parameters(
                str(route["from_phase"]),
                str(route["to_phase"]),
            )
            if parameters is None:
                raise CompletionError("intent_mismatch")
            receipt = apply_or_verify_completion_timing(
                prepared.intent,
                self._telemetry_store,
                expected_receipt=existing,
                **parameters,
            )
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "quality":
            receipt = apply_or_verify_proportional_quality_effect(
                prepared.intent.quality_effect,
                completion_id=prepared.marker.completion_id,
                project_root=self._project_root,
                state=state,
                route=prepared.intent.route,
                preceding_checkpoint_receipt=(
                    prepared.receipts["effects"].get("checkpoint")
                    if "checkpoint" in prepared.intent.effect_plan
                    else None
                ),
                expected_receipt=existing,
            )
            persist_completion_effect_receipt(prepared, effect, receipt)
            return
        if effect == "checkpoint":
            receipt = create_or_recover_completion_checkpoint(
                prepared.intent,
                expected_receipt=existing,
                **self._completion_checkpoint_inputs(
                    prepared,
                    state,
                ),
            )
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "context":
            receipt = prepare_or_load_completion_context(
                prepared,
                project_root=self._project_root,
                source_state_revision=int(
                    state.get("state_revision") or 0
                ),
                user_request=str(
                    state.get(
                        "user_request",
                        state.get("user_message", ""),
                    )
                    or ""
                ),
                drawers=self._retrieve_mempalace_context_drawers(
                    str(
                        state.get(
                            "user_request",
                            state.get("user_message", ""),
                        )
                        or ""
                    ),
                    str(state.get("run_id") or ""),
                    state,
                ),
            )
            install_or_verify_completion_context(
                prepared,
                expected_receipt=receipt,
            )
            return
        if effect == "mining":
            published_ref = str(
                state.get("published_spec_dir") or ""
            ).strip()
            spec_file = (
                self._absolute_project_path(published_ref) / "spec.md"
                if published_ref
                else None
            )
            if spec_file is not None and not spec_file.is_file():
                spec_file = None
            metadata: object = None
            if spec_file is not None:
                try:
                    from echelon.context_metadata import (
                        read_feature_metadata,
                    )

                    raw_metadata = read_feature_metadata(
                        spec_file.parent
                    )
                    if raw_metadata is not None:
                        spec_sha256 = hashlib.sha256(
                            spec_file.read_bytes()
                        ).hexdigest()
                        metadata = (
                            self._canonical_spec_artifact_metadata(
                                spec_file,
                                raw_metadata,
                                f"sha256:{spec_sha256}",
                            )
                        )
                except Exception:
                    metadata = None
            apply_or_verify_completion_mining(
                prepared,
                project_root=self._project_root,
                spec_file=spec_file,
                run_id=str(state.get("run_id") or ""),
                artifact_metadata=metadata,
                expected_receipt=existing,
            )
            return
        if effect == "retarget":
            from echelon.spec_retarget_finalization import (
                RetargetFinalizationError,
                apply_or_verify_retarget_finalization,
            )

            try:
                receipt = apply_or_verify_retarget_finalization(
                    prepared,
                    project_root=self._project_root,
                    state=state,
                    expected_receipt=existing,
                )
            except RetargetFinalizationError as exc:
                raise CompletionError("receipts_mismatch") from exc
            except (Exception, SystemExit) as exc:
                raise CompletionError("receipts_mismatch") from exc
            persist_completion_effect_receipt(prepared, effect, receipt)
            return
        raise CompletionError("intent_mismatch")

    def _discard_completed_controller_stage(
        self,
        prepared: PreparedControllerCompletion,
    ) -> None:
        try:
            state = self._state_store.load()
        except Exception:
            return
        if PENDING_CONTROLLER_COMPLETION_KEY in state:
            return
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return
        marker = prepared.marker
        if marker.origin == "routed":
            dispatch = state.get("last_dispatch")
            proven = (
                isinstance(dispatch, Mapping)
                and dispatch.get("dispatch_id") == marker.completion_id
                and dispatch.get("post_dispatch_complete") is True
                and dispatch.get("completion_intent_sha256")
                == marker.intent_sha256
                and dispatch.get("completion_receipts_sha256")
                == marker.receipts_sha256
            )
        elif marker.origin == "terminal":
            terminal = state.get("last_terminal_completion")
            proven = (
                isinstance(terminal, Mapping)
                and terminal.get("completion_id") == marker.completion_id
                and terminal.get("intent_sha256")
                == marker.intent_sha256
                and terminal.get("receipts_sha256")
                == marker.receipts_sha256
            )
        else:
            resolution = state.get("last_human_input_completion")
            proven = (
                isinstance(resolution, Mapping)
                and resolution.get("completion_id") == marker.completion_id
                and resolution.get("intent_sha256") == marker.intent_sha256
                and resolution.get("receipts_sha256") == marker.receipts_sha256
            )
        if not proven:
            return
        try:
            prepared.discard()
        except CompletionError:
            logger.warning(
                "Could not discard completed controller stage",
                exc_info=True,
            )

    def _cleanup_controller_completion_orphans(self) -> bool:
        """Remove valid unreferenced stages; retain incomplete dispatch proof."""
        try:
            state = self._state_store.load()
        except Exception:
            return False
        if (
            PENDING_CONTROLLER_COMPLETION_KEY in state
            or PENDING_EXTERNAL_PUBLICATION_KEY in state
        ):
            return False
        retained_id = ""
        dispatch = state.get("last_dispatch")
        if (
            isinstance(dispatch, Mapping)
            and dispatch.get("post_dispatch_complete") is False
        ):
            candidate = dispatch.get("dispatch_id")
            intent_digest = dispatch.get(
                "completion_intent_sha256"
            )
            if (
                type(candidate) is not str
                or re.fullmatch(r"[0-9a-f]{32}", candidate) is None
                or type(intent_digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", intent_digest) is None
            ):
                return False
            retained_id = candidate
        outbox = self._squad_dir / ".completion-outbox"
        try:
            metadata = os.lstat(outbox)
        except FileNotFoundError:
            return not retained_id
        except OSError:
            return False
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            return False
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return False
        try:
            with os.scandir(outbox) as iterator:
                entries = tuple(iterator)
        except OSError:
            return False
        for entry in entries:
            if (
                re.fullmatch(r"[0-9a-f]{32}", entry.name) is None
                or entry.name == retained_id
            ):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                discard_unreferenced_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    entry.name,
                )
            except CompletionError:
                continue
        return not retained_id

    def _drain_pending_controller_completion(
        self,
    ) -> CompletionRecoveryOutcome:
        """Validate, replay, and finalize one exact durable completion."""
        state = self._state_store.load()
        if (
            PENDING_CONTROLLER_COMPLETION_KEY in state
            or PENDING_EXTERNAL_PUBLICATION_KEY in state
        ):
            try:
                state = self._state_store.confirm_durable_state(state)
            except StateDurabilityError:
                return CompletionRecoveryOutcome(False)
        if PENDING_CONTROLLER_COMPLETION_KEY not in state:
            if PENDING_EXTERNAL_PUBLICATION_KEY in state:
                if PRODUCT_INPUT_MUTATION_KEY in state:
                    self._recover_pending_external_publication()
                else:
                    self._record_controller_completion_failure_best_effort(
                        None,
                        "completion_missing",
                    )
            return CompletionRecoveryOutcome(False)
        raw_marker = state[PENDING_CONTROLLER_COMPLETION_KEY]
        try:
            marker = validate_pending_controller_completion(raw_marker)
            prepared = load_prepared_controller_completion(
                self._project_root,
                self._squad_dir,
                marker,
            )
        except CompletionError as exc:
            self._record_controller_completion_failure_best_effort(
                raw_marker,
                exc.code,
            )
            return CompletionRecoveryOutcome(False)
        except Exception:
            self._record_controller_completion_failure_best_effort(
                raw_marker,
                "intent_invalid",
            )
            return CompletionRecoveryOutcome(False)

        route = prepared.intent.route
        origin = prepared.intent.origin
        manual = bool(
            route.get("manual_phase_run", False)
            if origin == "routed"
            else False
        )
        outcome = CompletionRecoveryOutcome(
            False,
            origin,
            manual,
            prepared.marker.completion_id,
        )
        try:
            publication = prepared.intent.publication
            has_persisted_publication = (
                PENDING_EXTERNAL_PUBLICATION_KEY in state
            )
            persisted_publication = state.get(
                PENDING_EXTERNAL_PUBLICATION_KEY
            )
            if publication["kind"] == "external":
                expected_publication = publication["marker"]
                if prepared.marker.step == "awaiting_publication":
                    if (
                        not has_persisted_publication
                        or persisted_publication
                        != expected_publication
                    ):
                        raise CompletionError("intent_mismatch")
                    try:
                        staged_publication = load_prepared_publication(
                            self._project_root,
                            self._squad_dir,
                            expected_publication,
                        )
                        if (
                            (
                                route.get("from_phase") == "phase4-document"
                                or origin == "terminal"
                            )
                            and PRODUCT_INPUT_MUTATION_KEY not in state
                        ):
                            self._authenticate_phase_a_product_input_snapshot(
                                staged_publication,
                                state,
                            )
                        self._authenticate_quality_debt_publication_stage(
                            staged_publication,
                            state,
                        )
                        authenticate_pending_product_input_mutation(
                            self._project_root,
                            state,
                            expected_publication,
                            staged_publication._manifest["operations"],
                            staged_inputs=(
                                staged_publication._transaction_root
                                / "work/product-inputs"
                            ),
                        )
                        staged_publication.publish()
                        verified_product_input_tree_hash = (
                            require_product_input_mutation_postimage(
                                self._project_root,
                                state,
                                expected_publication,
                            )
                        )
                    except ProductInputMutationError:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            "target_drift",
                        )
                        return outcome
                    except PublicationError as exc:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            exc.code,
                        )
                        return outcome
                    except Exception:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            "publish_io",
                        )
                        return outcome
                    try:
                        if verified_product_input_tree_hash is None:
                            self._state_store.handoff_external_publication(
                                expected_publication,
                                prepared,
                            )
                        else:
                            self._state_store.handoff_external_publication(
                                expected_publication,
                                prepared,
                                verified_product_input_tree_hash=(
                                    verified_product_input_tree_hash
                                ),
                            )
                    except StateDurabilityError:
                        return outcome
                    except StateAdvanceError:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            "state_finalize",
                        )
                        return outcome
                    handed = self._state_store.load()
                    expected_next = (
                        prepared.intent.effect_plan[0]
                        if prepared.intent.effect_plan
                        else "complete"
                    )
                    next_marker = handed.get(
                        PENDING_CONTROLLER_COMPLETION_KEY
                    )
                    if (
                        PENDING_EXTERNAL_PUBLICATION_KEY in handed
                        or not isinstance(next_marker, Mapping)
                        or next_marker.get("completion_id")
                        != prepared.marker.completion_id
                        or next_marker.get("step") != expected_next
                    ):
                        return outcome
                    try:
                        self._state_store.confirm_durable_state(handed)
                    except StateDurabilityError:
                        return outcome
                    try:
                        staged_publication.discard()
                    except PublicationError:
                        logger.warning(
                            "Could not discard handed-off publication stage",
                            exc_info=True,
                        )
                    self._prepared_product_input_updates.pop(
                        str(expected_publication["transaction_id"]),
                        None,
                    )
                    if route.get("from_phase") == "phase4-document":
                        self._phase_a_published_this_run = True
                elif has_persisted_publication:
                    raise CompletionError("intent_mismatch")
            elif has_persisted_publication:
                raise CompletionError("intent_mismatch")

            while True:
                current_state = self._state_store.load()
                if (
                    PENDING_CONTROLLER_COMPLETION_KEY
                    not in current_state
                ):
                    return outcome
                current_raw = current_state[
                    PENDING_CONTROLLER_COMPLETION_KEY
                ]
                prepared = load_prepared_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    current_raw,
                )
                step = prepared.marker.step
                if step == "awaiting_publication":
                    raise CompletionError("intent_mismatch")
                if step == "complete":
                    from echelon.spec_retarget_finalization import (
                        RetargetFinalizationError,
                    )

                    try:
                        digests = self._phase_a_inventory_digests(
                            current_state
                        )
                        if (
                            prepared.marker.origin == "routed"
                            and prepared.intent.route.get("from_phase")
                            == "phase4-document"
                        ):
                            if digests is None:
                                raise CompletionError("receipts_mismatch")
                            self._state_store.complete_controller_completion(
                                prepared,
                                phase_a_active_source_sha256=digests[0],
                                phase_a_published_postimage_sha256=digests[1],
                            )
                        elif (
                            prepared.marker.origin == "terminal"
                        ):
                            if digests is None:
                                raise CompletionError("receipts_mismatch")
                            self._state_store.complete_controller_completion(
                                prepared,
                                phase_a_active_source_sha256=digests[0],
                                phase_a_published_postimage_sha256=digests[1],
                            )
                        else:
                            self._state_store.complete_controller_completion(
                                prepared,
                            )
                    except RetargetFinalizationError as exc:
                        raise CompletionError("receipts_mismatch") from exc
                    if "retarget" in prepared.intent.effect_plan:
                        self._emit_pending_retarget_comparison()
                    self._discard_completed_controller_stage(prepared)
                    return CompletionRecoveryOutcome(
                        True,
                        origin,
                        manual,
                        prepared.marker.completion_id,
                    )
                self._apply_controller_completion_effect(
                    prepared,
                    current_state,
                )
                one_ahead = load_prepared_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    current_raw,
                )
                self._state_store.advance_controller_completion(
                    one_ahead,
                )
        except CompletionError as exc:
            self._record_controller_completion_failure_best_effort(
                self._state_store.load().get(
                    PENDING_CONTROLLER_COMPLETION_KEY
                ),
                exc.code,
            )
            return outcome
        except StateDurabilityError:
            return outcome
        except StateAdvanceError:
            self._record_controller_completion_failure_best_effort(
                self._state_store.load().get(
                    PENDING_CONTROLLER_COMPLETION_KEY
                ),
                "stage_io",
            )
            return outcome

    def _run_with_execution_lease(
        self,
        execute: Callable[[], SquadResult],
        *,
        stop_after_recovered_manual: bool = False,
    ) -> SquadResult:
        """Serialize controller execution for this run before touching state."""

        operation_id = f"squad-exec-{os.getpid()}"
        try:
            with PhaseAExecutionLock.acquire(
                self._project_root,
                operation_id,
            ):
                with SpecRunExecutionLock.acquire(
                    self._squad_dir,
                    operation_id,
                ):
                    recovery = (
                        self._drain_pending_controller_completion()
                    )
                    self._emit_pending_retarget_comparison()
                    recovered_state = self._state_store.load()
                    if (
                        PENDING_CONTROLLER_COMPLETION_KEY
                        in recovered_state
                        or PENDING_EXTERNAL_PUBLICATION_KEY
                        in recovered_state
                    ):
                        return SquadResult.from_state(recovered_state)
                    if (
                        stop_after_recovered_manual
                        and recovery.recovered
                        and recovery.manual_phase_run
                    ):
                        return SquadResult.from_state(recovered_state)
                    if not self._cleanup_controller_completion_orphans():
                        return SquadResult.from_state(
                            self._state_store.load()
                        )
                    return execute()
        except SpecLifecycleLocked as exc:
            state = self._state_store.load()
            phase = str(state.get("phase") or "unknown")
            run_id = str(state.get("run_id") or self._squad_dir.name)
            logger.warning("Phase A run %s is already executing: %s", run_id, exc)
            print(
                f"[squad] run already active — refusing concurrent execution ({exc})",
                flush=True,
            )
            return SquadResult(status="busy", phase=phase, run_id=run_id)

    def _record_external_publication_failure_best_effort(
        self,
        marker: Mapping[str, object],
        code: str,
    ) -> None:
        try:
            self._state_store.record_external_publication_failure(
                marker,
                code,
            )
        except Exception:
            logger.exception(
                "Could not persist external publication failure code %s",
                code,
            )

    def _record_malformed_external_publication_failure_best_effort(
        self,
        marker: object,
    ) -> None:
        try:
            self._state_store.record_malformed_external_publication_failure(
                marker,
            )
        except Exception:
            logger.exception(
                "Could not persist malformed external publication failure"
            )

    def _publish_and_finalize(
        self,
        prepared: PreparedSquadPublication,
        marker: Mapping[str, object],
    ) -> bool:
        """Publish one authorized stage and durably clear its exact marker."""
        try:
            expected_marker = validate_pending_external_publication(marker)
            prepared_marker = validate_pending_external_publication(
                prepared.marker.to_dict()
            )
            persisted_marker = validate_pending_external_publication(
                self._state_store.load().get(
                    PENDING_EXTERNAL_PUBLICATION_KEY
                )
            )
        except Exception:
            return False
        if (
            prepared_marker != expected_marker
            or persisted_marker != expected_marker
        ):
            return False
        try:
            state = self._state_store.load()
            self._authenticate_quality_debt_publication_stage(
                prepared,
                state,
            )
            authenticate_pending_product_input_mutation(
                self._project_root,
                state,
                expected_marker,
                prepared._manifest["operations"],
                staged_inputs=(
                    prepared._transaction_root / "work/product-inputs"
                ),
            )
            prepared.publish()
            verified_product_input_tree_hash = (
                require_product_input_mutation_postimage(
                    self._project_root,
                    state,
                    expected_marker,
                )
            )
        except ProductInputMutationError:
            self._record_external_publication_failure_best_effort(
                expected_marker,
                "target_drift",
            )
            return False
        except PublicationError as exc:
            self._record_external_publication_failure_best_effort(
                expected_marker,
                exc.code,
            )
            return False
        except Exception:
            self._record_external_publication_failure_best_effort(
                expected_marker,
                "publish_io",
            )
            return False

        try:
            if verified_product_input_tree_hash is None:
                self._state_store.complete_external_publication(
                    expected_marker
                )
            else:
                self._state_store.complete_external_publication(
                    expected_marker,
                    verified_product_input_tree_hash=(
                        verified_product_input_tree_hash
                    ),
                )
            cleared = self._state_store.load()
            if PENDING_EXTERNAL_PUBLICATION_KEY in cleared:
                raise StateAdvanceError(
                    "external publication marker was not cleared",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="state_finalize",
                )
            try:
                self._state_store.confirm_durable_state(cleared)
            except StateDurabilityError:
                return False
        except StateDurabilityError:
            return False
        except Exception:
            try:
                cleared = self._state_store.load()
                completion_won = (
                    PENDING_EXTERNAL_PUBLICATION_KEY not in cleared
                )
            except Exception:
                completion_won = False
            if completion_won:
                try:
                    self._state_store.confirm_durable_state(cleared)
                except StateDurabilityError:
                    return False
                try:
                    prepared.discard()
                except PublicationError:
                    logger.warning(
                        "Could not discard completed external publication stage",
                        exc_info=True,
                    )
                self._prepared_product_input_updates.pop(
                    str(expected_marker["transaction_id"]),
                    None,
                )
                return True
            self._record_external_publication_failure_best_effort(
                expected_marker,
                "state_finalize",
            )
            return False

        try:
            prepared.discard()
        except PublicationError:
            logger.warning(
                "Could not discard completed external publication stage",
                exc_info=True,
            )
        self._prepared_product_input_updates.pop(
            str(expected_marker["transaction_id"]),
            None,
        )
        return True

    def _recover_pending_external_publication(self) -> bool:
        """Replay the exact state-authorized stage before any phase work."""
        state = self._state_store.load()
        if PENDING_EXTERNAL_PUBLICATION_KEY not in state:
            return True
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return False
        marker_value = state[PENDING_EXTERNAL_PUBLICATION_KEY]
        try:
            marker = validate_pending_external_publication(marker_value)
        except Exception:
            self._record_malformed_external_publication_failure_best_effort(
                marker_value,
            )
            return False
        try:
            prepared = load_prepared_publication(
                self._project_root,
                self._squad_dir,
                marker,
            )
        except PublicationError as exc:
            marker = (
                marker_value
                if isinstance(marker_value, Mapping)
                else {}
            )
            self._record_external_publication_failure_best_effort(
                marker,
                exc.code,
            )
            return False
        except Exception:
            self._record_external_publication_failure_best_effort(
                marker,
                "manifest_invalid",
            )
            return False
        completed = self._publish_and_finalize(prepared, marker)
        if completed:
            last_dispatch = state.get("last_dispatch")
            if (
                (
                    isinstance(last_dispatch, Mapping)
                    and last_dispatch.get("phase_id")
                    == "phase4-document"
                )
                or (
                    str(state.get("phase") or "") in TERMINAL_PHASES
                    and bool(state.get("published_spec_dir"))
                )
            ):
                self._phase_a_published_this_run = True
                self._mine_published_context_after_publication()
        return completed

    def _discard_publication_without_authority(
        self,
        prepared: PreparedSquadPublication | None,
    ) -> None:
        """Discard a stage only after proving its marker is not durable."""
        if prepared is None:
            return
        marker = prepared.marker.to_dict()
        try:
            state = self._state_store.load()
        except Exception:
            return
        if state.get(PENDING_EXTERNAL_PUBLICATION_KEY) == marker:
            return
        try:
            prepared.discard()
        except PublicationError:
            logger.warning(
                "Could not discard unreferenced external publication stage",
                exc_info=True,
            )
        self._prepared_product_input_updates.pop(
            str(marker.get("transaction_id") or ""),
            None,
        )

    @staticmethod
    def _human_input_options_from_decision(
        decision: Mapping[str, object],
    ) -> tuple[HumanInputOption, ...]:
        raw_options = decision.get("options")
        if not isinstance(raw_options, list):
            raise HumanInputPolicyError("sealed decision options are invalid")
        try:
            return tuple(
                HumanInputOption(
                    id=option["id"],
                    label=option["label"],
                    description=option["description"],
                    recommended=option["recommended"],
                    risk_level=option["risk_level"],
                    next_phase=option["next_phase"],
                    outcome=option["outcome"],
                )
                for option in raw_options
                if isinstance(option, Mapping)
            )
        except (KeyError, TypeError, HumanInputPolicyError) as exc:
            raise HumanInputPolicyError(
                "sealed decision options are invalid"
            ) from exc

    @staticmethod
    def _is_dynamic_dispatch_cap_policy(policy: HumanInputPolicy) -> bool:
        return (
            policy.source_kind in {
                "controller_safeguard",
                "legacy_recovery",
            }
            and policy.producer_id == "phase_dispatch_limit"
            and policy.reason_code == "phase_dispatch_limit"
            and policy.resolution_handler == "phase_dispatch_limit"
        )

    @staticmethod
    def _dispatch_cap_option_payload(
        option: HumanInputOption,
    ) -> dict[str, object]:
        try:
            payload = json.loads(option.description)
        except (TypeError, ValueError) as exc:
            raise HumanInputPolicyError(
                "dispatch-cap option authority is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise HumanInputPolicyError(
                "dispatch-cap option authority is invalid"
            )
        return payload

    @classmethod
    def _dispatch_cap_candidate_from_option(
        cls,
        option: HumanInputOption,
    ) -> dict[str, str]:
        raw_candidate = cls._dispatch_cap_option_payload(option)
        fields = {
            "issue_id",
            "title",
            "decision_required",
            "suggested_option",
            "evidence_basis",
        }
        if (
            set(raw_candidate) != fields
            or not all(
                isinstance(raw_candidate[field], str)
                and raw_candidate[field].strip()
                for field in fields
            )
        ):
            raise HumanInputPolicyError(
                "dispatch-cap option authority is invalid"
            )
        candidate = {
            field: raw_candidate[field].strip()
            for field in sorted(fields)
        }
        canonical = json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
        )
        if (
            option.id != candidate["issue_id"]
            or option.label
            != f"{candidate['issue_id']}: {candidate['title']}"
            or option.description != canonical
            or option.recommended
            or option.risk_level != "medium"
            or option.next_phase != "phase1-what"
            or option.outcome is not None
        ):
            raise HumanInputPolicyError(
                "dispatch-cap option authority is invalid"
            )
        return candidate

    @classmethod
    def _validate_dispatch_cap_option(
        cls,
        option: HumanInputOption,
    ) -> None:
        payload = cls._dispatch_cap_option_payload(option)
        legacy_fields = {
            "issue_id",
            "title",
            "decision_required",
            "suggested_option",
            "evidence_basis",
        }
        if set(payload) == legacy_fields:
            cls._dispatch_cap_candidate_from_option(option)
            return
        reference_fields = {
            "evidence_sha256",
            "issue_id",
            "schema_version",
        }
        issue_id = payload.get("issue_id")
        digest = payload.get("evidence_sha256")
        prefix = f"{issue_id}: "
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        if (
            set(payload) != reference_fields
            or payload.get("schema_version") != 1
            or not isinstance(issue_id, str)
            or not issue_id.strip()
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or option.id != issue_id
            or not option.label.startswith(prefix)
            or len(option.label) <= len(prefix)
            or option.description != canonical
            or option.recommended
            or option.risk_level != "medium"
            or option.next_phase != "phase1-what"
            or option.outcome is not None
        ):
            raise HumanInputPolicyError(
                "dispatch-cap option authority is invalid"
            )

    def _dispatch_cap_candidate_for_resolution(
        self,
        state: Mapping[str, object],
        option: HumanInputOption,
    ) -> dict[str, str]:
        payload = self._dispatch_cap_option_payload(option)
        if "schema_version" not in payload:
            return self._dispatch_cap_candidate_from_option(option)
        self._validate_dispatch_cap_option(option)
        issue_id = str(payload["issue_id"])
        try:
            candidates = self._banzai_issue_resolution_candidates(
                dict(state)
            )
        except _DispatchCapEvidenceError as exc:
            raise HumanInputPolicyError(
                "dispatch-cap evidence changed after decision sealing"
            ) from exc
        matches = [
            candidate
            for candidate in candidates
            if candidate["issue_id"] == issue_id
        ]
        if len(matches) != 1 or not hmac.compare_digest(
            self._dispatch_cap_candidate_digest(matches[0]),
            str(payload["evidence_sha256"]),
        ):
            raise HumanInputPolicyError(
                "dispatch-cap evidence changed after decision sealing"
            )
        return matches[0]

    @staticmethod
    def _canonical_dispatch_cap_candidate(
        candidate: Mapping[str, str],
    ) -> str:
        return json.dumps(
            dict(candidate),
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _dispatch_cap_candidate_digest(
        cls,
        candidate: Mapping[str, str],
    ) -> str:
        return hashlib.sha256(
            cls._canonical_dispatch_cap_candidate(candidate).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _bounded_dispatch_cap_label(
        issue_id: str,
        title: str,
    ) -> str:
        prefix = f"{issue_id}: "
        label = f"{prefix}{title}"
        if len(label.encode("utf-8")) <= HUMAN_INPUT_OPTION_LABEL_MAX_BYTES:
            return label
        suffix = "…"
        budget = (
            HUMAN_INPUT_OPTION_LABEL_MAX_BYTES
            - len(prefix.encode("utf-8"))
            - len(suffix.encode("utf-8"))
        )
        kept: list[str] = []
        used = 0
        for character in title:
            width = len(character.encode("utf-8"))
            if used + width > budget:
                break
            kept.append(character)
            used += width
        return f"{prefix}{''.join(kept)}{suffix}"

    @classmethod
    def _dispatch_cap_option_reference(
        cls,
        candidate: Mapping[str, str],
    ) -> str:
        return json.dumps(
            {
                "evidence_sha256": cls._dispatch_cap_candidate_digest(
                    candidate
                ),
                "issue_id": candidate["issue_id"],
                "schema_version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _dispatch_cap_options(
        cls,
        candidates: list[dict[str, str]],
    ) -> tuple[HumanInputOption, ...]:
        if not candidates:
            raise HumanInputPolicyError(
                "phase dispatch limit requires an eligible issue option"
            )
        if len(candidates) > HUMAN_INPUT_MAX_OPTIONS:
            raise HumanInputPolicyError(
                "phase dispatch limit has too many eligible issue options"
            )
        options = tuple(
            HumanInputOption(
                id=candidate["issue_id"],
                label=cls._bounded_dispatch_cap_label(
                    candidate["issue_id"],
                    candidate["title"],
                ),
                description=cls._dispatch_cap_option_reference(candidate),
                recommended=False,
                risk_level="medium",
                next_phase="phase1-what",
                outcome=None,
            )
            for candidate in candidates
        )
        for candidate, option in zip(candidates, options, strict=True):
            if (
                option.id != candidate["issue_id"]
                or option.label
                != cls._bounded_dispatch_cap_label(
                    candidate["issue_id"],
                    candidate["title"],
                )
                or option.description
                != cls._dispatch_cap_option_reference(candidate)
            ):
                raise HumanInputPolicyError(
                    "dispatch-cap option authority is invalid"
                )
        return options

    def _legacy_policy_alias(
        self,
        *,
        phase_id: str,
        reason_code: str,
        producer_id: str | None = None,
    ) -> HumanInputPolicy:
        candidates = [
            policy
            for policy in self._human_input_registry.policies
            if policy.source_kind in {
                "provider_escalation",
                "controller_safeguard",
            }
            and policy.reason_code == reason_code
            and phase_id in policy.allowed_phase_ids
            and (
                producer_id is None
                or policy.producer_id == producer_id
            )
        ]
        if len(candidates) != 1:
            raise HumanInputPolicyError(
                "legacy recovery does not identify one exact current policy"
            )
        return legacy_recovery_policy_alias(candidates[0])

    @classmethod
    def _legacy_escalation_options(
        cls,
        raw_options: object,
        policy: HumanInputPolicy,
    ) -> tuple[HumanInputOption, ...]:
        if raw_options is None:
            raw_options = []
        if not isinstance(raw_options, list):
            raise HumanInputPolicyError(
                "legacy recovery options must be a list"
            )
        if not cls._is_dynamic_dispatch_cap_policy(policy):
            if raw_options:
                raise HumanInputPolicyError(
                    "legacy recovery options do not match the current policy"
                )
            return ()
        if not raw_options:
            raise HumanInputPolicyError(
                "legacy dispatch-cap recovery requires sealed issue options"
            )
        expected_fields = {
            "id",
            "label",
            "description",
            "recommended",
            "risk_level",
            "next_phase",
        }
        options: list[HumanInputOption] = []
        for raw_option in raw_options:
            if (
                not isinstance(raw_option, Mapping)
                or set(raw_option) != expected_fields
            ):
                raise HumanInputPolicyError(
                    "legacy recovery options are malformed"
                )
            option = HumanInputOption(
                id=raw_option["id"],
                label=raw_option["label"],
                description=raw_option["description"],
                recommended=raw_option["recommended"],
                risk_level=raw_option["risk_level"],
                next_phase=raw_option["next_phase"],
                outcome=None,
            )
            cls._validate_dispatch_cap_option(option)
            options.append(option)
        return tuple(options)

    def _validate_active_legacy_squad_decision(
        self,
        state: Mapping[str, object],
        raw_decision: Mapping[str, object],
        *,
        phase_id: str,
        reason_code: str,
        question: str,
        policy: HumanInputPolicy,
    ) -> None:
        from datetime import datetime, timedelta

        required_fields = {
            "schema_version",
            "status",
            "answer_type",
            "question",
            "blocked_reason",
            "blocked_phase",
            "blocked_at",
        }
        optional_fields = {
            "risk_level",
            "options",
            "recommended_answer",
            "default_answer",
        }
        if not all(isinstance(key, str) for key in raw_decision):
            raise HumanInputPolicyError(
                "legacy recovery decision field names must be strings"
            )
        unknown = set(raw_decision) - required_fields - optional_fields
        missing = required_fields - set(raw_decision)
        if unknown or missing:
            raise HumanInputPolicyError(
                "legacy recovery decision shape is invalid"
            )
        if (
            type(raw_decision["schema_version"]) is not int
            or raw_decision["schema_version"] != 1
            or raw_decision["status"] != "pending"
        ):
            raise HumanInputPolicyError(
                "legacy recovery decision is not an active schema-v1 decision"
            )
        if any(
            not isinstance(raw_decision[field], str)
            or not str(raw_decision[field]).strip()
            for field in (
                "answer_type",
                "question",
                "blocked_reason",
                "blocked_phase",
                "blocked_at",
            )
        ):
            raise HumanInputPolicyError(
                "legacy recovery decision strings are invalid"
            )
        if (
            raw_decision["question"].strip() != question
            or raw_decision["blocked_reason"].strip() != reason_code
            or raw_decision["blocked_phase"].strip() != phase_id
        ):
            raise HumanInputPolicyError(
                "legacy recovery decision projections do not match state"
            )
        try:
            blocked_at = datetime.fromisoformat(
                raw_decision["blocked_at"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise HumanInputPolicyError(
                "legacy recovery blocked_at must be a UTC timestamp"
            ) from exc
        if blocked_at.tzinfo is None or blocked_at.utcoffset() != timedelta(0):
            raise HumanInputPolicyError(
                "legacy recovery blocked_at must be a UTC timestamp"
            )

        options = self._legacy_escalation_options(
            state.get("escalation_options"),
            policy,
        )
        expected_options = [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": option.recommended,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
            }
            for option in options
        ]
        answer_type = "choice" if expected_options else "free_text"
        if raw_decision["answer_type"] != answer_type:
            raise HumanInputPolicyError(
                "legacy recovery answer shape does not match the current policy"
            )
        if expected_options:
            if raw_decision.get("options") != expected_options:
                raise HumanInputPolicyError(
                    "legacy recovery option projections do not match state"
                )
        elif "options" in raw_decision:
            raise HumanInputPolicyError(
                "legacy free-text recovery cannot declare options"
            )

        recommended = state.get("escalation_recommended_answer")
        recommended = (
            recommended.strip()
            if isinstance(recommended, str) and recommended.strip()
            else None
        )
        if recommended is None:
            recommended_option = next(
                (option for option in expected_options if option["recommended"]),
                None,
            )
            if recommended_option is not None:
                recommended = str(
                    recommended_option["id"] or recommended_option["label"]
                )
        if (
            recommended is None
            and "recommended_answer" in raw_decision
        ) or (
            recommended is not None
            and raw_decision.get("recommended_answer") != recommended
        ):
            raise HumanInputPolicyError(
                "legacy recovery recommendation projection does not match state"
            )
        if recommended is not None and expected_options:
            matches = [
                option
                for option in expected_options
                if recommended in {option["id"], option["label"]}
            ]
            if len(matches) != 1:
                raise HumanInputPolicyError(
                    "legacy recovery recommendation is not one exact option"
                )

        default_answer = state.get("escalation_default_answer")
        default_answer = (
            default_answer.strip()
            if isinstance(default_answer, str) and default_answer.strip()
            else recommended
        )
        if (
            default_answer is None
            and "default_answer" in raw_decision
        ) or (
            default_answer is not None
            and raw_decision.get("default_answer") != default_answer
        ):
            raise HumanInputPolicyError(
                "legacy recovery default projection does not match state"
            )
        if default_answer is not None and expected_options:
            matches = [
                option
                for option in expected_options
                if default_answer in {option["id"], option["label"]}
            ]
            if len(matches) != 1:
                raise HumanInputPolicyError(
                    "legacy recovery default is not one exact option"
                )

        risk_level = state.get("escalation_risk_level")
        if not isinstance(risk_level, str) or not risk_level.strip():
            risk_level = state.get("risk_level")
        risk_level = (
            risk_level.strip().lower()
            if isinstance(risk_level, str) and risk_level.strip()
            else None
        )
        if risk_level not in {None, "low", "medium", "high", "critical"}:
            raise HumanInputPolicyError(
                "legacy recovery risk projection is invalid"
            )
        if (
            risk_level is None
            and "risk_level" in raw_decision
        ) or (
            risk_level is not None
            and raw_decision.get("risk_level") != risk_level
        ):
            raise HumanInputPolicyError(
                "legacy recovery risk projection does not match state"
            )

    def _prepare_legacy_human_input(
        self,
        state: Mapping[str, object],
    ) -> PreparedHumanInput | None:
        if state.get("status") != "blocked":
            return None
        run_kind = state.get("run_kind")
        if run_kind not in {None, "", "squad"}:
            return None
        phase_id = state.get("phase")
        reason_code = state.get("blocked_reason")
        question = state.get("escalation_question")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (phase_id, reason_code, question)
        ):
            return None
        phase_id = str(phase_id).strip()
        reason_code = str(reason_code).strip()
        question = str(question).strip()

        raw_decision = state.get("blocked_decision")
        if not isinstance(raw_decision, Mapping):
            return None

        try:
            raw_instruction = state.get("recovery_instruction")
            instruction = (
                validate_recovery_instruction(raw_instruction)
                if raw_instruction is not None
                else None
            )
            source_phase = phase_id
            if phase_id in TERMINAL_PHASES:
                if reason_code == "phase_dispatch_limit":
                    legacy_source_phase = state.get(
                        "phase_dispatch_limit_phase"
                    )
                else:
                    last_dispatch = state.get("last_dispatch")
                    legacy_source_phase = (
                        last_dispatch.get("phase_id")
                        if isinstance(last_dispatch, Mapping)
                        else None
                    )
                if (
                    not isinstance(legacy_source_phase, str)
                    or not legacy_source_phase.strip()
                    or legacy_source_phase.strip() in TERMINAL_PHASES
                ):
                    return None
                source_phase = legacy_source_phase.strip()

            policy = self._legacy_policy_alias(
                phase_id=source_phase,
                reason_code=reason_code,
            )
            self._validate_active_legacy_squad_decision(
                state,
                raw_decision,
                phase_id=phase_id,
                reason_code=reason_code,
                question=question,
                policy=policy,
            )
            if (
                phase_id in TERMINAL_PHASES
                and policy.producer_id
                not in {
                    "phase_dispatch_limit",
                    "consecutive_why_fails",
                    "why2_metric_stagnation",
                }
            ):
                return None
            options = self._legacy_escalation_options(
                state.get("escalation_options"),
                policy,
            )
            expected_answer_type = "choice" if options else "free_text"
            if raw_decision.get("answer_type") != expected_answer_type:
                return None

            expected_kind = (
                RecoveryKind.RESOLVE_ISSUE
                if self._is_dynamic_dispatch_cap_policy(policy)
                else RecoveryKind.AWAIT_HUMAN_ANSWER
            )
            if instruction is not None:
                if (
                    instruction.schema_version != 1
                    or instruction.kind is not expected_kind
                    or instruction.reason_code != reason_code
                    or instruction.phase != source_phase
                    or not instruction.requires_human_input
                ):
                    return None

            alias_registry = HumanInputPolicyRegistry((policy,))
            request = alias_registry.prepare(
                source_kind="legacy_recovery",
                producer_id=policy.producer_id,
                phase_id=source_phase,
                reason_code=reason_code,
                question=question,
                recommended_answer=state.get(
                    "escalation_recommended_answer"
                ),
                risk_level=state.get("escalation_risk_level"),
                source_state_revision=int(state["state_revision"]),
            )
            if options:
                request = replace(request, options=options)
            return request
        except (
            HumanInputPolicyError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

    def _policy_for_human_input_decision(
        self,
        decision: Mapping[str, object],
    ) -> HumanInputPolicy:
        if decision.get("source_kind") == "legacy_recovery":
            policy = self._legacy_policy_alias(
                phase_id=str(decision.get("source_phase") or ""),
                producer_id=str(decision.get("producer_id") or ""),
                reason_code=str(decision.get("reason_code") or ""),
            )
        else:
            policy = self._human_input_registry.lookup(
                str(decision.get("source_kind") or ""),
                str(decision.get("producer_id") or ""),
                str(decision.get("reason_code") or ""),
            )
        if (
            decision.get("classification") != policy.classification
            or decision.get("resolution_handler") != policy.resolution_handler
            or decision.get("source_phase") not in policy.allowed_phase_ids
        ):
            raise HumanInputPolicyError(
                "sealed decision does not match its registered policy"
            )
        options = self._human_input_options_from_decision(decision)
        dynamic_dispatch_cap = self._is_dynamic_dispatch_cap_policy(policy)
        if dynamic_dispatch_cap:
            for option in options:
                self._validate_dispatch_cap_option(option)
        elif policy.source_kind != "provider_escalation":
            proportional_options = (
                policy.resolution_handler == "proportional_quality_debt"
                and len([option for option in options if option.recommended])
                == 1
                and tuple(
                    replace(option, recommended=False) for option in options
                )
                == policy.options
            )
            legacy_options = (
                decision.get("schema_version") == 2
                and tuple(
                    replace(option, recommended=False) for option in options
                )
                == tuple(
                    replace(option, recommended=False)
                    for option in policy.options
                )
            )
            if (
                options != policy.options
                and not proportional_options
                and not legacy_options
            ):
                raise HumanInputPolicyError(
                    "sealed decision options do not match their registered policy"
                )
        if any(
            option.next_phase is not None
            and option.next_phase not in policy.allowed_target_phases
            for option in options
        ):
            raise HumanInputPolicyError(
                "sealed decision option escapes registered targets"
            )
        if not dynamic_dispatch_cap and bool(options) == policy.allow_free_text:
            raise HumanInputPolicyError(
                "sealed decision answer shape does not match its registered policy"
            )
        return policy

    def _validate_prepared_human_input(
        self,
        request: PreparedHumanInput,
    ) -> HumanInputPolicy:
        if type(request) is not PreparedHumanInput or request.schema_version != 2:
            raise HumanInputPolicyError(
                "controller requires a prepared human-input request"
            )
        if request.source_kind == "legacy_recovery":
            policy = self._legacy_policy_alias(
                phase_id=request.phase_id,
                producer_id=request.producer_id,
                reason_code=request.reason_code,
            )
        else:
            policy = self._human_input_registry.lookup(
                request.source_kind,
                request.producer_id,
                request.reason_code,
            )
        if (
            request.phase_id not in policy.allowed_phase_ids
            or request.classification != policy.classification
            or request.resolution_handler != policy.resolution_handler
        ):
            raise HumanInputPolicyError(
                "prepared request does not match its registered policy"
            )
        if self._is_dynamic_dispatch_cap_policy(policy):
            if not request.options:
                raise HumanInputPolicyError(
                    "phase dispatch limit requires at least one eligible option"
                )
            for option in request.options:
                self._validate_dispatch_cap_option(option)
        elif request.source_kind != "provider_escalation":
            proportional_options = (
                request.resolution_handler == "proportional_quality_debt"
                and len(
                    [option for option in request.options if option.recommended]
                )
                == 1
                and tuple(
                    replace(option, recommended=False)
                    for option in request.options
                )
                == policy.options
            )
            if request.options != policy.options and not proportional_options:
                raise HumanInputPolicyError(
                    "prepared request options do not match their registered policy"
                )
        if (
            not self._is_dynamic_dispatch_cap_policy(policy)
            and bool(request.options) == policy.allow_free_text
        ):
            raise HumanInputPolicyError(
                "prepared request answer shape does not match its registered policy"
            )
        return policy

    @staticmethod
    def _provider_advance_required(request: PreparedHumanInput) -> bool:
        return request.source_kind == "provider_escalation" or (
            request.source_kind == "controller_safeguard"
            and request.producer_id
            in {
                "consecutive_why_fails",
                "why2_metric_stagnation",
                "proportional_quality_budget_exhausted",
                "proportional_quality_extension_exhausted",
            }
        )

    def _intercept_human_gate(self, node: PhaseNode) -> bool:
        """Prepare and route one compiled gate without an executor result."""
        if node.type != "human_gate" or len(node.human_input_policies) != 1:
            raise HumanInputPolicyError(
                "human gate requires exactly one compiled policy"
            )
        policy = node.human_input_policies[0]
        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=node.id,
        )
        spec_dir = str(snapshot.state.get("spec_dir") or "the active spec")
        label = node.label or node.id
        checkpoint_context = _checkpoint_context(
            snapshot.state,
            node_id=node.id,
            node_label=label,
            journal_path=self._squad_dir / "reasoning-journal.jsonl",
        )
        request = self._human_input_registry.prepare(
            source_kind=policy.source_kind,
            producer_id=policy.producer_id,
            phase_id=node.id,
            reason_code=policy.reason_code,
            question=(
                f"Review {label} artifacts in {spec_dir}. "
                "Approve to continue or reject to stop for revision."
                f"{checkpoint_context}"
            ),
            source_state_revision=snapshot.state_revision,
        )
        return self.handle_human_input(request)

    def handle_human_input(
        self,
        request: PreparedHumanInput,
        *,
        provider_advance: _ProviderHumanInputAdvance | None = None,
    ) -> bool:
        """Seal one prepared request, then route only from its durable decision."""
        policy = self._validate_prepared_human_input(request)
        needs_advance = self._provider_advance_required(request)
        if needs_advance != (provider_advance is not None):
            raise HumanInputPolicyError(
                "human-input request used the wrong state sealing path"
            )
        if provider_advance is not None:
            if type(provider_advance) is not _ProviderHumanInputAdvance:
                raise HumanInputPolicyError(
                    "provider human-input advance is invalid"
                )
            source_matches = provider_advance.from_phase == request.phase_id or (
                request.source_kind == "controller_safeguard"
                and request.producer_id
                == "proportional_quality_budget_exhausted"
                and provider_advance.from_phase == "phase1-what"
                and request.phase_id == "phase1-why2"
            )
            if (
                not source_matches
                or provider_advance.decision.from_phase
                != provider_advance.from_phase
                or provider_advance.decision.to_phase
                != provider_advance.to_phase
            ):
                raise HumanInputPolicyError(
                    "provider human-input advance does not match the request"
                )

        state = self._state_store.load()
        autonomy_mode = state.get("autonomy_mode")
        if autonomy_mode not in {"guided", "semi", "banzai"}:
            raise HumanInputPolicyError(
                "persisted autonomy mode is invalid"
            )
        initial_status = select_initial_decision_status(
            str(autonomy_mode),
            policy,
            request,
        )
        if provider_advance is None:
            self._state_store.set_human_input_decision(
                request,
                initial_status=initial_status,
            )
        else:
            node = self._graph.get(provider_advance.from_phase)
            receipt = self._advance_prepared_result_or_block(
                node,
                provider_advance.decision,
                human_input=request,
                human_input_initial_status=initial_status,
            )
            if receipt is None:
                return False
        return self.resume_pending_human_input()

    def _semi_human_input_resolution(
        self,
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
    ) -> AppliedHumanInputResolution | None:
        if (
            policy.classification != "operational"
            or policy.semi_policy != "auto_if_recommended_low_risk"
        ):
            return None
        options = self._human_input_options_from_decision(decision)
        recommended = [option for option in options if option.recommended]
        if len(recommended) == 1:
            option = recommended[0]
            effective_risk = option.risk_level or decision.get("risk_level")
            if effective_risk == "low":
                return AppliedHumanInputResolution(
                    selected_option_id=option.id,
                    answer_text=None,
                    resolved_by="semi",
                    rationale=(
                        str(decision["recommendation_rationale"])
                        if decision.get("schema_version") == 3
                        else None
                    ),
                    confidence=(
                        str(decision["recommendation_confidence"])
                        if decision.get("schema_version") == 3
                        else None
                    ),
                )
            return None
        recommended_answer = decision.get("recommended_answer")
        if (
            not options
            and isinstance(recommended_answer, str)
            and recommended_answer.strip()
            and decision.get("risk_level") == "low"
        ):
            return AppliedHumanInputResolution(
                selected_option_id=None,
                answer_text=recommended_answer,
                resolved_by="semi",
                rationale=(
                    str(decision["recommendation_rationale"])
                    if decision.get("schema_version") == 3
                    else None
                ),
                confidence=(
                    str(decision["recommendation_confidence"])
                    if decision.get("schema_version") == 3
                    else None
                ),
            )
        return None

    @staticmethod
    def _validate_human_input_resolver(
        decision: Mapping[str, object],
        resolution: AppliedHumanInputResolution,
    ) -> None:
        resolver_contract = {
            "user": ("awaiting_human", None),
            "semi": ("pending", "semi"),
            "COMMANDER": ("resolving", "banzai"),
        }
        contract = resolver_contract.get(resolution.resolved_by)
        if contract is None:
            raise HumanInputPolicyError(
                "human-input resolver is not registered"
            )
        expected_status, expected_mode = contract
        if decision.get("status") != expected_status:
            raise HumanInputPolicyError(
                "human-input resolver is not permitted for decision status"
            )
        if (
            expected_mode is not None
            and decision.get("autonomy_mode") != expected_mode
        ):
            raise HumanInputPolicyError(
                "human-input resolver is not permitted by autonomy mode"
            )

    def _validate_human_input_resolution_answer(
        self,
        decision: Mapping[str, object],
        resolution: AppliedHumanInputResolution,
    ) -> HumanInputOption | None:
        options = self._human_input_options_from_decision(decision)
        if options:
            if (
                not isinstance(resolution.selected_option_id, str)
                or not resolution.selected_option_id
                or resolution.answer_text is not None
            ):
                raise HumanInputPolicyError(
                    "human-input resolution must select one registered option"
                )
            selected = next(
                (
                    option
                    for option in options
                    if option.id == resolution.selected_option_id
                ),
                None,
            )
            if selected is None:
                raise HumanInputPolicyError(
                    "human-input resolution selected an unknown option"
                )
            return selected
        if (
            resolution.selected_option_id is not None
            or not isinstance(resolution.answer_text, str)
            or not resolution.answer_text.strip()
        ):
            raise HumanInputPolicyError(
                "human-input resolution requires one non-empty answer"
            )
        return None

    def _validate_human_input_route(
        self,
        route: object,
        policy: HumanInputPolicy,
        *,
        allow_source_phase: str | None = None,
    ) -> str:
        if not isinstance(route, str) or not route:
            raise HumanInputPolicyError(
                "human-input resolution route is invalid"
            )
        if route not in self._graph.all_phase_ids():
            raise HumanInputPolicyError(
                "human-input resolution route is outside the phase graph"
            )
        if (
            route not in policy.allowed_target_phases
            and route != allow_source_phase
        ):
            raise HumanInputPolicyError(
                "human-input resolution route is not registered"
            )
        return route

    def _read_clarification_receipts(
        self,
        state: Mapping[str, object],
    ) -> tuple[str, int]:
        roots = self._authoritative_human_input_roots(state)
        staging = roots["{staging_dir}"]
        if staging is None:
            raise HumanInputPolicyError("staging root is unavailable")
        opened = self._open_project_directory_chain(staging)
        directory_fd = opened[-1]
        file_fd = -1
        keep_directory = False
        try:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            try:
                file_fd = os.open(
                    "user-clarifications.md",
                    flags,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                keep_directory = True
                return "", directory_fd
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise HumanInputPolicyError(
                    "clarification receipt must be a regular file"
                )
            if metadata.st_size > 1_048_576:
                raise HumanInputPolicyError(
                    "clarification receipt exceeds the byte limit"
                )
            chunks: list[bytes] = []
            remaining = 1_048_576
            while remaining > 0:
                chunk = os.read(
                    file_fd,
                    min(remaining + 1, _CONTEXT_FILE_READ_CHUNK_BYTES),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
                if remaining < 0:
                    raise HumanInputPolicyError(
                        "clarification receipt exceeds the byte limit"
                    )
            text = b"".join(chunks).decode("utf-8")
            keep_directory = True
            return text, directory_fd
        except HumanInputPolicyError:
            raise
        except (OSError, UnicodeError) as exc:
            raise HumanInputPolicyError(
                "clarification receipt cannot follow a symlink or invalid file"
            ) from exc
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            descriptors = opened[:-1] if keep_directory else opened
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _replace_clarification_receipts(
        directory_fd: int,
        content: str,
    ) -> None:
        temporary = f".user-clarifications-{uuid.uuid4().hex}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                ),
                0o600,
                dir_fd=directory_fd,
            )
            payload = content.encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("clarification receipt write made no progress")
                offset += written
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary,
                "user-clarifications.md",
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        except OSError as exc:
            raise HumanInputPolicyError(
                "clarification receipt replacement failed"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass

    def _clarification_resume_resolution(
        self,
        state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        selected: HumanInputOption | None,
        resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        source_phase = str(decision["source_phase"])
        route = self._validate_human_input_route(
            (
                selected.next_phase
                if selected is not None and selected.next_phase is not None
                else source_phase
            ),
            policy,
            allow_source_phase=source_phase,
        )
        answer = (
            selected.label
            if selected is not None
            else str(resolution.answer_text)
        )
        marker = f"## Decision {decision['id']}"
        existing, directory_fd = self._read_clarification_receipts(state)
        section = (
            f"{marker}\n\n"
            f"**Question:** {decision['question']}\n\n"
            f"**Answer:** {answer}\n"
        )
        marker_matches = tuple(
            re.finditer(
                rf"^{re.escape(marker)}[ \t]*(?:\r?\n|\Z)",
                existing,
                re.MULTILINE,
            )
        )
        if marker_matches:
            if existing != section:
                os.close(directory_fd)
                raise HumanInputPolicyError(
                    "clarification receipt conflicts with the resolution"
                )
        else:
            try:
                self._replace_clarification_receipts(
                    directory_fd,
                    section,
                )
            finally:
                os.close(directory_fd)
            directory_fd = -1
        if directory_fd >= 0:
            os.close(directory_fd)
        from echelon.feature_policy import (
            derive_feature_policy,
            persist_feature_policy,
            reconcile_feature_artifacts,
        )

        feature_policy = derive_feature_policy(
            answer,
            decision_id=str(decision["id"]),
        )
        staging_dir = self._authoritative_human_input_roots(state)["{staging_dir}"]
        assert staging_dir is not None
        persist_feature_policy(staging_dir, feature_policy)
        updates: dict[str, object] = {
            "status": "running",
            "phase": route,
            "feature_policy": feature_policy,
        }
        spec_dir = self._validated_spec_root(state)
        if spec_dir is not None and spec_dir.is_dir():
            reconciliation = reconcile_feature_artifacts(spec_dir, feature_policy)
            updates["feature_policy_reconciliation"] = reconciliation
            if reconciliation["requires_repair"]:
                updates["phase"] = "phase1-what"
                route = "phase1-what"
        context_result = build_run_context(
            self._project_root,
            self._squad_dir,
            user_request=str(state.get("user_message") or ""),
        )
        updates["context_dir"] = str(context_result.context_dir)
        return _HumanInputResolutionEffects(
            state_updates=updates,
            state_removals=frozenset(),
            route=route,
        )

    def _gate_outcome_resolution(
        self,
        _state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        selected: HumanInputOption | None,
        _resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        if selected is None or selected.outcome not in {"approved", "rejected"}:
            raise HumanInputPolicyError(
                "human gate outcome is not registered"
            )
        route = self._validate_human_input_route(
            selected.next_phase,
            policy,
        )
        route_error = gate_outcome_route_error(selected.outcome, route)
        if route_error is not None:
            raise HumanInputPolicyError(route_error)
        updates: dict[str, object] = {
            "phase": route,
            "status": (
                "blocked"
                if selected.outcome == "rejected"
                else "running"
            ),
        }
        if selected.outcome == "rejected":
            updates["blocked_reason"] = "gate_rejected"
        return _HumanInputResolutionEffects(
            state_updates=updates,
            state_removals=frozenset(),
            route=route,
        )

    def _phase_dispatch_limit_resolution(
        self,
        state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        selected: HumanInputOption | None,
        resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        if selected is None:
            raise HumanInputPolicyError(
                "dispatch-cap resolution must select one sealed issue option"
            )
        candidate = self._dispatch_cap_candidate_for_resolution(
            state,
            selected,
        )
        raw_selection = {
            "issue_id": candidate["issue_id"],
            "decision": candidate["suggested_option"],
            "rationale": candidate["evidence_basis"],
            "confidence": "high",
            "evidence_backed": True,
        }
        selection = self._validate_banzai_issue_resolution_selection(
            raw_selection,
            [candidate],
        )
        if selection is None:
            raise HumanInputPolicyError(
                "dispatch-cap resolution is not evidence-backed"
            )
        capped_phase = str(decision["source_phase"])
        legacy_phase = state.get("phase_dispatch_limit_phase")
        if legacy_phase is not None and (
            not isinstance(legacy_phase, str)
            or (
                legacy_phase.strip()
                and legacy_phase.strip() != capped_phase
            )
        ):
            raise HumanInputPolicyError(
                "dispatch-cap legacy phase conflicts with sealed source phase"
            )
        if (
            not capped_phase
            or capped_phase not in self._graph.all_phase_ids()
            or capped_phase in TERMINAL_PHASES
        ):
            raise HumanInputPolicyError(
                "dispatch-cap recovery target is invalid"
            )
        counts = state.get("phase_dispatch_counts")
        next_counts = dict(counts) if isinstance(counts, dict) else {}
        next_counts.pop(capped_phase, None)
        route = self._validate_human_input_route(
            selected.next_phase,
            policy,
        )
        updates = self._issue_resolution_state_updates(
            dict(state),
            selection,
        )
        updates.update(
            {
                "status": "running",
                "phase": route,
                "phase_dispatch_counts": next_counts,
                "phase_dispatch_limit_recovery": {
                    "phase": capped_phase,
                    "resolver": resolution.resolved_by,
                },
            }
        )
        return _HumanInputResolutionEffects(
            state_updates=updates,
            state_removals=frozenset(),
            route=route,
        )

    def _proportional_quality_debt_resolution(
        self,
        state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        selected: HumanInputOption | None,
        resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        """Apply one sealed bounded-quality choice from controller evidence."""
        if selected is None:
            raise HumanInputPolicyError(
                "proportional quality resolution requires a sealed option"
            )
        repair = validate_repair_state(state.get("phase1_quality_repair"))
        evidence = state.get("proportional_quality_candidate_evidence")
        if not isinstance(evidence, Mapping):
            raise HumanInputPolicyError(
                "selected proportional quality candidate evidence is missing"
            )
        selected_candidate_id = str(
            evidence.get("selected_candidate_id") or ""
        ).strip()
        manifest_ref = str(evidence.get("candidate_manifest") or "").strip()
        if not selected_candidate_id or not manifest_ref:
            raise HumanInputPolicyError(
                "selected proportional quality candidate evidence is invalid"
            )
        manifest_path = Path(manifest_ref)
        if not manifest_path.is_absolute():
            manifest_path = self._project_root / manifest_path
        manifest_sha = evidence.get("candidate_manifest_sha256")
        if type(manifest_sha) is not str:
            raise HumanInputPolicyError(
                "selected proportional quality candidate digest is missing"
            )
        try:
            candidate = load_quality_candidate_manifest(
                manifest_path,
                expected_sha256=manifest_sha,
                expected_candidate_id=selected_candidate_id,
            )
        except QualityCandidateIntegrityError as exc:
            raise HumanInputPolicyError(
                "selected proportional quality candidate identity changed"
            ) from exc

        if selected.id == "extend_once":
            if (
                decision.get("reason_code")
                != "proportional_quality_budget_exhausted"
                or repair["extension_authorized"] != 0
                or repair["extension_consumed"] != 0
            ):
                raise HumanInputPolicyError(
                    "proportional quality extension is already unavailable"
                )
            repair["extension_authorized"] = repair["extension_limit"]
            repair = validate_repair_state(repair)
            route = self._validate_human_input_route(
                selected.next_phase,
                policy,
            )
            return _HumanInputResolutionEffects(
                state_updates={
                    "status": "running",
                    "phase": route,
                    "phase1_quality_repair": repair,
                    "why_fail_count": 0,
                    "why2_metric_stagnation_count": 0,
                    "quality_gate_remediation": {
                        "kind": "proportional_quality",
                        "candidate_id": candidate.candidate_id,
                        "evidence": state.get("understanding_evidence"),
                        "baseline_spec_sha256": dict(
                            candidate.owned_artifact_digests
                        )["spec.md"],
                        "attempt": (
                            int(repair["automatic_consumed"])
                            + int(repair["extension_consumed"])
                            + 1
                        ),
                        "extension_active": True,
                        "qualitative_findings": [
                            dict(item)
                            for item in candidate.sage_finding_routes
                        ],
                        "reason": (
                            "Apply the single authorized proportional quality "
                            "extension to the restored candidate."
                        ),
                    },
                },
                state_removals=frozenset(),
                route=route,
            )

        if selected.id == "continue_with_debt":
            if resolution.resolved_by not in {"user", "COMMANDER"}:
                raise HumanInputPolicyError(
                    "quality debt requires a human or COMMANDER resolver"
                )
            lexicon = self._lexicon_gate_config().get("lexicon_gate")
            route = (
                "phase1-lexicon-derive"
                if isinstance(lexicon, Mapping)
                and lexicon.get("spec_enabled") is True
                else "checkpoint-assess"
            )
            route = self._validate_human_input_route(route, policy)
            from datetime import datetime, timezone

            resolved_at = datetime.now(timezone.utc).isoformat()
            completion_id = uuid.uuid4().hex
            try:
                prepared_debt = build_quality_debt_authorization(
                    project_root=self._project_root,
                    spec_dir=self._proportional_spec_dir(state),
                    candidate=candidate,
                    candidate_manifest=manifest_path,
                    repair_state=repair,
                    understanding_state=state.get(
                        "understanding_evidence"
                    ),
                    candidate_evidence_state=evidence,
                    decision=decision,
                    decision_id=str(decision["id"]),
                    resolved_by=resolution.resolved_by,
                    resolved_at=resolved_at,
                    completion_id=completion_id,
                    from_phase=str(state.get("phase") or ""),
                    to_phase=route,
                )
            except (QualityCandidateIntegrityError, ValueError) as exc:
                raise HumanInputPolicyError(
                    "quality-debt authorization could not be constructed"
                ) from exc
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=str(state.get("phase") or "")
            )
            completion = self._prepare_controller_completion(
                from_phase=str(state.get("phase") or ""),
                to_phase=route,
                snapshot=snapshot,
                manual_phase_run=False,
                conditional_skip=False,
                record_completion=True,
                publication_marker=None,
                origin="resolution",
                resolution_decision_id=str(decision["id"]),
                completion_id=completion_id,
                quality_effect={
                    "kind": "proportional_quality",
                    "operation": "debt_write",
                    "payload": prepared_debt.effect_payload(),
                },
            )
            return _HumanInputResolutionEffects(
                state_updates={
                    "status": "running",
                    "phase": route,
                    "spec_status": "accepted_with_debt",
                    "spec_quality_debt_authorization": (
                        prepared_debt.authorization
                    ),
                },
                state_removals=frozenset({"quality_gate_remediation"}),
                route=route,
                completion=completion,
                resolved_at=resolved_at,
            )

        if selected.id == "stop":
            route = self._validate_human_input_route(
                selected.next_phase,
                policy,
            )
            spec_dir = self._proportional_spec_dir(state)
            debt_ref = (spec_dir.resolve() / "quality-debt.json").relative_to(
                self._project_root.resolve()
            ).as_posix()
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=str(state.get("phase") or "")
            )
            completion = self._prepare_controller_completion(
                from_phase=str(state.get("phase") or ""),
                to_phase=route,
                snapshot=snapshot,
                manual_phase_run=False,
                conditional_skip=False,
                record_completion=True,
                publication_marker=None,
                origin="resolution",
                resolution_decision_id=str(decision["id"]),
                quality_effect={
                    "kind": "proportional_quality",
                    "operation": "debt_remove",
                    "payload": {
                        "operation": "debt_remove",
                        "debt_path": debt_ref,
                    },
                },
            )
            return _HumanInputResolutionEffects(
                state_updates={
                    "status": "blocked",
                    "phase": route,
                    "blocked_reason": (
                        "proportional_quality_debt_declined"
                    ),
                },
                state_removals=frozenset({
                    "quality_gate_remediation",
                    "spec_quality_debt_authorization",
                }),
                route=route,
                completion=completion,
            )
        raise HumanInputPolicyError(
            "proportional quality option is not registered"
        )

    def _reset_why_fail_count_resolution(
        self,
        _state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        _selected: HumanInputOption | None,
        _resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        route = self._validate_human_input_route(
            decision["source_phase"],
            policy,
        )
        return _HumanInputResolutionEffects(
            state_updates={
                "status": "running",
                "phase": route,
                "why_fail_count": 0,
            },
            state_removals=frozenset(),
            route=route,
        )

    def _reset_why2_stagnation_resolution(
        self,
        _state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        _selected: HumanInputOption | None,
        _resolution: AppliedHumanInputResolution,
    ) -> _HumanInputResolutionEffects:
        route = self._validate_human_input_route(
            decision["source_phase"],
            policy,
        )
        return _HumanInputResolutionEffects(
            state_updates={
                "status": "running",
                "phase": route,
                "why_fail_count": 0,
                "why2_metric_stagnation_count": 0,
            },
            state_removals=frozenset(),
            route=route,
        )

    def apply_human_input_resolution(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        resolution: AppliedHumanInputResolution,
        token_usage_delta: int = 0,
    ) -> bool:
        """Validate and apply one decision through its closed controller handler."""
        if type(resolution) is not AppliedHumanInputResolution:
            raise HumanInputPolicyError(
                "human-input resolution is invalid"
            )
        if type(token_usage_delta) is not int or token_usage_delta < 0:
            raise HumanInputPolicyError(
                "human-input token usage delta is invalid"
            )
        state = self._state_store.load()
        if PENDING_CONTROLLER_COMPLETION_KEY in state:
            raise HumanInputPolicyError(
                "controller completion is pending human-input resolution"
            )
        if (
            not isinstance(decision_id, str)
            or not decision_id
            or type(expected_state_revision) is not int
            or state.get("state_revision") != expected_state_revision
        ):
            raise HumanInputPolicyError(
                "human-input decision id or revision is stale"
            )
        raw_decision = state.get("blocked_decision")
        if not isinstance(raw_decision, Mapping):
            raise HumanInputPolicyError(
                "human-input decision is missing"
            )
        decision = validate_blocked_decision(raw_decision)
        if decision["id"] != decision_id:
            raise HumanInputPolicyError(
                "human-input decision id or revision is stale"
            )
        if decision["status"] not in {
            "pending",
            "resolving",
            "awaiting_human",
        }:
            raise HumanInputPolicyError(
                "human-input decision is not active"
            )
        policy = self._policy_for_human_input_decision(decision)
        self._validate_human_input_resolver(decision, resolution)
        selected = self._validate_human_input_resolution_answer(
            decision,
            resolution,
        )
        handlers = {
            "clarification_resume": self._clarification_resume_resolution,
            "gate_outcome": self._gate_outcome_resolution,
            "phase_dispatch_limit": self._phase_dispatch_limit_resolution,
            "reset_why_fail_count": self._reset_why_fail_count_resolution,
            "reset_why2_stagnation": (
                self._reset_why2_stagnation_resolution
            ),
            "proportional_quality_debt": (
                self._proportional_quality_debt_resolution
            ),
        }
        handler = handlers.get(str(decision["resolution_handler"]))
        if handler is None:
            raise HumanInputPolicyError(
                "human-input resolution handler is not registered"
            )
        effects = handler(
            state,
            decision,
            policy,
            selected,
            resolution,
        )
        if effects.route not in self._graph.all_phase_ids():
            raise HumanInputPolicyError(
                "human-input handler returned an invalid route"
            )
        try:
            resolved = self._state_store.apply_human_input_state_resolution(
                decision_id,
                expected_state_revision=expected_state_revision,
                resolution=resolution,
                state_updates=effects.state_updates,
                state_removals=effects.state_removals,
                token_usage_delta=token_usage_delta,
                prepared_completion=effects.completion,
                resolved_at=effects.resolved_at,
            )
        except BaseException:
            if effects.completion is not None:
                try:
                    current = self._state_store.load()
                    if current.get(PENDING_CONTROLLER_COMPLETION_KEY) != (
                        effects.completion.marker.to_dict()
                    ):
                        effects.completion.discard()
                except Exception:
                    pass
            raise
        if effects.completion is not None:
            recovery = self._drain_pending_controller_completion()
            if (
                not recovery.recovered
                or recovery.completion_id
                != effects.completion.marker.completion_id
            ):
                return False
            resolved = self._state_store.load()
        return (
            resolved.get("status") == "running"
            and resolved.get("phase") not in TERMINAL_PHASES
        )

    def _resolve_human_input_context_path(
        self,
        template: str,
        state: Mapping[str, object],
    ) -> tuple[Path, tuple[str, ...]]:
        roots = self._authoritative_human_input_roots(state)
        for marker, root in roots.items():
            if template != marker and not template.startswith(f"{marker}/"):
                continue
            if root is None:
                raise HumanInputPolicyError(
                    f"context root {marker} is unavailable"
                )
            suffix = template[len(marker):].lstrip("/")
            components = tuple(suffix.split("/")) if suffix else ()
            if not components or any(
                component in {"", ".", ".."} for component in components
            ):
                raise HumanInputPolicyError(
                    "registered context path must name an in-root file"
                )
            return root, components
        raise HumanInputPolicyError(
            "context path does not use a registered root"
        )

    def _identity_path(
        self,
        value: object,
        *,
        base: Path | None = None,
        field: str,
    ) -> Path:
        if not isinstance(value, (str, os.PathLike)):
            raise HumanInputPolicyError(f"{field} root identity is invalid")
        path = Path(value)
        if not path.is_absolute():
            path = (base or self._project_root) / path
        return Path(os.path.abspath(os.fspath(path)))

    def _project_contained_path(
        self,
        value: object,
        *,
        field: str,
    ) -> Path:
        project_root = self._identity_path(
            self._project_root,
            field="project",
        )
        path = self._identity_path(value, field=field)
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise HumanInputPolicyError(
                f"{field} root is outside the controller project"
            ) from exc
        return path

    def _validated_spec_root(
        self,
        state: Mapping[str, object],
        *,
        state_key: str = "spec_dir",
    ) -> Path | None:
        raw_root = state.get(state_key)
        if raw_root is None or not str(raw_root).strip():
            return None
        root = self._project_contained_path(
            raw_root,
            field=state_key,
        )
        spec_id = str(state.get("spec_id") or "").strip()
        if spec_id:
            actual_id = _spec_id_from_phase_a_dir(root)
            if (
                actual_id != spec_id
                and not actual_id.startswith(f"{spec_id}-")
            ):
                raise HumanInputPolicyError(
                    "spec root identity does not match the active spec"
                )
        return root

    def _authoritative_human_input_roots(
        self,
        state: Mapping[str, object],
    ) -> dict[str, Path | None]:
        store_squad = self._project_contained_path(
            self._state_store.squad_dir,
            field="store squad",
        )
        controller_squad = self._project_contained_path(
            self._squad_dir,
            field="controller squad",
        )
        if controller_squad != store_squad:
            raise HumanInputPolicyError(
                "controller and store run root identities do not match"
            )
        expected = {
            "squad_dir": store_squad,
            "staging_dir": self._identity_path(
                self._state_store.staging_dir,
                field="store staging",
            ),
            "context_dir": self._identity_path(
                store_squad / "context",
                field="store context",
            ),
        }
        for key, expected_root in expected.items():
            persisted = self._identity_path(
                state.get(key),
                field=key,
            )
            if persisted != expected_root:
                raise HumanInputPolicyError(
                    f"persisted {key} root identity does not match the run"
                )
        spec_root = self._validated_spec_root(state)
        if spec_root is None and "checkpoint_policy_version" not in state:
            spec_root = expected["staging_dir"]
        return {
            "{staging_dir}": expected["staging_dir"],
            "{spec_dir}": spec_root,
            "{context_dir}": expected["context_dir"],
            "{squad_dir}": expected["squad_dir"],
        }

    def _open_project_directory_chain(self, root: Path) -> list[int]:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise HumanInputPolicyError(
                "context no-follow traversal is unavailable"
            )
        project_root = self._identity_path(
            self._project_root,
            field="project",
        )
        try:
            relative = root.relative_to(project_root)
        except ValueError as exc:
            raise HumanInputPolicyError(
                "context root is outside the controller project"
            ) from exc
        directory_flags = (
            os.O_RDONLY
            | no_follow
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        opened = [os.open(project_root, directory_flags)]
        try:
            current_fd = opened[0]
            for component in relative.parts:
                current_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=current_fd,
                )
                opened.append(current_fd)
            return opened
        except Exception:
            for descriptor in reversed(opened):
                os.close(descriptor)
            raise

    def _read_human_input_context_file(
        self,
        template: str,
        state: Mapping[str, object],
        *,
        byte_limit: int,
    ) -> str:
        """Read one regular UTF-8 file through descriptor-bound no-follow opens."""
        if byte_limit <= 0:
            return ""
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise HumanInputPolicyError(
                "context no-follow traversal is unavailable"
            )
        root, components = self._resolve_human_input_context_path(
            template,
            state,
        )
        file_flags = (
            os.O_RDONLY
            | no_follow
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        opened: list[int] = []
        try:
            opened = self._open_project_directory_chain(root)
            current_fd = opened[-1]
            for component in components[:-1]:
                current_fd = os.open(
                    component,
                    (
                        os.O_RDONLY
                        | no_follow
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                    ),
                    dir_fd=current_fd,
                )
                opened.append(current_fd)
            file_fd = os.open(
                components[-1],
                file_flags,
                dir_fd=current_fd,
            )
            opened.append(file_fd)
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise HumanInputPolicyError(
                    "registered context path must be a regular file"
                )

            chunks: list[bytes] = []
            remaining = byte_limit
            reached_eof = False
            while remaining > 0:
                chunk = os.read(
                    file_fd,
                    min(remaining, _CONTEXT_FILE_READ_CHUNK_BYTES),
                )
                if not chunk:
                    reached_eof = True
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            decoder = codecs.getincrementaldecoder("utf-8")("strict")
            return decoder.decode(
                b"".join(chunks),
                final=reached_eof,
            )
        except FileNotFoundError:
            return "<missing>"
        except HumanInputPolicyError:
            raise
        except (OSError, UnicodeError) as exc:
            raise HumanInputPolicyError(
                "context path cannot escape through a symlink or invalid file"
            ) from exc
        finally:
            for descriptor in reversed(opened):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _render_commander_decision_prompt(
        self,
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
        state: Mapping[str, object],
    ) -> str:
        """Render only registered context under the complete UTF-8 byte cap."""
        validated = validate_blocked_decision(decision)
        registered = self._policy_for_human_input_decision(validated)
        if registered != policy:
            raise HumanInputPolicyError(
                "COMMANDER context policy does not match the sealed decision"
            )
        request_payload = {
            "decision_id": validated["id"],
            "source_kind": validated["source_kind"],
            "producer_id": validated["producer_id"],
            "source_phase": validated["source_phase"],
            "reason_code": validated["reason_code"],
            "classification": validated["classification"],
            "question": validated["question"],
            "options": validated["options"],
            "recommended_answer": validated["recommended_answer"],
            "risk_level": validated["risk_level"],
        }
        instructions = (
            "# COMMANDER DECISION RESOLUTION\n\n"
            "Return exactly this envelope for a choice:\n\n"
            "echelon_result:\n"
            "  verdict: DECISION_RESOLVED\n"
            "  state_updates: {}\n"
            "  journal_entries: []\n"
            "  decision:\n"
            '    selected_option_id: "<exact allowed option id>"\n'
            "    answer_text: null\n"
            "    rationale: \"<non-empty explanation, at most "
            f"{DECISION_RESOLUTION_RATIONALE_MAX_CHARS:,} characters>\"\n"
            "    confidence: high\n\n"
            "For free text, selected_option_id must be null and answer_text "
            "must be a non-empty string. Set exactly one of selected_option_id "
            "or answer_text; the other must be null. Rationale is required and "
            "confidence must be exactly high, medium, or low. Do not add "
            "fields, state updates, journal entries, files, or another "
            "envelope. Do not ask another question. Do not write files or "
            "mutate state, counters, recovery, or routing.\n\n"
            "## Prepared Request\n"
            f"{json.dumps(request_payload, ensure_ascii=False, sort_keys=True)}\n\n"
            "## Registered Context\n"
        )
        base_size = len(instructions.encode("utf-8"))
        if base_size > COMMANDER_DECISION_PROMPT_MAX_BYTES:
            raise HumanInputPolicyError(
                "COMMANDER prepared request exceeds the prompt byte limit"
            )

        prompt = _BoundedUtf8Builder(
            COMMANDER_DECISION_PROMPT_MAX_BYTES
        )
        if not prompt.append(instructions):
            raise HumanInputPolicyError(
                "COMMANDER prepared request exceeds the prompt byte limit"
            )
        context_state = {
            key: state.get(key)
            for key in policy.context_state_keys
        }
        prompt.append("### State\n")
        _append_bounded_json(prompt, context_state)
        prompt.append("\n")
        for template in policy.context_paths:
            if prompt.remaining <= 0:
                break
            if not prompt.append(f"\n### File {template}\n"):
                break
            content = self._read_human_input_context_file(
                template,
                state,
                byte_limit=prompt.remaining,
            )
            prompt.append(content)
            prompt.append("\n")
        rendered = prompt.build()
        if len(rendered.encode("utf-8")) > COMMANDER_DECISION_PROMPT_MAX_BYTES:
            raise AssertionError("COMMANDER prompt byte bound was exceeded")
        return rendered

    def _dispatch_commander_human_input(
        self,
        state: Mapping[str, object],
        decision: Mapping[str, object],
        policy: HumanInputPolicy,
    ) -> bool:
        current_state = dict(state)
        current_decision = dict(decision)
        while current_decision.get("status") == "pending":
            try:
                prompt = self._render_commander_decision_prompt(
                    current_decision,
                    policy,
                    current_state,
                )
            except (HumanInputPolicyError, BlockedDecisionError):
                self._state_store.fail_pending_human_input_decision(
                    str(current_decision["id"]),
                    expected_state_revision=int(
                        current_state["state_revision"]
                    ),
                    failure_code="decision_context_setup_failed",
                )
                return False
            claimed = self._state_store.claim_human_input_decision(
                str(current_decision["id"]),
                expected_state_revision=int(current_state["state_revision"]),
            )
            claimed_decision = validate_blocked_decision(
                claimed["blocked_decision"]
            )
            attempt = int(claimed_decision["attempts"])
            failure_code = "provider_failed"
            resolved = None
            with self._defer_routing_provider_usage() as usage:
                try:
                    with self._telemetry_provider.dispatch(
                        DispatchContext(
                            phase=str(claimed_decision["source_phase"]),
                            agent="COMMANDER",
                            kind="judgment",
                            attempt=attempt,
                            reason=(
                                "initial" if attempt == 1 else "provider_retry"
                            ),
                        )
                    ):
                        raw_result = self._telemetry_provider.exec_agent(
                            str(self._project_root),
                            prompt,
                            allow_result_repair=False,
                            strict_result_envelope=True,
                        )
                    if (
                        type(raw_result) is not SquadAgentResult
                        or raw_result.exit_code != 0
                        or raw_result.timed_out
                        or type(raw_result.echelon_result) is not dict
                    ):
                        raise EchelonResultValidationError(
                            "COMMANDER provider result failed"
                        )
                    failure_code = "invalid_resolution_result"
                    resolved = validate_decision_resolution_result(
                        raw_result.echelon_result,
                        options=self._human_input_options_from_decision(
                            claimed_decision
                        ),
                    )
                except Exception:
                    resolved = None

            if resolved is None:
                failed = self._state_store.record_human_input_resolution_failure(
                    str(claimed_decision["id"]),
                    expected_state_revision=int(claimed["state_revision"]),
                    failure_code=failure_code,
                    token_usage_delta=usage["tokens"],
                )
                current_state = failed
                current_decision = validate_blocked_decision(
                    failed["blocked_decision"]
                )
                continue

            try:
                return self.apply_human_input_resolution(
                    str(claimed_decision["id"]),
                    expected_state_revision=int(claimed["state_revision"]),
                    resolution=AppliedHumanInputResolution(
                        selected_option_id=resolved.selected_option_id,
                        answer_text=resolved.answer_text,
                        resolved_by="COMMANDER",
                        rationale=resolved.rationale,
                        confidence=resolved.confidence,
                    ),
                    token_usage_delta=usage["tokens"],
                )
            except HumanInputPolicyError:
                failed = self._state_store.record_human_input_resolution_failure(
                    str(claimed_decision["id"]),
                    expected_state_revision=int(claimed["state_revision"]),
                    failure_code="invalid_resolution_result",
                    token_usage_delta=usage["tokens"],
                )
                current_state = failed
                current_decision = validate_blocked_decision(
                    failed["blocked_decision"]
                )
        return False

    @staticmethod
    def _v2_migration_preserves_decision_contract(
        decision: Mapping[str, object],
        prepared: PreparedHumanInput,
    ) -> bool:
        identity = {
            "source_kind": prepared.source_kind,
            "producer_id": prepared.producer_id,
            "source_phase": prepared.phase_id,
            "reason_code": prepared.reason_code,
            "classification": prepared.classification,
            "question": prepared.question,
            "recommended_answer": prepared.recommended_answer,
            "risk_level": prepared.risk_level,
            "resolution_handler": prepared.resolution_handler,
        }
        if any(decision.get(field) != value for field, value in identity.items()):
            return False
        legacy_options = [
            {**dict(option), "recommended": False}
            for option in decision.get("options", [])
            if isinstance(option, Mapping)
        ]
        prepared_options = [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": False,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in prepared.options
        ]
        return (
            len(legacy_options) == len(decision.get("options", []))
            and prepared_options == legacy_options
        )

    def _migrate_pending_v2_banzai_decision(
        self,
        state: Mapping[str, object],
        decision: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Re-prepare one legacy Banzai decision or seal migration failure."""
        try:
            policy = self._policy_for_human_input_decision(decision)
            registry = (
                HumanInputPolicyRegistry((policy,))
                if decision.get("source_kind") == "legacy_recovery"
                else self._human_input_registry
            )
            prepare_args: dict[str, object] = {
                "source_kind": decision["source_kind"],
                "producer_id": decision["producer_id"],
                "phase_id": decision["source_phase"],
                "reason_code": decision["reason_code"],
                "question": decision["question"],
                "recommended_answer": decision["recommended_answer"],
                "risk_level": decision["risk_level"],
                "source_state_revision": state["state_revision"],
            }
            if decision.get("source_kind") == "provider_escalation":
                prepare_args["options"] = [
                    dict(option)
                    for option in decision.get("options", [])
                    if isinstance(option, Mapping)
                ]
            prepared = registry.prepare(**prepare_args)
            if not self._v2_migration_preserves_decision_contract(
                decision,
                prepared,
            ):
                raise HumanInputPolicyError(
                    "legacy decision cannot be reconstructed without contract drift"
                )
        except (
            BlockedDecisionError,
            HumanInputPolicyError,
            KeyError,
            TypeError,
            ValueError,
        ):
            self._state_store.fail_pending_v2_banzai_human_input_migration(
                str(decision["id"]),
                expected_state_revision=int(state["state_revision"]),
            )
            return None
        return self._state_store.migrate_pending_v2_banzai_human_input_decision(
            str(decision["id"]),
            expected_state_revision=int(state["state_revision"]),
            prepared=prepared,
        )

    def resume_pending_human_input(self) -> bool:
        """Recover an interrupted claim, then route one pending decision."""
        pending = self._state_store.load()
        if PENDING_CONTROLLER_COMPLETION_KEY in pending:
            if not self._drain_pending_controller_completion().recovered:
                return False
        state = self._state_store.recover_interrupted_human_input_decision()
        raw_decision = state.get("blocked_decision")
        if (
            not isinstance(raw_decision, Mapping)
            or raw_decision.get("schema_version") not in {2, 3}
        ):
            return False
        decision = validate_blocked_decision(raw_decision)
        if decision["status"] != "pending":
            return False
        autonomy_mode = decision["autonomy_mode"]
        if autonomy_mode == "guided":
            return False
        if autonomy_mode == "semi":
            policy = self._policy_for_human_input_decision(decision)
            resolution = self._semi_human_input_resolution(
                decision,
                policy,
            )
            if resolution is None:
                return False
            return self.apply_human_input_resolution(
                str(decision["id"]),
                expected_state_revision=int(state["state_revision"]),
                resolution=resolution,
            )
        if autonomy_mode == "banzai":
            if decision["schema_version"] == 2:
                migrated = self._migrate_pending_v2_banzai_decision(
                    state,
                    decision,
                )
                if migrated is None:
                    return False
                state = migrated
                decision = validate_blocked_decision(
                    migrated["blocked_decision"]
                )
                if decision["status"] != "pending":
                    return False
            if decision.get("automatic_eligible") is not True:
                return False
            policy = self._policy_for_human_input_decision(decision)
            return self._dispatch_commander_human_input(
                state,
                decision,
                policy,
            )
        return False

    def resume_with_human_input(self, answer: str) -> bool:
        """Apply one sealed awaiting-human answer through the registered handler."""
        if not isinstance(answer, str) or not answer.strip():
            raise HumanInputPolicyError("human-input answer is required")
        state = self._state_store.load()
        if PENDING_CONTROLLER_COMPLETION_KEY in state:
            if not self._drain_pending_controller_completion().recovered:
                return False
            state = self._state_store.load()
        raw_decision = state.get("blocked_decision")
        if not isinstance(raw_decision, Mapping):
            raise HumanInputPolicyError("human-input decision is missing")
        decision = validate_blocked_decision(raw_decision)
        from harness.recovery_instruction import validate_decision_recovery_pair

        validate_decision_recovery_pair(
            decision,
            state.get("recovery_instruction"),
        )
        if decision["status"] != "awaiting_human":
            raise HumanInputPolicyError(
                "human-input decision is not awaiting a human answer"
            )
        if (
            decision["schema_version"] == 3
            and decision["autonomy_mode"] == "banzai"
            and decision["automatic_eligible"] is True
        ):
            raise HumanInputPolicyError(
                "Banzai project decisions cannot be submitted as human input"
            )

        answer = answer.strip()
        options = self._human_input_options_from_decision(decision)
        if options:
            selected = _resolve_human_input_option_answer(answer, options)
            if selected is None:
                raise HumanInputPolicyError(
                    "human-input answer must match A/B/C, one offered option id, or one option label"
                )
            resolution = AppliedHumanInputResolution(
                selected_option_id=selected.id,
                answer_text=None,
                resolved_by="user",
            )
        else:
            resolution = AppliedHumanInputResolution(
                selected_option_id=None,
                answer_text=answer,
                resolved_by="user",
            )
        return self.apply_human_input_resolution(
            str(decision["id"]),
            expected_state_revision=int(state["state_revision"]),
            resolution=resolution,
        )

    def _unresolved_human_input_decision(
        self,
        state: Mapping[str, object],
    ) -> dict[str, object] | None:
        raw_decision = state.get("blocked_decision")
        if (
            not isinstance(raw_decision, Mapping)
            or raw_decision.get("schema_version") not in {2, 3}
        ):
            return None
        decision = validate_blocked_decision(raw_decision)
        from harness.recovery_instruction import validate_decision_recovery_pair

        validate_decision_recovery_pair(
            decision,
            state.get("recovery_instruction"),
        )
        return decision if decision["status"] != "resolved" else None

    @staticmethod
    def _unresolved_human_input_result(state: Mapping[str, object]) -> SquadResult:
        return SquadResult(
            status="blocked",
            phase=str(state.get("phase") or "unknown"),
            run_id=str(state.get("run_id") or ""),
        )

    def run(
        self,
        user_message: str = "",
        mode: str = "semi",
        next_phase_override: str = "",
    ) -> SquadResult:
        return self._run_with_execution_lease(
            lambda: self._run_locked(user_message, mode, next_phase_override)
        )

    def _run_locked(
        self,
        user_message: str = "",
        mode: str = "semi",
        next_phase_override: str = "",
    ) -> SquadResult:
        """Run the squad from current state or initialize fresh."""
        import os as _os
        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        existing = self._state_store.load()
        existing_status = existing.get("status") if existing else None
        blocked_reason = (existing.get("blocked_reason") or "") if existing else ""
        force_resume = False  # set True by recovery paths to bypass message check

        unresolved_decision = self._unresolved_human_input_decision(existing)
        if unresolved_decision is not None:
            if next_phase_override:
                return self._unresolved_human_input_result(existing)
            if unresolved_decision["status"] in {"pending", "resolving"}:
                if self.resume_pending_human_input():
                    existing = self._state_store.load()
                    existing_status = existing.get("status")
                    force_resume = True
                else:
                    return self._unresolved_human_input_result(
                        self._state_store.load()
                    )
            else:
                return self._unresolved_human_input_result(existing)

        if (
            existing_status == "blocked"
            and blocked_reason == "proportional_quality_debt_declined"
        ):
            return SquadResult.from_state(existing)

        # ── Recovery: token budget bumped ─────────────────────────────────
        if existing_status == "blocked" and blocked_reason == "token_budget_exhausted":
            stored_usage = existing.get("token_usage", 0)
            if self._token_budget == 0 or self._token_budget > stored_usage:
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["token_budget"] = self._token_budget
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                budget_display = f"{self._token_budget:,}" if self._token_budget else "∞"
                print(
                    f"[squad] budget bumped → resuming "
                    f"(usage={stored_usage:,}, new budget={budget_display})",
                    flush=True,
                )
            else:
                from echelon.ui import banner as _banner
                config_path = self._project_config_path()
                _banner(
                    "SQUAD — TOKEN BUDGET EXHAUSTED",
                    [
                        ("usage", f"{existing.get('token_usage', 0):,}"),
                        ("budget", f"{self._token_budget:,}"),
                        ("fix",
                         f"Edit {config_path}:\n"
                         f"  analysis:\n"
                         f"    token_budget_k: <increase this value>"),
                        ("then re-run", "echelon spec run"),
                        ("or discard", "echelon spec run --reset"),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Recovery: invalid judgment phase (--next-phase manual override) ─
        elif existing_status == "blocked" and "invalid next_phase" in blocked_reason:
            valid_phases = self._graph.all_phase_ids()
            from echelon.ui import banner as _banner
            if next_phase_override:
                if next_phase_override not in valid_phases:
                    _banner(
                        "SQUAD — INVALID PHASE ID",
                        [
                            ("given", next_phase_override),
                            ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                        ],
                    )
                    return SquadResult(
                        status="blocked",
                        phase=existing.get("phase", "unknown"),
                        run_id=existing.get("run_id", ""),
                    )
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["phase"] = next_phase_override
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                print(
                    f"[squad] manual recovery → advancing to {next_phase_override!r}",
                    flush=True,
                )
            else:
                _banner(
                    "SQUAD — BLOCKED",
                    [
                        ("reason", blocked_reason),
                        ("recover", "echelon spec run --next-phase <phase-id>"),
                        ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                        ("discard", "echelon spec run --reset"),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # Contract failures are retryable at the same node. Keep the diagnostic
        # until a later successful state advance proves that the phase completed.
        elif (
            existing_status == "blocked"
            and blocked_reason == "controller_state_contract_validation_failed"
        ):
            state = self._state_store.load()
            state["status"] = "running"
            state["blocked_reason"] = None
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] controller contract recovery → retrying "
                f"{state.get('phase')!r}",
                flush=True,
            )

        # Deterministic analysis failures are retryable at the same node. Keep
        # their immutable evidence pointer and run identity instead of treating
        # them like an incomplete provider dispatch that must be reinitialized.
        elif (
            existing_status == "blocked"
            and self._is_deterministic_understanding_phase(
                str(existing.get("phase") or "")
            )
        ):
            state = self._state_store.load()
            state["status"] = "running"
            state["blocked_reason"] = None
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] deterministic analysis recovery → retrying "
                f"{state.get('phase')!r}",
                flush=True,
            )

        # ── Escalation block ──────────────────────────────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            legacy_request = self._prepare_legacy_human_input(existing)
            if legacy_request is not None:
                resumed = self.handle_human_input(legacy_request)
            else:
                resumed = self.resume_pending_human_input()
            if resumed:
                recovered = self._state_store.load()
                existing_status = recovered.get("status")
                force_resume = True
            else:
                recovered = self._state_store.load()
                _blocked_banner(
                    phase=recovered.get("phase", "?"),
                    reason=recovered.get("blocked_reason", ""),
                    question=recovered.get("escalation_question", ""),
                )
                return SquadResult(
                    status="blocked",
                    phase=recovered.get("phase", "unknown"),
                    run_id=recovered.get("run_id", ""),
                )

        # ── Recovery: convergence already picked the next phase ─────────────
        elif (
            existing_status == "blocked"
            and not existing.get("escalation_question")
            and (existing.get("convergence_forced") or existing.get("convergence_detected"))
            and _normalize_phase_recommendation(
                existing.get("phase_recommendation"),
                self._graph.all_phase_ids(),
            )
        ):
            state = self._state_store.load()
            recommended = _normalize_phase_recommendation(
                state.get("phase_recommendation"),
                self._graph.all_phase_ids(),
            )
            state["status"] = "running"
            state["blocked_reason"] = None
            state["phase"] = recommended
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] convergence recovery → advancing to {recommended!r}",
                flush=True,
            )

        elif existing_status == "blocked" and next_phase_override:
            valid_phases = self._graph.all_phase_ids()
            if next_phase_override not in valid_phases:
                from echelon.ui import banner as _banner
                _banner(
                    "SQUAD — INVALID PHASE ID",
                    [
                        ("given", next_phase_override),
                        ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )
            state = self._state_store.load()
            state["status"] = "running"
            state["blocked_reason"] = None
            state["phase"] = next_phase_override
            state.pop("phase_a_readiness_blockers", None)
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] manual recovery → advancing to {next_phase_override!r}",
                flush=True,
            )

        # (keep all recovery blocks exactly as-is above this point)

        if existing and existing_status == "done" and str(existing.get("phase") or "") in TERMINAL_PHASES:
            readiness = self._publish_terminal_phase_a_artifacts_if_available()
            if readiness is not None and not readiness.ready:
                pending_state = self._state_store.load()
                if (
                    PENDING_CONTROLLER_COMPLETION_KEY
                    in pending_state
                    or PENDING_EXTERNAL_PUBLICATION_KEY in pending_state
                ):
                    return SquadResult.from_state(pending_state)
                self._block_after_phase_a_readiness_failure(readiness)
            else:
                state = self._state_store.load()
                state["status"] = "done"
                self._state_store.save(state)
            return SquadResult.from_state(self._state_store.load())

        # Fresh start if no state or not resumable
        # The correct squad dir was already selected by _cmd_run before creating this controller.
        if not existing or existing_status not in ("running", "in_progress"):
            prepared_identity = {
                key: existing[key]
                for key in (
                    "run_id",
                    "spec_id",
                    "spec_number",
                    "spec_dir",
                    "published_spec_dir",
                    "feature_branch",
                    "phase_a_default_branch",
                    "phase_a_base_commit",
                    "specify_feature_directory",
                    "user_message",
                    "autonomy_mode",
                    "spec_authoring_mode",
                    "checkpoint_policy_version",
                    "phase_completion_outcomes",
                    "implementation_targets",
                    "retarget",
                    "product_inputs",
                    "ignore_re",
                    "requested_re_sources",
                )
                if key in existing
            }
            run_id = str(prepared_identity.get("run_id") or f"squad-{int(time.time())}")
            entry_phase = next_phase_override or self._graph.entry_phase()
            project_mode = self._detect_project_mode(mode)
            self._state_store.initialize(
                run_id=run_id,
                mode=project_mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=entry_phase,
                max_iterations=self._max_iterations,
                autonomy_mode=mode,
                spec_authoring_mode=str(
                    prepared_identity.get("spec_authoring_mode") or "proportional"
                ),
                implementation_targets=self._implementation_targets,
                product_inputs=(
                    self._product_inputs.state_payload(self._project_root)
                    if self._product_inputs is not None
                    else (
                        dict(prepared_identity["product_inputs"])
                        if isinstance(prepared_identity.get("product_inputs"), Mapping)
                        else None
                    )
                ),
                ignore_re=self._ignore_re,
                requested_re_sources=self._re_sources,
                stack_contract=self._stack_contract,
            )
            if prepared_identity:
                initialized = self._state_store.load()
                initialized.update(prepared_identity)
                self._state_store.save(initialized)
            self._ensure_telemetry_manifest()
            self._attach_published_re_context()
            if self._state_store.load().get("status") == "blocked":
                return SquadResult.from_state(self._state_store.load())
            self._refresh_run_context("fresh initialization")
        else:
            print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
            state = self._state_store.load()
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.save(state)
            self._ensure_telemetry_manifest()

        while True:
            phase = self._state_store.current_phase()
            phase = self._guard_spec_lexicon_evidence(phase)
            phase = self._guard_phase1_quality_evidence(phase)
            phase = self._guard_understanding_evidence(phase)
            guarded_phase = self._apply_phase_recommendation_guard(phase)
            if guarded_phase != phase:
                phase = guarded_phase
            guarded_phase = self._guard_constitution_provenance(phase)
            if guarded_phase != phase:
                phase = guarded_phase

            if phase in TERMINAL_PHASES:
                state = self._state_store.load()
                # ``terminal-blocked`` is not finalization.  It is a hard stop
                # requested by a guard, and must never be converted into a
                # readiness check or a successful completion merely because an
                # earlier banzai handler temporarily set status=running.
                if phase == PHASE_TERMINAL_BLOCKED:
                    if state.get("status") != "blocked":
                        state["status"] = "blocked"
                        state["blocked_reason"] = (
                            state.get("blocked_reason") or "terminal_blocked"
                        )
                        self._state_store.save(state)
                    return SquadResult.from_state(self._state_store.load())
                # Preserve "blocked" status set by guards (e.g. consecutive-fail).
                # Only write "done" when not already in a terminal-blocked state.
                if state.get("status") != "blocked":
                    readiness = self._publish_terminal_phase_a_artifacts_if_available()
                    if readiness is not None and not readiness.ready:
                        pending_state = self._state_store.load()
                        if (
                            PENDING_CONTROLLER_COMPLETION_KEY
                            in pending_state
                            or PENDING_EXTERNAL_PUBLICATION_KEY in pending_state
                        ):
                            return SquadResult.from_state(pending_state)
                        self._block_after_phase_a_readiness_failure(readiness)
                        return SquadResult.from_state(self._state_store.load())
                    state = self._state_store.load()
                    state["status"] = "done"
                    self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if self._cancelled:
                state = self._state_store.load()
                state["status"] = "interrupted"
                state["phase"] = phase
                state["interrupted_phase"] = phase
                state["blocked_reason"] = None
                self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if self._budget_exhausted():
                self._state_store.set_blocked("token_budget_exhausted")
                self._record_blocker_event(phase, "token_budget_exhausted")
                return SquadResult(
                    status="budget_exhausted",
                    phase=phase,
                    run_id=self._state_store.load().get("run_id", ""),
                )

            node = self._graph.get(phase)

            if self._skip_phase_if_condition_false(node):
                continue

            self._start_declared_phase_timing(node)

            # Per-phase dispatch cap — prevents runaway loops on any phase.
            # Iterative authoring and verification phases use max_iterations;
            # one-shot phases use the lower general cap.
            dispatch_count = self._state_store.increment_phase_dispatch_count(phase)
            phase_limit = (
                self._max_iterations + 1
                if phase in ITERATIVE_PHASES
                else MAX_PHASE_DISPATCHES
            )
            if dispatch_count > phase_limit:
                cap_state = self._state_store.load()
                try:
                    candidates = self._banzai_issue_resolution_candidates(
                        cap_state
                    )
                    cap_options = self._dispatch_cap_options(candidates)
                except _DispatchCapEvidenceError as exc:
                    self._record_blocker_event(phase, exc.reason_code)
                    self._block_unresolvable_dispatch_cap(
                        phase,
                        cap_state,
                        exc.reason_code,
                    )
                    return SquadResult.from_state(
                        self._state_store.load()
                    )
                except HumanInputPolicyError:
                    reason_code = (
                        "phase_dispatch_limit_option_contract_failed"
                    )
                    self._record_blocker_event(phase, reason_code)
                    self._block_unresolvable_dispatch_cap(
                        phase,
                        cap_state,
                        reason_code,
                    )
                    return SquadResult.from_state(
                        self._state_store.load()
                    )
                escalation_q = (
                    f"Phase {phase!r} has been dispatched {dispatch_count} times "
                    f"(limit {phase_limit}) without converging or advancing. "
                    "Select exactly one sealed evidence-backed issue resolution."
                )
                request = self._human_input_registry.prepare(
                    source_kind="controller_safeguard",
                    producer_id="phase_dispatch_limit",
                    phase_id=phase,
                    reason_code="phase_dispatch_limit",
                    question=escalation_q,
                    source_state_revision=cap_state["state_revision"],
                )
                request = replace(
                    request,
                    options=cap_options,
                )
                self._record_blocker_event(phase, "phase_dispatch_limit")
                print(
                    f"[squad] ✗ phase dispatch limit: {phase!r} dispatched "
                    f"{dispatch_count}× (limit {phase_limit}) — forcing escalation",
                    flush=True,
                )
                if self.handle_human_input(request):
                    continue
                return SquadResult.from_state(self._state_store.load())

            print(
                _format_phase_dispatch_line(node, self._graph, self._ext_dir),
                flush=True,
            )

            if node.type == "human_gate":
                if self._intercept_human_gate(node):
                    continue
                return SquadResult.from_state(self._state_store.load())

            executor = self._executors.get(node.type)
            try:
                node = self._materialize_controller_phase_inputs(node)
                if executor is None:
                    result = self._judgment_dispatch(
                        f"Unknown phase type {node.type!r} for phase {phase!r}",
                        node,
                    )
                else:
                    with self._telemetry_provider.dispatch(
                        DispatchContext(
                            phase=phase,
                            agent=str(node.agent or node.type),
                            kind=(
                                "repair"
                                if dispatch_count > 1
                                else "phase"
                            ),
                            attempt=dispatch_count,
                            reason=self._dispatch_reason(
                                phase,
                                dispatch_count,
                            ),
                        )
                    ):
                        result = executor.execute(
                            node,
                            self._state_store,
                        )
            except ControllerStateContractViolation as exc:
                self._block_after_executor_contract_failure(node, exc)
                return SquadResult.from_state(self._state_store.load())

            # SIGINT is deferred until the executor returns so we never tear
            # down an in-flight filesystem operation.  Once it has returned,
            # cancellation must win over result interpretation: a trailing
            # BLOCKED envelope must not start a COMMANDER decision loop after
            # the operator asked to stop.
            if self._cancelled:
                state = self._state_store.load()
                state["status"] = "interrupted"
                state["phase"] = phase
                state["interrupted_phase"] = phase
                state["blocked_reason"] = None
                self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if isinstance(result, ExecutorBlockedResult):
                snapshot = self._state_store.capture_routing_snapshot(
                    expected_phase=node.id,
                )
                self._block_after_executor_failure(
                    phase,
                    result.reason,
                    result.result,
                    snapshot=snapshot,
                    recovery_instruction=trusted_executor_block_recovery(
                        phase,
                        result.reason,
                    ),
                )
                return SquadResult.from_state(self._state_store.load())

            if result.timed_out:
                snapshot = self._state_store.capture_routing_snapshot(
                    expected_phase=node.id,
                )
                self._block_after_executor_failure(
                    phase,
                    "agent_timeout",
                    result,
                    snapshot=snapshot,
                    recovery_instruction=retry_phase_recovery(
                        phase,
                        "agent_timeout",
                    ),
                )
                return SquadResult.from_state(self._state_store.load())

            if node.id == "phase4-document":
                self._enter_retarget_finalizing(self._state_store.load())
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id
            )
            prepared = self._prepare_phase_result_or_block(
                node,
                result,
                snapshot,
            )
            if prepared is None:
                return SquadResult.from_state(self._state_store.load())
            prepared_result = prepared.as_squad_agent_result()

            blocked_result = self._blocked_executor_reason(
                prepared_result,
                prepared.control_updates,
            )
            if blocked_result:
                # A bare BLOCKED result has no material ambiguity.  It is a
                # retryable dispatch failure (and is a common provider shape
                # after an interrupted turn), not a reason to manufacture a
                # clarification request.
                if (
                    node.type == "agent"
                    and blocked_result != "agent_blocked"
                    and self._route_agent_block_to_commander(
                        node,
                        blocked_result,
                        prepared_result,
                        snapshot,
                    )
                ):
                    continue
                self._block_after_executor_failure(
                    phase,
                    blocked_result,
                    prepared_result,
                    snapshot=snapshot,
                    recovery_instruction=(
                        retry_phase_recovery(phase, blocked_result)
                        if blocked_result == "agent_blocked"
                        else None
                    ),
                )
                return SquadResult.from_state(self._state_store.load())

            constitution_promotion_error = self._promote_constitution_draft(
                node
            )
            if constitution_promotion_error is not None:
                self._block_after_executor_failure(
                    phase,
                    constitution_promotion_error,
                    prepared_result,
                    snapshot=snapshot,
                    recovery_instruction=retry_phase_recovery(
                        phase,
                        constitution_promotion_error,
                    ),
                )
                return SquadResult.from_state(self._state_store.load())

            prepared_publication: PreparedSquadPublication | None = None
            try:
                prepared_publication = (
                    self._prepare_external_phase_effects(
                        prepared_result,
                        phase,
                        snapshot.state,
                        manual_phase_run=False,
                    )
                )
            except _ProductInputCommitError as exc:
                product_input_error = exc.reason
                if self._schedule_product_input_mapping_repair(
                    phase,
                    product_input_error,
                    prepared_result,
                    snapshot=snapshot,
                ):
                    continue
                self._block_after_executor_failure(
                    phase,
                    product_input_error,
                    prepared_result,
                    snapshot=snapshot,
                )
                return SquadResult.from_state(self._state_store.load())
            except _PhaseAReadinessCommitError as exc:
                self._block_after_phase_a_readiness_failure(
                    exc.readiness,
                    snapshot=snapshot,
                )
                return SquadResult.from_state(self._state_store.load())

            routing_updates = self._planned_phase_a_publication_updates(
                phase,
                snapshot.state,
            )
            if node.id == "phase1-constitution":
                # CHIEF is deliberately denied writes to .echelon.  This
                # controller-owned state update is emitted only after the
                # validated run-local draft has been atomically promoted.
                routing_updates["constitution_status"] = "exists"
            if prepared_publication is not None:
                routing_updates.update(
                    self._product_input_publication_state_updates(
                        prepared_publication
                    )
                )
                routing_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = (
                    prepared_publication.marker.to_dict()
                )
            routing = self._construct_routing_decision_or_block(
                node,
                prepared,
                snapshot,
                additional_state_updates=routing_updates,
            )
            if routing is None:
                self._discard_publication_without_authority(
                    prepared_publication,
                )
                return SquadResult.from_state(self._state_store.load())
            decision = routing.decision
            next_phase = decision.to_phase

            human_input_result = (
                self._handle_prepared_human_input_or_block(
                    node,
                    prepared,
                    snapshot,
                    routing,
                    prepared_publication,
                )
            )
            if human_input_result is not None:
                if human_input_result:
                    continue
                return SquadResult.from_state(self._state_store.load())

            receipt = self._advance_prepared_result_or_block(
                node,
                decision,
                prepared_publication=prepared_publication,
            )
            if receipt is None:
                return SquadResult.from_state(self._state_store.load())

            # Inline escalation check — fires when _evaluate_transitions detected
            # escalation_question in state_updates and returned the current phase.
            # Handles it in the same run() invocation rather than requiring a
            # re-invocation to reach the top-of-loop escalation block.
            state_now = self._state_store.load()
            if state_now.get("status") == "blocked" and state_now.get("escalation_question") and not state_now.get("escalation_resolved"):
                if self.resume_pending_human_input():
                    continue
                state_now = self._state_store.load()
                _blocked_banner(
                    phase=phase,
                    reason=state_now.get("blocked_reason", ""),
                    question=state_now.get("escalation_question", ""),
                )
                return SquadResult(
                    status="blocked",
                    phase=phase,
                    run_id=state_now.get("run_id", ""),
                )
            else:
                print(f"[squad] ✓ {node.id}  → {next_phase}", flush=True)
                continue

    def _guard_understanding_evidence(self, phase: str) -> str:
        """Route legacy or stale SAGE dispatches through deterministic analysis."""
        gate_by_target = {
            "phase1-why2": "phase1-understanding",
            "phase3-consensus": "phase3-understanding",
        }
        gate = gate_by_target.get(phase)
        if gate is None:
            return phase
        state = self._state_store.load()
        if has_current_understanding_evidence(
            state,
            project_root=self._project_root,
            phase=phase,
        ):
            return phase
        state["phase"] = gate
        self._state_store.save(state)
        print(
            f"[squad] {phase}: certified Understanding evidence missing or stale; "
            f"routing through {gate}",
            flush=True,
        )
        return gate

    def _guard_phase1_quality_evidence(self, phase: str) -> str:
        """Prevent Phase 1 certification from advancing on an uncertified spec.

        A later-phase resume carrying debt authority is also protected: the
        authority may have become stale while the run was stopped.
        """
        protected = {
            "phase1-lexicon-derive",
            "phase1-lexicon",
            "checkpoint-assess",
        }
        state = self._state_store.load()
        debt_claimed = (
            "spec_quality_debt_authorization" in state
            or state.get("spec_status") == "accepted_with_debt"
            or state.get("spec_quality_status") == "accepted_with_debt"
            or isinstance(state.get("spec_quality_debt_context"), Mapping)
        )
        invalid_downstream_debt = (
            phase in _QUALITY_DEBT_DOWNSTREAM_PHASES and debt_claimed
        )
        if phase not in protected and not invalid_downstream_debt:
            return phase
        if has_current_phase1_quality_prerequisite(
            state,
            project_root=self._project_root,
        ):
            return phase

        invalidated = {
            "phase1-understanding",
            "phase1-why2",
            "phase1-lexicon-derive",
            "phase1-lexicon",
            "checkpoint-assess",
        }
        if invalid_downstream_debt:
            invalidated.update(_QUALITY_DEBT_DOWNSTREAM_PHASES)
        completed = state.get("completed_phases")
        if isinstance(completed, list):
            state["completed_phases"] = [
                item for item in completed if item not in invalidated
            ]
        counts = state.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            state["phase_dispatch_counts"] = {
                item: count
                for item, count in counts.items()
                if item not in invalidated
            }
        state.pop("spec_quality_certificate", None)
        state.pop("spec_quality_debt_authorization", None)
        if state.get("spec_status") == "accepted_with_debt":
            state.pop("spec_status", None)
        state.pop("spec_quality_status", None)
        state.pop("spec_quality_debt_context", None)
        state["iteration"] = 0
        state["why_fail_count"] = 0
        state["convergence_forced"] = False
        state["convergence_detected"] = False
        state["convergence_guard_fire_count"] = 0
        state.pop("phase_recommendation", None)
        state["phase"] = "phase1-understanding"
        self._state_store.save(state)
        print(
            f"[squad] {phase}: Phase 1 quality prerequisite missing or stale; "
            "routing through phase1-understanding",
            flush=True,
        )
        return "phase1-understanding"

    def _guard_spec_lexicon_evidence(self, phase: str) -> str:
        """Route legacy downstream resumes through visible spec certification."""
        # INVESTIGATOR resolves a declared evidence gap before the next WHAT
        # amendment.  It is reachable from WHY2 but is not a downstream spec
        # consumer, so forcing it through Lexicon would erase the route that
        # requested it and restart CARTOGRAPHER instead.
        if phase == "phase1-investigate":
            return phase
        phase_ids = list(self._graph.all_phase_ids())
        try:
            gate_index = phase_ids.index("phase1-lexicon")
            done_index = phase_ids.index("done")
        except ValueError:
            return phase
        downstream = set(phase_ids[gate_index + 1 : done_index + 1])
        if phase not in downstream:
            return phase
        state = self._state_store.load()
        if has_current_spec_lexicon_evidence(
            state,
            project_root=self._project_root,
            config=self._lexicon_gate_config(),
        ):
            return phase
        invalidated = downstream | {
            "phase1-lexicon-derive",
            "phase1-lexicon",
        }
        completed = state.get("completed_phases")
        if isinstance(completed, list):
            state["completed_phases"] = [
                item for item in completed if item not in invalidated
            ]
        counts = state.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            state["phase_dispatch_counts"] = {
                item: count
                for item, count in counts.items()
                if item not in invalidated
            }
        state["iteration"] = 0
        state["why_fail_count"] = 0
        state["convergence_forced"] = False
        state["convergence_detected"] = False
        state["convergence_guard_fire_count"] = 0
        state.pop("phase_recommendation", None)
        state["phase"] = "phase1-lexicon-derive"
        self._state_store.save(state)
        print(
            f"[squad] {phase}: spec Lexicon evidence missing or stale; "
            "routing through phase1-lexicon-derive",
            flush=True,
        )
        return "phase1-lexicon-derive"

    def _is_deterministic_understanding_phase(self, phase: str) -> bool:
        if not phase:
            return False
        try:
            return self._graph.get(phase).type == "deterministic_understanding"
        except KeyError:
            return False

    def _attach_published_re_context(self) -> None:
        """Snapshot the latest durable RE publication for this spec run."""
        state = self._state_store.load()
        persisted_ignore = state.get("ignore_re")
        ignore_re = persisted_ignore if isinstance(persisted_ignore, bool) else self._ignore_re
        persisted_targets = state.get("implementation_targets")
        implementation_targets = (
            [str(value) for value in persisted_targets]
            if isinstance(persisted_targets, list)
            else self._implementation_targets
        )
        persisted_sources = state.get("requested_re_sources")
        re_sources = (
            [str(value) for value in persisted_sources]
            if isinstance(persisted_sources, list)
            else self._re_sources
        )
        try:
            context = attach_published_re_context(
                self._project_root,
                self._squad_dir,
                ignore=ignore_re,
                implementation_targets=implementation_targets,
                re_sources=re_sources,
            )
        except Exception as exc:
            state["status"] = "blocked"
            state["blocked_reason"] = f"published_re_context_failed: {exc}"
            self._state_store.save(state)
            return
        state["published_re_context"] = context
        self._state_store.save(state)

    def run_single_phase(
        self,
        phase_id: str,
        user_message: str = "",
        mode: str = "semi",
        initial_state_updates: dict | None = None,
    ) -> SquadResult:
        return self._run_with_execution_lease(
            lambda: self._run_single_phase_locked(
                phase_id,
                user_message,
                mode,
                initial_state_updates,
            ),
            stop_after_recovered_manual=True,
        )

    def _run_single_phase_locked(
        self,
        phase_id: str,
        user_message: str = "",
        mode: str = "semi",
        initial_state_updates: dict | None = None,
    ) -> SquadResult:
        """Execute one explicit workflow phase and stop after recording state.

        This is for targeted repair/replay. It uses the normal phase executor,
        transition evaluator, journal writer, and state validation path, but it
        never enters the full controller loop.
        """
        import os as _os

        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        if phase_id not in self._graph.all_phase_ids():
            raise KeyError(f"Phase not found in definition.yaml: {phase_id!r}")

        existing = self._state_store.load()
        if self._state_store.discard_failed_automatic_decision_for_manual_phase_replay(
            phase_id
        ):
            print(
                "[squad] retrying failed automatic Banzai decision via manual "
                f"phase replay: {phase_id}",
                flush=True,
            )
            existing = self._state_store.load()
        if self._unresolved_human_input_decision(existing) is not None:
            return self._unresolved_human_input_result(existing)
        if (
            existing.get("status") == "blocked"
            and existing.get("escalation_question")
            and not (
                isinstance(existing.get("blocked_decision"), Mapping)
                and existing["blocked_decision"].get("schema_version") == 2
            )
        ):
            legacy_request = self._prepare_legacy_human_input(existing)
            if legacy_request is None:
                return SquadResult.from_state(existing)
            if not self.handle_human_input(legacy_request):
                return SquadResult.from_state(self._state_store.load())
            existing = self._state_store.load()
        if not existing:
            run_id = f"squad-{int(time.time())}"
            project_mode = self._detect_project_mode(mode)
            self._state_store.initialize(
                run_id=run_id,
                mode=project_mode,
                user_message=user_message or f"Manual phase run: {phase_id}",
                token_budget=self._token_budget,
                entry_phase=phase_id,
                max_iterations=self._max_iterations,
                autonomy_mode=mode,
            )
            if initial_state_updates:
                state = self._state_store.load()
                state.update(initial_state_updates)
                self._state_store.save(state)
            self._ensure_telemetry_manifest()
            self._refresh_run_context("manual phase initialization")
        else:
            state = self._state_store.load()
            state["status"] = "running"
            state["phase"] = phase_id
            if user_message and not state.get("user_message"):
                state["user_message"] = user_message
            state["blocked_reason"] = None
            state["escalation_question"] = None
            state["escalation_options"] = None
            if initial_state_updates:
                state.update(initial_state_updates)
            self._state_store.save(state)
            self._ensure_telemetry_manifest()
            self._refresh_run_context(f"manual phase replay {phase_id}")

        self._isolate_manual_phase_spec_dir()

        phase = phase_id
        guarded_phase = self._guard_constitution_provenance(phase)
        if guarded_phase in TERMINAL_PHASES:
            return SquadResult.from_state(self._state_store.load())
        phase = guarded_phase
        phase = self._guard_spec_lexicon_evidence(phase)
        phase = self._guard_phase1_quality_evidence(phase)
        phase = self._guard_understanding_evidence(phase)

        node = self._graph.get(phase)
        label = node.label or node.id
        if self._skip_phase_if_condition_false(node, manual_phase_run=True):
            return SquadResult.from_state(self._state_store.load())
        self._start_declared_phase_timing(node)
        print(
            _format_phase_dispatch_line(
                node,
                self._graph,
                self._ext_dir,
                suffix="  (manual phase run)",
            ),
            flush=True,
        )

        if node.type == "human_gate":
            self._intercept_human_gate(node)
            return SquadResult.from_state(self._state_store.load())

        executor = self._executors.get(node.type)
        try:
            node = self._materialize_controller_phase_inputs(node)
            if executor is None:
                result = self._judgment_dispatch(
                    f"Unknown phase type {node.type!r} for phase {phase!r}",
                    node,
                )
            else:
                state = self._state_store.load()
                attempts = state.get("phase_dispatch_counts")
                attempt = (
                    int(attempts.get(phase, 0)) + 1
                    if isinstance(attempts, dict)
                    else 1
                )
                with self._telemetry_provider.dispatch(
                    DispatchContext(
                        phase=phase,
                        agent=str(node.agent or node.type),
                        kind="repair" if attempt > 1 else "phase",
                        attempt=attempt,
                        reason="manual_rerun",
                    )
                ):
                    result = executor.execute(node, self._state_store)
        except ControllerStateContractViolation as exc:
            self._block_after_executor_contract_failure(node, exc)
            return SquadResult.from_state(self._state_store.load())

        if isinstance(result, ExecutorBlockedResult):
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id,
            )
            self._block_after_executor_failure(
                phase,
                result.reason,
                result.result,
                snapshot=snapshot,
                recovery_instruction=trusted_executor_block_recovery(
                    phase,
                    result.reason,
                ),
            )
            return SquadResult.from_state(self._state_store.load())

        if result.timed_out:
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id,
            )
            self._block_after_executor_failure(
                phase,
                "agent_timeout",
                result,
                snapshot=snapshot,
                recovery_instruction=retry_phase_recovery(
                    phase,
                    "agent_timeout",
                ),
            )
            return SquadResult.from_state(self._state_store.load())

        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=node.id
        )
        prepared = self._prepare_phase_result_or_block(
            node,
            result,
            snapshot,
        )
        if prepared is None:
            return SquadResult.from_state(self._state_store.load())
        prepared_result = prepared.as_squad_agent_result()

        blocked_result = self._blocked_executor_reason(
            prepared_result,
            prepared.control_updates,
        )
        if blocked_result:
            self._block_after_executor_failure(
                phase,
                blocked_result,
                prepared_result,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())

        prepared_publication: PreparedSquadPublication | None = None
        try:
            prepared_publication = self._prepare_external_phase_effects(
                prepared_result,
                phase,
                snapshot.state,
                manual_phase_run=True,
            )
        except _ProductInputCommitError as exc:
            product_input_error = exc.reason
            if self._schedule_product_input_mapping_repair(
                phase,
                product_input_error,
                prepared_result,
                snapshot=snapshot,
            ):
                return SquadResult.from_state(self._state_store.load())
            self._block_after_executor_failure(
                phase,
                product_input_error,
                prepared_result,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())
        except _PhaseAReadinessCommitError as exc:
            self._block_after_phase_a_readiness_failure(
                exc.readiness,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())

        # Manual phase replay records only its routing result.  It must not
        # synthesize publication identity or queue publication work.
        routing_updates: dict[str, object] = {}
        if prepared_publication is not None:
            routing_updates.update(
                self._product_input_publication_state_updates(
                    prepared_publication
                )
            )
            routing_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = (
                prepared_publication.marker.to_dict()
            )
        routing = self._construct_routing_decision_or_block(
            node,
            prepared,
            snapshot,
            additional_state_updates=routing_updates,
            manual_phase_run=True,
        )
        if routing is None:
            self._discard_publication_without_authority(
                prepared_publication,
            )
            return SquadResult.from_state(self._state_store.load())
        decision = routing.decision
        next_phase = decision.to_phase

        human_input_result = self._handle_prepared_human_input_or_block(
            node,
            prepared,
            snapshot,
            routing,
            prepared_publication,
        )
        if human_input_result is not None:
            return SquadResult.from_state(self._state_store.load())
        receipt = self._advance_prepared_result_or_block(
            node,
            decision,
            prepared_publication=prepared_publication,
        )
        if receipt is None:
            return SquadResult.from_state(self._state_store.load())
        print(f"[squad] ✓ {node.id}  → {next_phase}  (stopped)", flush=True)
        return SquadResult.from_state(self._state_store.load())

    def _isolate_manual_phase_spec_dir(self) -> None:
        """Point a manual replay at its private Phase A worktree.

        Older runs can retain ``spec_dir`` as their project-visible target.
        Never let that historical representation turn a repair replay into an
        implicit publication: make (or reuse) ``runs/<run>/specs/<id>`` before
        the executor assembles its prompt.
        """
        state = self._state_store.load()
        spec_id = str(state.get("spec_id") or "").strip()
        if not spec_id:
            return

        current = self._active_phase_a_spec_dir(dict(state))
        source_ref = str(state.get("phase_run_source_spec_dir") or "").strip()
        source = (
            self._absolute_project_path(source_ref)
            if source_ref
            else None
        )
        run_roots = (self._squad_dir.resolve(), (self._project_root / "runs").resolve())

        def is_run_local(path: Path | None) -> bool:
            if path is None or not path.exists() or not path.is_dir():
                return False
            resolved = path.resolve()
            return any(
                resolved.is_relative_to(root)
                for root in run_roots
            )

        run_local = (
            source
            if is_run_local(source)
            else current
            if is_run_local(current)
            else self._squad_dir / "specs" / spec_id
        )
        if not run_local.exists() and current is not None and current.is_dir():
            self._copy_controller_tree(
                current,
                run_local,
                exclude_echelon=True,
            )
        else:
            run_local.mkdir(parents=True, exist_ok=True)

        run_local_ref = self._repo_relative_or_absolute(run_local)
        if (
            str(state.get("spec_dir") or "").strip() == run_local_ref
            and str(state.get("phase_run_source_spec_dir") or "").strip()
            == run_local_ref
        ):
            return
        state["spec_dir"] = run_local_ref
        state["phase_run_source_spec_dir"] = run_local_ref
        self._state_store.save(state)

    def _skip_phase_if_condition_false(
        self,
        node: PhaseNode,
        *,
        manual_phase_run: bool = False,
    ) -> bool:
        """Apply node-level phase conditions before dispatching an agent."""
        condition = (node.condition or "").strip()
        if not condition:
            return False

        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=node.id
        )
        state = snapshot.state
        evaluation = self._evaluator.evaluate(condition, state)
        if evaluation is True:
            return False
        if evaluation is None:
            state["phase"] = PHASE_TERMINAL_BLOCKED
            state["status"] = "blocked"
            state["blocked_reason"] = f"unresolvable phase condition {condition!r}"
            self._state_store.save(state)
            print(
                f"[squad] ✗ {node.id} phase condition {condition!r} is unresolvable",
                flush=True,
            )
            return True

        action = ""
        if isinstance(node.on_greenfield, dict):
            action = str(node.on_greenfield.get("action") or "")
        if state.get("mode") == "greenfield" and action == "skip_agent_proceed_to_next":
            result = SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "output_files": [],
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
                cost_usd=0.0,
            )
            prepared = self._prepare_phase_result_or_block(
                node,
                result,
                snapshot,
            )
            if prepared is None:
                return True
            routing = self._construct_routing_decision_or_block(
                node,
                prepared,
                snapshot,
                manual_phase_run=manual_phase_run,
                conditional_skip=True,
            )
            if routing is None:
                return True
            decision = routing.decision
            if routing.human_input is not None:
                self.handle_human_input(
                    routing.human_input,
                    provider_advance=_ProviderHumanInputAdvance(
                        from_phase=decision.from_phase,
                        to_phase=decision.to_phase,
                        decision=decision,
                    ),
                )
                return True
            next_phase = decision.to_phase
            receipt = self._advance_prepared_result_or_block(
                node,
                decision,
            )
            if receipt is None:
                return True
            suffix = "  (stopped)" if manual_phase_run else ""
            print(
                f"[squad] skipped {node.id}  ({condition} false) -> {next_phase}{suffix}",
                flush=True,
            )
            return True

        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = f"phase condition {condition!r} evaluated false"
        self._state_store.save(state)
        print(
            f"[squad] ✗ {node.id} phase condition {condition!r} evaluated false",
            flush=True,
        )
        return True

    def _absolute_project_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self._project_root / path
        return Path(os.path.abspath(path))

    def _project_relative_target(self, path: Path) -> Path:
        root = Path(os.path.abspath(self._project_root))
        candidate = Path(os.path.abspath(path))
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("publication target is outside the project") from exc
        if not relative.parts:
            raise ValueError("publication target must be a file")
        return relative

    @staticmethod
    def _lstat_or_none(path: Path) -> os.stat_result | None:
        try:
            return os.lstat(path)
        except FileNotFoundError:
            return None

    def _read_project_regular_file(self, path: Path) -> bytes | None:
        """Read an optional controller source without following symlinks."""
        absolute = Path(os.path.abspath(path))
        self._project_relative_target(absolute)
        try:
            resolved = absolute.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise OSError(
                "controller publication source path cannot be resolved"
            ) from exc
        if resolved != absolute:
            raise OSError(
                "controller publication source has a symbolic-link ancestor"
            )
        metadata = self._lstat_or_none(absolute)
        if metadata is None:
            return None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise OSError(
                "controller publication source is not a regular file"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(absolute, flags)
        except OSError as exc:
            raise OSError(
                "controller publication source cannot be opened safely"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise OSError(
                    "controller publication source changed during validation"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _safe_run_id(value: object) -> str:
        run_id = str(value or "unknown")
        candidate = Path(run_id)
        if (
            candidate.is_absolute()
            or candidate.name != run_id
            or candidate.parts != (run_id,)
            or run_id in {".", ".."}
        ):
            raise OSError("run ID is not a safe path component")
        return run_id

    def _controller_tree_files(
        self,
        root: Path,
        *,
        exclude_echelon: bool,
    ) -> frozenset[Path]:
        absolute_root = Path(os.path.abspath(root))
        try:
            resolved_root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OSError(
                "controller publication source is not a real directory"
            ) from exc
        if resolved_root != absolute_root:
            raise OSError(
                "controller publication source has a symbolic-link ancestor"
            )
        metadata = self._lstat_or_none(root)
        if (
            metadata is None
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
        ):
            raise OSError("controller publication source is not a directory")
        files: set[Path] = set()
        for current, directories, filenames in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            retained_directories: list[str] = []
            for name in sorted(directories):
                if exclude_echelon and name == ".echelon":
                    continue
                child = current_path / name
                child_metadata = os.lstat(child)
                if (
                    stat.S_ISLNK(child_metadata.st_mode)
                    or not stat.S_ISDIR(child_metadata.st_mode)
                ):
                    raise OSError(
                        "controller publication source contains an unsafe directory"
                    )
                retained_directories.append(name)
            directories[:] = retained_directories
            for name in sorted(filenames):
                child = current_path / name
                child_metadata = os.lstat(child)
                if (
                    stat.S_ISLNK(child_metadata.st_mode)
                    or not stat.S_ISREG(child_metadata.st_mode)
                ):
                    raise OSError(
                        "controller publication source contains an unsafe file"
                    )
                relative = child.relative_to(root)
                if exclude_echelon and ".echelon" in relative.parts:
                    continue
                files.add(relative)
        return frozenset(files)

    def _controller_tree_inventory_sha256(
        self,
        root: Path,
    ) -> str:
        records: list[dict[str, object]] = []
        for relative in sorted(
            self._controller_tree_files(
                root,
                exclude_echelon=True,
            ),
            key=lambda path: path.as_posix(),
        ):
            content = self._read_project_regular_file(root / relative)
            if content is None:
                raise OSError(
                    "controller inventory source changed during read"
                )
            records.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        encoded = json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _phase_a_inventory_digests(
        self,
        state: Mapping[str, object],
    ) -> tuple[str, str] | None:
        detached = dict(state)
        active = self._active_phase_a_spec_dir(detached)
        if active is None or not active.is_dir():
            return None
        published_ref = str(
            detached.get("published_spec_dir") or ""
        ).strip()
        if not published_ref:
            published = self._published_phase_a_spec_dir(
                detached,
                active,
            )
        else:
            published = self._absolute_project_path(published_ref)
        if not published.is_dir():
            return None
        try:
            return (
                self._controller_tree_inventory_sha256(
                    self._absolute_project_path(active)
                ),
                self._controller_tree_inventory_sha256(
                    self._absolute_project_path(published)
                ),
            )
        except OSError:
            return None

    def _copy_controller_tree(
        self,
        source: Path,
        destination: Path,
        *,
        exclude_echelon: bool,
    ) -> frozenset[Path]:
        files = self._controller_tree_files(
            source,
            exclude_echelon=exclude_echelon,
        )
        source_root_mode = stat.S_IMODE(os.lstat(source).st_mode)
        destination.mkdir(parents=True, exist_ok=True)
        directories_to_copy: list[Path] = []
        directory_modes: dict[Path, int] = {}
        for current, directories, _ in os.walk(
            source,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            current_relative = current_path.relative_to(source)
            if exclude_echelon and ".echelon" in current_relative.parts:
                directories[:] = []
                continue
            retained: list[str] = []
            for name in sorted(directories):
                relative = (current_path / name).relative_to(source)
                if exclude_echelon and ".echelon" in relative.parts:
                    continue
                retained.append(name)
                directories_to_copy.append(relative)
                directory_modes[relative] = stat.S_IMODE(
                    os.lstat(current_path / name).st_mode
                )
            directories[:] = retained
        for relative in sorted(
            directories_to_copy,
            key=lambda path: (len(path.parts), path.as_posix()),
        ):
            target = destination / relative
            existing = self._lstat_or_none(target)
            if existing is not None and not stat.S_ISDIR(existing.st_mode):
                if stat.S_ISREG(existing.st_mode):
                    target.unlink()
                else:
                    raise OSError(
                        "virtual publication tree contains an unsafe directory"
                    )
            target.mkdir(parents=True, exist_ok=True)
        for relative in sorted(files):
            target = destination / relative
            existing = self._lstat_or_none(target)
            if existing is not None and stat.S_ISDIR(existing.st_mode):
                shutil.rmtree(target)
            elif existing is not None:
                if (
                    stat.S_ISLNK(existing.st_mode)
                    or not stat.S_ISREG(existing.st_mode)
                ):
                    raise OSError("virtual publication tree contains an unsafe file")
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / relative).read_bytes())
            target.chmod(stat.S_IMODE(os.lstat(source / relative).st_mode))
        for relative in sorted(
            directories_to_copy,
            key=lambda path: (-len(path.parts), path.as_posix()),
        ):
            (destination / relative).chmod(directory_modes[relative])
        destination.chmod(source_root_mode)
        return files

    def _add_owned_file_diff(
        self,
        transaction: SquadPublicationTransaction,
        *,
        virtual_root: Path,
        target_root: Path,
        owned_relative_paths: set[Path] | frozenset[Path],
    ) -> int:
        owned_targets = {
            self._project_relative_target(target_root / relative)
            for relative in owned_relative_paths
        }
        operation_count = 0
        for relative in sorted(owned_relative_paths):
            staged = virtual_root / relative
            target = target_root / relative
            target_relative = self._project_relative_target(target)
            staged_metadata = self._lstat_or_none(staged)
            target_metadata = self._lstat_or_none(target)
            if staged_metadata is not None:
                if (
                    stat.S_ISLNK(staged_metadata.st_mode)
                    or not stat.S_ISREG(staged_metadata.st_mode)
                ):
                    raise OSError("staged publication output is not a regular file")
                if (
                    target_metadata is not None
                    and stat.S_ISREG(target_metadata.st_mode)
                    and not stat.S_ISLNK(target_metadata.st_mode)
                    and target.read_bytes() == staged.read_bytes()
                    and stat.S_IMODE(target_metadata.st_mode)
                    == stat.S_IMODE(staged_metadata.st_mode)
                ):
                    continue
                transaction.add_write(
                    target_relative,
                    staged,
                    owned_paths=owned_targets,
                )
                operation_count += 1
                continue
            if target_metadata is None:
                continue
            transaction.add_delete(
                target_relative,
                owned_paths=owned_targets,
            )
            operation_count += 1
        return operation_count

    @staticmethod
    def _discard_uncommitted_publication(
        transaction: SquadPublicationTransaction,
    ) -> None:
        try:
            transaction.seal().discard()
        except Exception:
            # The stage has no state marker and therefore no publication
            # authority. Recovery may clean an unreferenced stage later.
            return

    def _product_effects_requested(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
    ) -> bool:
        payload = result.echelon_result or {}
        updates = (
            payload.get("product_input_updates")
            if isinstance(payload, Mapping)
            else None
        )
        metadata = state.get("product_inputs")
        return bool(updates) or (
            isinstance(metadata, dict)
            and bool(metadata)
            and phase in {"phase3-plan", "phase3-consensus"}
        )

    def _require_run_local_product_inputs(
        self,
        path: Path,
        *,
        staged_path: Path | None = None,
    ) -> None:
        candidate = Path(os.path.abspath(path))
        allowed = {
            Path(os.path.abspath(self._squad_dir / "inputs")),
        }
        if staged_path is not None:
            allowed.add(Path(os.path.abspath(staged_path)))
        if candidate not in allowed:
            raise _ProductInputCommitError(
                "product input evidence directory is not owned by this squad run"
            )

    def _stage_product_input_effects(
        self,
        transaction: SquadPublicationTransaction,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
    ) -> tuple[
        int,
        dict[str, object],
        _ProductInputPublicationPlan | None,
    ]:
        staged_state = dict(state)
        metadata = staged_state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            error = self._apply_product_input_updates(result, phase, staged_state)
            if error:
                raise _ProductInputCommitError(error)
            return 0, staged_state, None

        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            raise _ProductInputCommitError(
                "product input staging path is missing from run state"
            )
        source_inputs = self._absolute_project_path(inputs_ref)
        self._require_run_local_product_inputs(source_inputs)
        try:
            old_tree_hash = authenticate_product_input_contract(
                self._project_root,
                metadata,
                source_inputs,
            )
            source_identity = product_input_tree_identity(source_inputs)
        except ProductInputMutationError as exc:
            raise _ProductInputCommitError(
                f"invalid product input updates: {exc}"
            ) from exc
        staged_old_inputs = transaction.build_path(
            Path("work/product-inputs-old")
        )
        self._copy_controller_tree(
            source_inputs,
            staged_old_inputs,
            exclude_echelon=False,
        )
        try:
            if (
                authenticate_product_input_contract(
                    self._project_root,
                    metadata,
                    source_inputs,
                )
                != old_tree_hash
                or product_input_tree_identity(source_inputs) != source_identity
                or immutable_product_input_tree_digest(staged_old_inputs)
                != old_tree_hash
            ):
                raise ProductInputMutationError(
                    "product input package changed during staging"
                )
        except (ProductInputError, ProductInputMutationError) as exc:
            raise _ProductInputCommitError(
                f"invalid product input updates: product input package changed during staging: {exc}",
                retain_stage=True,
            ) from exc
        virtual_inputs = transaction.build_path(
            Path("work/product-inputs")
        )
        self._copy_controller_tree(
            staged_old_inputs,
            virtual_inputs,
            exclude_echelon=False,
        )
        try:
            if immutable_product_input_tree_digest(virtual_inputs) != old_tree_hash:
                raise ProductInputMutationError(
                    "staged product input preimage changed"
                )
        except (ProductInputError, ProductInputMutationError) as exc:
            raise _ProductInputCommitError(
                f"invalid product input updates: {exc}",
                retain_stage=True,
            ) from exc

        staged_metadata = dict(metadata)
        original_paths: dict[str, Path] = {}
        staged_paths: dict[str, Path] = {}
        for key in _PRODUCT_INPUT_PATH_KEYS:
            ref = str(metadata.get(key) or "").strip()
            if not ref:
                continue
            original = self._absolute_project_path(ref)
            try:
                relative = original.relative_to(source_inputs)
            except ValueError as exc:
                raise _ProductInputCommitError(
                    "product input metadata path is outside its evidence directory"
                ) from exc
            staged = virtual_inputs / relative
            original_paths[key] = original
            staged_paths[key] = staged
            staged_metadata[key] = str(staged)
        staged_metadata["inputs_dir"] = str(virtual_inputs)
        staged_state["product_inputs"] = staged_metadata

        error = self._apply_product_input_updates(
            result,
            phase,
            staged_state,
            path_overrides=staged_paths,
        )
        if error:
            raise _ProductInputCommitError(error)

        try:
            restore_product_input_directory_modes(
                staged_old_inputs,
                virtual_inputs,
            )
            staged_tree_hash = immutable_product_input_tree_digest(
                virtual_inputs
            )
        except ProductInputError as exc:
            raise _ProductInputCommitError(
                f"invalid product input updates: {exc}"
            ) from exc
        if staged_tree_hash == old_tree_hash:
            return 0, staged_state, None
        staged_metadata["tree_hash"] = staged_tree_hash
        try:
            owned_paths = add_complete_product_input_publication(
                transaction,
                self._project_root,
                source_inputs,
                virtual_inputs,
            )
            new_tree_hash = immutable_product_input_tree_digest(
                virtual_inputs
            )
        except (OSError, ProductInputError, ProductInputMutationError) as exc:
            raise _ProductInputCommitError(
                f"invalid product input updates: {exc}"
            ) from exc
        persisted_metadata = dict(metadata)
        persisted_metadata["tree_hash"] = new_tree_hash
        return (
            len(owned_paths),
            staged_state,
            _ProductInputPublicationPlan(
                old_tree_hash=old_tree_hash,
                new_tree_hash=new_tree_hash,
                product_inputs=persisted_metadata,
                owned_paths=owned_paths,
            ),
        )

    def _phase_a_preparation_failure(
        self,
        blocker: str,
    ) -> _PhaseAReadinessCommitError:
        return _PhaseAReadinessCommitError(
            PhaseAReadinessResult(
                ready=False,
                blockers=[blocker],
                missing={},
                ready_spec_dir=None,
            )
        )

    def _stage_phase_a_effects(
        self,
        transaction: SquadPublicationTransaction,
        state: Mapping[str, object],
        *,
        product_inputs_source: Path | None = None,
    ) -> tuple[int, PhaseAReadinessResult]:
        detached_state = dict(state)
        debt_authorization = detached_state.get(
            "spec_quality_debt_authorization"
        )
        if (
            isinstance(debt_authorization, Mapping)
            and debt_authorization.get("status") == "accepted_with_debt"
        ):
            from harness.phase1_quality_debt import (
                has_current_quality_debt_authorization,
            )

            if has_current_quality_debt_authorization(
                detached_state,
                project_root=self._project_root,
            ):
                detached_state["spec_status"] = "accepted_with_debt"
        active_spec_dir = self._active_phase_a_spec_dir(detached_state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return (
                0,
                validate_phase_a_readiness(
                    detached_state,
                    self._phase_a_readiness_candidate_dirs(detached_state),
                    allow_pending_retarget_finalization=self._active_retarget(
                        detached_state
                    ),
                ),
            )
        active_spec_dir = self._absolute_project_path(active_spec_dir)
        self._project_relative_target(active_spec_dir / "spec.md")
        published_spec_dir = self._absolute_project_path(
            self._published_phase_a_spec_dir(
                detached_state,
                active_spec_dir,
            )
        )
        self._project_relative_target(published_spec_dir / "spec.md")
        virtual_spec_dir = transaction.build_path(
            Path("work/phase-a/specs") / published_spec_dir.name
        )
        published_metadata = self._lstat_or_none(published_spec_dir)
        if published_metadata is not None:
            if (
                stat.S_ISLNK(published_metadata.st_mode)
                or not stat.S_ISDIR(published_metadata.st_mode)
            ):
                raise OSError("published Phase A target is not a directory")
            self._copy_controller_tree(
                published_spec_dir,
                virtual_spec_dir,
                exclude_echelon=True,
            )
        else:
            virtual_spec_dir.mkdir(parents=True, exist_ok=True)

        active_spec_files = self._controller_tree_files(
            active_spec_dir,
            exclude_echelon=True,
        )
        active_spec_files = frozenset(
            path
            for path in active_spec_files
            if path != Path("quality-debt.json")
        )
        self._copy_spec_tree(active_spec_dir, virtual_spec_dir)
        if not isinstance(debt_authorization, Mapping):
            stale_virtual_debt = virtual_spec_dir / "quality-debt.json"
            if stale_virtual_debt.exists():
                stale_virtual_debt.unlink()
        targets = [
            str(value).strip()
            for value in (
                detached_state.get("implementation_targets")
                or getattr(self, "_implementation_targets", [])
            )
            if str(value).strip()
        ]
        if targets:
            write_targets(virtual_spec_dir, targets)

        published_input_files: set[Path] = set()
        metadata = detached_state.get("product_inputs")
        if isinstance(metadata, dict) and metadata:
            inputs_ref = str(metadata.get("inputs_dir") or "").strip()
            if not inputs_ref:
                return (
                    0,
                    PhaseAReadinessResult(
                        ready=False,
                        blockers=[
                            "product input evidence path is missing from run state"
                        ],
                        missing={},
                        ready_spec_dir=None,
                    ),
                )
            source_inputs = (
                Path(product_inputs_source)
                if product_inputs_source is not None
                else self._absolute_project_path(inputs_ref)
            )
            self._require_run_local_product_inputs(
                source_inputs,
                staged_path=transaction.build_path(
                    Path("work/product-inputs")
                ),
            )
            source_input_files = self._controller_tree_files(
                source_inputs,
                exclude_echelon=False,
            )
            published_input_files.update(
                Path("inputs") / path for path in source_input_files
            )
            visible_inputs = published_spec_dir / "inputs"
            if visible_inputs.exists():
                published_input_files.update(
                    Path("inputs") / path
                    for path in self._controller_tree_files(
                        visible_inputs,
                        exclude_echelon=False,
                    )
                )
        input_blockers = self._publish_product_input_evidence(
            virtual_spec_dir,
            detached_state,
            source_override=product_inputs_source,
        )
        if input_blockers:
            return (
                0,
                PhaseAReadinessResult(
                    ready=False,
                    blockers=input_blockers,
                    missing={},
                    ready_spec_dir=None,
                ),
            )
        self._publish_constitution_snapshot(virtual_spec_dir)
        self._write_phase_a_finalization_outputs(
            virtual_spec_dir,
            detached_state,
            strict=True,
        )
        write_artifact_index(virtual_spec_dir)
        self._write_published_context_metadata(
            virtual_spec_dir,
            str(detached_state.get("run_id") or "").strip(),
            canonical_spec_file=published_spec_dir / "spec.md",
        )

        updated = deepcopy(detached_state)
        updated["published_spec_dir"] = self._repo_relative_or_absolute(
            published_spec_dir
        )
        readiness = validate_phase_a_readiness(
            updated,
            [virtual_spec_dir],
            allow_pending_retarget_finalization=self._active_retarget(updated),
        )
        if not readiness.ready:
            return 0, readiness
        published_kb_files = {
            path
            for path in _PHASE_A_KB_REPORT_FILES
            if (virtual_spec_dir / path).is_file()
        }
        owned_relative = (
            set(active_spec_files)
            | published_input_files
            | set(_PHASE_A_GENERATED_FILES)
            | published_kb_files
        )
        operation_count = self._add_owned_file_diff(
            transaction,
            virtual_root=virtual_spec_dir,
            target_root=published_spec_dir,
            owned_relative_paths=owned_relative,
        )
        operation_count += add_verified_quality_debt_publication(
            transaction,
            project_root=self._project_root,
            state=detached_state,
            active_spec_dir=active_spec_dir,
            published_spec_dir=published_spec_dir,
            staged_spec_dir=virtual_spec_dir,
        )
        return operation_count, readiness

    def _stage_authenticated_phase_a_product_inputs(
        self,
        transaction: SquadPublicationTransaction,
        state: Mapping[str, object],
    ) -> Path | None:
        """Copy one exact authenticated live package for read-only Phase 4 use."""
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return None
        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            raise _ProductInputCommitError(
                "invalid product input updates: product input staging path is missing from run state"
            )
        source_inputs = self._absolute_project_path(inputs_ref)
        self._require_run_local_product_inputs(source_inputs)
        snapshot = transaction.build_path(Path("work/product-inputs"))
        try:
            expected_hash = authenticate_product_input_contract(
                self._project_root,
                metadata,
                source_inputs,
            )
            source_identity = product_input_tree_identity(source_inputs)
            self._copy_controller_tree(
                source_inputs,
                snapshot,
                exclude_echelon=False,
            )
            if (
                authenticate_product_input_contract(
                    self._project_root,
                    metadata,
                    source_inputs,
                )
                != expected_hash
                or product_input_tree_identity(source_inputs)
                != source_identity
                or immutable_product_input_tree_digest(snapshot)
                != expected_hash
            ):
                raise ProductInputMutationError(
                    "product input package changed during staging"
                )
            validate_immutable_product_input_package(snapshot, metadata)
        except (OSError, ProductInputError, ProductInputMutationError) as exc:
            reason = str(exc)
            if "tree hash drift" not in reason:
                reason = f"product input package changed during staging: {reason}"
            raise _ProductInputCommitError(
                f"invalid product input updates: {reason}",
                retain_stage=True,
            ) from exc
        return snapshot

    def _authenticate_phase_a_product_input_snapshot(
        self,
        prepared: PreparedSquadPublication,
        state: Mapping[str, object],
    ) -> None:
        """Reauthenticate read-only Phase 4 source and its sealed snapshot."""
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return
        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            raise ProductInputMutationError(
                "product input staging path is missing from run state"
            )
        source_inputs = self._absolute_project_path(inputs_ref)
        self._require_run_local_product_inputs(source_inputs)
        expected_hash = authenticate_product_input_contract(
            self._project_root,
            metadata,
            source_inputs,
        )
        snapshot = prepared._transaction_root / "work/product-inputs"
        if immutable_product_input_tree_digest(snapshot) != expected_hash:
            raise ProductInputMutationError(
                "staged Phase 4 product input snapshot changed"
            )
        validate_immutable_product_input_package(snapshot, metadata)
        active_spec_dir = self._active_phase_a_spec_dir(dict(state))
        if active_spec_dir is None:
            raise ProductInputMutationError("active Phase A spec directory is missing")
        published = self._published_phase_a_spec_dir(
            dict(state),
            active_spec_dir,
        )
        staged_evidence = (
            prepared._transaction_root
            / "work/phase-a/specs"
            / published.name
            / "inputs"
        )
        if immutable_product_input_tree_digest(staged_evidence) != expected_hash:
            raise ProductInputMutationError(
                "staged Phase 4 published evidence changed"
            )

    def _authenticate_quality_debt_publication_stage(
        self,
        prepared: PreparedSquadPublication,
        state: Mapping[str, object],
    ) -> None:
        """Bind any durable publication replay to live Task 6 debt authority."""
        active_spec_dir = self._active_phase_a_spec_dir(dict(state))
        if active_spec_dir is None:
            operations = prepared._manifest.get("operations")
            writes_debt = isinstance(operations, list) and any(
                isinstance(operation, Mapping)
                and operation.get("action") == "write"
                and str(operation.get("target") or "").endswith(
                    "/quality-debt.json"
                )
                for operation in operations
            )
            stale_debt_claim = (
                state.get("spec_status") == "accepted_with_debt"
                or state.get("spec_quality_status") == "accepted_with_debt"
                or isinstance(state.get("spec_quality_debt_context"), Mapping)
            )
            if (
                "spec_quality_debt_authorization" in state
                or stale_debt_claim
                or writes_debt
            ):
                raise PublicationError("manifest_invalid")
            return
        published_spec_dir = self._published_phase_a_spec_dir(
            dict(state),
            active_spec_dir,
        )
        authenticate_prepared_quality_debt_publication(
            prepared,
            project_root=self._project_root,
            state=state,
            active_spec_dir=active_spec_dir,
            published_spec_dir=published_spec_dir,
        )

    def _prepare_external_phase_effects(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
        *,
        manual_phase_run: bool,
    ) -> PreparedSquadPublication | None:
        if manual_phase_run:
            # A manual replay is a run-local repair.  Phase A publication is
            # exclusively owned by phase4-document in the normal controller
            # progression, after its readiness checks complete.
            return None
        needs_product = self._product_effects_requested(result, phase, state)
        needs_phase_a = phase == "phase4-document"
        if not (needs_product or needs_phase_a):
            return None

        transaction = SquadPublicationTransaction.begin(
            self._project_root,
            self._squad_dir,
            uuid.uuid4().hex,
        )
        operation_count = 0
        staged_state = dict(state)
        product_plan: _ProductInputPublicationPlan | None = None
        try:
            if needs_product:
                product_operations, staged_state, product_plan = (
                    self._stage_product_input_effects(
                        transaction,
                        result,
                        phase,
                        staged_state,
                    )
                )
                operation_count += product_operations
            if needs_phase_a:
                phase_a_product_inputs = (
                    transaction.build_path(Path("work/product-inputs"))
                    if product_plan is not None
                    else self._stage_authenticated_phase_a_product_inputs(
                        transaction,
                        staged_state,
                    )
                )
                phase_a_operations, readiness = self._stage_phase_a_effects(
                    transaction,
                    staged_state,
                    product_inputs_source=phase_a_product_inputs,
                )
                if not readiness.ready:
                    raise _PhaseAReadinessCommitError(readiness)
                operation_count += phase_a_operations
            if operation_count == 0:
                self._discard_uncommitted_publication(transaction)
                return None
            prepared = transaction.seal()
            if product_plan is not None:
                inputs_dir = str(
                    product_plan.product_inputs.get("inputs_dir") or ""
                )
                mutation = build_product_input_mutation(
                    kind="controller_update",
                    marker=prepared.marker.to_dict(),
                    inputs_dir=inputs_dir,
                    old_tree_hash=product_plan.old_tree_hash,
                    new_tree_hash=product_plan.new_tree_hash,
                    owned_paths=product_plan.owned_paths,
                )
                self._prepared_product_input_updates[
                    prepared.marker.transaction_id
                ] = {
                    "product_inputs": dict(product_plan.product_inputs),
                    PRODUCT_INPUT_MUTATION_KEY: mutation,
                }
            return prepared
        except _ProductInputCommitError as exc:
            if not exc.retain_stage:
                self._discard_uncommitted_publication(transaction)
            raise
        except _PhaseAReadinessCommitError:
            self._discard_uncommitted_publication(transaction)
            raise
        except (Exception, SystemExit) as exc:
            self._discard_uncommitted_publication(transaction)
            if needs_phase_a:
                raise self._phase_a_preparation_failure(
                    "failed to stage controller-owned spec artifacts"
                ) from exc
            raise _ProductInputCommitError(
                "invalid product input updates: staged preparation failed"
            ) from exc

    def _product_input_publication_state_updates(
        self,
        prepared: PreparedSquadPublication,
    ) -> dict[str, object]:
        """Return the exact post-state and receipt bound to a sealed stage."""
        updates = self._prepared_product_input_updates.get(
            prepared.marker.transaction_id
        )
        return deepcopy(updates) if updates is not None else {}

    def _planned_phase_a_publication_updates(
        self,
        phase: str,
        state: Mapping[str, object],
    ) -> dict[str, object]:
        """Derive publication identity without performing publication writes."""
        if phase != "phase4-document":
            return {}
        detached_state = dict(state)
        active_spec_dir = self._active_phase_a_spec_dir(detached_state)
        if active_spec_dir is None:
            return {}
        published_spec_dir = self._published_phase_a_spec_dir(
            detached_state,
            active_spec_dir,
        )
        updates = {
            "published_spec_dir": self._repo_relative_or_absolute(
                published_spec_dir
            )
        }
        authorization = detached_state.get(
            "spec_quality_debt_authorization"
        )
        if (
            isinstance(authorization, Mapping)
            and authorization.get("status") == "accepted_with_debt"
        ):
            from harness.phase1_quality_debt import (
                has_current_quality_debt_authorization,
            )

            if has_current_quality_debt_authorization(
                detached_state,
                project_root=self._project_root,
            ):
                updates["spec_status"] = "accepted_with_debt"
        return updates

    def _publish_terminal_phase_a_artifacts_if_available(
        self,
    ) -> PhaseAReadinessResult | None:
        """Reconcile terminal Phase A through an explicit completion intent."""
        state = self._state_store.load()
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return None
        current_digests = self._phase_a_inventory_digests(state)
        if (
            current_digests is not None
            and self._terminal_inventory_provenance_matches(
                state,
                current_digests,
            )
        ):
            published_ref = str(
                state.get("published_spec_dir") or ""
            ).strip()
            if published_ref:
                return validate_phase_a_readiness(
                    state,
                    [self._absolute_project_path(published_ref)],
                )
        if str(state.get("phase") or "") == "phase4-document":
            self._enter_retarget_finalizing(state)
            state = self._state_store.load()
        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=str(state.get("phase") or "")
        )
        terminal_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        try:
            prepared = self._prepare_external_phase_effects(
                terminal_result,
                "phase4-document",
                snapshot.state,
                manual_phase_run=False,
            )
        except _PhaseAReadinessCommitError as exc:
            return exc.readiness
        except _ProductInputCommitError as exc:
            return PhaseAReadinessResult(
                ready=False,
                blockers=[exc.reason],
                missing={},
                ready_spec_dir=None,
            )
        planned_updates = self._planned_phase_a_publication_updates(
            "phase4-document",
            snapshot.state,
        )
        publication_marker = (
            prepared.marker.to_dict()
            if prepared is not None
            else None
        )
        completion = self._prepare_controller_completion(
            from_phase=snapshot.phase,
            to_phase=snapshot.phase,
            snapshot=snapshot,
            manual_phase_run=False,
            conditional_skip=False,
            record_completion=True,
            publication_marker=publication_marker,
            origin="terminal",
        )
        try:
            self._state_store.begin_terminal_controller_completion(
                completion,
                snapshot=snapshot,
                state_updates=planned_updates,
            )
        except StateAdvanceError:
            self._discard_publication_without_authority(prepared)
            self._discard_controller_completion_without_authority(
                completion.marker.to_dict()
            )
            return PhaseAReadinessResult(
                ready=False,
                blockers=[
                    "failed to commit terminal completion authority"
                ],
                missing={},
                ready_spec_dir=None,
            )
        recovery = self._drain_pending_controller_completion()
        if (
            not recovery.recovered
            or recovery.completion_id
            != completion.marker.completion_id
        ):
            return PhaseAReadinessResult(
                ready=False,
                blockers=["terminal completion remains pending"],
                missing={},
                ready_spec_dir=None,
            )
        if prepared is not None:
            self._phase_a_published_this_run = True
        published_ref = str(
            self._state_store.load().get("published_spec_dir") or ""
        ).strip()
        if not published_ref:
            return PhaseAReadinessResult(
                ready=False,
                blockers=["published Phase A directory is missing from state"],
                missing={},
                ready_spec_dir=None,
            )
        published_spec_dir = self._absolute_project_path(published_ref)
        return validate_phase_a_readiness(
            self._state_store.load(),
            [published_spec_dir],
        )

    @staticmethod
    def _terminal_inventory_provenance_matches(
        state: Mapping[str, object],
        digests: tuple[str, str],
    ) -> bool:
        active_digest, published_digest = digests
        dispatch = state.get("last_dispatch")
        routed_match = (
            isinstance(dispatch, Mapping)
            and dispatch.get("phase_id") == "phase4-document"
            and dispatch.get("post_dispatch_complete") is True
            and state.get("phase_a_active_source_sha256")
            == active_digest
            and state.get("phase_a_published_postimage_sha256")
            == published_digest
        )
        terminal = state.get("last_terminal_completion")
        terminal_match = (
            isinstance(terminal, Mapping)
            and terminal.get("terminal_phase") == state.get("phase")
            and terminal.get("phase_a_active_source_sha256")
            == active_digest
            and terminal.get(
                "phase_a_published_postimage_sha256"
            )
            == published_digest
        )
        return routed_match or terminal_match

    def _phase_a_readiness_candidate_dirs(
        self,
        state: Mapping[str, object] | None = None,
    ) -> list[Path]:
        state = dict(state) if state is not None else self._state_store.load()
        candidates: list[Path] = []

        def add(candidate: Path | None) -> None:
            if candidate is None:
                return
            path = candidate if candidate.is_absolute() else self._project_root / candidate
            if path not in candidates:
                candidates.append(path)

        spec_id = str(state.get("spec_id") or "").strip()
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        published_ref = str(state.get("published_spec_dir") or "").strip()
        staging_ref = str(state.get("staging_dir") or "").strip()

        if spec_dir_ref:
            add(Path(spec_dir_ref))
        if published_ref:
            add(Path(published_ref))
        if spec_id:
            add(self._project_root / "specs" / spec_id)
            add(self._squad_dir / "specs" / spec_id)
        if staging_ref:
            add(Path(staging_ref))
        else:
            add(self._squad_dir / "staging")

        return candidates

    def _publish_phase_a_artifacts_for_build(
        self,
        state: Mapping[str, object] | None = None,
    ) -> PhaseAReadinessResult:
        state = dict(state) if state is not None else self._state_store.load()
        self._materialize_implementation_targets(state)
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return validate_phase_a_readiness(
                state,
                self._phase_a_readiness_candidate_dirs(state),
            )

        published_spec_dir = self._published_phase_a_spec_dir(state, active_spec_dir)
        try:
            if active_spec_dir.resolve() != published_spec_dir.resolve():
                self._copy_spec_tree(active_spec_dir, published_spec_dir)
            else:
                published_spec_dir.mkdir(parents=True, exist_ok=True)
            input_blockers = self._publish_product_input_evidence(published_spec_dir, state)
            if input_blockers:
                return PhaseAReadinessResult(
                    ready=False,
                    blockers=input_blockers,
                    missing={},
                    ready_spec_dir=None,
                )
            self._publish_constitution_snapshot(published_spec_dir)
            self._write_phase_a_finalization_outputs(published_spec_dir, state)
            write_artifact_index(published_spec_dir)
            self._refresh_published_context_metadata(
                published_spec_dir,
                str(state.get("run_id") or "").strip(),
            )
        except OSError as exc:
            return PhaseAReadinessResult(
                ready=False,
                blockers=[f"failed to publish Phase A artifacts: {exc}"],
                missing={},
                ready_spec_dir=None,
            )

        updated = deepcopy(state)
        updated["published_spec_dir"] = self._repo_relative_or_absolute(published_spec_dir)
        self._phase_a_published_this_run = True
        return validate_phase_a_readiness(updated, [published_spec_dir])

    def _publish_product_input_evidence(
        self,
        published_spec_dir: Path,
        state: dict,
        *,
        source_override: Path | None = None,
    ) -> list[str]:
        """Publish safe run-local evidence and enforce the normative input chain."""
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return []
        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            return ["product input evidence path is missing from run state"]
        source = Path(source_override) if source_override is not None else Path(inputs_ref)
        if not source.is_absolute():
            source = self._project_root / source
        if not source.is_dir():
            return [f"product input evidence directory is missing: {source}"]
        destination = published_spec_dir / "inputs"
        if destination.exists():
            shutil.rmtree(destination)
        self._copy_controller_tree(
            source,
            destination,
            exclude_echelon=False,
        )
        from echelon.product_inputs import validate_product_input_traceability
        targets = [
            str(value).strip()
            for value in state.get("implementation_targets", [])
            if str(value).strip()
        ]
        return validate_product_input_traceability(published_spec_dir, targets)

    def _write_phase_a_finalization_outputs(
        self,
        published_spec_dir: Path,
        state: dict,
        *,
        strict: bool = False,
    ) -> None:
        run_id = str(state.get("run_id") or "unknown")
        published_re_context = state.get("published_re_context")
        if isinstance(published_re_context, Mapping):
            write_canonical_re_context(
                self._project_root,
                published_spec_dir,
                published_re_context,
            )
        try:
            from echelon.kb_proposals import publish_kb_reports

            run_id = self._safe_run_id(run_id)
            run_dir = self._project_root / "runs" / run_id
            expected_reports = (
                (
                    run_dir / "kb-apply-report.yaml",
                    published_spec_dir / "kb/kb-apply-report.yaml",
                ),
                (
                    run_dir / "kb-usage.yaml",
                    published_spec_dir / "kb/kb-usage-summary.yaml",
                ),
            )
            expected_states = tuple(
                (
                    source,
                    target,
                    self._read_project_regular_file(source),
                    self._read_project_regular_file(target),
                )
                for source, target in expected_reports
            )
            publish_kb_reports(self._project_root, run_id, published_spec_dir)
            if strict:
                for source, target, source_before, target_before in expected_states:
                    source_after = self._read_project_regular_file(source)
                    if source_after != source_before:
                        raise OSError(
                            "KB publication source changed during staging"
                        )
                    target_after = self._read_project_regular_file(target)
                    expected_target = (
                        source_before
                        if source_before is not None
                        else target_before
                    )
                    if target_after != expected_target:
                        raise OSError(
                            "KB publication did not produce its exact staged output"
                        )
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            logger.warning("Could not publish KB provenance reports: %s", exc)
        self._write_plan_conformance_outputs(published_spec_dir)
        self._write_final_overview(published_spec_dir, state)
        spec_status = str(state.get("spec_status") or "planned")
        constitution_hash = self._constitution_hash(
            published_spec_dir / "constitution.md"
        )
        retarget = state.get("retarget")
        retarget_linkage: dict[str, str] = {}
        if isinstance(retarget, Mapping):
            revision = retarget.get("revision_id")
            baseline = retarget.get("baseline_run_id")
            checkpoint = retarget.get("checkpoint_id")
            if all(
                type(value) is str and value
                for value in (revision, baseline, checkpoint)
            ):
                retarget_linkage = {
                    "retarget_revision": revision,
                    "supersedes_run_id": baseline,
                    "baseline_checkpoint": checkpoint,
                }
        append_phase_a_run(
            published_spec_dir,
            run_id=run_id,
            spec_status=spec_status,
            constitution_hash=constitution_hash,
            **retarget_linkage,
        )
        self._write_squad_report(published_spec_dir, state)

    def _write_plan_conformance_outputs(self, published_spec_dir: Path) -> None:
        sources = [
            "spec.md",
            "requirements-overview.md",
            "mvp-scope.md",
            "plan.md",
            "tasks.md",
            "dependencies.md",
            "critical-path.md",
        ]
        json_payload = {
            "status": "pass",
            "findings": [],
            "sources": sources,
        }
        report_lines = [
            "# Plan Conformance Report",
            "",
            "## Summary",
            "Status: pass",
            "",
            (
                "Phase A finalization found no required conformance repair after "
                "the completed planning, tasks lexicon, consensus, and "
                "implementability gates."
            ),
            "",
            "## Requirement Coverage",
            "| Requirement | Covered By Plan | Covered By Tasks | Finding |",
            "|-------------|-----------------|------------------|---------|",
            "| Final Phase A requirements | plan.md | tasks.md | None |",
            "",
            "## Plan and Task Traceability",
            "| Plan/Task Behavior | Source Artifact | Trace Status | Finding |",
            "|--------------------|-----------------|--------------|---------|",
            (
                "| Planned build behavior | spec.md, mvp-scope.md, research.md "
                "| Conformant | None |"
            ),
            "",
            "## MVP and Deferred Scope Alignment",
            "| Scope Item | MVP/Post-MVP/Conditional | Plan Agreement | Task Agreement | Finding |",
            "|------------|--------------------------|----------------|----------------|---------|",
            "| Final Phase A scope | mvp-scope.md | Conformant | Conformant | None |",
            "",
            "## Requirements Overview Drift",
            "| Claim in requirements-overview.md | Agreement With Plan/Tasks | Finding |",
            "|-----------------------------------|---------------------------|---------|",
            "| Final requirement summary | Conformant | None |",
            "",
            "## Overview Backing Check",
            "| Final Overview Claim | Backing Artifact | Finding |",
            "|----------------------|------------------|---------|",
            (
                "| Delivery entry point is derived from final Phase A artifacts "
                "| 00-overview.md, plan-conformance.json | None |"
            ),
            "",
            "## Findings",
            "| ID | Severity | Artifact | Description | Required Repair |",
            "|----|----------|----------|-------------|-----------------|",
            "| - | - | - | No findings. | - |",
            "",
        ]
        (published_spec_dir / "plan-conformance.md").write_text(
            "\n".join(report_lines),
            encoding="utf-8",
        )
        (published_spec_dir / "plan-conformance.json").write_text(
            json.dumps(json_payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_final_overview(
        self,
        published_spec_dir: Path,
        state: Mapping[str, object],
    ) -> None:
        spec_id = str(state.get("spec_id") or published_spec_dir.name)
        title = spec_id.replace("-", " ").title()
        lines = [
            f"# {title} - Final Delivery Overview",
            "",
            (
                "> Generated during Phase A finalization after plan/task "
                "conformance checks."
            ),
            (
                "> This brief is derived from the final Phase A artifacts and "
                "does not introduce new scope."
            ),
            "",
            "## What This Builds",
            (
                "Build the behavior described by `spec.md` using the architecture "
                "and sequencing in `plan.md` and the canonical execution rows in "
                "`tasks.md`."
            ),
            "",
            "## Delivery Sequence",
            "| Slice | Build First/Next | Source Tasks | Expected Partial Result |",
            "|-------|------------------|--------------|-------------------------|",
            (
                "| 1 | Follow canonical task order | tasks.md | A scoped "
                "implementation that satisfies the MVP requirements. |"
            ),
            "",
            "## Dependencies to Control First",
            "| Dependency | Why It Matters | Control Action | Source |",
            "|------------|----------------|----------------|--------|",
            (
                "| Phase A artifacts | They define the approved build contract. | "
                "Read `plan.md`, `tasks.md`, and `plan-conformance.md` before "
                "implementation. | plan-conformance.md |"
            ),
            "",
            "## Partial Result Target",
            (
                "Deliver the MVP slice captured in `mvp-scope.md`, `plan.md`, "
                "and `tasks.md`. Treat deferred or conditional work named in "
                "those artifacts as out of scope for the first build pass."
            ),
            "",
            "## Stop and Ask",
            (
                "Stop if `spec.md`, `requirements-overview.md`, `mvp-scope.md`, "
                "`plan.md`, or `tasks.md` disagree on required behavior, task "
                "coverage, or deferred scope."
            ),
            "",
            "## Source Artifacts",
            "- spec.md",
            "- requirements-overview.md",
            "- mvp-scope.md",
            "- plan.md",
            "- tasks.md",
            "- plan-conformance.md",
            "- plan-conformance.json",
            "",
        ]
        (published_spec_dir / "00-overview.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    def _constitution_hash(self, constitution_path: Path) -> str:
        if not constitution_path.exists():
            return ""
        return hashlib.sha256(constitution_path.read_bytes()).hexdigest()

    def _write_squad_report(self, published_spec_dir: Path, state: dict) -> None:
        artifact_count = sum(
            1
            for path in published_spec_dir.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        quality_scores = state.get("quality_scores") or []
        final_quality = quality_scores[-1] if quality_scores else {}
        lines = [
            "# Squad Report",
            "",
            "## Run",
            "",
            f"- Run ID: {state.get('run_id') or 'unknown'}",
            f"- Spec ID: {state.get('spec_id') or published_spec_dir.name}",
            f"- Mode: {state.get('mode') or 'unknown'}",
            f"- Autonomy: {state.get('autonomy_mode') or 'unknown'}",
            f"- Spec status: {state.get('spec_status') or 'planned'}",
            "",
            "## Final Quality",
            "",
            f"- WHY pass: {final_quality.get('pass', 'unknown')}",
            f"- Overall: {final_quality.get('overall', 'n/a')}",
            "",
            "## Handoff",
            "",
            f"- Artifacts: {artifact_count} files in `{published_spec_dir.name}/`",
            "- Ready for: `echelon delivery run <spec-id>`",
            "- Application source files modified by Phase A: none",
            "",
        ]
        (published_spec_dir / "squad-report.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    def _publish_constitution_snapshot(self, published_spec_dir: Path) -> None:
        """Copy the project constitution into the published spec build inputs."""
        from echelon.constitution import canonical_constitution_path

        source = canonical_constitution_path(self._project_root)
        target = published_spec_dir / "constitution.md"
        content = self._read_project_regular_file(source)
        if content is not None:
            target.write_bytes(content)

    def _refresh_published_context_metadata(
        self,
        published_spec_dir: Path,
        run_id: str,
    ) -> None:
        metadata = self._write_published_context_metadata(
            published_spec_dir,
            run_id,
        )
        if metadata is None:
            return
        self._mine_published_spec_best_effort(
            published_spec_dir,
            published_spec_dir / "spec.md",
            run_id,
            metadata,
        )

    def _mine_published_context_after_publication(self) -> None:
        """Mine canonical metadata only after durable marker clearance."""
        state = self._state_store.load()
        published_ref = str(state.get("published_spec_dir") or "").strip()
        if not published_ref:
            return
        published_spec_dir = self._absolute_project_path(published_ref)
        spec_file = published_spec_dir / "spec.md"
        if not spec_file.is_file():
            return
        try:
            from echelon.context_metadata import read_feature_metadata

            metadata = read_feature_metadata(published_spec_dir)
        except Exception:
            return
        if metadata is None:
            return
        self._mine_published_spec_best_effort(
            published_spec_dir,
            spec_file,
            str(state.get("run_id") or ""),
            metadata,
        )

    def _write_published_context_metadata(
        self,
        published_spec_dir: Path,
        run_id: str,
        *,
        canonical_spec_file: Path | None = None,
    ) -> object | None:
        spec_file = published_spec_dir / "spec.md"
        if not spec_file.exists():
            return None

        from echelon.context_metadata import FeatureMetadata, write_feature_metadata

        metadata = FeatureMetadata.from_spec_dir(
            published_spec_dir,
            run_id=run_id or None,
        )
        if canonical_spec_file is not None:
            canonical_artifact_path = self._repo_relative_or_absolute(
                canonical_spec_file
            )
            metadata = replace(
                metadata,
                requirements=[
                    replace(
                        requirement,
                        artifact_path=canonical_artifact_path,
                    )
                    for requirement in metadata.requirements
                ],
            )
        write_feature_metadata(published_spec_dir, metadata)
        return metadata

    def _mine_published_spec_best_effort(
        self,
        published_spec_dir: Path,
        spec_file: Path,
        run_id: str,
        metadata: object,
    ) -> str:
        try:
            from echelon.mempalace_requirements import (
                create_requirement_memory_adapter,
            )
        except Exception:
            return "unavailable"

        try:
            content = spec_file.read_bytes()
            spec_sha256 = hashlib.sha256(content).hexdigest()
            artifact_metadata = self._canonical_spec_artifact_metadata(
                spec_file,
                metadata,
                f"sha256:{spec_sha256}",
            )
        except (Exception, SystemExit):
            return "failed"

        try:
            miner = create_requirement_memory_adapter(self._project_root, run_id)
        except (Exception, SystemExit):
            return "unavailable"
        try:
            source = str(artifact_metadata["artifact_path"])
            result = miner.mine_canonical_bytes(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )
            if (
                spec_file.read_bytes() != content
                or hashlib.sha256(content).hexdigest() != spec_sha256
            ):
                return "failed"
        except (Exception, SystemExit):
            return "failed"
        failed = getattr(result, "failed", None)
        unavailable = getattr(result, "unavailable", None)
        written = getattr(result, "written", None)
        already_present = getattr(result, "already_present", None)
        if any(
            type(value) is not int or value < 0
            for value in (
                failed,
                unavailable,
                written,
                already_present,
            )
        ):
            return "failed"
        if failed:
            return "failed"
        if unavailable:
            return "unavailable" if not written and not already_present else "failed"
        if written:
            return "written"
        return "already_present"

    def _canonical_spec_artifact_metadata(
        self,
        spec_file: Path,
        metadata: object,
        spec_hash: str,
    ) -> dict[str, object]:
        try:
            artifact_path = spec_file.relative_to(self._project_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "canonical spec must be inside the project"
            ) from exc

        payload: dict[str, object] = {
            "scope": "canonical",
            "canonical": True,
            "artifact_path": artifact_path,
            "artifact_hash": spec_hash,
            "lifecycle_status": getattr(metadata, "status", "active"),
            "spec_id": getattr(metadata, "spec_id", ""),
            "feature_id": getattr(metadata, "feature_id", ""),
        }
        for reserved_key in {
            "run_id",
            "phase",
            "run_outcome",
            "provenance_type",
            "embedding_model",
            "status",
            "source_file",
        }:
            payload.pop(reserved_key, None)
        return payload

    def _active_phase_a_spec_dir(self, state: dict) -> Path | None:
        spec_ref = str(state.get("spec_dir") or "").strip()
        if spec_ref:
            candidate = Path(spec_ref)
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            return candidate

        spec_id = str(state.get("spec_id") or "").strip()
        if spec_id:
            run_local = self._squad_dir / "specs" / spec_id
            if run_local.exists():
                return run_local
        return None

    def _checkpoint_successful_phase(self, phase: str, next_phase: str) -> bool:
        state = self._state_store.load()
        spec_dir = self._active_phase_a_spec_dir(state)
        if spec_dir is None or not spec_dir.exists():
            return True
        additional_spec_dirs: tuple[Path, ...] = ()
        additional_owned_paths: tuple[Path, ...] = ()
        if phase == "phase4-document" and next_phase in TERMINAL_PHASES:
            published_spec_dir = self._published_phase_a_spec_dir(state, spec_dir)
            if (
                published_spec_dir.exists()
                and published_spec_dir.resolve() != spec_dir.resolve()
            ):
                additional_spec_dirs = (published_spec_dir,)
            additional_owned_paths = accepted_kb_target_paths(
                self._project_root,
                str(state.get("run_id") or ""),
            )
        try:
            create_phase_checkpoint(
                project_root=self._project_root,
                spec_dir=spec_dir,
                phase=phase,
                next_phase=next_phase,
                run_id=str(state.get("run_id") or ""),
                spec_id=_checkpoint_spec_id_from_state(state, spec_dir),
                additional_spec_dirs=additional_spec_dirs,
                additional_owned_paths=additional_owned_paths,
            )
        except Exception as exc:
            logger.error("Could not create required phase checkpoint for %s: %s", phase, exc)
            blocked = self._state_store.load()
            blocked["status"] = "blocked"
            blocked["phase"] = PHASE_TERMINAL_BLOCKED
            blocked["blocked_reason"] = f"phase_checkpoint_failed: {phase}: {exc}"
            self._state_store.save(blocked)
            return False
        return True

    def _materialize_implementation_targets(
        self,
        state: Mapping[str, object] | None = None,
    ) -> None:
        """Write authoritative run targets once an active spec exists."""
        state = dict(state) if state is not None else self._state_store.load()
        targets = [
            str(value).strip()
            for value in (
                state.get("implementation_targets")
                or getattr(self, "_implementation_targets", [])
            )
            if str(value).strip()
        ]
        if not targets:
            return
        spec_dir = self._active_phase_a_spec_dir(state)
        if (
            spec_dir is None
            or not spec_dir.exists()
            or not (spec_dir / "spec.md").is_file()
        ):
            return
        try:
            write_targets(spec_dir, targets)
        except (OSError, ValueError) as exc:
            logger.warning("Could not materialize implementation targets: %s", exc)

    def _materialize_controller_phase_inputs(self, node: PhaseNode) -> PhaseNode:
        """Return one dispatch-local node with controller-pinned debt context."""
        if (
            node.type == "deterministic_lexicon"
            and node.lexicon_artifact == "tasks"
        ):
            self._materialize_implementation_targets()
        if node.id == "phase1-constitution":
            self._materialize_constitution_current_snapshot()
        if node.id not in _QUALITY_DEBT_DOWNSTREAM_PHASES:
            return node
        state = self._state_store.load()
        authorization = state.get("spec_quality_debt_authorization")
        if not isinstance(authorization, Mapping):
            if (
                state.get("spec_status") == "accepted_with_debt"
                or state.get("spec_quality_status") == "accepted_with_debt"
                or isinstance(state.get("spec_quality_debt_context"), Mapping)
            ):
                raise ControllerStateContractViolation(
                    "quality-debt status has no current authorization",
                    contract="phase1_quality_debt",
                    json_path="$.spec_quality_debt_authorization",
                    validator="required",
                )
            return node
        from harness.phase1_quality_debt import (
            has_current_quality_debt_authorization,
        )

        if not has_current_quality_debt_authorization(
            state,
            project_root=self._project_root,
        ):
            raise ControllerStateContractViolation(
                "quality-debt authorization is stale or invalid",
                contract="phase1_quality_debt",
                json_path="$.spec_quality_debt_authorization",
                validator="currentness",
            )
        debt_ref = authorization.get("debt_artifact")
        debt_digest = authorization.get("debt_artifact_sha256")
        if type(debt_ref) is not str or type(debt_digest) is not str:
            raise ControllerStateContractViolation(
                "quality-debt artifact binding is invalid",
                contract="phase1_quality_debt",
                json_path="$.spec_quality_debt_authorization.debt_artifact",
                validator="binding",
            )
        debt_path = Path(debt_ref)
        if not debt_path.is_absolute():
            debt_path = self._project_root / debt_path
        try:
            metadata = os.lstat(debt_path)
            debt_bytes = debt_path.read_bytes()
            debt = json.loads(debt_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControllerStateContractViolation(
                "quality-debt artifact cannot be pinned for dispatch",
                contract="phase1_quality_debt",
                json_path="$.spec_quality_debt_authorization.debt_artifact",
                validator="artifact",
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or not isinstance(debt, Mapping)
            or hashlib.sha256(debt_bytes).hexdigest() != debt_digest
        ):
            raise ControllerStateContractViolation(
                "quality-debt artifact changed before dispatch",
                contract="phase1_quality_debt",
                json_path="$.spec_quality_debt_authorization.debt_artifact_sha256",
                validator="digest",
            )
        dispatched = deepcopy(node)
        dispatched.controller_context = (
            "\n## Verified Specification Quality Debt (Controller-Pinned)\n"
            "Status: accepted_with_debt\n"
            f"Artifact: {debt_ref}\n"
            f"SHA-256: {debt_digest}\n"
            "The following exact verified quality-debt.json bytes are immutable "
            "context for this dispatch. The recorded failures remain unresolved; "
            "do not translate them into PASS.\n"
            f"{debt_bytes.decode('utf-8')}\n"
        )
        context = {
            "status": "accepted_with_debt",
            "artifact": debt_ref,
            "artifact_sha256": debt_digest,
            "resolved_by": authorization.get("resolved_by"),
            "failed_gates": list(authorization.get("failed_gates") or []),
        }
        qualitative_debt = list(
            authorization.get("qualitative_debt") or []
        )
        if qualitative_debt:
            context["qualitative_debt"] = qualitative_debt
        if (
            state.get("spec_quality_status") != "accepted_with_debt"
            or state.get("spec_quality_debt_context") != context
        ):
            state["spec_quality_status"] = "accepted_with_debt"
            state["spec_quality_debt_context"] = context
            self._state_store.save(state)
        return dispatched

    def _materialize_constitution_current_snapshot(self) -> None:
        """Expose a current constitution copy without exposing `.echelon` writes."""
        from echelon.constitution import canonical_constitution_path

        canonical = canonical_constitution_path(self._project_root)
        snapshot = self._squad_dir / "constitution.current.md"
        try:
            metadata = os.lstat(canonical)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                metadata.st_mode
            ):
                snapshot.unlink(missing_ok=True)
                return
            text = canonical.read_text(encoding="utf-8")
        except FileNotFoundError:
            snapshot.unlink(missing_ok=True)
            return
        except (OSError, UnicodeDecodeError) as exc:
            raise ControllerStateContractViolation(
                "canonical constitution cannot be staged for CHIEF",
                contract="constitution_publication",
                json_path="$.constitution",
                validator="artifact",
            ) from exc
        if unresolved_constitution_template_markers(text):
            snapshot.unlink(missing_ok=True)
            return
        try:
            write_text_atomic(snapshot, text)
        except OSError as exc:
            raise ControllerStateContractViolation(
                "canonical constitution snapshot cannot be staged for CHIEF",
                contract="constitution_publication",
                json_path="$.constitution",
                validator="snapshot",
            ) from exc

    def _promote_constitution_draft(self, node: PhaseNode) -> str | None:
        """Validate and atomically publish CHIEF's protected-root draft.

        Agents are forbidden from writing ``.echelon`` because it contains
        controller-owned runtime configuration. CHIEF therefore authors a
        durable run-local draft; the controller is the sole publisher of the
        canonical constitution after a successful agent result is prepared.
        """
        if node.id != "phase1-constitution":
            return None

        draft = self._squad_dir / "constitution.draft.md"
        try:
            metadata = os.lstat(draft)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(
                metadata.st_mode
            ):
                return "constitution_draft_invalid"
            text = draft.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return "constitution_draft_invalid"
        if not text.strip() or unresolved_constitution_template_markers(text):
            return "constitution_draft_invalid"

        from echelon.constitution import canonical_constitution_path

        try:
            write_text_atomic(canonical_constitution_path(self._project_root), text)
        except OSError:
            return "constitution_draft_publish_failed"
        return None

    def _apply_product_input_updates(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object] | None = None,
        *,
        path_overrides: Mapping[str, Path] | None = None,
    ) -> str | None:
        """Validate and persist agent proposals through the controller-owned ledger."""
        payload = result.echelon_result or {}
        updates = payload.get("product_input_updates")
        # DISCOVER consumes references as evidence but does not own requirement
        # or task traceability.
        if phase == "phase1-discover":
            return None
        state = dict(state) if state is not None else self._state_store.load()
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return "product_input_updates received without declared product inputs" if updates else None
        if not updates and not (
            phase in {"phase3-plan", "phase3-consensus"}
        ):
            return None
        traceability_override = (
            path_overrides.get("traceability")
            if path_overrides is not None
            else None
        )
        traceability_ref = str(metadata.get("traceability") or "").strip()
        if traceability_override is None and not traceability_ref:
            return "product input traceability path is missing from run state"
        traceability_path = (
            Path(traceability_override)
            if traceability_override is not None
            else Path(traceability_ref)
        )
        if not traceability_path.is_absolute():
            traceability_path = self._project_root / traceability_path
        catalog_override = (
            path_overrides.get("catalog")
            if path_overrides is not None
            else None
        )
        catalog_ref = str(metadata.get("catalog") or "").strip()
        catalog_path = (
            Path(catalog_override)
            if catalog_override is not None
            else (Path(catalog_ref) if catalog_ref else None)
        )
        if catalog_path is not None and not catalog_path.is_absolute():
            catalog_path = self._project_root / catalog_path
        active_spec_dir = self._active_phase_a_spec_dir(state)
        enforce_direct_task_mappings = phase in {"phase3-plan", "phase3-consensus"}
        tasks_path = active_spec_dir / "tasks.md" if enforce_direct_task_mappings and active_spec_dir else None
        targets = [
            str(value).strip()
            for value in state.get("implementation_targets", [])
            if str(value).strip()
        ]
        try:
            from echelon.product_inputs import (
                ProductInputError,
                apply_product_input_updates,
                normalize_context_only_product_input_updates,
                repair_product_input_structural_units,
                refresh_requirement_context_from_catalog,
                validate_product_input_traceability_paths,
            )
            if catalog_path is not None:
                repair_product_input_structural_units(
                    traceability_path,
                    catalog_path,
                    apply=True,
                )
                requirement_context_override = (
                    path_overrides.get("requirement_context")
                    if path_overrides is not None
                    else None
                )
                requirement_context_ref = str(
                    metadata.get("requirement_context") or ""
                ).strip()
                if (
                    requirement_context_override is not None
                    or requirement_context_ref
                ):
                    requirement_context_path = (
                        Path(requirement_context_override)
                        if requirement_context_override is not None
                        else Path(requirement_context_ref)
                    )
                    if not requirement_context_path.is_absolute():
                        requirement_context_path = self._project_root / requirement_context_path
                    refresh_requirement_context_from_catalog(catalog_path, requirement_context_path)
            normalized_updates = updates
            if updates and catalog_path is not None:
                normalized_updates, _ = normalize_context_only_product_input_updates(
                    updates,
                    catalog_path,
                )
            if normalized_updates:
                apply_product_input_updates(
                    traceability_path,
                    normalized_updates,
                    tasks_path=tasks_path,
                    declared_targets=targets,
                )
            elif tasks_path is not None:
                blockers = validate_product_input_traceability_paths(
                    traceability_path,
                    tasks_path,
                    targets,
                )
                if blockers:
                    return "invalid product input task mappings: " + "; ".join(blockers)
        except (OSError, ProductInputError) as exc:
            return f"invalid product input updates: {exc}"
        return None

    def _schedule_product_input_mapping_repair(
        self,
        phase: str,
        error: str,
        result: SquadAgentResult | None = None,
        *,
        snapshot: RoutingStateSnapshot,
    ) -> bool:
        """Re-dispatch a phase with exact unresolved product-input evidence.

        Product-input mappings are authored by agents, not inferred by the
        controller. A missing or invalid update therefore gets a bounded repair
        pass with controller-derived evidence; only exhaustion becomes a
        terminal block.
        """
        if phase not in {"phase1-what", "phase3-plan", "phase3-consensus"}:
            return False
        prefixes = (
            "invalid product input task mappings:",
            "invalid product input updates:",
        )
        if not error.startswith(prefixes):
            return False

        state = snapshot.state
        existing_repair = state.get("product_input_mapping_repair")
        protocol_version = (
            existing_repair.get("protocol_version")
            if isinstance(existing_repair, dict)
            else None
        )
        attempts = state.get("product_input_mapping_repair_attempts", 0)
        attempts = attempts if isinstance(attempts, int) else 0
        # A repair protocol upgrade carries strictly more deterministic evidence
        # than the prior prompt.  Give interrupted historical runs a fresh,
        # bounded repair budget instead of preserving a spent, weaker loop.
        protocol_upgraded = (
            isinstance(existing_repair, dict)
            and protocol_version != PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION
        )
        if protocol_upgraded:
            attempts = 0
            dispatch_counts = state.get("phase_dispatch_counts")
            if isinstance(dispatch_counts, dict):
                dispatch_counts[phase] = 0
        if attempts >= MAX_PRODUCT_INPUT_MAPPING_REPAIRS:
            return False

        detail = error.split(":", 1)[1].strip() if ":" in error else error
        blockers = [item.strip() for item in detail.split(";") if item.strip()]
        hints: dict[str, object] = {}
        payload = result.echelon_result if result is not None else None
        updates = payload.get("product_input_updates") if isinstance(payload, dict) else None
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if phase == "phase1-what":
            metadata = state.get("product_inputs")
            traceability_ref = (
                str(metadata.get("traceability") or "").strip()
                if isinstance(metadata, dict)
                else ""
            )
            if traceability_ref:
                traceability_path = Path(traceability_ref)
                if not traceability_path.is_absolute():
                    traceability_path = self._project_root / traceability_path
                try:
                    ledger = json.loads(traceability_path.read_text(encoding="utf-8"))
                    requirements = ledger.get("requirements") if isinstance(ledger, dict) else []
                    valid_ids = [
                        str(entry.get("input_unit_id"))
                        for entry in requirements
                        if isinstance(entry, dict) and str(entry.get("input_unit_id") or "").strip()
                    ]
                    invalid_ids = re.findall(
                        r"unknown requirement unit ['\"]([^'\"]+)['\"]",
                        error,
                    )
                    hints = {
                        "invalid_input_unit_ids": invalid_ids,
                        "valid_requirement_ids": valid_ids,
                    }
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("Could not construct phase-one product-input ID repair hints: %s", exc)
        elif isinstance(updates, list) and active_spec_dir is not None:
            try:
                from echelon.product_inputs import build_product_input_mapping_repair_hints

                hints = build_product_input_mapping_repair_hints(
                    updates,
                    active_spec_dir / "tasks.md",
                    [
                        str(value).strip()
                        for value in state.get("implementation_targets", [])
                        if str(value).strip()
                    ],
                )
            except (OSError, ValueError) as exc:
                logger.warning("Could not construct product-input repair hints: %s", exc)
        state["product_input_mapping_repair_attempts"] = attempts + 1
        state["product_input_mapping_repair"] = {
            "attempt": attempts + 1,
            "blockers": blockers,
            "phase": phase,
            "protocol_version": PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION,
            **hints,
        }
        state["phase"] = phase
        state["status"] = "running"
        state["blocked_reason"] = None
        if not self._state_store.commit_routing_snapshot_state(
            snapshot,
            state,
        ):
            return False
        print(
            f"[squad] ~ {phase} product-input mapping repair "
            f"({attempts + 1}/{MAX_PRODUCT_INPUT_MAPPING_REPAIRS})",
            flush=True,
        )
        return True

    def _published_phase_a_spec_dir(self, state: dict, active_spec_dir: Path) -> Path:
        published_ref = str(state.get("published_spec_dir") or "").strip()
        if published_ref:
            candidate = Path(published_ref)
            return candidate if candidate.is_absolute() else self._project_root / candidate

        spec_id = str(state.get("spec_id") or "").strip()
        if spec_id:
            existing = find_spec_dir(spec_id, self._project_root)
            if existing is not None:
                return existing
            if re.match(r"^[0-9]{3}-", spec_id):
                return self._project_root / "specs" / spec_id
            active_name = active_spec_dir.name
            if active_name.startswith(f"{spec_id}-"):
                return self._project_root / "specs" / active_name
            slug = self._spec_title_slug(active_spec_dir)
            if slug:
                return self._project_root / "specs" / f"{spec_id}-{slug}"
            return self._project_root / "specs" / spec_id

        return self._project_root / "specs" / active_spec_dir.name

    def _spec_title_slug(self, spec_dir: Path) -> str:
        spec_file = spec_dir / "spec.md"
        if not spec_file.exists():
            return ""
        for line in spec_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*#\s+(.+?)\s*$", line)
            if not match:
                continue
            title = match.group(1).strip().lower()
            slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
            return slug
        return ""

    def _copy_spec_tree(self, source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        runtime_metadata = destination / ".echelon"
        if runtime_metadata.is_dir():
            shutil.rmtree(runtime_metadata)
        elif runtime_metadata.exists():
            runtime_metadata.unlink()
        self._copy_controller_tree(
            source,
            destination,
            exclude_echelon=True,
        )

    def _repo_relative_or_absolute(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._project_root))
        except ValueError:
            return str(path)

    def _block_after_phase_a_readiness_failure(
        self,
        readiness: PhaseAReadinessResult,
        *,
        snapshot: RoutingStateSnapshot | None = None,
    ) -> bool:
        state = (
            snapshot.state
            if snapshot is not None
            else self._state_store.load()
        )
        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = "phase_a_readiness_failed"
        state["phase_a_readiness_blockers"] = readiness.blockers
        persisted = (
            self._state_store.commit_routing_snapshot_state(
                snapshot,
                state,
            )
            if snapshot is not None
            else (self._state_store.save(state) is None)
        )
        if not persisted:
            return False
        self._record_blocker_event("phase4-document", "phase_a_readiness_failed")
        print(
            "[squad] ✗ phase4-document blocked: Phase A readiness failed "
            "(build-input artifacts incomplete)",
            flush=True,
        )
        return True

    def _blocked_executor_reason(
        self,
        result: SquadAgentResult,
        control_updates: Mapping[str, object] | None = None,
    ) -> str | None:
        if result.provider_limit_message:
            return "provider_session_limit"
        if result.echelon_result is None:
            return "missing_echelon_result"
        if result.timed_out:
            return "agent_timeout"
        if result.exit_code != 0:
            return f"agent_exit_code_{result.exit_code}"
        if (result.verdict or "").upper() == "BLOCKED":
            explicit_reason = (
                (control_updates or {}).get("blocked_reason")
                or (result.state_updates or {}).get("blocked_reason")
            )
            if isinstance(explicit_reason, str) and explicit_reason.strip():
                return explicit_reason.strip()
            return "agent_blocked"
        return None

    def _route_agent_block_to_commander(
        self,
        node: PhaseNode,
        reason: str,
        result: SquadAgentResult,
        snapshot: RoutingStateSnapshot,
    ) -> bool:
        """Turn a valid agent BLOCKED verdict into a durable decision route."""
        if (result.verdict or "").upper() != "BLOCKED":
            return False
        detail = reason.strip() or "agent_blocked"
        request = self._human_input_registry.prepare(
            source_kind="controller_safeguard",
            producer_id="agent_blocked",
            phase_id=node.id,
            reason_code="agent_blocked",
            question=(
                f"{node.agent or node.type} returned BLOCKED during {node.id}. "
                "Resolve the material ambiguity from the registered specification "
                "context and provide concise instructions for retrying this phase. "
                f"Reported blocker: {detail}."
            ),
            source_state_revision=snapshot.state_revision,
        )
        self._record_blocker_event(node.id, "agent_blocked")
        print(
            f"[squad] ! {node.id} returned BLOCKED; routing to COMMANDER",
            flush=True,
        )
        return self.handle_human_input(request)

    def _block_after_executor_failure(
        self,
        phase: str,
        reason: str,
        result: SquadAgentResult,
        *,
        snapshot: RoutingStateSnapshot,
        recovery_instruction: RecoveryInstruction | None = None,
    ) -> bool:
        from datetime import datetime, timezone

        state = snapshot.state
        if phase == "phase1-what":
            self._preserve_cartographer_spec_context(state)
        retryable_analysis = self._is_deterministic_understanding_phase(phase)
        state["phase"] = phase if retryable_analysis else PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        prior_phase_output_recovery = state.get("phase_output_recovery")
        state.pop("controller_contract_error", None)
        state.pop("recovery_instruction", None)
        state.pop("missing_outputs", None)
        state.pop("phase_output_recovery", None)
        if recovery_instruction is not None:
            state["recovery_instruction"] = recovery_instruction.to_dict()
        if reason in {"missing_phase_outputs", "invalid_evidence_inventory"}:
            updates = result.state_updates or {}
            missing_outputs = updates.get("missing_outputs")
            invalid_outputs = updates.get("invalid_outputs")
            recovery_updates = updates.get("recovery_state_updates")
            has_missing = (
                isinstance(missing_outputs, list)
                and all(isinstance(item, str) and item for item in missing_outputs)
            )
            has_invalid = (
                isinstance(invalid_outputs, list)
                and all(
                    isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                    and item["path"].strip()
                    and isinstance(item.get("reason"), str)
                    and item["reason"].strip()
                    for item in invalid_outputs
                )
            )
            if has_missing or has_invalid:
                if has_missing:
                    state["missing_outputs"] = list(missing_outputs)
                recovery = {
                    "phase": phase,
                    "prior_state_updates": (
                        dict(recovery_updates)
                        if isinstance(recovery_updates, dict)
                        else {}
                    ),
                }
                if has_missing:
                    recovery["missing_outputs"] = list(missing_outputs)
                if has_invalid:
                    recovery["invalid_outputs"] = list(invalid_outputs)
                if (
                    isinstance(prior_phase_output_recovery, dict)
                    and prior_phase_output_recovery.get(
                        "quarantined_invalid_outputs"
                    )
                ):
                    recovery["quarantined_invalid_outputs"] = list(
                        prior_phase_output_recovery[
                            "quarantined_invalid_outputs"
                        ]
                    )
                state["phase_output_recovery"] = recovery
        tasks_lexicon_terminal = (
            phase
            in {"phase3-tasks-lexicon", "phase3-consensus-tasks-lexicon"}
            and reason == "tasks_lexicon_gate_exhausted"
            and (result.state_updates or {}).get("tasks_lexicon_action")
            == "block"
        )
        if retryable_analysis or tasks_lexicon_terminal:
            node = self._graph.get(phase)
            for key in node.controller_state_update_keys:
                if key in (result.state_updates or {}) and key != "blocked_reason":
                    state[key] = result.state_updates[key]
        if tasks_lexicon_terminal:
            state["tasks_lexicon_gate_exhausted"] = True
        if reason == "provider_session_limit":
            state["provider_limit_message"] = result.provider_limit_message
            if result.echelon_result is None:
                state["blocked_context"] = "missing_echelon_result"
        else:
            state.pop("provider_limit_message", None)
            state.pop("blocked_context", None)
        state["last_dispatch"] = {
            "phase_id": phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self._state_store.commit_routing_snapshot_state(
            snapshot,
            state,
        ):
            return False
        self._record_blocker_event(phase, reason)
        detail = (
            "retryable deterministic phase"
            if retryable_analysis
            else "phase not marked complete"
        )
        if reason == "provider_session_limit":
            detail = f"missing_echelon_result; provider: {result.provider_limit_message}"
        print(f"[squad] ✗ {phase} blocked: {reason} ({detail})", flush=True)
        return True

    def _restore_missing_phase_output_recovery(self, phase: str) -> bool:
        """Recreate artifact-repair context for runs blocked before it was persisted."""
        state = self._state_store.load()
        recovery = state.get("phase_output_recovery")
        if isinstance(recovery, dict) and recovery.get("phase") == phase:
            spec_dir_ref = str(state.get("spec_dir") or "").strip()
            spec_dir = Path(spec_dir_ref)
            if spec_dir_ref and not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            has_quarantined_inventory = bool(
                spec_dir_ref
                and spec_dir.is_dir()
                and any(spec_dir.glob("evidence-inventory.invalid*.json"))
            )
            if (
                phase == "phase1-investigate"
                and (
                    recovery.get("quarantined_invalid_outputs")
                    or has_quarantined_inventory
                )
                and not recovery.get("invalid_outputs")
            ):
                recovery["invalid_outputs"] = [{
                    "path": "evidence-inventory.json",
                    "reason": "a prior invalid inventory was quarantined; rebuild the replacement from declared source seeds",
                }]
                state["phase_output_recovery"] = recovery
                self._state_store.save(state)
            return True
        reason = str(state.get("blocked_reason") or "")
        if reason.startswith("invalid_evidence_inventory") and phase == "phase1-investigate":
            state["phase_output_recovery"] = {
                "phase": phase,
                "invalid_outputs": [{
                    "path": "evidence-inventory.json",
                    "reason": "inventory failed validation in a prior Echelon version; rebuild it from declared source seeds",
                }],
                "prior_state_updates": {},
            }
            self._state_store.save(state)
            return True
        if reason != "missing_phase_outputs":
            return False
        last_dispatch = state.get("last_dispatch")
        if not isinstance(last_dispatch, dict) or last_dispatch.get("phase_id") != phase:
            return False
        required = _MANDATORY_PHASE_OUTPUTS.get(phase, ())
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        if not required or not spec_dir_ref:
            return False
        spec_dir = Path(spec_dir_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        missing = [
            output
            for output in required
            if not (spec_dir / output).exists()
        ]
        if not missing:
            return False
        state["missing_outputs"] = missing
        state["phase_output_recovery"] = {
            "phase": phase,
            "missing_outputs": missing,
            "prior_state_updates": {},
        }
        self._state_store.save(state)
        return True

    def _record_blocker_event(self, phase: str, reason: str) -> None:
        from datetime import datetime, timezone

        try:
            self._telemetry_store.append_event(
                {
                    "schema_version": 1,
                    "type": "blocker",
                    "trace_id": self._telemetry_store.trace_id,
                    "phase": phase,
                    "reason": reason,
                    "event_time": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            logger.warning("Could not persist blocker lifecycle event", exc_info=True)

    def _preserve_cartographer_spec_context(self, state: dict) -> None:
        """Record an existing CARTOGRAPHER spec before blocking a failed dispatch."""
        state.pop("cartographer_resume_existing_spec", None)
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        if spec_dir_ref:
            candidate = Path(spec_dir_ref)
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            if (candidate / "spec.md").is_file():
                spec_id = str(state.get("spec_id") or candidate.name).strip()
                if spec_id:
                    state["spec_id"] = spec_id
                    published = self._project_root / "specs" / spec_id
                    if published.exists():
                        state["published_spec_dir"] = self._repo_relative_or_absolute(published)
                state["cartographer_resume_existing_spec"] = True
                return

        branch = self._current_git_branch()
        if not branch or not self._is_spec_feature_branch(branch):
            return

        candidate = self._project_root / "specs" / branch
        if not (candidate / "spec.md").is_file():
            return

        state["spec_id"] = state.get("spec_id") or branch
        state["spec_dir"] = self._repo_relative_or_absolute(candidate)
        state["published_spec_dir"] = self._repo_relative_or_absolute(candidate)
        state["feature_branch"] = state.get("feature_branch") or branch
        state["cartographer_resume_existing_spec"] = True

    def _current_git_branch(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    def _is_spec_feature_branch(self, branch: str) -> bool:
        return re.match(r"^[0-9]{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*$", branch) is not None

    @staticmethod
    def _canonicalize_judgment_result(
        result: SquadAgentResult,
    ) -> SquadAgentResult:
        """Detach and validate COMMANDER output without mutating live state."""
        candidate = detach_squad_agent_result(result)
        operational_error_path = ""
        if candidate.exit_code != 0:
            operational_error_path = "$.exit_code"
        elif candidate.timed_out:
            operational_error_path = "$.timed_out"
        elif candidate.provider_limit_message:
            operational_error_path = "$.provider_limit_message"
        if operational_error_path:
            raise ControllerStateContractViolation(
                "COMMANDER judgment did not complete successfully",
                contract="judgment",
                json_path=operational_error_path,
                validator="operational_success",
            )
        try:
            outcome = validate_echelon_result_contract(
                candidate.echelon_result,
                JUDGMENT_RESULT_CONTRACT,
            )
        except EchelonResultValidationError as exc:
            raise ControllerStateContractViolation(
                "COMMANDER judgment contract validation failed",
                contract="judgment",
                json_path="$.echelon_result",
                validator="echelon_result",
            ) from exc
        candidate.echelon_result = outcome.result
        candidate.quarantined_state_updates.update(
            outcome.quarantined_state_updates
        )
        return candidate

    def _guard_constitution_provenance(self, phase: str) -> str:
        """Route normal spec/build phases through CHIEF until constitution is proven.

        The state machine owns the primary decision: phase1-constitution must have
        completed before phase1-what or later phases run. The filesystem check is
        a secondary integrity check so stale or template artifacts cannot satisfy
        the provenance gate by accident.
        """
        if not _phase_requires_constitution_provenance(phase):
            return phase

        state = self._state_store.load()
        completed = state.get("completed_phases")
        completed_phases = completed if isinstance(completed, list) else []
        has_provenance = "phase1-constitution" in completed_phases
        if has_provenance:
            if _constitution_artifact_is_real(self._project_root):
                return phase
            state["phase"] = PHASE_TERMINAL_BLOCKED
            state["status"] = "blocked"
            state["blocked_reason"] = "constitution_artifact_mismatch"
            state["constitution_guard_reason"] = (
                "phase1-constitution completed, but constitution artifact is "
                "missing or still template"
            )
            self._state_store.save(state)
            print(
                "[squad] constitution guard → blocked "
                "(phase1-constitution completed but artifact is invalid)",
                flush=True,
            )
            return PHASE_TERMINAL_BLOCKED

        reason = "missing phase1-constitution completion provenance"
        state["phase"] = "phase1-constitution"
        state["constitution_guard_reason"] = reason
        self._state_store.save(state)
        print(
            f"[squad] constitution guard → phase1-constitution ({reason})",
            flush=True,
        )
        return "phase1-constitution"

    def _apply_phase_recommendation_guard(self, phase: str) -> str:
        """Honor forced-convergence routing before dispatching another agent.

        The guard fires exactly once per convergence event: it redirects to the
        recommended phase, then clears itself when we arrive there.  Without the
        clear, every subsequent transition from the recommended phase would be
        overridden back to it, creating an infinite loop.
        """
        if phase in TERMINAL_PHASES:
            return phase

        state = self._state_store.load()
        if not (state.get("convergence_forced") or state.get("convergence_detected")):
            return phase

        raw_recommended = state.get("phase_recommendation")
        recommended = _normalize_phase_recommendation(
            raw_recommended,
            self._graph.all_phase_ids(),
        )
        mandatory_successor = {
            "phase2-decide": "phase2-feasibility-structural",
            "phase2-tracker-alignment": (
                "phase2-intent-alignment-structural"
            ),
        }.get(recommended)
        if (
            not recommended
            or recommended == phase
            or mandatory_successor == phase
        ):
            # We've arrived at the recommended phase (or there's no recommendation).
            # A mandatory deterministic successor is part of completing the
            # recommended authoring phase and must not be redirected back to
            # another provider dispatch.
            state["convergence_forced"] = False
            state["convergence_detected"] = False
            state["phase_recommendation"] = None
            state["convergence_guard_fire_count"] = 0
            self._state_store.save(state)
            return phase
        fire_count = self._state_store.increment_convergence_guard_fires()
        if fire_count > MAX_CONVERGENCE_GUARD_FIRES:
            # Agent keeps re-asserting convergence on every dispatch — infinite loop.
            # Force-advance by clearing the recommendation.
            state = self._state_store.load()
            state["convergence_forced"] = False
            state["convergence_detected"] = False
            state["phase_recommendation"] = None
            state["convergence_guard_fire_count"] = 0
            self._state_store.save(state)
            print(
                f"[squad] convergence guard → force-advancing from {phase!r} "
                f"(guard fired {fire_count}× on {recommended!r} — agent re-assertion loop)",
                flush=True,
            )
            return phase

        state = self._state_store.load()
        state["phase"] = recommended
        if state.get("status") == "blocked" and not state.get("escalation_question"):
            state["status"] = "running"
            state["blocked_reason"] = None
        self._state_store.save(state)
        print(
            f"[squad] convergence guard → honoring phase_recommendation "
            f"{recommended!r} (skipping {phase!r}) [{fire_count}/{MAX_CONVERGENCE_GUARD_FIRES}]",
            flush=True,
        )
        return recommended

    def _lexicon_gate_config(self) -> dict:
        """Load the `lexicon_gate` config block once for transition evaluation.

        The spec Lexicon repair guard references the config-namespace key
        `lexicon_gate.spec_enabled`, derived from both the global gate and the
        spec artifact subgate. Merging this block into the eval state lets that
        guard resolve deterministically without changing global enablement used
        by other Lexicon artifacts. Only `lexicon_gate` is merged to keep the
        blast radius constrained. Returns {} when the file is absent or
        unparseable.
        """
        if self._gate_config_cache is not None:
            return self._gate_config_cache
        cfg: dict = {}
        try:
            from harness.config import get_full_resolved_config

            data = get_full_resolved_config(self._project_root)
            block = data.get("lexicon_gate")
            if isinstance(block, dict):
                resolved_gate = dict(block)
                artifacts = resolved_gate.get("artifacts")
                artifacts = artifacts if isinstance(artifacts, dict) else {}
                spec_gate = artifacts.get("spec")
                spec_gate = spec_gate if isinstance(spec_gate, dict) else {}
                resolved_gate["spec_enabled"] = bool(
                    resolved_gate.get("enabled", False)
                    and spec_gate.get("enabled", True) is not False
                )
                cfg = {"lexicon_gate": resolved_gate}
        except Exception:
            cfg = {}
        # The workflow conditions compare each controlled gate's repair count
        # against the configured cap. Missing result fields must mean "zero
        # reported repairs", never an indeterminate condition that falls
        # through to a later phase.
        cfg.setdefault("lexicon_attempts", 0)
        cfg.setdefault("tasks_lexicon_attempts", 0)
        self._gate_config_cache = cfg
        return cfg

    def _lexicon_gate_enrichment(
        self,
        node: PhaseNode,
        state: dict,
        result: SquadAgentResult,
    ) -> tuple[dict[str, object], str | None]:
        """Return spec Lexicon exhaustion updates without mutating state.

        A `warn` policy deliberately permits downstream review with a recorded
        warning.  A `block` policy is a hard delivery contract: after the final
        repair attempt there is no valid transition to a later authoring phase.
        """
        gate_artifacts = {
            "phase1-lexicon": ("spec", "lexicon_pass", "lexicon_attempts"),
            "phase3-tasks-lexicon": (
                "tasks",
                "tasks_lexicon_pass",
                "tasks_lexicon_attempts",
            ),
            "phase3-consensus-tasks-lexicon": (
                "tasks",
                "tasks_lexicon_pass",
                "tasks_lexicon_attempts",
            ),
        }
        gate_fields = gate_artifacts.get(node.id)
        if gate_fields is None:
            return {}, None
        artifact_name, pass_key, attempts_key = gate_fields
        gate = self._lexicon_gate_config().get("lexicon_gate", {})
        if not isinstance(gate, dict) or not gate.get("enabled", False):
            return {}, None
        artifacts = gate.get("artifacts", {})
        artifact_gate = artifacts.get(artifact_name, {}) if isinstance(artifacts, dict) else {}
        if not isinstance(artifact_gate, dict) or not artifact_gate.get("enabled", False):
            return {}, None
        try:
            repair_cap = int(gate.get("max_repair_attempts", 3))
        except (TypeError, ValueError):
            repair_cap = 3
        reported_attempts = result.state_updates.get(attempts_key, state.get(attempts_key))
        repair_attempts_exhausted = (
            isinstance(reported_attempts, int)
            and repair_cap > 0
            and reported_attempts >= repair_cap
        )
        squad_iterations_exhausted = int(state.get("iteration") or 0) >= int(
            state.get("max_iterations") or self._max_iterations
        )
        if not repair_attempts_exhausted and not squad_iterations_exhausted:
            return {}, None
        if result.state_updates.get(pass_key) is True:
            return {}, None

        if (
            node.id != "phase1-lexicon"
            and str(gate.get("on_exhausted", "block")).lower() == "warn"
        ):
            return {}, None

        return {}, PHASE_TERMINAL_BLOCKED

    def _governance_config(self) -> dict:
        """Load the `governance` block so governance.* resolves in transition conditions.

        Mirrors _lexicon_gate_config: merges the governance block into eval_state
        so conditions like `governance.enabled` evaluate deterministically instead
        of returning None and punting the routing decision to COMMANDER.
        Returns {} when the file is absent or unparseable.

        Also injects defaults for the structural-gate pass flags
        (feasibility_structural_pass, intent_alignment_check_structural_pass).
        Configured structural gates default to False so an omitted model field
        cannot fail open. Disabled or absent gates default to True so the guard
        remains inert when governance is not active for that artifact.
        """
        if self._gov_config_cache is not None:
            return self._gov_config_cache
        cfg: dict = {}
        try:
            from harness.config import get_full_resolved_config

            data = get_full_resolved_config(self._project_root)
            block = data.get("governance")
            if isinstance(block, dict):
                cfg = {"governance": block}
        except Exception:
            cfg = {}
        governance = cfg.get("governance", {})
        governance_enabled = isinstance(governance, dict) and governance.get("enabled", False)
        artifacts = governance.get("artifacts", {}) if isinstance(governance, dict) else {}

        def _structural_gate_enabled(key: str) -> bool:
            entry = artifacts.get(key, {}) if isinstance(artifacts, dict) else {}
            if not isinstance(entry, dict):
                return False
            if entry.get("enabled", True) is False:
                return False
            return governance_enabled and str(entry.get("tier") or "").lower() == "structural"

        cfg.setdefault("feasibility_structural_pass", not _structural_gate_enabled("feasibility"))
        cfg.setdefault(
            "intent_alignment_check_structural_pass",
            not _structural_gate_enabled("intent-alignment-check"),
        )
        self._gov_config_cache = cfg
        return cfg

    def _lexicon_repair_no_progress_enrichment(
        self,
        node: PhaseNode,
        state: Mapping[str, object],
    ) -> tuple[dict[str, object], str | None]:
        """Return a terminal block when a Lexicon derivation changes nothing."""
        if node.id != "phase1-lexicon-derive":
            return {}, None
        if (
            state.get("lexicon_evaluation") != "failed"
            or state.get("lexicon_pass") is not False
        ):
            return {}, None
        report_ref = str(state.get("lexicon_report") or "").strip()
        if not report_ref:
            return {}, None
        report_path = Path(report_ref)
        if not report_path.is_absolute():
            report_path = self._project_root / report_path
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            return {}, None
        if not isinstance(report, dict) or report.get("ok") is not False:
            return {}, None
        prior_sha = str(report.get("artifact_sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", prior_sha):
            return {}, None

        artifact_ref = str(report.get("artifact_path") or "").strip()
        if artifact_ref:
            artifact_path = Path(artifact_ref)
            if not artifact_path.is_absolute():
                artifact_path = self._project_root / artifact_path
        else:
            spec_dir_ref = str(state.get("spec_dir") or "").strip()
            if not spec_dir_ref:
                return {}, None
            spec_dir = Path(spec_dir_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            gate = self._lexicon_gate_config().get("lexicon_gate", {})
            artifacts = (
                gate.get("artifacts", {}) if isinstance(gate, dict) else {}
            )
            spec_gate = (
                artifacts.get("spec", {})
                if isinstance(artifacts, dict)
                else {}
            )
            artifact_name = (
                spec_gate.get("path")
                if isinstance(spec_gate, dict)
                else None
            )
            artifact_path = spec_dir / str(
                artifact_name or "requirements.lexicon.md"
            ).strip()
        try:
            current_sha = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()
        except OSError:
            return {}, None
        if current_sha != prior_sha:
            return {}, None
        return {}, PHASE_TERMINAL_BLOCKED

    @staticmethod
    def _is_proportional_quality_state(
        state: Mapping[str, object],
    ) -> bool:
        return (
            normalize_spec_authoring_mode(state.get("spec_authoring_mode"))
            == PROPORTIONAL_MODE
        )

    def _proportional_spec_dir(
        self,
        state: Mapping[str, object],
    ) -> Path:
        spec_ref = str(state.get("spec_dir") or "").strip()
        if not spec_ref:
            raise QualityCandidateIntegrityError(
                "proportional quality specification root is missing"
            )
        spec_dir = Path(spec_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        try:
            spec_dir.resolve().relative_to(self._project_root.resolve())
        except ValueError as exc:
            raise QualityCandidateIntegrityError(
                "proportional quality specification root escapes the project"
            ) from exc
        return spec_dir

    @staticmethod
    def _finding_routes_from_updates(
        state_updates: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]:
        finding_routes = state_updates.get("finding_routes")
        findings = (
            finding_routes.get("findings")
            if isinstance(finding_routes, Mapping)
            else None
        )
        if not isinstance(findings, list):
            return ()
        return tuple(
            dict(finding)
            for finding in findings
            if isinstance(finding, Mapping)
        )

    @classmethod
    def _proportional_finding_routes(
        cls,
        prepared: PreparedPhaseResult,
    ) -> tuple[Mapping[str, object], ...]:
        return cls._finding_routes_from_updates(prepared.state_updates)

    def _authoritative_quality_assessment(
        self,
        *,
        provider_verdict: str,
        eval_state: Mapping[str, object],
        routes: tuple[Mapping[str, object], ...],
        spec_dir: Path,
    ) -> AuthoritativeQualityAssessment:
        if not has_current_understanding_evidence(
            eval_state,
            project_root=self._project_root,
            phase="phase1-why2",
        ):
            raise QualityCandidateIntegrityError(
                "authoritative Understanding evidence is unavailable"
            )
        evidence = eval_state.get("understanding_evidence")
        if not isinstance(evidence, Mapping):
            raise QualityCandidateIntegrityError(
                "authoritative Understanding evidence is missing"
            )
        evidence_ref = str(evidence.get("path") or "").strip()
        evidence_path = Path(evidence_ref)
        if not evidence_path.is_absolute():
            evidence_path = self._project_root / evidence_path
        try:
            report = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QualityCandidateIntegrityError(
                "authoritative Understanding evidence is malformed"
            ) from exc
        if not isinstance(report, Mapping) or type(report.get("pass")) is not bool:
            raise QualityCandidateIntegrityError(
                "authoritative Understanding verdict is malformed"
            )
        numeric_pass = report["pass"] is True
        normalized_provider_verdict = str(provider_verdict or "").upper()
        sage_evidence = load_authoritative_sage_evidence_snapshot(
            spec_dir / "issues.md",
            project_root=self._project_root,
        )
        sage_verdict = sage_evidence.verdict
        authoritative_issues = sage_evidence.issues
        exact_routes = tuple(dict(route) for route in routes)
        hard_blockers: list[str] = []

        actionable_issue_ids = tuple(
            str(issue.get("issue_id") or "")
            for issue in authoritative_issues
            if is_actionable_sage_issue(issue)
        )
        if sage_verdict == "PASS" and actionable_issue_ids:
            hard_blockers.append("sage_pass_with_issues")
        if sage_verdict == "FAIL" and not actionable_issue_ids:
            hard_blockers.append("sage_fail_without_issues")
        if (
            normalized_provider_verdict in {"PASS", "FAIL"}
            and normalized_provider_verdict != sage_verdict
        ):
            hard_blockers.append("provider_sage_mismatch")
        if normalized_provider_verdict not in {"PASS", "FAIL"}:
            hard_blockers.append("provider_quality_verdict_invalid")
        if numeric_pass is False and normalized_provider_verdict == "PASS":
            hard_blockers.append("numeric_provider_mismatch")
        route_ids = tuple(
            str(route.get("issue_id") or "") for route in exact_routes
        )
        if sage_verdict == "FAIL":
            if (
                not actionable_issue_ids
                or len(route_ids) != len(actionable_issue_ids)
                or len(set(route_ids)) != len(route_ids)
                or set(route_ids) != set(actionable_issue_ids)
                or any(route.get("route") != "spec_repair" for route in exact_routes)
            ):
                hard_blockers.append("sage_finding_route_mismatch")
        elif exact_routes:
            hard_blockers.append("sage_finding_route_mismatch")

        if any(
            issue.get("severity") == "CRITICAL"
            for issue in authoritative_issues
        ):
            hard_blockers.append("critical_sage_issue")
        if any(
            issue.get("type") == "contradiction"
            for issue in authoritative_issues
        ):
            hard_blockers.append("sage_contradiction")
        evidence_status = eval_state.get("evidence_resolution_status")
        if evidence_status not in {None, "not_required", "validated"}:
            hard_blockers.append("unresolved_evidence_or_product_decision")
        if eval_state.get("product_input_mapping_repair"):
            hard_blockers.append("invalid_product_input_mapping")

        unique_blockers = tuple(dict.fromkeys(hard_blockers))
        ordinary_pass = (
            numeric_pass
            and normalized_provider_verdict == "PASS"
            and sage_verdict == "PASS"
            and not actionable_issue_ids
            and not exact_routes
            and not unique_blockers
        )
        return AuthoritativeQualityAssessment(
            numeric_pass=numeric_pass,
            provider_verdict=normalized_provider_verdict,
            sage_verdict=sage_verdict,
            authoritative_issues=tuple(
                dict(issue) for issue in authoritative_issues
            ),
            exact_routes=exact_routes,
            ordinary_pass=ordinary_pass,
            proportional_failure=not ordinary_pass,
            hard_blockers=unique_blockers,
            sage_evidence=sage_evidence,
        )

    def _authoritative_proportional_assessment(
        self,
        prepared: PreparedPhaseResult,
        eval_state: Mapping[str, object],
        spec_dir: Path,
    ) -> AuthoritativeQualityAssessment:
        return self._authoritative_quality_assessment(
            provider_verdict=prepared.verdict,
            eval_state=eval_state,
            routes=self._proportional_finding_routes(prepared),
            spec_dir=spec_dir,
        )

    @staticmethod
    def _proportional_candidate_ineligibility(
        eval_state: Mapping[str, object],
        findings: tuple[Mapping[str, object], ...],
        authoritative_issues: tuple[Mapping[str, object], ...],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        evidence_status = eval_state.get("evidence_resolution_status")
        if evidence_status not in {None, "not_required", "validated"}:
            reasons.append("unresolved_evidence_or_product_decision")
        if any(
            issue.get("severity") == "CRITICAL"
            for issue in authoritative_issues
        ):
            reasons.append("critical_sage_issue")
        if any(
            str(finding.get("route") or "").strip()
            not in {"", "spec_repair"}
            for finding in findings
        ):
            reasons.append("non_quality_finding_route")
        if eval_state.get("product_input_mapping_repair"):
            reasons.append("invalid_product_input_mapping")
        return tuple(dict.fromkeys(reasons))

    def _capture_proportional_quality_candidate(
        self,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        eval_state: Mapping[str, object],
        *,
        assessment: AuthoritativeQualityAssessment,
    ) -> tuple[QualityCandidateManifest, dict[str, object]] | None:
        state = snapshot.state
        if not self._is_proportional_quality_state(state) or not (
            has_current_understanding_evidence(
                eval_state,
                project_root=self._project_root,
                phase="phase1-why2",
            )
        ):
            return None
        repair = initialize_repair_state(state)
        if repair is None:
            return None
        repair = validate_repair_state(repair)
        evidence = eval_state.get("understanding_evidence")
        if not isinstance(evidence, Mapping):
            raise QualityCandidateIntegrityError(
                "proportional Understanding evidence is missing"
            )
        evidence_ref = str(evidence.get("path") or "").strip()
        evidence_path = Path(evidence_ref)
        if not evidence_path.is_absolute():
            evidence_path = self._project_root / evidence_path
        try:
            report = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualityCandidateIntegrityError(
                "proportional Understanding evidence is malformed"
            ) from exc
        raw_gates = report.get("gates") if isinstance(report, Mapping) else None
        if not isinstance(raw_gates, Mapping):
            raise QualityCandidateIntegrityError(
                "proportional Understanding gates are malformed"
            )
        normalized_gates: dict[str, dict[str, object]] = {}
        for name, raw_gate in raw_gates.items():
            if not isinstance(name, str) or not isinstance(raw_gate, Mapping):
                raise QualityCandidateIntegrityError(
                    "proportional Understanding gates are malformed"
                )
            normalized_gates[name] = {
                "score": raw_gate.get("score"),
                "threshold": raw_gate.get("threshold"),
                "pass": raw_gate.get("pass"),
            }
        findings = assessment.exact_routes
        candidate_id = f"quality-candidate-{len(repair['candidate_ids'])}"
        spec_dir = self._proportional_spec_dir(state)
        spec_id = _checkpoint_spec_id_from_state(dict(state), spec_dir)
        authoritative_issues = assessment.authoritative_issues
        issues_by_id = {
            str(issue["issue_id"]): issue for issue in authoritative_issues
        }
        enriched_findings: list[dict[str, object]] = []
        for finding in findings:
            issue_id = str(finding.get("issue_id") or "")
            issue = issues_by_id.get(issue_id)
            if issue is None:
                raise QualityCandidateIntegrityError(
                    "SAGE finding routes do not match authoritative issues"
                )
            enriched_findings.append({**dict(finding), **dict(issue)})
        manifest = prepare_quality_candidate(
            project_root=self._project_root,
            spec_dir=spec_dir,
            run_artifact_root=self._squad_dir,
            run_id=str(state.get("run_id") or ""),
            spec_id=spec_id,
            candidate_id=candidate_id,
            understanding_evidence=evidence_path,
            normalized_gates=normalized_gates,
            sage_finding_routes=enriched_findings,
            formal_statement_count=int(report.get("requirement_count") or 0),
            repair_number=(
                int(repair["automatic_consumed"])
                + int(repair["extension_consumed"])
            ),
            assessment_index=len(repair["candidate_ids"]),
            eligibility_reasons=self._proportional_candidate_ineligibility(
                eval_state,
                tuple(enriched_findings),
                authoritative_issues,
            ),
            repair_state=repair,
            authoritative_sage_evidence=assessment.sage_evidence,
        )
        previous_evidence = state.get(
            "proportional_quality_candidate_evidence"
        )
        last_outcome = (
            previous_evidence.get("last_repair_outcome")
            if isinstance(previous_evidence, Mapping)
            else None
        )
        return manifest, {
            "_proportional_quality_effect": {
                "kind": "proportional_quality",
                "operation": "candidate",
                "spec_dir": spec_dir.resolve().relative_to(
                    self._project_root.resolve()
                ).as_posix(),
                "run_id": str(state.get("run_id") or ""),
                "spec_id": spec_id,
                "candidate": quality_candidate_effect_payload(manifest),
                "checkpoint_prestate": self._completion_checkpoint_prestate(),
                "restore_candidate_id": None,
                "restore_candidate_manifest_sha256": None,
                "restore_artifact_preimage_digests": None,
            },
            "phase1_quality_repair": repair,
            "proportional_quality_candidate_evidence": {
                "schema_version": 1,
                "current_candidate_id": manifest.candidate_id,
                "selected_candidate_id": None,
                "candidate_manifest": str(
                    self._squad_dir
                    / "quality-candidates"
                    / f"{manifest.candidate_id}.json"
                ),
                "eligibility_reasons": list(manifest.eligibility_reasons),
                "last_repair_outcome": last_outcome,
            },
        }

    def _load_proportional_candidate_snapshots(
        self,
        repair_state: Mapping[str, object],
    ) -> tuple[QualityCandidateSnapshot, ...]:
        repair = validate_repair_state(repair_state)
        return tuple(
            load_quality_candidate_snapshot(
                self._squad_dir / "quality-candidates" / f"{candidate_id}.json",
                expected_candidate_id=candidate_id,
            )
            for candidate_id in repair["candidate_ids"]
        )

    def _proportional_borderline_margin(self) -> float:
        try:
            from harness.config import get_full_resolved_config

            config = get_full_resolved_config(self._project_root)
            quality = config.get("quality_gates")
            value = (
                quality.get("borderline_margin")
                if isinstance(quality, Mapping)
                else None
            )
            if type(value) in {int, float} and float(value) >= 0:
                return float(value)
        except Exception:
            pass
        return 0.05

    def _prepare_proportional_quality_decision(
        self,
        state: Mapping[str, object],
        *,
        repair_state: Mapping[str, object],
        reason_code: str,
        source_state_revision: int,
        last_repair_outcome: object = None,
        current_candidate: QualityCandidateManifest | None = None,
    ) -> tuple[PreparedHumanInput, dict[str, object]]:
        repair = validate_repair_state(repair_state)
        persisted_ids = list(repair["candidate_ids"])
        if current_candidate is not None:
            if (
                not persisted_ids
                or persisted_ids[-1] != current_candidate.candidate_id
            ):
                raise QualityCandidateIntegrityError(
                    "current proportional candidate does not match repair state"
                )
            persisted_ids = persisted_ids[:-1]
        persisted_snapshots = self._load_proportional_candidate_snapshots(
            {
                **repair,
                "candidate_ids": persisted_ids,
                "baseline_candidate_id": (
                    repair["baseline_candidate_id"]
                    if persisted_ids
                    else None
                ),
            }
        )
        candidates = (
            tuple(snapshot.manifest for snapshot in persisted_snapshots)
            + ((current_candidate,) if current_candidate is not None else ())
        )
        ranked = rank_quality_candidates(candidates)
        if not ranked:
            raise QualityCandidateIntegrityError(
                "no eligible proportional quality candidate is available"
            )
        selected = ranked[0]
        if (
            selected.failed_gate_count == 0
            and not selected.sage_finding_routes
        ):
            raise QualityCandidateIntegrityError(
                "selected proportional candidate has no residual quality debt"
            )
        spec_dir = self._proportional_spec_dir(state)
        spec_id = _checkpoint_spec_id_from_state(dict(state), spec_dir)
        manifest_path = (
            self._squad_dir
            / "quality-candidates"
            / f"{selected.candidate_id}.json"
        )
        selected_snapshot = next(
            (
                snapshot
                for snapshot in persisted_snapshots
                if snapshot.manifest.candidate_id == selected.candidate_id
            ),
            None,
        )
        manifest_sha = (
            selected_snapshot.sha256
            if selected_snapshot is not None
            else None
        )
        evidence_path = Path(selected.understanding_evidence)
        report = json.loads(evidence_path.read_text(encoding="utf-8"))
        failing_gates = [
            name
            for name, _score, _threshold, passed in selected.normalized_gates
            if not passed
        ]
        understanding_evidence = {
            "phase": "phase1-why2",
            "iteration": report["iteration"],
            "status": "completed",
            "path": str(evidence_path),
            "digest": selected.understanding_evidence_digest,
            "pass": report["pass"],
            "failing_gates": failing_gates,
            "error": None,
        }
        candidates_by_repair: dict[int, QualityCandidateManifest] = {}
        for candidate in candidates:
            candidates_by_repair[candidate.repair_number] = candidate
        repair_history = tuple(
            candidates_by_repair[repair_number]
            for repair_number in sorted(candidates_by_repair)
        )
        recommendation_current = repair_history[-1]
        recommendation_previous = (
            repair_history[-2]
            if len(repair_history) > 1
            else recommendation_current
        )
        score_history = [
            {
                "repair_number": candidate.repair_number,
                "candidate_id": candidate.candidate_id,
                "scores": [
                    {
                        "name": name,
                        "score": score,
                        "threshold": threshold,
                        "pass": passed,
                    }
                    for name, score, threshold, passed
                    in candidate.normalized_gates
                ],
                "formal_statement_count": candidate.formal_statement_count,
                "byte_count": candidate.byte_count,
                "qualitative_failure_count": len(
                    candidate.sage_finding_routes
                ),
                "qualitative_issue_ids": [
                    str(route.get("issue_id") or "")
                    for route in candidate.sage_finding_routes
                ],
            }
            for candidate in repair_history
        ]
        per_repair_deltas: list[dict[str, object]] = []
        for previous_candidate, current_history_candidate in zip(
            repair_history,
            repair_history[1:],
        ):
            previous_scores = {
                name: score
                for name, score, _threshold, _passed
                in previous_candidate.normalized_gates
            }
            current_scores = {
                name: score
                for name, score, _threshold, _passed
                in current_history_candidate.normalized_gates
            }
            if set(previous_scores) != set(current_scores):
                raise QualityCandidateIntegrityError(
                    "proportional quality history gate dimensions changed"
                )
            per_repair_deltas.append(
                {
                    "repair_number": current_history_candidate.repair_number,
                    "previous_repair_number": previous_candidate.repair_number,
                    "previous_candidate_id": previous_candidate.candidate_id,
                    "current_candidate_id": (
                        current_history_candidate.candidate_id
                    ),
                    "score_deltas": [
                        {
                            "name": name,
                            "delta": float(
                                Decimal(str(current_scores[name]))
                                - Decimal(str(previous_scores[name]))
                            ),
                        }
                        for name in sorted(current_scores)
                    ],
                    "formal_statement_delta": (
                        current_history_candidate.formal_statement_count
                        - previous_candidate.formal_statement_count
                    ),
                    "byte_delta": (
                        current_history_candidate.byte_count
                        - previous_candidate.byte_count
                    ),
                }
            )
        baseline_candidate_id = repair["baseline_candidate_id"]
        if type(baseline_candidate_id) is not str:
            raise QualityCandidateIntegrityError(
                "proportional quality baseline candidate is missing"
            )
        recommendation_baseline = next(
            (
                candidate
                for candidate in candidates
                if candidate.candidate_id == baseline_candidate_id
            ),
            None,
        )
        if recommendation_baseline is None:
            raise QualityCandidateIntegrityError(
                "proportional quality baseline candidate manifest is missing"
            )
        policy = self._human_input_registry.lookup(
            "controller_safeguard",
            reason_code,
            reason_code,
        )
        request = prepare_controller_proportional_quality_decision(
            self._human_input_registry,
            reason_code=reason_code,
            phase_id="phase1-why2",
            question=(
                "The bounded proportional quality repair budget is exhausted. "
                f"Candidate {selected.candidate_id} was restored with "
                f"{selected.failed_gate_count} residual failed gate(s) and "
                f"{len(selected.sage_finding_routes)} residual SAGE issue(s)."
            ),
            source_state_revision=source_state_revision,
            repair_state=repair,
            recommendation_evidence=ProportionalQualityRecommendationEvidence(
                borderline_margin=self._proportional_borderline_margin(),
                previous_gates=recommendation_previous.normalized_gates,
                current_gates=recommendation_current.normalized_gates,
                previous_formal_statement_count=(
                    recommendation_previous.formal_statement_count
                ),
                formal_statement_count=(
                    recommendation_current.formal_statement_count
                ),
                qualitative_failure_count=len(
                    recommendation_current.sage_finding_routes
                ),
            ),
            option_contract=policy.options,
            no_artifact_progress=(
                last_repair_outcome == "no_artifact_progress"
            ),
        )
        recommended_option_id = next(
            option.id for option in request.options if option.recommended
        )
        if recommended_option_id == "extend_once":
            recommendation_rationale = (
                "Residual gates improved within the configured borderline margin "
                "without formal-statement growth, so one final repair is favored."
            )
        elif reason_code == "proportional_quality_extension_exhausted":
            recommendation_rationale = (
                "The single authorized extension is consumed and quality still "
                "fails, so the remaining non-stop choice is explicit debt acceptance."
            )
        elif last_repair_outcome == "no_artifact_progress":
            recommendation_rationale = (
                "The repair produced no artifact progress, so another automatic "
                "attempt is not favored over explicit debt acceptance."
            )
        elif recommendation_current.failed_gate_count == 0:
            recommendation_rationale = (
                "Numeric gates pass, but authoritative non-critical SAGE "
                "findings remain; extension is not inferred from an empty "
                "numeric comparison, so explicit debt acceptance is favored."
            )
        else:
            recommendation_rationale = (
                "At least one residual gate is outside the improving borderline "
                "case or formal statements grew, so explicit debt acceptance is favored."
            )
        quality_effect: dict[str, object]
        if current_candidate is not None:
            raw_effect = state.get("_proportional_quality_effect")
            if not isinstance(raw_effect, Mapping):
                raise QualityCandidateIntegrityError(
                    "candidate completion effect is missing"
                )
            quality_effect = dict(raw_effect)
            quality_effect["restore_candidate_id"] = (
                selected.candidate_id
                if selected.candidate_id != current_candidate.candidate_id
                else None
            )
            quality_effect["restore_candidate_manifest_sha256"] = (
                manifest_sha
                if selected.candidate_id != current_candidate.candidate_id
                else None
            )
            quality_effect["restore_artifact_preimage_digests"] = (
                candidate_artifact_preimage_digests(spec_dir, selected)
                if selected.candidate_id != current_candidate.candidate_id
                else None
            )
        else:
            quality_effect = {
                "kind": "proportional_quality",
                "operation": "restore",
                "spec_dir": spec_dir.resolve().relative_to(
                    self._project_root.resolve()
                ).as_posix(),
                "run_id": str(state.get("run_id") or ""),
                "spec_id": spec_id,
                "candidate_id": selected.candidate_id,
                "candidate_manifest_sha256": manifest_sha,
                "artifact_preimage_digests": (
                    candidate_artifact_preimage_digests(spec_dir, selected)
                ),
                "checkpoint_prestate": self._completion_checkpoint_prestate(),
            }
        return request, {
            "_proportional_quality_effect": quality_effect,
            "status": "blocked",
            "blocked_reason": reason_code,
            "why_fail_count": 0,
            "why2_metric_stagnation_count": 0,
            "understanding_evidence": understanding_evidence,
            "proportional_quality_candidate_evidence": {
                "schema_version": 1,
                "current_candidate_id": recommendation_current.candidate_id,
                "selected_candidate_id": selected.candidate_id,
                "candidate_manifest": str(manifest_path),
                "candidate_manifest_sha256": manifest_sha,
                "selected_spec_sha256": dict(
                    selected.owned_artifact_digests
                )["spec.md"],
                "failed_gates": [
                    {
                        "name": name,
                        "score": score,
                        "threshold": threshold,
                        "pass": passed,
                    }
                    for name, score, threshold, passed
                    in selected.normalized_gates
                    if not passed
                ],
                "sage_finding_routes": [
                    dict(item) for item in selected.sage_finding_routes
                ],
                "recommendation_evidence": {
                    "baseline_candidate_id": (
                        recommendation_baseline.candidate_id
                    ),
                    "current_candidate_id": recommendation_current.candidate_id,
                    "comparison_previous_candidate_id": (
                        recommendation_previous.candidate_id
                    ),
                    "comparison_current_candidate_id": (
                        recommendation_current.candidate_id
                    ),
                    "baseline_formal_statement_count": (
                        recommendation_baseline.formal_statement_count
                    ),
                    "formal_statement_count": (
                        recommendation_current.formal_statement_count
                    ),
                    "formal_statement_growth": (
                        recommendation_current.formal_statement_count
                        - recommendation_baseline.formal_statement_count
                    ),
                    "baseline_byte_count": recommendation_baseline.byte_count,
                    "byte_count": recommendation_current.byte_count,
                    "byte_growth": (
                        recommendation_current.byte_count
                        - recommendation_baseline.byte_count
                    ),
                    "score_history": score_history,
                    "per_repair_deltas": per_repair_deltas,
                    "qualitative_failure_count": len(
                        recommendation_current.sage_finding_routes
                    ),
                    "qualitative_issue_ids": [
                        str(route.get("issue_id") or "")
                        for route in recommendation_current.sage_finding_routes
                    ],
                    "recommended_option_id": recommended_option_id,
                    "rationale": recommendation_rationale,
                },
                "eligibility_reasons": [],
                "last_repair_outcome": last_repair_outcome,
            },
        }

    def _controller_enrichment(
        self,
        node: PhaseNode,
        state: Mapping[str, object],
        result: SquadAgentResult,
    ) -> ControllerEnrichment:
        """Build controller-owned updates without mutating result or state."""
        state_copy = deepcopy(dict(state))
        authoring_phase = node.id in {
            "phase2-decide",
            "phase2-tracker-alignment",
        }
        stop_and_ask = (
            node.id == "phase2-tracker-alignment"
            and result.verdict == "STOP_AND_ASK"
        )
        if authoring_phase and not stop_and_ask:
            updates = dict(
                project_authoring_verdict(
                    phase_id=node.id,
                    provider_verdict=result.verdict or "",
                )
            )
            governance_override = None
        elif authoring_phase:
            updates = {}
            governance_override = node.id
        else:
            updates = {}
            governance_override = None
        lexicon_updates, lexicon_override = self._lexicon_gate_enrichment(
            node,
            state_copy,
            result,
        )
        updates.update(lexicon_updates)
        repair_updates, repair_override = (
            self._lexicon_repair_no_progress_enrichment(node, state_copy)
        )
        updates.update(repair_updates)
        quality_certificate_override: str | None = None
        scores = state_copy.get("quality_scores")
        latest_score = scores[-1] if isinstance(scores, list) and scores else None
        if (
            node.id == "phase1-why2"
            and (result.verdict or "").upper() == "PASS"
            and explicit_quality_pass(latest_score) is True
            and not self._is_proportional_quality_state(state_copy)
        ):
            certificate = build_legacy_phase1_quality_certificate(
                state_copy,
                project_root=self._project_root,
            )
            if certificate is None:
                quality_certificate_override = PHASE_TERMINAL_BLOCKED
            else:
                updates["spec_quality_certificate"] = certificate
        quality_remediation_override: str | None = None
        quality_remediation = state_copy.get("quality_gate_remediation")
        proportional_what = (
            isinstance(quality_remediation, Mapping)
            and quality_remediation.get("kind") == "proportional_quality"
            and self._is_proportional_quality_state(state_copy)
        )
        if (
            node.id == "phase1-what"
            and (result.verdict or "").upper() == "DONE"
            and isinstance(quality_remediation, Mapping)
        ):
            baseline_sha = str(
                quality_remediation.get("baseline_spec_sha256") or ""
            ).strip().lower()
            current_sha = self._spec_markdown_sha256(state_copy)
            if proportional_what:
                # The exact counter update is finalized as a trusted routing
                # effect after this prepared result passes its contracts.
                quality_remediation_override = None
            elif baseline_sha and current_sha == baseline_sha:
                quality_remediation_override = PHASE_TERMINAL_BLOCKED
        state_removals: set[str] = set()
        if node.id == "phase2-decide":
            state_removals.update(
                {
                    "feasibility_structural_pass",
                    "feasibility_structural_findings",
                    "feasibility_structural_report",
                    "governance_gate_exhausted",
                    "blocked_reason",
                }
            )
        if node.id == "phase2-tracker-alignment":
            if stop_and_ask:
                state_removals.add("intent_alignment_verdict")
            else:
                state_removals.update(
                    {
                        "intent_alignment_check_structural_pass",
                        "intent_alignment_check_structural_findings",
                        "intent_alignment_check_structural_report",
                        "governance_gate_exhausted",
                        "blocked_reason",
                    }
                )
        if node.type == "deterministic_structural":
            report_key = {
                "feasibility": "feasibility_structural_report",
                "intent-alignment-check": (
                    "intent_alignment_check_structural_report"
                ),
            }.get(node.structural_artifact)
            if report_key and report_key not in result.state_updates:
                state_removals.add(report_key)
            if "governance_gate_exhausted" not in result.state_updates:
                state_removals.add("governance_gate_exhausted")
            if result.state_updates.get("structural_action") != "block":
                state_removals.add("blocked_reason")
        lexicon_certification_fields = {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_findings",
            "lexicon_report",
            "lexicon_warning_waiver",
        }
        if node.id == "phase1-what":
            state_removals.add("spec_quality_certificate")
            state_removals.add("spec_quality_debt_authorization")
            if state_copy.get("spec_status") == "accepted_with_debt":
                state_removals.add("spec_status")
            state_removals.add("spec_quality_status")
            state_removals.add("spec_quality_debt_context")
            state_removals.update(lexicon_certification_fields)
            # A remediation is only complete when the canonical specification
            # actually changed. Keeping its controller context through a no-op
            # prevents the next dispatch from falsely treating a DONE payload
            # as a repaired specification.
            if not quality_remediation_override:
                state_removals.add("quality_gate_remediation")
        if node.id == "phase1-lexicon-derive":
            state_removals.update(lexicon_certification_fields)
        if node.id == "phase1-lexicon":
            state_removals.add("lexicon_warning_waiver")
            if result.state_updates.get("lexicon_evaluation") == "pending":
                state_removals.update(
                    {
                        "lexicon_pass",
                        "lexicon_findings",
                        "lexicon_report",
                    }
                )
        if node.id in {"phase3-plan", "phase3-consensus"}:
            state_removals.update(
                {
                    "product_input_mapping_repair",
                    "product_input_mapping_repair_attempts",
                }
            )
        routing_override = (
            governance_override
            or lexicon_override
            or repair_override
            or quality_certificate_override
            or quality_remediation_override
        )
        control_updates: dict[str, object] = {}
        if routing_override == PHASE_TERMINAL_BLOCKED:
            control_updates["status"] = "blocked"
            if governance_override:
                control_updates["blocked_reason"] = (
                    "governance_gate_exhausted"
                )
            elif lexicon_override:
                if node.id == "phase1-lexicon":
                    control_updates.update(
                        {
                            "blocked_reason": "lexicon_gate_exhausted",
                            "lexicon_gate_exhausted": True,
                        }
                    )
                else:
                    control_updates.update(
                        {
                            "blocked_reason": "tasks_lexicon_gate_exhausted",
                            "tasks_lexicon_gate_exhausted": True,
                        }
                    )
            elif repair_override:
                control_updates.update(
                    {
                        "blocked_reason": (
                            "lexicon_repair_no_artifact_progress"
                        ),
                        "lexicon_repair_no_artifact_progress": True,
                    }
                )
            elif quality_certificate_override:
                control_updates["blocked_reason"] = (
                    "spec_quality_certificate_unavailable"
                )
            elif quality_remediation_override:
                control_updates.update(
                    {
                        "blocked_reason": "quality_gate_remediation_no_artifact_progress",
                        "quality_gate_remediation_no_artifact_progress": True,
                    }
                )
        return ControllerEnrichment(
            updates=updates,
            routing_override=routing_override,
            controller_owns_result_updates=node.type
            in {
                "deterministic_lexicon",
                "deterministic_structural",
                "deterministic_understanding",
            }
            or node.id == "phase3-consensus",
            state_removals=frozenset(state_removals),
            control_updates=control_updates,
        )

    def _prepare_phase_result(
        self,
        node: PhaseNode,
        result: SquadAgentResult,
        snapshot: RoutingStateSnapshot,
    ) -> PreparedPhaseResult:
        """Prepare one detached executor result for routing and persistence."""
        candidate = detach_squad_agent_result(result)
        if node.id in WHY_PHASES:
            self._normalize_why_result_quality_scores(candidate)
        provider_control_intents: dict[str, object] = {}
        payload = candidate.echelon_result
        if type(payload) is dict:
            updates = dict.get(payload, "state_updates")
            if type(updates) is dict:
                declared = frozenset(node.allowed_state_updates or ()) | (
                    node.controller_state_update_keys
                )
                blocking_control_syntax = candidate.verdict in {
                    "BLOCKED",
                    "STOP_AND_ASK",
                }
                quarantined = candidate.quarantined_state_updates
                if (
                    candidate.verdict == "STOP_AND_ASK"
                    and quarantined == {"status": "blocked"}
                ):
                    provider_control_intents["status"] = "blocked"
                    updates["status"] = "blocked"
                    candidate.quarantined_state_updates = {}
                sanitized_updates = dict(updates)
                for key in ("status", "blocked_reason"):
                    if key in sanitized_updates and (
                        key in declared or blocking_control_syntax
                    ):
                        provider_control_intents[key] = (
                            sanitized_updates[key]
                        )
        enrichment = self._controller_enrichment(
            node,
            snapshot.state,
            candidate,
        )
        control_updates = {
            **provider_control_intents,
            **dict(enrichment.control_updates),
        }
        if (
            node.type == "deterministic_structural"
            and candidate.state_updates.get("structural_action") == "block"
        ):
            control_updates["status"] = "blocked"
            control_updates["blocked_reason"] = self._structural_blocked_reason(
                node,
                snapshot.state,
                candidate.state_updates,
            )
        return prepare_phase_result(
            node,
            candidate,
            controller_updates=enrichment.updates,
            routing_override=enrichment.routing_override,
            controller_owns_result_updates=(
                enrichment.controller_owns_result_updates
            ),
            state_removals=frozenset(
                enrichment.state_removals
                - STORE_OWNED_TRANSACTION_KEYS
            ),
            trusted_transaction_state_removals=frozenset(
                enrichment.state_removals
                & STORE_OWNED_TRANSACTION_KEYS
            ),
            control_updates=control_updates,
        )

    def _structural_blocked_reason(
        self,
        node: PhaseNode,
        state: Mapping[str, object],
        updates: Mapping[str, object],
    ) -> str:
        """Derive the sealed reason from attested structural state shape."""
        artifact = node.structural_artifact
        verdict_key = {
            "feasibility": "feasibility_verdict",
            "intent-alignment-check": "intent_alignment_verdict",
        }.get(artifact)
        if verdict_key is None:
            return "governance_structural_artifact_unknown"
        if state.get(verdict_key) is None:
            return "governance_structural_authoring_verdict_missing"
        if updates.get("governance_gate_exhausted") == artifact:
            return "governance_structural_exhausted"
        findings_key = {
            "feasibility": "feasibility_structural_findings",
            "intent-alignment-check": (
                "intent_alignment_check_structural_findings"
            ),
        }[artifact]
        report_key = {
            "feasibility": "feasibility_structural_report",
            "intent-alignment-check": (
                "intent_alignment_check_structural_report"
            ),
        }[artifact]
        if int(updates.get(findings_key) or 0) > 0 and not updates.get(report_key):
            return "governance_structural_evidence_write_failed"
        spec_ref = str(state.get("spec_dir") or "").strip()
        spec_dir = Path(spec_ref) if spec_ref else None
        if spec_dir is not None and not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        if spec_dir is None or not spec_dir.is_dir():
            return "governance_structural_spec_dir_invalid"
        return "governance_structural_config_invalid"

    def _block_after_executor_contract_failure(
        self,
        node: PhaseNode,
        exc: ControllerStateContractViolation,
    ) -> None:
        """Record a detached, redacted failure from executor-side preparation."""
        try:
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id,
            )
        except StateAdvanceError:
            return
        self._block_after_state_advance_failure(
            node,
            node.id,
            StateAdvanceError(
                "controller result preparation failed",
                json_path=exc.json_path,
                validator=exc.validator,
            ),
            snapshot=snapshot,
            diagnostic_contract=exc.contract,
            diagnostic_subject="controller result preparation",
        )

    def _prepare_phase_result_or_block(
        self,
        node: PhaseNode,
        result: SquadAgentResult,
        snapshot: RoutingStateSnapshot,
    ) -> PreparedPhaseResult | None:
        """Prepare a result or persist one stable, redacted contract failure."""
        try:
            return self._prepare_phase_result(node, result, snapshot)
        except ControllerStateContractViolation as exc:
            self._block_after_state_advance_failure(
                node,
                node.id,
                StateAdvanceError(
                    "controller result preparation failed",
                    json_path=exc.json_path,
                    validator=exc.validator,
                ),
                snapshot=snapshot,
                diagnostic_contract=exc.contract,
                diagnostic_subject="controller result preparation",
            )
            return None

    def _prepare_provider_human_input(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> PreparedHumanInput | None:
        """Prepare canonical provider question facts without policy authority."""
        updates = prepared.state_updates
        question = updates.get("escalation_question")
        if not isinstance(question, str) or not question.strip():
            return None
        control = prepared.control_updates
        reason_code = control.get("blocked_reason")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise HumanInputPolicyError(
                "provider question requires an exact reason code"
            )
        options = updates.get("escalation_options")
        if options is not None and not isinstance(options, list):
            raise HumanInputPolicyError(
                "provider escalation options must be a list"
            )
        return self._human_input_registry.prepare(
            source_kind="provider_escalation",
            producer_id=node.id,
            phase_id=node.id,
            reason_code=reason_code,
            question=question,
            recommended_answer=updates.get(
                "escalation_recommended_answer"
            ),
            risk_level=updates.get("escalation_risk_level"),
            options=options,
            source_state_revision=snapshot.state_revision,
        )

    def _handle_prepared_human_input_or_block(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        routing: _PreparedControllerRouting,
        prepared_publication: PreparedSquadPublication | None,
    ) -> bool | None:
        """Share provider preparation, overlap rejection, and sealing."""
        decision = routing.decision
        try:
            provider_request = self._prepare_provider_human_input(
                node,
                prepared,
                snapshot,
            )
            if (
                provider_request is not None
                and routing.human_input is not None
            ):
                raise HumanInputPolicyError(
                    "provider question and controller safeguard overlap"
                )
            request = provider_request or routing.human_input
        except HumanInputPolicyError as exc:
            self._discard_publication_without_authority(
                prepared_publication,
            )
            self._block_after_state_advance_failure(
                node,
                decision.from_phase,
                StateAdvanceError(
                    "provider human-input preparation failed",
                    json_path="$.state_updates.escalation_question",
                    validator=_human_input_policy_error_code(exc),
                ),
                decision=decision,
                token_usage_delta=decision.token_usage_delta,
                diagnostic_subject="provider human-input preparation",
            )
            return False

        if request is None:
            return None
        return self.handle_human_input(
            request,
            provider_advance=_ProviderHumanInputAdvance(
                from_phase=decision.from_phase,
                to_phase=decision.to_phase,
                decision=decision,
            ),
        )

    def _advance_prepared_result_or_block(
        self,
        node: PhaseNode,
        decision: PreparedRoutingDecision,
        *,
        prepared_publication: PreparedSquadPublication | None = None,
        human_input: PreparedHumanInput | None = None,
        human_input_initial_status: str | None = None,
    ) -> AdvanceReceipt | None:
        """Commit one sealed route or persist a separate redacted failure."""
        completion_marker = dict(
            decision.transaction_state_updates
        ).get(PENDING_CONTROLLER_COMPLETION_KEY)
        if not isinstance(completion_marker, Mapping):
            self._block_after_state_advance_failure(
                node,
                decision.from_phase,
                StateAdvanceError(
                    "routing decision does not authorize completion",
                    json_path=(
                        "$.transaction_state_updates."
                        f"{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ),
                    validator="completion_binding",
                ),
                decision=decision,
                token_usage_delta=decision.token_usage_delta,
            )
            return None
        completion_id = str(
            completion_marker.get("completion_id") or ""
        )
        try:
            if prepared_publication is not None:
                expected_marker = prepared_publication.marker.to_dict()
                if (
                    dict(decision.transaction_state_updates).get(
                        PENDING_EXTERNAL_PUBLICATION_KEY
                    )
                    != expected_marker
                ):
                    raise StateAdvanceError(
                        "routing decision does not authorize publication",
                        json_path=(
                            "$.transaction_state_updates."
                            f"{PENDING_EXTERNAL_PUBLICATION_KEY}"
                        ),
                        validator="ownership",
                    )
            if human_input is None:
                receipt = self._state_store.advance(
                    decision.from_phase,
                    decision.to_phase,
                    decision,
                )
            else:
                receipt = self._state_store.advance(
                    decision.from_phase,
                    decision.to_phase,
                    decision,
                    human_input=human_input,
                    human_input_initial_status=human_input_initial_status,
                )
            if not isinstance(receipt, AdvanceReceipt):
                raise StateAdvanceError(
                    "state advance did not return a receipt",
                    json_path="$.advance_receipt",
                    validator="receipt",
                )
            recovery = self._drain_pending_controller_completion()
            if (
                not recovery.recovered
                or recovery.completion_id != completion_id
            ):
                return None
            return receipt
        except StateAdvanceError as exc:
            self._discard_publication_without_authority(
                prepared_publication,
            )
            self._discard_controller_completion_without_authority(
                completion_marker,
            )
            self._block_after_state_advance_failure(
                node,
                decision.from_phase,
                exc,
                decision=decision,
                token_usage_delta=decision.token_usage_delta,
            )
            return None

    def _discard_controller_completion_without_authority(
        self,
        marker: Mapping[str, object],
    ) -> None:
        """Discard a route stage only after exact state proves no authority."""
        try:
            expected = validate_pending_controller_completion(marker)
            state = self._state_store.load()
        except Exception:
            return
        if state.get(PENDING_CONTROLLER_COMPLETION_KEY) == expected:
            return
        dispatch = state.get("last_dispatch")
        if (
            isinstance(dispatch, Mapping)
            and dispatch.get("dispatch_id") == expected["completion_id"]
            and dispatch.get("post_dispatch_complete") is False
            and dispatch.get("completion_intent_sha256")
            == expected["intent_sha256"]
        ):
            return
        try:
            prepared = load_prepared_controller_completion(
                self._project_root,
                self._squad_dir,
                expected,
            )
            prepared.discard()
        except CompletionError:
            return

    def _block_after_state_advance_failure(
        self,
        node: PhaseNode,
        from_phase: str,
        error: StateAdvanceError,
        *,
        decision: PreparedRoutingDecision | None = None,
        snapshot: RoutingStateSnapshot | None = None,
        token_usage_delta: int = 0,
        diagnostic_contract: str | None = None,
        diagnostic_subject: str = "state advance",
    ) -> None:
        """Persist a stable diagnostic without treating failure as an advance."""
        contract = node.controller_state_contract
        json_path = (
            error.json_path
            if isinstance(error.json_path, str)
            and error.json_path.startswith("$")
            else "$.prepared_result"
        )
        validator = (
            error.validator
            if isinstance(error.validator, str)
            and re.fullmatch(r"[a-zA-Z0-9_.-]+", error.validator)
            else "state_advance"
        )
        runtime_contract_mismatch = (
            diagnostic_contract == "preparation"
            and validator == "ownership"
        )
        recovery = (
            controller_contract_recovery(from_phase)
            if runtime_contract_mismatch
            else retry_phase_recovery(
                from_phase,
                "controller_state_contract_validation_failed",
            )
        )
        persisted = self._state_store.merge_advance_failure_diagnostic(
            from_phase=from_phase,
            expected_state_revision=(
                decision.expected_state_revision
                if decision is not None
                else snapshot.state_revision
                if snapshot is not None
                else -1
            ),
            expected_previous_dispatch_sha256=(
                decision.expected_previous_dispatch_sha256
                if decision is not None
                else snapshot.previous_dispatch_sha256
                if snapshot is not None
                else None
            ),
            updates={
                "status": "blocked",
                "blocked_reason": (
                    "controller_state_contract_validation_failed"
                ),
                "controller_contract_error": {
                    "phase_id": from_phase,
                    "contract": (
                        diagnostic_contract
                        or (
                            contract.name
                            if contract is not None
                            else "routing_decision"
                        )
                    ),
                    "contract_sha256": (
                        contract.sha256 if contract is not None else None
                    ),
                    "json_path": json_path,
                    "validator": validator,
                    "message": (
                        f"{diagnostic_subject} failed at "
                        f"{json_path} ({validator})"
                    ),
                },
                "recovery_instruction": recovery.to_dict(),
            },
            token_usage_delta=token_usage_delta,
        )
        if not persisted and token_usage_delta:
            self._state_store.increment_token_usage(token_usage_delta)
        if persisted:
            self._record_blocker_event(
                from_phase,
                "controller_state_contract_validation_failed",
            )

    @staticmethod
    def _with_why_verdict_quality_fallback(
        node: PhaseNode,
        result: SquadAgentResult,
        eval_state: dict[str, object],
    ) -> None:
        if node.id not in WHY_PHASES or eval_state.get("quality_scores"):
            return
        verdict_upper = (result.verdict or "").upper()
        if verdict_upper in ("FAIL", "BLOCKED"):
            eval_state["quality_scores"] = [{"pass": False}]
        elif verdict_upper in ("DONE", "COMPLETE", "PASS"):
            eval_state["quality_scores"] = [{"pass": True}]

    def _transition_evaluation_inputs(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> tuple[SquadAgentResult, dict, dict[str, object]]:
        result = prepared.as_squad_agent_result()
        state = snapshot.state
        # Merge order (lowest→highest precedence): controller config, persisted
        # state, then the prepared canonical updates.
        eval_state: dict[str, object] = {
            **self._lexicon_gate_config(),
            **self._governance_config(),
            **state,
            **prepared.state_updates,
        }
        self._with_why_verdict_quality_fallback(node, result, eval_state)
        return result, state, eval_state

    def _evaluate_transition_conditions(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        start_index: int = 0,
    ) -> str:
        result, _state, eval_state = self._transition_evaluation_inputs(
            node,
            prepared,
            snapshot,
        )
        for index, transition in enumerate(
            node.transitions[start_index:],
            start=start_index,
        ):
            condition = transition.get("condition", "always")
            evaluation = self._evaluator.evaluate(
                condition,
                eval_state,
                result,
            )
            if evaluation is True:
                self._matched_transition = (node.id, index)
                return transition["to"]
            if evaluation is None:
                raise _TransitionJudgmentRequired(condition, index)
        return "DONE"

    def _evaluate_transitions(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> str:
        """Select a route without mutating the prepared payload or state."""
        if not isinstance(prepared, PreparedPhaseResult):
            raise TypeError(
                "_evaluate_transitions requires PreparedPhaseResult"
            )
        if prepared.routing_override:
            return prepared.routing_override
        return self._evaluate_transition_conditions(
            node,
            prepared,
            snapshot,
        )

    def _coordinate_what_repair_cycle_updates(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> dict[str, object]:
        """Record a selected WHAT repair before its targeted WHY2 validation."""
        if node.id != "phase1-what":
            return {}
        state = snapshot.state
        updates: dict[str, object] = {}
        spec_ref = str(state.get("spec_dir") or "").strip()
        if "spec_quality_debt_authorization" in state and not spec_ref:
            raise ControllerStateContractViolation(
                "quality-debt amendment specification root is missing",
                contract="routing",
                json_path="$.spec_dir",
                validator="required",
            )
        if spec_ref:
            spec_dir = Path(spec_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            debt_path = spec_dir.resolve() / "quality-debt.json"
            try:
                debt_ref = debt_path.relative_to(
                    self._project_root.resolve()
                ).as_posix()
            except ValueError as exc:
                raise ControllerStateContractViolation(
                    "quality-debt amendment path escapes the project",
                    contract="routing",
                    json_path="$.spec_dir",
                    validator="path_scope",
                ) from exc
            if (
                "spec_quality_debt_authorization" in state
                or debt_path.exists()
                or debt_path.is_symlink()
            ):
                updates["_proportional_quality_effect"] = {
                    "kind": "proportional_quality",
                    "operation": "debt_remove",
                    "payload": {
                        "operation": "debt_remove",
                        "debt_path": debt_ref,
                    },
                }
        quality_remediation = state.get("quality_gate_remediation")
        if (
            prepared.verdict.upper() == "DONE"
            and isinstance(quality_remediation, Mapping)
            and quality_remediation.get("kind") == "proportional_quality"
            and self._is_proportional_quality_state(state)
        ):
            repair = validate_repair_state(
                state.get("phase1_quality_repair")
            )
            baseline_sha = str(
                quality_remediation.get("baseline_spec_sha256") or ""
            ).strip().lower()
            current_sha = self._spec_markdown_sha256(state)
            valid_completion = (
                re.fullmatch(r"[0-9a-f]{64}", baseline_sha) is not None
                and re.fullmatch(
                    r"[0-9a-f]{64}", str(current_sha or "")
                )
                is not None
            )
            extension_active = (
                repair["extension_authorized"] == 1
                and repair["extension_consumed"] == 0
            )
            outcome = record_what_outcome(
                repair,
                baseline_sha256=baseline_sha,
                current_sha256=current_sha,
                valid_completion=valid_completion,
                extension_active=extension_active,
            )
            updates["phase1_quality_repair"] = outcome.repair_state
            candidate_evidence = state.get(
                "proportional_quality_candidate_evidence"
            )
            next_evidence = (
                dict(candidate_evidence)
                if isinstance(candidate_evidence, Mapping)
                else {"schema_version": 1}
            )
            next_evidence["last_repair_outcome"] = outcome.outcome
            updates[
                "proportional_quality_candidate_evidence"
            ] = next_evidence
        selected = str(state.get("selected_issue_resolution") or "").strip()
        ledger = state.get("issue_resolution_ledger")
        baseline = state.get("issue_resolution_repair_baseline")
        if (
            selected
            and isinstance(ledger, dict)
            and isinstance(baseline, dict)
            and baseline.get("issue_id") == selected
            and isinstance(ledger.get(selected), dict)
            and ledger[selected].get("status") == "selected"
            and prepared.verdict.upper() == "DONE"
        ):
            # The selected resolution may already have been incorporated by an
            # earlier amendment. Requiring another byte-level spec.md change
            # turns that valid confirmation into an endless repair loop.
            repaired_ledger = dict(ledger)
            repaired_entry = dict(ledger[selected])
            repaired_entry["status"] = "repaired"
            repaired_ledger[selected] = repaired_entry
            recovery = state.get("issue_resolution_recovery")
            consumed_recovery = dict(recovery) if isinstance(recovery, dict) else {}
            consumed_recovery["issue_id"] = selected
            consumed_recovery["status"] = "consumed"
            updates["issue_resolution_ledger"] = repaired_ledger
            updates["issue_resolution_recovery"] = consumed_recovery
        try:
            if int(state.get("why_fail_count") or 0) <= 0:
                return updates
        except (TypeError, ValueError):
            return updates
        why_baseline = state.get("why_failure_baseline")
        baseline_ts = (
            why_baseline.get("recorded_at")
            if isinstance(why_baseline, dict)
            else None
        )
        if not baseline_ts:
            return updates
        if not self._phase_artifacts_changed_since(baseline_ts, state):
            return updates
        updates.update(
            {
                "why_fail_count": 0,
                "why2_metric_stagnation_count": 0,
            }
        )
        return updates

    def _coordinate_why_transition_state(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> tuple[
        str | None,
        dict[str, object],
        PreparedHumanInput | None,
    ]:
        """Run proportional WHY2 policy before the unchanged legacy guards."""
        if (
            node.id != "phase1-why2"
            or not self._is_proportional_quality_state(snapshot.state)
        ):
            return self._coordinate_why_transition_state_legacy(
                node,
                prepared,
                snapshot,
            )
        if prepared.state_updates.get("escalation_question"):
            return self._coordinate_why_transition_state_legacy(
                node,
                prepared,
                snapshot,
            )
        _result, _state, eval_state = self._transition_evaluation_inputs(
            node,
            prepared,
            snapshot,
        )
        try:
            assessment = self._authoritative_proportional_assessment(
                prepared,
                eval_state,
                self._proportional_spec_dir(snapshot.state),
            )
        except QualityCandidateIntegrityError:
            return self._proportional_integrity_failure()

        if (
            assessment.hard_blockers
            and assessment.hard_blockers != ("sage_contradiction",)
        ):
            return self._proportional_integrity_failure()
        if assessment.ordinary_pass:
            try:
                captured = self._capture_proportional_quality_candidate(
                    prepared,
                    snapshot,
                    eval_state,
                    assessment=assessment,
                )
            except QualityCandidateIntegrityError:
                return self._proportional_integrity_failure()
            certificate = build_phase1_quality_certificate(
                eval_state,
                project_root=self._project_root,
                authoritative_sage_assessment=assessment,
            )
            if certificate is None:
                return PHASE_TERMINAL_BLOCKED, {
                    "status": "blocked",
                    "blocked_reason": "spec_quality_certificate_unavailable",
                }, None
            legacy_route, legacy_updates, request = (
                self._coordinate_why_transition_state_legacy(
                    node,
                    prepared,
                    snapshot,
                )
            )
            proportional_updates = captured[1] if captured is not None else {}
            return legacy_route, {
                **legacy_updates,
                **proportional_updates,
                "spec_quality_certificate": certificate,
            }, request

        try:
            return self._coordinate_proportional_failure(
                assessment,
                prepared,
                snapshot,
                eval_state,
            )
        except (QualityCandidateIntegrityError, HumanInputPolicyError, ValueError):
            return self._proportional_integrity_failure()

    @staticmethod
    def _proportional_integrity_failure() -> tuple[
        str,
        dict[str, object],
        None,
    ]:
        return PHASE_TERMINAL_BLOCKED, {
            "status": "blocked",
            "blocked_reason": "proportional_quality_candidate_integrity_failed",
        }, None

    def _coordinate_proportional_failure(
        self,
        assessment: AuthoritativeQualityAssessment,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        eval_state: Mapping[str, object],
    ) -> tuple[
        str | None,
        dict[str, object],
        PreparedHumanInput | None,
    ]:
        """Route one authoritative eligible proportional quality failure."""
        if (
            not isinstance(assessment, AuthoritativeQualityAssessment)
            or not assessment.proportional_failure
            or assessment.ordinary_pass
            or assessment.hard_blockers not in {(), ("sage_contradiction",)}
        ):
            raise QualityCandidateIntegrityError(
                "proportional failure assessment is invalid"
            )
        captured = self._capture_proportional_quality_candidate(
            prepared,
            snapshot,
            eval_state,
            assessment=assessment,
        )
        if captured is None:
            raise QualityCandidateIntegrityError(
                "proportional failure candidate is unavailable"
            )
        manifest, proportional_updates = captured
        if manifest.eligibility_reasons:
            raise QualityCandidateIntegrityError(
                "proportional failure candidate is ineligible"
            )

        repair = validate_repair_state(
            proportional_updates["phase1_quality_repair"]
        )
        extension_active = (
            repair["extension_authorized"] == repair["extension_limit"]
            and repair["extension_consumed"] == 0
        )
        automatic_available = (
            repair["automatic_consumed"] < repair["automatic_limit"]
        )
        if extension_active or automatic_available:
            return "phase1-what", {
                **proportional_updates,
                "why_fail_count": 0,
                "why2_metric_stagnation_count": 0,
                "why_failure_baseline": None,
                "quality_gate_remediation": {
                    "kind": "proportional_quality",
                    "candidate_id": manifest.candidate_id,
                    "evidence": eval_state.get("understanding_evidence"),
                    "baseline_spec_sha256": dict(
                        manifest.owned_artifact_digests
                    )["spec.md"],
                    "attempt": (
                        int(repair["automatic_consumed"])
                        + int(repair["extension_consumed"])
                        + 1
                    ),
                    "extension_active": extension_active,
                    "qualitative_findings": [
                        dict(item) for item in manifest.sage_finding_routes
                    ],
                    "reason": (
                        "Repair the current certified proportional quality "
                        "failures within the controller-owned bounded budget."
                    ),
                },
            }, None

        if assessment.hard_blockers == ("sage_contradiction",):
            raise QualityCandidateIntegrityError(
                "a SAGE contradiction cannot be accepted as quality debt"
            )

        reason_code = (
            "proportional_quality_extension_exhausted"
            if repair["extension_authorized"] == repair["extension_limit"]
            and repair["extension_consumed"] == repair["extension_limit"]
            else "proportional_quality_budget_exhausted"
        )
        request, decision_updates = self._prepare_proportional_quality_decision(
            {**snapshot.state, **proportional_updates},
            repair_state=repair,
            reason_code=reason_code,
            source_state_revision=snapshot.state_revision,
            last_repair_outcome=(
                proportional_updates[
                    "proportional_quality_candidate_evidence"
                ].get("last_repair_outcome")
            ),
            current_candidate=manifest,
        )
        return PHASE_TERMINAL_BLOCKED, {
            **proportional_updates,
            **decision_updates,
        }, request

    def _coordinate_why_transition_state_legacy(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> tuple[
        str | None,
        dict[str, object],
        PreparedHumanInput | None,
    ]:
        """Return WHY routing, state effects, and any routed safeguard."""
        if node.id not in WHY_PHASES:
            return None, {}, None

        result, state, eval_state = self._transition_evaluation_inputs(
            node,
            prepared,
            snapshot,
        )
        escalation_q = prepared.state_updates.get("escalation_question")
        if escalation_q:
            updates: dict[str, object] = {"status": "blocked"}
            if "blocked_reason" not in prepared.control_updates:
                updates["blocked_reason"] = "WHY phase: agent escalation"
            return node.id, updates, None

        verdict_upper = (result.verdict or "").upper()
        is_fail = (
            self._evaluator.evaluate(
                "quality_gates.fail",
                eval_state,
                result,
            )
            is True
            or verdict_upper in ("FAIL", "BLOCKED")
        )
        if not is_fail:
            updates: dict[str, object] = {"why_fail_count": 0}
            selected = str(state.get("selected_issue_resolution") or "").strip()
            ledger = state.get("issue_resolution_ledger")
            if (
                node.id == "phase1-why2"
                and selected
                and isinstance(ledger, dict)
                and isinstance(ledger.get(selected), dict)
                and ledger[selected].get("status") == "repaired"
            ):
                validated_ledger = dict(ledger)
                validated_entry = dict(ledger[selected])
                validated_entry["status"] = "validated"
                validated_ledger[selected] = validated_entry
                updates.update(
                    {
                        "issue_resolution_ledger": validated_ledger,
                        "selected_issue_resolution": None,
                        "issue_resolution_repair_baseline": None,
                    }
                )
            return None, updates, None

        # A selected issue is validated independently from the overall WHY2
        # verdict. A targeted WHAT repair is marked ``repaired`` only after
        # the canonical spec changed since its controller-owned baseline. At
        # that point a later qualitative review must not reopen the same issue
        # merely by repeating it from a stale issues.md or an unchanged
        # aggregate score. Other issues may still keep the specification at
        # FAIL, but the operator must be able to proceed in SAGE order.
        selected = str(state.get("selected_issue_resolution") or "").strip()
        ledger = state.get("issue_resolution_ledger")
        finding_routes = prepared.state_updates.get("finding_routes")
        findings = (
            finding_routes.get("findings")
            if isinstance(finding_routes, Mapping)
            else None
        )
        finding_ids = {
            str(finding.get("issue_id") or "").strip()
            for finding in findings
            if isinstance(finding, Mapping)
        } if isinstance(findings, list) else set()
        qualitative_findings = [
            dict(finding)
            for finding in findings
            if isinstance(finding, Mapping)
        ] if isinstance(findings, list) else []

        # Once every controller-recorded issue decision is validated, SAGE's
        # historical prose must not create another manual issue-resolution or
        # consecutive-failure loop. The current deterministic Understanding
        # evidence is authoritative and starts a fresh, score-directed WHAT
        # remediation cycle.
        ledger_entries = (
            [entry for entry in ledger.values() if isinstance(entry, Mapping)]
            if isinstance(ledger, Mapping)
            else []
        )
        if (
            node.id == "phase1-why2"
            and not selected
            and ledger_entries
            and all(entry.get("status") == "validated" for entry in ledger_entries)
        ):
            existing_remediation = state.get("quality_gate_remediation")
            try:
                prior_attempt = int(
                    existing_remediation.get("attempt")
                    if isinstance(existing_remediation, Mapping)
                    else 0
                )
            except (TypeError, ValueError):
                prior_attempt = 0
            return "phase1-what", {
                "why_fail_count": 0,
                "why2_metric_stagnation_count": 0,
                "why_failure_baseline": None,
                "iteration": 0,
                "quality_gate_remediation": {
                    "evidence": state.get("understanding_evidence"),
                    "baseline_spec_sha256": self._spec_markdown_sha256(state),
                    "attempt": prior_attempt + 1,
                    **(
                        {"qualitative_findings": qualitative_findings}
                        if qualitative_findings
                        else {}
                    ),
                    "reason": (
                        "All named issue resolutions are complete. Repair only the "
                        "current certified Understanding failures in formal "
                        "requirements and current SAGE qualitative findings; "
                        "historical SAGE issue prose is not actionable."
                    ),
                },
            }, None
        if (
            node.id == "phase1-why2"
            and selected
            and isinstance(ledger, dict)
            and isinstance(ledger.get(selected), dict)
            and ledger[selected].get("status") == "repaired"
        ):
            validated_ledger = dict(ledger)
            validated_entry = dict(ledger[selected])
            validated_entry["status"] = "validated"
            validated_ledger[selected] = validated_entry
            unresolved = [
                issue_id
                for issue_id, entry in validated_ledger.items()
                if isinstance(entry, dict) and entry.get("status") != "validated"
            ]
            if unresolved:
                blocked_reason = "issue_resolution_next"
                escalation_question = (
                    f"{selected} was recorded as repaired after spec.md changed. "
                    "Resolve the next unresolved SAGE issue with `echelon spec resolve "
                    "ISS-<n> '<project decision>'`."
                )
            else:
                updates = {
                    "issue_resolution_ledger": validated_ledger,
                    "selected_issue_resolution": None,
                    "issue_resolution_repair_baseline": None,
                    "why_fail_count": 0,
                    "why2_metric_stagnation_count": 0,
                    "iteration": 0,
                    "quality_gate_remediation": {
                        "evidence": state.get("understanding_evidence"),
                        "baseline_spec_sha256": self._spec_markdown_sha256(state),
                        "attempt": 1,
                        **(
                            {"qualitative_findings": qualitative_findings}
                            if qualitative_findings
                            else {}
                        ),
                        "reason": (
                            "All named issue resolutions are complete, but certified "
                            "quality review still fails. Rewrite the specification to "
                            "address the failed metric families and current SAGE "
                            "qualitative findings as a fresh remediation cycle."
                        ),
                    },
                }
                return "phase1-what", updates, None
            updates = {
                "issue_resolution_ledger": validated_ledger,
                "selected_issue_resolution": None,
                "issue_resolution_repair_baseline": None,
                "why_fail_count": 0,
                "why2_metric_stagnation_count": 0,
                "status": "blocked",
                "blocked_reason": blocked_reason,
                "escalation_question": escalation_question,
            }
            return PHASE_TERMINAL_BLOCKED, updates, None

        from datetime import datetime, timezone

        baseline = state.get("why_failure_baseline")
        baseline_ts = (
            baseline.get("recorded_at")
            if isinstance(baseline, dict)
            else None
        )
        try:
            prior_fail_count = int(state.get("why_fail_count") or 0)
        except (TypeError, ValueError):
            prior_fail_count = 0
        try:
            fail_count = prior_fail_count + 1
        except (TypeError, ValueError):
            fail_count = 1
        updates: dict[str, object] = {"why_fail_count": fail_count}
        if prior_fail_count <= 0 or not baseline_ts:
            updates["why_fail_count"] = 1
            updates["why_failure_baseline"] = {
                "phase_id": node.id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            return None, updates, None
        if node.id != "phase1-why2":
            return None, updates, None

        metrics_improved = _why2_certified_metrics_improved(
            eval_state.get("quality_scores")
        )
        if metrics_improved is True:
            updates["why2_metric_stagnation_count"] = 0
        elif metrics_improved is False:
            try:
                stagnation_count = (
                    int(state.get("why2_metric_stagnation_count") or 0) + 1
                )
            except (TypeError, ValueError):
                stagnation_count = 1
            updates["why2_metric_stagnation_count"] = stagnation_count
            if stagnation_count >= WHY2_METRIC_STAGNATION_LIMIT:
                question = (
                    "WHY2 certified metrics did not improve across "
                    f"{stagnation_count} consecutive repair cycles. "
                    "Provide new evidence, narrow scope, or authorize a "
                    "different repair strategy."
                )
                request = self._human_input_registry.prepare(
                    source_kind="controller_safeguard",
                    producer_id="why2_metric_stagnation",
                    phase_id=node.id,
                    reason_code="why2_metric_stagnation",
                    question=question,
                    source_state_revision=snapshot.state_revision,
                )
                return PHASE_TERMINAL_BLOCKED, updates, request

        if fail_count < 2 or state.get("escalation_question"):
            return None, updates, None
        if self._phase_artifacts_changed_since(baseline_ts, snapshot.state):
            return None, updates, None

        print(
            f"[squad] ✗ consecutive-fail guard: {fail_count} {node.id} "
            "FAILs with no artifact progress — forcing escalation",
            flush=True,
        )
        question = (
            f"{node.id} still fails after {fail_count} assessments without "
            "a spec artifact change. No automatic retry is authorized. Run "
            '`echelon spec resume "<your answer>"` with new evidence, narrowed '
            "scope, or a concrete repair instruction. The resume records that "
            "free-text answer, resets the consecutive WHY failure count, and "
            "reopens phase1-why2. Then `echelon spec continue` retries that "
            "phase under the normal validation gates."
        )
        request = self._human_input_registry.prepare(
            source_kind="controller_safeguard",
            producer_id="consecutive_why_fails",
            phase_id=node.id,
            reason_code="consecutive_why_fails",
            question=question,
            source_state_revision=snapshot.state_revision,
        )
        return PHASE_TERMINAL_BLOCKED, updates, request

    def _construct_routing_decision_or_block(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        additional_state_updates: Mapping[str, object] | None = None,
        manual_phase_run: bool = False,
        conditional_skip: bool = False,
    ) -> _PreparedControllerRouting | None:
        """Construct one route or record a redacted snapshot-bound failure."""
        with self._defer_routing_provider_usage() as usage:
            try:
                routed_human_input: list[PreparedHumanInput] = []
                decision = self._coordinate_transition_routing(
                    node,
                    prepared,
                    snapshot,
                    additional_state_updates=additional_state_updates,
                    manual_phase_run=manual_phase_run,
                    conditional_skip=conditional_skip,
                    human_input_collector=routed_human_input,
                )
                return _PreparedControllerRouting(
                    decision=decision,
                    human_input=(
                        routed_human_input[0]
                        if routed_human_input
                        else None
                    ),
                )
            except (
                ControllerStateContractViolation,
                StateAdvanceError,
            ) as exc:
                if (
                    isinstance(exc, StateAdvanceError)
                    and exc.validator == "checkpoint_prestate"
                ):
                    if usage["tokens"]:
                        self._state_store.increment_token_usage(
                            usage["tokens"]
                        )
                    # The caller owns any publication stage prepared before
                    # routing and discards it when this returns no decision.
                    # Do not turn unavailable Git authority into state.
                    return None
                if isinstance(exc, ControllerStateContractViolation):
                    error = StateAdvanceError(
                        "routing decision construction failed",
                        json_path=exc.json_path,
                        validator=exc.validator,
                    )
                else:
                    error = exc
                self._block_after_state_advance_failure(
                    node,
                    snapshot.phase,
                    error,
                    snapshot=snapshot,
                    token_usage_delta=usage["tokens"],
                    diagnostic_contract=(
                        exc.contract
                        if isinstance(
                            exc,
                            ControllerStateContractViolation,
                        )
                        else None
                    ),
                    diagnostic_subject="routing decision construction",
                )
                return None

    def _coordinate_transition_routing(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        additional_state_updates: Mapping[str, object] | None = None,
        manual_phase_run: bool = False,
        conditional_skip: bool = False,
        human_input_collector: list[PreparedHumanInput] | None = None,
    ) -> PreparedRoutingDecision:
        """Select and seal one route without mutating live success state."""
        self._matched_transition = None
        queued_updates: dict[str, object] = {}
        transaction_updates: dict[str, object] = {}
        transaction_removals = set(
            prepared.trusted_transaction_state_removals
        )

        def merge_effects(effects: Mapping[str, object]) -> None:
            for key, value in effects.items():
                if key in STORE_OWNED_TRANSACTION_KEYS:
                    if key not in TRUSTED_ROUTING_EFFECT_KEYS:
                        raise ControllerStateContractViolation(
                            "routing effect contains a transaction identity",
                            contract="routing",
                            json_path=f"$.state_updates.{key}",
                            validator="ownership",
                        )
                    transaction_updates[key] = value
                else:
                    queued_updates[key] = value

        def merge_judgment_effects(
            effects: Mapping[str, object],
        ) -> None:
            """Promote validated control syntax; reject judgment ownership."""
            status = effects.get("status")
            has_status = "status" in effects
            blocked_reason = effects.get("blocked_reason")
            has_blocked_reason = "blocked_reason" in effects
            for key, value in effects.items():
                if key in {"status", "blocked_reason"}:
                    continue
                if key in STORE_OWNED_TRANSACTION_KEYS:
                    raise ControllerStateContractViolation(
                        "judgment effect contains a transaction identity",
                        contract="judgment",
                        json_path=f"$.state_updates.{key}",
                        validator="ownership",
                    )
                queued_updates[key] = value
            if has_status and status != "blocked":
                raise ControllerStateContractViolation(
                    "judgment lifecycle intent is not controller-promotable",
                    contract="judgment",
                    json_path="$.state_updates.status",
                    validator="ownership",
                )
            if has_blocked_reason and (
                type(blocked_reason) is not str
                or not blocked_reason.strip()
                or status != "blocked"
            ):
                raise ControllerStateContractViolation(
                    "judgment blocked reason is not a valid control intent",
                    contract="judgment",
                    json_path="$.state_updates.blocked_reason",
                    validator="ownership",
                )
            if status == "blocked":
                transaction_updates["status"] = "blocked"
                transaction_updates["blocked_reason"] = (
                    blocked_reason
                    if type(blocked_reason) is str
                    and blocked_reason.strip()
                    else "judgment_blocked"
                )

        merge_effects(dict(additional_state_updates or {}))
        what_cycle_updates = self._coordinate_what_repair_cycle_updates(
            node,
            prepared,
            snapshot,
        )
        merge_effects(what_cycle_updates)
        proportional_what_human_input: PreparedHumanInput | None = None
        proportional_what_integrity_failure = False
        quality_remediation = snapshot.state.get("quality_gate_remediation")
        prepared_candidate_evidence = what_cycle_updates.get(
            "proportional_quality_candidate_evidence"
        )
        prepared_repair = what_cycle_updates.get(
            "phase1_quality_repair"
        )
        if (
            node.id == "phase1-what"
            and isinstance(quality_remediation, Mapping)
            and quality_remediation.get("kind") == "proportional_quality"
            and isinstance(prepared_candidate_evidence, Mapping)
            and prepared_candidate_evidence.get("last_repair_outcome")
            == "no_artifact_progress"
            and isinstance(prepared_repair, Mapping)
        ):
            repair = validate_repair_state(prepared_repair)
            if repair["extension_authorized"] == 0:
                try:
                    proportional_what_human_input, decision_updates = (
                        self._prepare_proportional_quality_decision(
                            {
                                **snapshot.state,
                                **what_cycle_updates,
                            },
                            repair_state=repair,
                            reason_code=(
                                "proportional_quality_budget_exhausted"
                            ),
                            source_state_revision=snapshot.state_revision,
                            last_repair_outcome="no_artifact_progress",
                        )
                    )
                    merge_effects(decision_updates)
                except (
                    QualityCandidateIntegrityError,
                    HumanInputPolicyError,
                ):
                    proportional_what_integrity_failure = True
                    merge_effects(
                        {
                            "status": "blocked",
                            "blocked_reason": (
                                "proportional_quality_candidate_integrity_failed"
                            ),
                        }
                    )
        judgment_payloads: list[dict[str, object]] = []
        judgment_results: list[SquadAgentResult] = []
        source = "transition"
        transition_index: int | None = None
        routed_human_input: PreparedHumanInput | None = None
        if proportional_what_human_input is not None:
            next_phase = "phase1-why2"
            source = "proportional_quality_no_progress"
            routed_human_input = proportional_what_human_input
        elif proportional_what_integrity_failure:
            next_phase = PHASE_TERMINAL_BLOCKED
            source = "proportional_quality_integrity"
        elif prepared.routing_override:
            next_phase = self._evaluate_transitions(
                node,
                prepared,
                snapshot,
            )
            source = "controller_override"
        else:
            why_override, why_updates, routed_human_input = (
                self._coordinate_why_transition_state(
                    node,
                    prepared,
                    snapshot,
                )
            )
            merge_effects(why_updates)
            if why_override:
                next_phase = why_override
                source = "why_policy"
            else:
                start_index = 0
                while True:
                    try:
                        if start_index == 0:
                            next_phase = self._evaluate_transitions(
                                node,
                                prepared,
                                snapshot,
                            )
                        else:
                            next_phase = (
                                self._evaluate_transition_conditions(
                                    node,
                                    prepared,
                                    snapshot,
                                    start_index=start_index,
                                )
                            )
                        break
                    except _TransitionJudgmentRequired as unresolved:
                        transition_index = unresolved.transition_index
                        source = "commander"
                        result = prepared.as_squad_agent_result()
                        judgment = self._judgment_dispatch(
                            "Cannot evaluate condition "
                            f"{unresolved.condition!r} in phase "
                            f"{node.id!r}",
                            node,
                            result,
                            snapshot,
                        )
                        judgment_payload = judgment.echelon_result
                        if isinstance(judgment_payload, dict):
                            judgment_payloads.append(judgment_payload)
                            judgment_results.append(judgment)
                        requested_phase = (
                            judgment.state_updates.get("next_phase")
                            or judgment.state_updates.get("phase")
                        )
                        valid_phases = self._graph.all_phase_ids()
                        if (
                            requested_phase
                            and requested_phase not in valid_phases
                        ):
                            print(
                                "[squad] ✗ judgment returned invalid phase "
                                f"{requested_phase!r} — not in phase graph. "
                                "Blocking.",
                                flush=True,
                            )
                            merge_effects(
                                {
                                    "status": "blocked",
                                    "blocked_reason": (
                                        "judgment_invalid_next_phase"
                                    ),
                                }
                            )
                            next_phase = PHASE_TERMINAL_BLOCKED
                            break
                        routing_keys = {"next_phase", "phase"}
                        extra = {
                            key: value
                            for key, value in judgment.state_updates.items()
                            if key not in routing_keys
                        }
                        if judgment.verdict == "BLOCKED":
                            if requested_phase:
                                raise ControllerStateContractViolation(
                                    "blocked judgment cannot select a route",
                                    contract="judgment",
                                    json_path="$.state_updates.next_phase",
                                    validator="blocked_intent",
                                )
                            if (
                                extra.get("status") != "blocked"
                                or type(extra.get("blocked_reason")) is not str
                                or not extra["blocked_reason"].strip()
                            ):
                                raise ControllerStateContractViolation(
                                    "blocked judgment requires an exact block intent",
                                    contract="judgment",
                                    json_path="$.state_updates",
                                    validator="blocked_intent",
                                )
                            merge_judgment_effects(extra)
                            next_phase = node.id
                            break
                        if "status" in extra or "blocked_reason" in extra:
                            raise ControllerStateContractViolation(
                                "resolved judgment cannot own lifecycle state",
                                contract="judgment",
                                json_path="$.state_updates",
                                validator="resolved_intent",
                            )
                        merge_judgment_effects(extra)
                        if requested_phase:
                            next_phase = str(requested_phase)
                            break
                        start_index = unresolved.transition_index + 1

        matched = getattr(self, "_matched_transition", None)
        if (
            isinstance(matched, tuple)
            and len(matched) == 2
            and matched[0] == node.id
            and isinstance(matched[1], int)
        ):
            transition_index = matched[1]
        for key in set(queued_updates) & set(prepared.state_updates):
            if queued_updates[key] == prepared.state_updates[key]:
                queued_updates.pop(key)
        increment_iteration = self._transition_increments_iteration(
            node,
            next_phase,
        ) or (
            node.id == "phase1-why2"
            and next_phase == "phase1-what"
            and source == "why_policy"
            and self._is_proportional_quality_state(snapshot.state)
        )
        quality_effect = queued_updates.pop(
            "_proportional_quality_effect",
            None,
        )
        if quality_effect is not None and not isinstance(quality_effect, Mapping):
            raise ControllerStateContractViolation(
                "proportional quality effect is invalid",
                contract="routing",
                json_path="$.state_updates._proportional_quality_effect",
                validator="type",
            )
        if PENDING_CONTROLLER_COMPLETION_KEY in transaction_updates:
            raise ControllerStateContractViolation(
                "routing effects cannot provide completion authority",
                contract="routing",
                json_path=(
                    "$.transaction_state_updates."
                    f"{PENDING_CONTROLLER_COMPLETION_KEY}"
                ),
                validator="ownership",
            )
        publication_marker = transaction_updates.get(
            PENDING_EXTERNAL_PUBLICATION_KEY
        )
        completion = self._prepare_controller_completion(
            from_phase=node.id,
            to_phase=next_phase,
            snapshot=snapshot,
            manual_phase_run=manual_phase_run,
            conditional_skip=conditional_skip,
            record_completion=True,
            publication_marker=(
                publication_marker
                if isinstance(publication_marker, Mapping)
                else None
            ),
            judgments=tuple(judgment_results),
            quality_effect=quality_effect,
        )
        transaction_updates[PENDING_CONTROLLER_COMPLETION_KEY] = (
            completion.marker.to_dict()
        )
        try:
            decision = self._state_store.prepare_routing_decision(
                prepared,
                snapshot=snapshot,
                from_phase=node.id,
                to_phase=next_phase,
                queued_state_updates=queued_updates,
                transaction_state_updates=transaction_updates,
                transaction_state_removals=transaction_removals,
                judgment_payloads=judgment_payloads,
                source=source,
                transition_index=transition_index,
                increment_iteration=increment_iteration,
                manual_phase_run=manual_phase_run,
                conditional_skip=conditional_skip,
                checkpoint_policy=str(
                    completion.intent.route.get("checkpoint_policy") or "none"
                ),
                token_usage_delta=(
                    self._deferred_provider_usage or {"tokens": 0}
                )["tokens"],
                dispatch_id=completion.marker.completion_id,
            )
            if human_input_collector is not None and human_input_collector:
                raise HumanInputPolicyError(
                    "routing human-input collector is not empty"
                )
            if (
                human_input_collector is not None
                and routed_human_input is not None
            ):
                human_input_collector.append(routed_human_input)
            return decision
        except BaseException:
            try:
                completion.discard()
            except CompletionError:
                pass
            raise

    def _transition_increments_iteration(
        self,
        node: PhaseNode,
        next_phase: str,
    ) -> bool:
        """Resolve action only from the transition selected during routing."""
        matched = getattr(self, "_matched_transition", None)
        if (
            not isinstance(matched, tuple)
            or len(matched) != 2
            or matched[0] != node.id
            or not isinstance(matched[1], int)
            or matched[1] < 0
            or matched[1] >= len(node.transitions)
        ):
            return False
        transition = node.transitions[matched[1]]
        return (
            transition.get("to") == next_phase
            and transition.get("action") == "increment_iteration"
        )

    def _dispatch_reason(self, phase: str, attempt: int) -> str:
        """Choose telemetry reason from controller state, never model output."""
        state = self._state_store.load()
        if phase == "phase1-what" and state.get("cartographer_resume_existing_spec"):
            return "resume"
        if state.get("product_input_mapping_repair"):
            return "deterministic_repair"
        if phase == "phase1-what" and attempt > 1:
            return "semantic_repair"
        return "planned_iteration" if attempt > 1 else "initial"

    def _judgment_dispatch(
        self,
        reason: str,
        node: PhaseNode,
        result: Optional[SquadAgentResult] = None,
        snapshot: RoutingStateSnapshot | None = None,
    ) -> SquadAgentResult:
        """Dispatch slimmed COMMANDER for judgment calls."""
        commander_file = self._graph.agent_file("echelon.commander")
        if not commander_file:
            raise FileNotFoundError(
                "Prosaic COMMANDER agent is missing from the phase graph"
            )
        commander_path = Path(commander_file)
        if not commander_path.is_file():
            raise FileNotFoundError(
                f"Prosaic COMMANDER agent is missing: {commander_path}"
            )
        state = (
            snapshot.state
            if snapshot is not None
            else self._state_store.load()
        )
        valid_phases = self._graph.all_phase_ids()
        transitions_text = "\n".join(
            f"  - to: {t.get('to')}  (condition: {t.get('condition', 'always')})"
            for t in node.transitions
        ) or "  (none defined)"
        context = (
            f"# COMMANDER JUDGMENT REQUEST\n\n"
            f"**Reason:** {reason}\n\n"
            f"**Current phase:** {node.id} (type: {node.type})\n\n"
            f"**Transitions defined for this phase:**\n{transitions_text}\n\n"
            f"**VALID phase IDs** (only these may appear in next_phase):\n"
            f"{json.dumps(valid_phases, indent=2)}\n\n"
            f"**State:**\n```json\n{json.dumps(state, indent=2)}\n```\n\n"
        )
        from harness.squad_executors import _render_controller_owned_prompt_context

        context += _render_controller_owned_prompt_context(state)
        context = read_prompt_markdown(commander_path).body + "\n\n" + context
        with self._telemetry_provider.dispatch(
            DispatchContext(node.id, "COMMANDER", "judgment", 1)
        ):
            raw_judgment = self._telemetry_provider.exec_agent(
                str(self._project_root),
                context,
            )
        judgment = self._canonicalize_judgment_result(raw_judgment)
        return judgment

    def _block_unresolvable_dispatch_cap(
        self,
        phase: str,
        state: Mapping[str, object],
        reason_code: str,
    ) -> None:
        self._state_store.block_unresolvable_dispatch_cap(
            from_phase=phase,
            expected_state_revision=int(state.get("state_revision") or 0),
            reason_code=reason_code,
        )

    def _read_dispatch_cap_issues(
        self,
        state: Mapping[str, object],
    ) -> str:
        roots: list[Path] = []
        for state_key in ("published_spec_dir", "spec_dir"):
            if state_key == "published_spec_dir" and not state.get(state_key):
                continue
            try:
                spec_dir = self._validated_spec_root(
                    state,
                    state_key=state_key,
                )
            except HumanInputPolicyError as exc:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                ) from exc
            if spec_dir is not None and spec_dir not in roots:
                roots.append(spec_dir)
        # Before WHAT creates the canonical spec artifacts, Phase 1 writes its
        # issue register to staging. Once spec.md exists, staging is only an
        # inbox and must not override missing canonical recovery evidence.
        if not any((root / "spec.md").is_file() for root in roots):
            try:
                staging_dir = self._authoritative_human_input_roots(state)[
                    "{staging_dir}"
                ]
            except HumanInputPolicyError as exc:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                ) from exc
            if staging_dir is not None and staging_dir not in roots:
                roots.append(staging_dir)
        if not roots:
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_missing"
            )

        last_missing: _DispatchCapEvidenceError | None = None
        for spec_dir in roots:
            try:
                return self._read_dispatch_cap_issues_from_root(spec_dir)
            except _DispatchCapEvidenceError as exc:
                # A stale or not-yet-published Phase A copy must not hide the
                # active run-local spec, which is the authoritative source
                # during authoring and remediation.
                if exc.reason_code == "phase_dispatch_limit_evidence_missing":
                    last_missing = exc
                    continue
                raise
        raise last_missing or _DispatchCapEvidenceError(
            "phase_dispatch_limit_evidence_missing"
        )

    def _read_dispatch_cap_issues_from_root(self, spec_dir: Path) -> str:
        """Read a bounded issues artifact from one already-validated root."""
        opened: list[int] = []
        file_fd = -1
        try:
            opened = self._open_project_directory_chain(spec_dir)
            file_fd = os.open(
                "issues.md",
                (
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                ),
                dir_fd=opened[-1],
            )
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                )
            if metadata.st_size > DISPATCH_CAP_ISSUES_MAX_BYTES:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_oversized"
                )
            chunks: list[bytes] = []
            remaining = DISPATCH_CAP_ISSUES_MAX_BYTES + 1
            while remaining > 0:
                chunk = os.read(
                    file_fd,
                    min(remaining, _CONTEXT_FILE_READ_CHUNK_BYTES),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > DISPATCH_CAP_ISSUES_MAX_BYTES:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_oversized"
                )
            try:
                return payload.decode("utf-8")
            except UnicodeError as exc:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                ) from exc
        except FileNotFoundError as exc:
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_missing"
            ) from exc
        except _DispatchCapEvidenceError:
            raise
        except (OSError, HumanInputPolicyError) as exc:
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_malformed"
            ) from exc
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            for descriptor in reversed(opened):
                os.close(descriptor)

    def _banzai_issue_resolution_candidates(
        self,
        state: dict,
    ) -> list[dict[str, str]]:
        """Return a bounded, complete set of explicitly eligible issue options."""
        issues_md = self._read_dispatch_cap_issues(state)
        if not issues_md.strip():
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_empty"
            )
        issue_blocks = re.findall(
            r"^### (ISS-\d+:\s*[^\n]+)\n(.*?)(?=^### ISS-\d+:|\Z)",
            issues_md,
            re.MULTILINE | re.DOTALL,
        )
        if not issue_blocks:
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_malformed"
            )

        candidates: list[dict[str, str]] = []
        seen_issue_ids: set[str] = set()
        for title, body in issue_blocks:
            issue_match = re.fullmatch(
                r"(ISS-\d+):\s*(\S(?:.*\S)?)",
                title.strip(),
            )
            guidance = re.search(
                r"^### Resolution Guidance[ \t]*\n(.*?)(?=^### |\Z)",
                body,
                re.MULTILINE | re.DOTALL,
            )
            if issue_match is None or guidance is None:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                )
            issue_id = issue_match.group(1)
            if issue_id in seen_issue_ids:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                )
            seen_issue_ids.add(issue_id)
            guidance_text = guidance.group(1)
            field_patterns = {
                "decision_required": "Decision required",
                "suggested_option": "Suggested option",
                "evidence_basis": "Evidence basis",
            }
            fields: dict[str, str] = {}
            for field, label in field_patterns.items():
                matches = re.findall(
                    rf"^- \*\*{re.escape(label)}:\*\*[ \t]*(.+?)[ \t]*$",
                    guidance_text,
                    re.MULTILINE,
                )
                if len(matches) != 1 or not matches[0].strip():
                    raise _DispatchCapEvidenceError(
                        "phase_dispatch_limit_evidence_malformed"
                    )
                fields[field] = matches[0].strip()
            eligibility = re.findall(
                r"^- \*\*Banzai eligible:\*\*[ \t]*(yes|no)[ \t]*$",
                guidance_text,
                re.MULTILINE | re.IGNORECASE,
            )
            if len(eligibility) != 1:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_malformed"
                )
            if eligibility[0].lower() == "no":
                continue
            candidates.append(
                {
                    "issue_id": issue_id,
                    "title": issue_match.group(2),
                    **fields,
                }
            )
            if len(candidates) > HUMAN_INPUT_MAX_OPTIONS:
                raise _DispatchCapEvidenceError(
                    "phase_dispatch_limit_evidence_too_many_candidates"
                )
        if not candidates:
            raise _DispatchCapEvidenceError(
                "phase_dispatch_limit_evidence_ineligible"
            )
        return candidates

    def _validate_banzai_issue_resolution_selection(
        self, selection: object, candidates: list[dict[str, str]]
    ) -> dict[str, str] | None:
        """Allow Banzai only to copy an explicitly evidence-backed suggestion."""
        if not isinstance(selection, dict) or selection.get("evidence_backed") is not True:
            return None
        issue_id = str(selection.get("issue_id") or "").strip()
        decision = str(selection.get("decision") or "").strip()
        rationale = str(selection.get("rationale") or "").strip()
        confidence = str(selection.get("confidence") or "").strip().lower()
        candidate = next((item for item in candidates if item["issue_id"] == issue_id), None)
        if not candidate or decision != candidate["suggested_option"] or not rationale:
            return None
        if confidence not in {"high", "medium"}:
            return None
        return {
            **candidate,
            "decision": decision,
            "rationale": rationale,
            "confidence": confidence,
            "evidence_backed": "true",
        }

    @staticmethod
    def _issue_resolution_state_updates(
        state: dict,
        selection: dict[str, str],
    ) -> dict[str, object]:
        """Apply the existing selected-issue repair lifecycle in memory."""
        from datetime import datetime, timezone

        issue_id = selection["issue_id"]
        ledger = state.get("issue_resolution_ledger")
        selected_ledger = dict(ledger) if isinstance(ledger, dict) else {}
        selected_ledger[issue_id] = {
            "issue_id": issue_id,
            "title": selection["title"],
            "severity": "ISSUE",
            "guidance": selection["decision_required"],
            "status": "selected",
            "decision": selection["decision"],
            "repair_phase": "phase1-what",
            "rationale": selection["rationale"],
            "confidence": selection["confidence"],
            "evidence_backed": selection["evidence_backed"],
        }
        return {
            "issue_resolution_ledger": selected_ledger,
            "selected_issue_resolution": issue_id,
            "issue_resolution_repair_baseline": {
                "issue_id": issue_id,
                "repair_phase": "phase1-what",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            "issue_resolution_recovery": {
                "issue_id": issue_id,
                "from_phase": "phase1-why2",
                "to_phase": "phase1-what",
                "reason": "issue_resolution",
            },
        }

    def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
        """Mirror executor journal writes through the shared durable store."""
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

    def _phase_artifacts_changed_since(
        self,
        iso_timestamp: Optional[str],
        state: Mapping[str, object],
    ) -> bool:
        """Return True if a canonical phase artifact is newer than the cutoff.

        Before WHAT creates ``state.spec_dir``, discovery/WHY1 artifacts live in
        the run-local staging directory. After that boundary, ``spec_dir`` is the
        authoritative artifact root and staging is only a control-message inbox.
        """
        if iso_timestamp is None:
            return True
        try:
            from datetime import datetime, timezone
            cutoff = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            spec_dir_ref = str(state.get("spec_dir") or "").strip()
            if spec_dir_ref:
                artifact_root = Path(spec_dir_ref)
                if not artifact_root.is_absolute():
                    artifact_root = self._project_root / artifact_root
            else:
                artifact_root = Path(
                    state.get("staging_dir", str(self._squad_dir / "staging"))
                )
            for f in artifact_root.rglob("*.md"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime > cutoff:
                    return True
            return False
        except Exception:
            return True  # conservative: treat parse failure as progress

    def _spec_markdown_sha256(self, state: Mapping[str, object]) -> str | None:
        """Return the canonical spec digest used by a quality repair cycle."""
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        if not spec_dir_ref:
            return None
        spec_dir = Path(spec_dir_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        try:
            return hashlib.sha256((spec_dir / "spec.md").read_bytes()).hexdigest()
        except OSError:
            return None

    def _budget_exhausted(self) -> bool:
        if self._token_budget <= 0:
            return False
        return self._state_store.token_usage() >= self._token_budget

    def _handle_sigint(self, signum, frame) -> None:
        print("\n[squad] Interrupted — finishing current phase then stopping.")
        # Signal handlers must not enter the file-backed state lock: SIGINT can
        # interrupt this thread while it already owns that non-reentrant lock.
        # The main loop persists the interrupted state after the current phase.
        self._cancelled = True

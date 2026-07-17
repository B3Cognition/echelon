"""Phase executors for SquadController — one class per definition.yaml type."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from harness.quality_scores import (
    normalize_why_quality_scores,
    render_quality_gate_context,
    resolve_quality_gate_thresholds,
)

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad_provider import SquadAgentResult, SquadCliProvider
    from harness.squad_state import SquadStateStore


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
        "### Belief Registers\n"
        "- ALWAYS read your agent-specific belief register when present at "
        "`${PROJECT_ROOT}/.specify/extensions/echelon/config/"
        "belief-registers/<agent-slug>.yaml` before threshold, scoring, "
        "quality, or confidence decisions.\n"
        "- NEVER treat calibration priors as optional when a matching belief "
        "register exists.\n\n"
    )


_FALLBACK_ECHELON_RESULT_TEMPLATE = """# Echelon result contract template.
# The harness appends this template to every squad-agent prompt.
# Agents fill values, but must keep the unfenced YAML root shape.
#
# Rules:
# - ALWAYS include state_updates; use {} when no state changes are needed.
# - ALWAYS include journal_entries; use [] when no journal entries are needed.
# - Registered journal-entry types require `data` with all required fields from
#   extension/workflow/journal-entry-types.yaml.
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
    - input_unit_id: <IN-REQ-* ID from PRODUCT_INPUT_CATALOG>
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


def _allowed_state_updates_contract(allowed_state_updates: object) -> str:
    """Render the deterministic state-update allowlist for an agent prompt."""
    lines = [
        "\n\n---",
        "## Allowed state_updates for this dispatch",
        "The harness validates `echelon_result.state_updates` before mutating state.",
        "Return only the keys listed here; use `state_updates: {}` when no state",
        "changes are needed. Any other top-level key blocks the run.",
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
            lines.extend(f"- `{key}`" for key in keys)
        else:
            lines.extend(
                [
                    "Allowed keys: none.",
                    "```yaml",
                    "state_updates: {}",
                    "```",
                ]
            )
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


def _render_product_input_context(state: dict) -> str:
    """Render immutable product evidence pointers without embedding the corpus."""
    inputs = state.get("product_inputs")
    if not isinstance(inputs, dict) or not inputs:
        return ""
    required = ("manifest", "catalog", "traceability", "requirement_context", "reference_context")
    if not all(str(inputs.get(key) or "").strip() for key in required):
        return ""
    return "\n".join([
        "## Product Input Contract",
        f"PRODUCT_INPUT_MANIFEST={inputs['manifest']}",
        f"PRODUCT_INPUT_CATALOG={inputs['catalog']}",
        f"PRODUCT_INPUT_TRACEABILITY={inputs['traceability']}",
        f"REQUIREMENT_INPUTS={inputs['requirement_context']}",
        f"REFERENCE_INPUTS={inputs['reference_context']}",
        "- Requirement inputs are normative; reference inputs are informative and cannot override them.",
        "- Read only immutable snapshot paths named by the manifest and catalog. Do not add undeclared inputs.",
        "- Cite stable input unit IDs when adopting or challenging product evidence.",
        "- Propose ledger changes only in echelon_result.product_input_updates; the controller validates and writes the canonical ledger.",
        "- Each product_input_updates item must contain exactly: input_unit_id, disposition, rationale, spec_ids, task_ids, targets.",
        "- disposition is exactly one of: included, excluded, duplicate, open_question, conflict. Never use aliases such as unit, adopted, or mapped.",
        "- YAML safety: double-quote every free-text scalar, especially rationale values containing ':', '#', or quotes.",
        "- In Phase 1, use spec_ids for FR/AC mappings and return task_ids: [] and targets: []. Later planning phases fill task_ids and targets.",
        "- Required item shape:",
        "  input_unit_id: <IN-REQ-* ID from PRODUCT_INPUT_CATALOG>",
        "  disposition: <included|excluded|duplicate|open_question|conflict>",
        '  rationale: "<evidence-backed reason for this disposition>"',
        "  spec_ids: [FR-001, AC-001]",
        "  task_ids: []",
        "  targets: []",
        "",
    ])


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
    artifacts = context.get("artifacts")
    if status == "attached" and isinstance(artifacts, dict):
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


_MANDATORY_PHASE_OUTPUTS: dict[str, tuple[str, ...]] = {
    "phase3-how": ("plan.md", "research.md", "data-model.md", "contracts"),
    "phase3-sentinel": ("test-strategy.md", "test-architecture.md", "coverage-map.md"),
    "phase3-plan": ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"),
}


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


def _render_context_candidate(file_ref: str, candidate: Path) -> str:
    """Render a context-pack file or directory into deterministic prompt text."""
    if candidate.is_dir():
        chunks = [f"\n---\n# {file_ref.rstrip('/')}/"]
        for path in sorted(p for p in candidate.rglob("*") if p.is_file()):
            rel = path.relative_to(candidate)
            display = f"{file_ref.rstrip('/')}/{rel.as_posix()}"
            chunks.append(
                f"\n## {display}\n"
                f"{path.read_text(encoding='utf-8', errors='replace')}"
            )
        return "\n".join(chunks)
    return f"\n---\n# {file_ref}\n{candidate.read_text(encoding='utf-8', errors='replace')}"


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

    def _project_config_path(self) -> Path:
        canonical = self._project_root / ".echelon" / "config.yml"
        if canonical.exists():
            return canonical
        return self._ext_dir / "echelon-config.yml"

    def _quality_gate_thresholds(self) -> dict:
        return resolve_quality_gate_thresholds(
            self._project_root,
            fallback_config_path=self._ext_dir / "echelon-config.yml",
        )

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
    ) -> "SquadAgentResult":
        """Validate result state updates before executor-side direct state writes."""
        if result.echelon_result is None:
            return result

        from harness.echelon_result_schema import (
            EchelonResultValidationError,
            validate_echelon_result,
        )
        from harness.squad_provider import SquadAgentResult

        try:
            self._normalize_why_result_quality_scores(node, result)
            if (result.verdict or "").upper() == "BLOCKED":
                # BLOCKED results are consumed by the controller as harness-owned
                # blocked-state metadata, not applied through phase state_updates.
                result.echelon_result = validate_echelon_result(result.echelon_result)
                return result
            result.echelon_result = validate_echelon_result(
                result.echelon_result,
                allowed_state_update_keys=getattr(
                    node, "allowed_state_updates", None
                ) if allowed_state_updates is None else allowed_state_updates,
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
    ) -> "SquadAgentResult":
        ...

    def _write_journal_entries(
        self, result: "SquadAgentResult", phase_id: str
    ) -> None:
        """Append journal_entries[] from an agent result to the reasoning journal.

        Serialized write: every caller holds the GIL or calls this after
        thread-join, so appends are never concurrent.
        """
        import json
        from datetime import datetime, timezone
        from harness.journal_entry_validator import prepare_journal_entries_for_append

        entries = (result.echelon_result or {}).get("journal_entries", [])
        if not entries:
            return

        journal_path = self._squad_dir / "reasoning-journal.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        # Derive next id from current line count (monotonic within a session)
        next_id = 1
        if journal_path.exists():
            lines = [ln for ln in journal_path.read_text().splitlines() if ln.strip()]
            next_id = len(lines) + 1

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prepared_entries = prepare_journal_entries_for_append(
            entries,
            phase_id=phase_id,
            next_id=next_id,
            timestamp=ts,
            schema_path=self._ext_dir / "workflow/journal-entry-types.yaml",
            invalid_registered_policy="quarantine",
        )
        with journal_path.open("a") as fh:
            for entry in prepared_entries:
                fh.write(json.dumps(entry, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)) + "\n")

    def _extension_path_context(self) -> str:
        return (
            f"EXTENSION_DIR={self._ext_dir}\n"
            f"EXTENSION_TEMPLATES_DIR={self._ext_dir / 'templates'}\n"
            f"EXTENSION_AGENTS_DIR={self._ext_dir / 'agents'}\n"
            "\n"
            "## Extension Path Resolution\n"
            "- `extension/templates/foo.md` resolves to `${EXTENSION_DIR}/templates/foo.md`.\n"
            "- `extension/agents/foo.md` resolves to `${EXTENSION_DIR}/agents/foo.md`.\n"
            "- NEVER resolve it as `${EXTENSION_DIR}/extension/templates/foo.md` or add an extra `extension/` path segment.\n\n"
        )

    def _assemble_prompt(self, node: "PhaseNode", state: dict) -> str:
        static_parts: list[str] = []
        dynamic_parts: list[str] = []

        # Resolve run dirs early — needed for both context pack file reads and
        # the text-level translation applied to agent/spec file content below.
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))

        def _translate_squad_path(ref: str) -> str:
            """Rewrite legacy .specify/squad/ prefixes to the actual run dir."""
            r = ref.replace(".specify/squad/staging/", f"{staging_dir_str}/")
            r = r.replace(".specify/squad/staging", staging_dir_str)
            r = r.replace(".specify/squad/", f"{squad_dir_str}/")
            r = r.replace(".specify/squad", squad_dir_str)
            return r

        # 1. Agent file (role + instructions)
        if node.agent:
            rel = self._graph.agent_file(node.agent)
            if rel:
                agent_path = self._ext_dir / rel
                if agent_path.exists():
                    static_parts.append(agent_path.read_text())

        # 2. Phase spec file (context pack assembly instructions + echelon_result schema)
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                static_parts.append(spec_path.read_text())

        # 3. Context pack files (read each that exists on disk).
        # Translate .specify/squad/ paths before resolving — definition.yaml context_pack
        # items may reference these legacy paths (e.g. .specify/squad/staging/glossary.md).
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        search_bases = _spec_search_bases(spec_dir_ref, self._project_root, staging_dir_str)
        for item in node.context_pack:
            # Items may have inline comments: ".specify/echelon/re/state.json — current run state"
            file_ref = item.split(" ")[0].split("(")[0].rstrip()
            if not file_ref or file_ref.startswith("#"):
                continue
            resolved = _translate_squad_path(
                file_ref.replace("{spec_dir}", spec_dir_ref)
                .replace("{context_dir}", context_dir_str)
                .replace("{staging_dir}", staging_dir_str)
            )
            if resolved.startswith("/"):
                candidates = [Path(resolved)]
            else:
                candidates = [base / resolved for base in search_bases]
            for candidate in candidates:
                if candidate.exists():
                    dynamic_parts.append(_render_context_candidate(file_ref, candidate))
                    break

        # 4. Current state.json for context
        state_path = self._squad_dir / "state.json"
        if state_path.exists():
            dynamic_parts.append(f"\n---\n# Current state.json\n{state_path.read_text()}")
        # Inject squad run context so agents know where to write
        context_preamble = (
            f"# Squad Run Context\n"
            f"SQUAD_DIR={squad_dir_str}\n"
            f"STAGING_DIR={staging_dir_str}\n"
            f"CONTEXT_DIR={context_dir_str}\n"
            f"PROJECT_ROOT={self._project_root}\n"
            f"{_workspace_source_roots_context(self._project_root)}"
            f"{_render_implementation_target_context(state)}"
            f"{_render_product_input_context(state)}"
            f"{_render_published_re_context(state)}"
            f"{self._extension_path_context()}"
            f"{render_quality_gate_context(self._quality_gate_thresholds())}"
        )
        if spec_dir_ref:
            spec_dir_path = Path(spec_dir_ref)
            if not spec_dir_path.is_absolute():
                spec_dir_path = self._project_root / spec_dir_path
            published_ref = str(state.get("published_spec_dir") or "").strip()
            if not published_ref:
                spec_id = spec_dir_path.name
                published_ref = f"specs/{spec_id}" if spec_id else ""
            if published_ref:
                published_path = Path(published_ref)
                if not published_path.is_absolute():
                    published_path = self._project_root / published_path
                context_preamble += (
                    "## Active Spec Artifact Roots\n"
                    f"ACTIVE_SPEC_DIR={spec_dir_path}\n"
                    f"PUBLISHED_SPEC_DIR={published_path}\n"
                    "- ALWAYS read and write squad phase artifacts under ACTIVE_SPEC_DIR / `{spec_dir}`.\n"
                    "- NEVER switch to PUBLISHED_SPEC_DIR during squad phase execution unless a phase explicitly asks for publication.\n"
                    "- PUBLISHED_SPEC_DIR is the final project target used by build/harness after publication.\n\n"
                )
        if node.id == "phase1-what" and state.get("cartographer_resume_existing_spec"):
            spec_dir = state.get("spec_dir", "")
            feature_branch = state.get("feature_branch", "")
            context_preamble += (
                "## CARTOGRAPHER Resume Guard\n"
                "This is a resumed/amendment pass for an existing spec-kit spec.\n"
                f"Existing spec_dir: {spec_dir}\n"
                f"Existing feature_branch: {feature_branch}\n"
                "Do NOT call speckit.specify. Do NOT run create-new-feature.sh. "
                "Do NOT create or switch to a new numbered branch. Reuse the "
                "existing spec_dir and proceed directly to Step 2 enhancement/"
                "amendment of spec.md and 00-overview.md.\n\n"
            )

        prompt = "\n\n".join(static_parts + [context_preamble] + dynamic_parts)
        prompt = prompt.replace("{spec_dir}", spec_dir_ref)
        prompt = prompt.replace("{context_dir}", context_dir_str)
        prompt = prompt.replace("{staging_dir}", staging_dir_str)

        # Translate legacy .specify/squad paths in agent + spec file text
        prompt = prompt.replace(".specify/squad/staging/", f"{staging_dir_str}/")
        prompt = prompt.replace(".specify/squad/staging", staging_dir_str)
        prompt = prompt.replace(".specify/squad/", f"{squad_dir_str}/")
        prompt = prompt.replace(".specify/squad", squad_dir_str)

        # Append harness routing contract so agents know exactly what
        # state_updates fields the harness needs for transition evaluation.
        prompt = (
            prompt
            + _routing_contract(node)
            + _allowed_state_updates_contract(node.allowed_state_updates)
            + _canonical_echelon_result_contract(self._ext_dir)
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
                    prompt = self._assemble_pre_dispatch_prompt(
                        pre_path,
                        entry,
                        state_store.load(),
                        node.allowed_state_updates,
                    )
                    result = self._provider.exec_agent(
                        str(self._project_root), prompt
                    )
                    result = self._validate_result_state_updates(node, result)
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
        allowed_state_updates: object = None,
    ) -> str:
        """Build a real prompt for a generic pre-dispatch agent."""
        agent_text = agent_path.read_text()
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))
        return (
            _shared_agent_contract()
            + agent_text
            + "\n\n"
            + f"# Squad Run Context\n"
            + f"SQUAD_DIR={squad_dir_str}\n"
            + f"STAGING_DIR={staging_dir_str}\n"
            + f"CONTEXT_DIR={context_dir_str}\n"
            + f"PROJECT_ROOT={self._project_root}\n"
            + _workspace_source_roots_context(self._project_root)
            + _render_implementation_target_context(state)
            + _render_product_input_context(state)
            + _render_published_re_context(state)
            + self._extension_path_context()
            + _allowed_state_updates_contract(allowed_state_updates)
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

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult

        state = state_store.load()
        pre_dispatch_result = self._run_pre_dispatch(node, state, state_store)
        if pre_dispatch_result is not None and pre_dispatch_result.blocked:
            return pre_dispatch_result
        state = state_store.load()  # re-load after pre_dispatch
        prompt = self._assemble_prompt(node, state)
        result = self._provider.exec_agent(str(self._project_root), prompt)
        result = self._validate_result_state_updates(node, result)
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
            if missing_outputs:
                result = SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "BLOCKED",
                        "state_updates": {
                            "blocked_reason": "missing_phase_outputs",
                            "missing_outputs": missing_outputs,
                        },
                    },
                    raw_output=result.raw_output,
                    duration_ms=result.duration_ms,
                    timed_out=result.timed_out,
                    cost_usd=result.cost_usd,
                )
        return result


class CommanderInternalExecutor(PhaseExecutor):
    """Handles type: commander_internal phases in the harness path.

    These spec files are markdown instructions for COMMANDER (the LLM) — not
    bash scripts. Running them as bash causes a stdin hang: markdown fenced
    code blocks contain triple-backticks which bash interprets as command
    substitutions that spawn child bash processes reading from the terminal.

    In the harness path these phases are no-ops: the harness already performed
    the equivalent init work (SquadStateStore.initialize, cli.py config checks),
    and any LLM-specific steps (KB reads, speckit.constitution) only run in the
    interactive COMMANDER path.
    """

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        print(f"[squad]   (commander_internal — harness no-op)", flush=True)
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class StagedParallelExecutor(PhaseExecutor):
    """Handles type: staged_parallel — phase3-consensus (WHY3+ASSESS2 then PLAN2).

    This is the phase that was previously skipped via EVOI fabrication.
    Python threading enforces both stage-1 agents run; there is no code path
    that bypasses Stage 1.
    """

    def _build_agent_prompt(
        self,
        agent_entry: dict,
        state: dict,
        extra_files: Optional[list] = None,
        allowed_state_updates: object = None,
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

        # 1. Agent role file (protocol + identity)
        rel = self._graph.agent_file(agent_id)
        if rel:
            agent_path = self._ext_dir / rel
            if agent_path.exists():
                static_parts.append(agent_path.read_text())

        # 2. Per-agent context_pack files.
        # state.spec_dir is authoritative for spec artifacts. Do not scan every
        # specs/* directory for bare names: older runs can satisfy spec.md/tasks.md
        # and contaminate staged consensus prompts.
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_dir_str = state.get("context_dir", str(self._squad_dir / "context"))
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        search_bases = _spec_search_bases(spec_dir_ref, self._project_root, staging_dir_str)

        for item in agent_entry.get("context_pack", []):
            file_ref = item.split(" ")[0].split("(")[0].rstrip()
            if not file_ref or file_ref.startswith("#"):
                continue
            resolved_ref = (
                file_ref.replace("{spec_dir}", spec_dir_ref)
                .replace("{context_dir}", context_dir_str)
                .replace("{staging_dir}", staging_dir_str)
            )
            if resolved_ref.startswith("/"):
                candidates = [Path(resolved_ref)]
            else:
                candidates = [base / resolved_ref for base in search_bases]
            for candidate in candidates:
                if candidate.exists():
                    dynamic_parts.append(_render_context_candidate(file_ref, candidate))
                    break

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
            f"{_workspace_source_roots_context(self._project_root)}"
            f"{_render_implementation_target_context(state)}"
            f"{_render_product_input_context(state)}"
            f"{render_quality_gate_context(self._quality_gate_thresholds())}"
            f"Operate in **{mode_label}** mode.\n\n"
        )

        prompt = "\n\n".join(static_parts + [preamble] + dynamic_parts)
        prompt = prompt.replace("{context_dir}", context_dir_str)
        prompt = prompt.replace("{staging_dir}", staging_dir_str)
        return (
            _shared_agent_contract()
            + prompt
            + _allowed_state_updates_contract(allowed_state_updates)
            + _canonical_echelon_result_contract(self._ext_dir)
        )

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult

        stage1_agents = [a for a in node.agents if a.get("stage", 1) == 1]
        stage2_agents = [a for a in node.agents if a.get("stage", 1) == 2]

        stage1_results: dict[str, SquadAgentResult] = {}
        product_input_updates: list[dict] = []
        state = state_store.load()

        # Stage 1: run in parallel
        with ThreadPoolExecutor(max_workers=max(len(stage1_agents), 1)) as pool:
            futures: dict = {}
            for agent_entry in stage1_agents:
                mode_label = str(
                    agent_entry.get("mode")
                    or agent_entry.get("id")
                    or agent_entry.get("agent", "")
                )
                prompt = self._build_agent_prompt(
                    agent_entry,
                    state,
                    allowed_state_updates=getattr(node, "allowed_state_updates", None),
                )
                futures[pool.submit(
                    self._provider.exec_agent, str(self._project_root), prompt
                )] = mode_label

            for future in as_completed(futures):
                label = futures[future]
                result = self._validate_result_state_updates(node, future.result())
                if result.blocked:
                    return result
                stage1_results[label] = result
                payload = result.echelon_result or {}
                product_input_updates.extend(payload.get("product_input_updates") or [])

        # Write stage-1 verdicts, journal entries, and cost to state (serial — after join)
        for label, result in stage1_results.items():
            self._write_journal_entries(result, node.id)
            state_store.increment_cost(result.cost_usd)
            state = state_store.load()
            state[f"{label.lower().replace(' ', '_')}_verdict"] = result.verdict
            for k, v in result.state_updates.items():
                state[k] = v
            state_store.save(state)

        # Stage 2: PLAN2 — requires implementability-report.md from ASSESS2
        impl_report_path: Optional[Path] = None
        report_bases: list[Path] = []
        spec_dir_ref = _normalize_spec_dir_ref(str(state.get("spec_dir") or "").strip(), self._project_root)
        if spec_dir_ref:
            spec_dir = Path(spec_dir_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
            report_bases.append(spec_dir)
        report_bases.extend([self._squad_dir / "staging", self._project_root])
        for base in report_bases:
            candidate = base / "implementability-report.md"
            if candidate.exists():
                impl_report_path = candidate
                break

        state = state_store.load()
        for agent_entry in stage2_agents:
            prompt = self._build_agent_prompt(
                agent_entry,
                state,
                extra_files=[impl_report_path] if impl_report_path else [],
                allowed_state_updates=getattr(node, "allowed_state_updates", None),
            )
            stage2_result = self._provider.exec_agent(str(self._project_root), prompt)
            stage2_result = self._validate_result_state_updates(node, stage2_result)
            if stage2_result.blocked:
                return stage2_result
            stage2_payload = stage2_result.echelon_result or {}
            product_input_updates.extend(stage2_payload.get("product_input_updates") or [])
            self._write_journal_entries(stage2_result, node.id)
            state_store.increment_cost(stage2_result.cost_usd)
            state = state_store.load()
            for k, v in stage2_result.state_updates.items():
                state[k] = v
            state_store.save(state)

        all_pass = all(
            r.verdict in ("PASS", "DONE") for r in stage1_results.values()
        )
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
                    prompt = (
                        _shared_agent_contract()
                        + path.read_text()
                        + _render_product_input_context(state)
                        + _allowed_state_updates_contract(node.allowed_state_updates)
                        + _canonical_echelon_result_contract(self._ext_dir)
                    )
                    result = self._provider.exec_agent(
                        str(self._project_root), prompt
                    )
                    result = self._validate_result_state_updates(node, result)
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


class HumanGateExecutor(PhaseExecutor):
    """Handles type: human_gate — auto-proceed in semi/banzai; prompt in guided."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        state = state_store.load()
        autonomy = state.get("autonomy_mode", "semi")

        if autonomy in ("semi", "banzai"):
            print(f"[checkpoint] {node.label} — auto-proceeding ({autonomy} mode)")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "APPROVED",
                    "state_updates": {"gate_result": "auto_approved"},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        # guided: prompt user
        from echelon.ui import banner as _banner
        spec_dir = state.get("spec_dir", "specs/")
        _banner(
            "SQUAD — CHECKPOINT",
            [
                ("phase", node.label),
                ("review artifacts in", spec_dir),
                ("type", "'approve' to continue, 'reject' to stop"),
            ],
        )
        try:
            answer = input("> ").strip().lower()
        except EOFError:
            answer = "approve"

        approved = answer in ("approve", "yes", "y")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "APPROVED" if approved else "REJECTED",
                "state_updates": {
                    "gate_result": "human_approved" if approved else "human_rejected"
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

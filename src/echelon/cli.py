#!/usr/bin/env python3
"""echelon CLI — deterministic entry points for echelon skills.

LLM commands read the corresponding skill markdown, inject arguments,
and invoke the configured LLM CLI so the LLM only executes the skill.

`init` is pure Python — no LLM involved.

Command prose for every AI tool:
  .echelon/prosaic/commands/echelon.<cmd>.md
Auto-detected from ECHELON_LLM (default: claude).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import fcntl
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from harness.banzai_protocol import active_banzai_default_protocol_fingerprint
from harness.squad_state import (
    StateAdvanceError,
    validate_banzai_default_reassessment_record,
    validate_banzai_evidence_reassessment_record,
)
from harness.gitops import copy_prosaic_runtime_tree, copy_runtime_tree
from harness.recovery_instruction import (
    RecoveryInstruction,
    RecoveryInstructionError,
    RecoveryKind,
    retry_phase_recovery,
    validate_recovery_instruction,
)
from harness.runtime_surface import prune_delivery_workflow_definition
from harness.phase_a_readiness import coverage_contract_error
from harness.phase1_quality import has_current_phase1_quality_prerequisite
from harness.issue_identity import (
    issue_fingerprint,
    matching_issue_resolution,
    record_issue_resolution,
)
from echelon.version import CLI_VERSION

# Maps CLI commands to deployed Prosaic command names used to derive file paths.
# NOTE: "run" is intentionally absent — it is handled by the Python harness
# (_cmd_run) and must never fall through to the skill-based LLM path.
# Keeping "run" here would cause infinite recursion: skill → claude -p →
# echelon.run.md → "echelon spec run" → skill → ... (155 nested processes).



from echelon.workspace_model import discover_workspace  # noqa: E402  (after stdlib imports)
from echelon.ui import banner as _banner  # noqa: E402  (after stdlib imports)


_RE_V2_MAX_CLI_DISPATCH_ACTIVE_MS = 30 * 60_000


def _bound_re_v2_executor_active_ms(
    catalog: object,
    *,
    preserve_contract_hashes: object = (),
) -> object:
    """Bound one RE provider call independently of the cumulative run budget."""
    from dataclasses import replace

    preserved = frozenset(preserve_contract_hashes)

    def bounded_entry(entry: object) -> object:
        if getattr(entry, "executor_contract_hash", None) in preserved:
            return entry
        if getattr(entry, "execution_mode", None) != "cli":
            return entry
        limits = getattr(entry, "limits", None)
        current = getattr(limits, "max_active_ms_per_dispatch", None)
        if not isinstance(current, int) or current <= _RE_V2_MAX_CLI_DISPATCH_ACTIVE_MS:
            return entry
        return replace(
            entry,
            limits=replace(
                limits,
                max_active_ms_per_dispatch=_RE_V2_MAX_CLI_DISPATCH_ACTIVE_MS,
            ),
        )

    inherited = getattr(catalog, "inherited_catalog", None)
    semantic = getattr(catalog, "semantic_entries", None)
    if inherited is not None and isinstance(semantic, tuple):
        return replace(
            catalog,
            inherited_catalog=_bound_re_v2_executor_active_ms(
                inherited,
                preserve_contract_hashes=preserved,
            ),
            semantic_entries=tuple(bounded_entry(item) for item in semantic),
        )
    entries = getattr(catalog, "entries", None)
    if isinstance(entries, tuple):
        return replace(catalog, entries=tuple(bounded_entry(item) for item in entries))
    return catalog


USAGE = f"""\
echelon {CLI_VERSION}

Usage: echelon <command> [args...]

Commands:
  workspace init [--llm <provider>] [--openai-base-url <url>] [--openai-model <model>]
                    [--openai-api-key-file <path>|--openai-api-key-env <env>]
                    [--allow-unsafe-host-execution|--no-unsafe-host-execution]
                    One-time project setup (no LLM)
  workspace doctor                          Check workspace/source/runtime contract
  workspace sources sync [--write]          Sync discovered sources/* roots into config
  workspace migrate [--write] [--commit] [--message <msg>]
                                            Migrate legacy workspace layout

  spec run <description> [--mode semi|banzai|guided] [--reset] [--perfectionist]
                    [--message <text>] [--next-phase <id>]
                    [--target <source-id-or-path>]... [--re-source <source-id-or-re-path>]... [--init]
                    [--ignore-re]
                                            Run Phase A squad spec authoring;
                                            --perfectionist requests exhaustive Cartographer authoring.
  spec status                               Show current run state, artifacts, cost, and next action.
  spec continue [--mode semi|banzai|guided] Run the next no-input Phase A recovery action.
  spec resume "<answers>"                   Answer escalation questions from a blocked run.
  spec rewind <phase-id> [--commit <sha>] [--next-phase <phase-id>]
                                            Rewind the active squad run to a safe checkpoint.
  spec switch <spec-or-run-id> [--stash | --discard --confirm] [--restore-stash]
                                            Select a checkpointed Phase A spec run.
  spec drop-target <spec_id> <target> --confirm
                                            Remove an unused target from an unfinished run.
  spec retarget <spec_id> --target <source-id-or-path>... [--confirm]
                                            Destructively replace all implementation targets.
  spec checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]
                                            Manage Phase A/spec checkpoints.
  spec targets <spec_id>                    Display every task grouped by delivery target.
  spec artifacts <spec_id>                  Generate specs/<id>/ARTIFACTS.md.
  spec verify <spec_id> [--reconcile] [--dry-run]
                                            Audit implementation against spec.
  spec reopen <spec_id> [from=<report>]      Reopen spec from fulfillment gaps.
  spec bugfix <spec_id> <description>        Diagnose and plan a bugfix.
  spec change <spec_id> <description>        Plan a scope change.
  spec amend <spec_id> <description> [--input <role:path>]... [--dry-run]
                                            Prepare an isolated amendment for an unbuilt spec.

  phase list                                List workflow phases available for manual replay.
  phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided]
                    [--message <text>]
                                            Run one explicit phase through COMMANDER contracts.

  re run [--engine v1|v2] [--goal baseline|inventory] [--shadow]
                    [--re-policy none|cached-only|changed|refresh-all]
                    [--re-max-inner <n>] [--reset]
                                            Run or reuse workspace reverse engineering.
  re refresh --source <source-id>           Refresh and publish one declared source.
  re status [--json]                        Show live RE state, source quality, debt, and next action.
  re continue [--re-max-inner <n>] [--re-token-limit <n>] [--re-time-limit-minutes <n>]
                                            Continue the active RE run.
  re resume (<answer>|--recommended|--banzai) [--re-token-limit <n>] [--re-time-limit-minutes <n>] [--re-semantic-token-limit <n>] [--re-semantic-time-limit-minutes <n>]
                                            Resume blocked RE with a human answer.
  re finalize [<run-id>] --allow-partial    Accept recorded debt and stop a blocked RE run.
  re synthesize [<run-id>] --allow-partial [--re-token-limit <n>]
                                            Build workspace synthesis from partial source results.
  re publish <run-id> [--allow-partial] [--commit]
                                            Publish validated workspace RE output.

  benchmark list                            List experimental benchmark fixtures and variants.
  benchmark show [latest|<summary-path-or-run-dir>]
                                            Print saved benchmark scores.
  benchmark run <fixture> --variant <id> [--baseline-ref <ref>] [--artifact-only] [--dry-run]
                                            Run or print an artifact-quality benchmark variant.

  llm smoke-openai-compatible [--base-url <url>] [--model <model>]
                    [--api-key-file <path>|--api-key-env <env>] [--no-streaming]
                                            Exercise an OpenAI-compatible endpoint with a tiny tool-call loop.

  stack list [--json]                       List available Echelon stacks.
  stack detect [--target <path>] [--artifacts <path>] [--write] [--format text|yaml] [--json]
                                            Detect source/artifact stack evidence.
  stack preflight [--stack <id>] [--target-archetype <id>] [--from-detect <path>] [--probe-tools] [--json]
                                            Check selected stack commands, registries, and tool probes.

  delivery init                              Initialize delivery environment: sandbox, mirror, verify.
  delivery target <spec_id>                  Prepare target-scoped delivery metadata from spec targets.
  delivery status [spec_id] [--strategy <s>] Show current Phase B delivery/Ralph state.
  delivery verify-local <spec_id> [--target <id>] [--engine auto|docker|podman] [--yes]
                                            Explicit macOS local verification; does not affect landing.
  delivery cleanup-local <local-run-id>      Recover one journalled local verification run.
  delivery run <spec_id> [--mode <m>] [--strategy <s>] [--max-outer <n>] [--max-inner <n>]
                    [--token-budget <n>] [--auto-merge|--no-auto-merge] [--kill-losers] [--reset]
                                            Run build→verify→PR loop.
                    Legacy key=value options remain accepted for compatibility.
  delivery continue <spec_id> [--strategy <s>] [--mode <guided|semi|banzai>]
                                            Continue a blocked delivery run without a new answer.
  delivery resume <spec_id> "<answer>" [--strategy <s>] [--mode <guided|semi|banzai>]
                                            Resume a blocked delivery run with a human answer.
  delivery checkpoint list <spec_id> [--strategy <s>]
                                            List delivery checkpoint/recovery commits.
  delivery land <spec_id> [--continue] [--prepare-only] [--no-autoresolve]
                    [--allow-fulfillment-gaps] [--strategy merge|rebase]
                                            Land a spec: merge PR/branch, clean up.

Command prose for every provider:
  .echelon/prosaic/commands/echelon.<cmd>.md
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

def _workspace_git_preflight(project_root: Path, *, command_name: str) -> None:
    manifest = discover_workspace(project_root)
    if manifest.workspace.git_present:
        return

    source_paths = [source.path for source in manifest.sources if source.path != "."]
    ignore_entries = [f"/{path}/" for path in source_paths] or ["/source-repo/"]
    ignore_entries.append("/runs/")
    ignore_lines = "\n".join(ignore_entries)
    print(
        "✗ Echelon workspace root is not a Git repo.\n\n"
        "Echelon requires workspace Git so specs, run state, and recovery metadata "
        "have durable version history.\n\n"
        "Fix:\n"
        "  git init\n"
        f"  printf \"{ignore_lines}\\n\" >> .gitignore\n"
        "  git add .gitignore specs\n"
        "  git commit -m \"chore: initialize echelon workspace\"\n\n"
        "Then rerun:\n"
        f"  {command_name}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _workspace_git_present(project_root: Path) -> bool:
    return discover_workspace(project_root).workspace.git_present



def _print_legacy_branchless_recovery_notice(command_name: str) -> None:
    print(
        "legacy branchless run detected; continuing for recovery only\n"
        "Initialize workspace Git before starting new Echelon runs.",
        file=sys.stderr,
    )


def _command_display(prefix: str, args: list[str]) -> str:
    return shlex.join([*prefix.split(), *args])





# ── land (pure Python, no LLM) ────────────────────────────────────────────







# ── harness subcommands (pure Python, no LLM) ────────────────────────────

def _print_harness_config_error(error: Exception) -> None:
    field_path = getattr(error, "field_path", None)
    if field_path == "target_repo":
        print(f"✗ Harness config error: {error}", file=sys.stderr)
        return
    print(f"✗ Harness config error: {error}\n  Fix: re-run 'echelon delivery init'.", file=sys.stderr)


from echelon.delivery_service import (
    HarnessWorkspaceTarget,
    _apply_target_verify_command_detection,
    _block_if_spec_task_targets_mismatch,
    _format_missing_verify_command_resume_message,
    _resolve_harness_workspace_target,
    _source_dispatch_metadata,
    _sync_polyrepo_runtime_extension,
    _workspace_target_dispatch_metadata,
)


_RUNS_GITIGNORE_PATTERNS = (
    "**/.echelon/checkpoints.json",
    "**/.echelon/checkpoints.lock",
    "**/.echelon/.checkpoints.json.*.tmp",
    "*/state.json",
    "*/*.tmp",
    ".current*",
)


def _ensure_runs_gitignore(gitignore: Path) -> None:
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [pattern for pattern in _RUNS_GITIGNORE_PATTERNS if pattern not in lines]
    if not missing:
        return
    gitignore.write_text("\n".join([*lines, *missing]) + "\n", encoding="utf-8")


def _setup_run_dir(project_root: Path, run_id: str) -> Path:
    """Create runs/<run_id>/ + staging/, write runs/.gitignore, update runs/.current."""
    from harness.paths import runs_dir
    runs_root = runs_dir(project_root)
    runs_root.mkdir(exist_ok=True)

    _ensure_runs_gitignore(runs_root / ".gitignore")

    run_dir = runs_root / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "staging").mkdir(exist_ok=True)

    (runs_root / ".current").write_text(f"{run_id}\n")
    return run_dir


def _find_current_run_dir(project_root: Path) -> Optional[Path]:
    """Return the active run dir from a .current pointer, or the newest run dir.

    Checks runs/.current first, then falls back to the newest run directory
    with state.json when no pointer exists.
    """
    from echelon.spec_service import _is_squad_run_dir, _iter_run_dirs

    base_dir = project_root / "runs"
    current_file = base_dir / ".current"
    if current_file.exists():
        run_id = current_file.read_text().strip()
        if run_id:
            run_dir = base_dir / run_id
            if _is_squad_run_dir(run_dir, require_state=False):
                return run_dir
    # No .current pointer — fall back to newest run dir that has state.json
    all_runs = _iter_run_dirs(project_root)
    return all_runs[0] if all_runs else None












def _active_versioned_decision(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Return one exact unresolved v2/v3 decision authority."""
    decision = _validated_versioned_decision(state)
    if decision is None:
        return None
    return (
        decision
        if decision["status"]
        in {"pending", "resolving", "awaiting_human", "failed"}
        else None
    )


def _active_v2_decision(state: dict) -> dict[str, object] | None:
    """Compatibility view retained for callers auditing legacy v2 state."""
    raw_decision = state.get("blocked_decision")
    if not isinstance(raw_decision, dict) or raw_decision.get("schema_version") != 2:
        return None
    return _active_versioned_decision(state)


def _validated_versioned_decision(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Validate a persisted v2/v3 decision and its exact recovery pair."""
    from harness.blocked_decision import validate_blocked_decision
    from harness.recovery_instruction import validate_decision_recovery_pair

    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    decision = validate_blocked_decision(raw_decision)
    validate_decision_recovery_pair(
        decision,
        state.get("recovery_instruction"),
    )
    return decision


def _v2_automatic_decision_is_registered(
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
    graph: object | None = None,
) -> bool:
    """Reconstruct intrinsic v2 automatic eligibility from registered policy."""
    from echelon.spec_service import (
        _decision_automatic_eligibility_under_current_policy,
    )

    return (
        decision.get("schema_version") == 2
        and _decision_automatic_eligibility_under_current_policy(
            decision,
            project_root=project_root,
            graph=graph,
        )
    )














































































































def _find_latest_harness_build_state(project_root: Path) -> Optional[dict]:
    """Return the newest readable harness build state, unless newer spec work exists.

    Returns None when a newer squad run exists than the newest harness build;
    that means new spec work has been done since the last harness run.
    """
    runs = project_root / "runs"
    if not runs.exists():
        return None

    # Latest squad-run timestamp (spec-* current format, run-* legacy)
    latest_squad_ts = ""
    for d in runs.iterdir():
        if (
            d.is_dir()
            and (d.name.startswith("spec-") or d.name.startswith("run-"))
            and (d / "state.json").exists()
        ):
            ts = d.name.partition("-")[2]  # "YYYYMMDD-HHMMSS-ffffff"
            if ts > latest_squad_ts:
                latest_squad_ts = ts

    states = _iter_harness_build_states(project_root)
    if not states:
        return None
    latest = states[0]
    build_id = str(latest.get("build_id") or "")
    build_ts = build_id.partition("-")[2]
    if latest_squad_ts > build_ts:
        # A squad run is newer than this harness build — new spec work exists.
        return None
    return latest


def _iter_harness_build_states(project_root: Path) -> list[dict]:
    import json as _json

    states: list[dict] = []
    runs = project_root / "runs"
    if not runs.exists():
        return states
    build_roots: list[tuple[Path, str]] = [(runs, "")]
    for target_runs in sorted(runs.glob("targets/*/runs")):
        build_roots.append((target_runs, target_runs.parent.name))
    for build_root, target_id in build_roots:
        for build in sorted(build_root.glob("build-*/"), reverse=True):
            state_dir = build / "state"
            if not state_dir.exists():
                continue
            for state_file in sorted(state_dir.glob("*.json")):
                try:
                    data = _json.loads(state_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict):
                    data.setdefault("build_id", build.name)
                    data.setdefault("strategy_id", state_file.stem)
                    data.setdefault("state_file", str(state_file))
                    if target_id:
                        data.setdefault("target_id", target_id)
                    states.append(data)
    return sorted(states, key=lambda state: str(state.get("build_id") or ""), reverse=True)






















def _find_converged_harness_build(project_root: Path) -> Optional[tuple[str, Optional[str]]]:
    """Return (spec_id, pr_url) when the most recent harness build converged."""
    data = _find_latest_harness_build_state(project_root)
    if data and data.get("status") == "converged":
        return data.get("spec_id", ""), data.get("pr_url")
    return None




































def _project_echelon_config(project_root: Path) -> Path:
    return project_root / ".echelon" / "config.yml"


















def _repo_relative_or_absolute(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)






def _copy_missing_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if target.exists():
            continue
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)




































# Fallback only. Normal status rendering derives the roadmap from
# workflow/definition.yaml so the UI cannot drift from the externalized graph.











































# ── Skill resolution ──────────────────────────────────────────────────────

from harness.skill_loader import (
    find_skill as _find_skill_impl,
)
from harness.prosaic_prompt_loader import (
    ProsaicPromptLoadError,
    ProsaicPromptLoader,
)
from harness.config import load_config
from harness.llm_provider import AICodingCliProvider
from harness.provider_capability import ProviderCapability


def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    return _find_skill_impl(skill_base, project_dir, cli)






def _load_cli_config(project_dir: Path):
    from harness.config import effective_llm_config

    return effective_llm_config(load_config(project_dir, squad_only=True))








def _require_provider_capability(
    command_name: str,
    required: ProviderCapability,
    *,
    project_dir: Path | None = None,
) -> None:
    from echelon.spec_service import (
        _capability_article,
        _capability_label,
        _supported_capability_label,
    )

    root = project_dir or Path.cwd()
    try:
        config = _load_cli_config(root)
    except Exception:
        # Capability gates must not mask existing config/preflight diagnostics.
        # If config cannot load, let the command's normal validation report it.
        return
    provider = AICodingCliProvider(config)
    if required in provider.capabilities:
        return
    provider_name = config.llm.cli
    supported = _supported_capability_label(provider.capabilities)
    required_label = _capability_label(required)
    article = _capability_article(required)
    print(
        f'Provider "{provider_name}" supports {supported}.\n'
        f'Command "{command_name}" requires {required_label} capability.\n'
        f"Choose {article} {required_label}-capable provider.",
        file=sys.stderr,
    )
    sys.exit(2)








# ── RE lifecycle and publication subcommands ────────────────────────────────

_RE_PHASE_LABELS = {
    "re-extract-0-preflight": "preflight",
    "re-extract-1-analyze": "source analysis",
    "re-extract-2-specify": "domain specification and workspace synthesis",
    "re-extract-3-verify": "coverage verification",
    "re-extract-4-expand": "coverage expansion",
    "re-extract-5-validate": "semantic validation",
    "re-extract-6-checklist": "extraction checklist",
    "re-extract-7-constitute": "constitution generation",
}


def _read_re_summary_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _re_source_progress(state: dict) -> str:
    raw_states = state.get("re_source_states")
    source_states = raw_states if isinstance(raw_states, dict) else {}
    raw_order = state.get("re_source_order")
    ordered = (
        [value for value in raw_order if isinstance(value, str)]
        if isinstance(raw_order, list)
        else []
    )
    source_ids = list(
        dict.fromkeys(
            [*ordered, *(key for key in source_states if isinstance(key, str))]
        )
    )
    if not source_ids:
        return "not initialized"
    statuses = [
        str(source_states.get(source_id, {}).get("status") or "pending")
        if isinstance(source_states.get(source_id), dict)
        else "pending"
        for source_id in source_ids
    ]
    passed = statuses.count("passed")
    summary = f"{passed}/{len(source_ids)} passed"
    partial = statuses.count("partial_quality_debt")
    active = statuses.count("active")
    blocked = statuses.count("blocked")
    pending = statuses.count("pending")
    extras: list[str] = []
    if partial:
        extras.append(f"{partial} partial")
    if active:
        extras.append(f"{active} active")
    if blocked:
        extras.append(f"{blocked} blocked")
    if pending:
        extras.append(f"{pending} pending")
    return summary + (" · " + " · ".join(extras) if extras else "")


def _re_domain_count(run_re_dir: Path) -> str:
    architecture = _read_re_summary_state(
        run_re_dir / "workspace" / "architecture-map.json"
    )
    domains = architecture.get("domains")
    if not isinstance(domains, list):
        return "not available"
    return str(len(domains))


def _re_status_source_rows(run_re_dir: Path, state: dict) -> list[str]:
    """Render source-quality evidence without requiring callers to inspect JSON."""
    raw_states = state.get("re_source_states")
    source_states = raw_states if isinstance(raw_states, dict) else {}
    raw_order = state.get("re_source_order")
    ordered = (
        [source_id for source_id in raw_order if isinstance(source_id, str)]
        if isinstance(raw_order, list)
        else []
    )
    source_ids = list(
        dict.fromkeys([*ordered, *(key for key in source_states if isinstance(key, str))])
    )
    rows: list[str] = []
    for source_id in source_ids:
        raw_source_state = source_states.get(source_id)
        source_state = raw_source_state if isinstance(raw_source_state, dict) else {}
        report = _read_re_summary_state(
            run_re_dir / "quality" / "sources" / f"{source_id}.json"
        )
        status = str(source_state.get("status") or "pending").replace(
            "_", " "
        )
        coverage = report.get("coverage_pct", source_state.get("coverage_pct"))
        coverage_text = f"{coverage:.1f}%" if isinstance(coverage, (int, float)) else "—"
        details = [coverage_text]
        orphan_paths = report.get("orphan_paths")
        if isinstance(orphan_paths, list) and orphan_paths:
            details.append(f"{len(orphan_paths)} uncovered")
        domain_failures = report.get("domain_failures")
        if isinstance(domain_failures, list) and domain_failures:
            count = len(domain_failures)
            details.append(f"{count} incomplete domain" + ("s" if count != 1 else ""))
        rows.append(f"  {source_id:<38} {status:<22} {' · '.join(details)}")
    return rows


def _re_status_display_state(state: dict, controller_status: str) -> dict:
    """Project stale active sources into the controller's terminal state."""
    if controller_status != "blocked":
        return state
    raw_states = state.get("re_source_states")
    if not isinstance(raw_states, dict):
        return state
    source_states: dict[str, object] = {}
    for source_id, raw_source_state in raw_states.items():
        if (
            isinstance(raw_source_state, dict)
            and raw_source_state.get("status") == "active"
        ):
            source_states[source_id] = {**raw_source_state, "status": "blocked"}
        else:
            source_states[source_id] = raw_source_state
    return {**state, "re_source_states": source_states}


def _format_re_token_budget(state: dict, outer: dict) -> str:
    usage = state.get("re_token_usage")
    profile = state.get("re_execution_profile")
    if not isinstance(profile, dict):
        profile = outer.get("re_execution_profile")
    limit = profile.get("hard_token_limit") if isinstance(profile, dict) else None
    if not isinstance(usage, int) or not isinstance(limit, int) or limit <= 0:
        return "not available"
    return f"{usage / 1_000_000:.1f}M / {limit / 1_000_000:.1f}M ({usage / limit:.0%})"


def _detect_re_engine_for_cli(run_dir: Path) -> str:
    """Detect a pinned engine and preserve recorded identity in refusal errors."""
    from harness.re_v2.run_store import ReV2RunStoreError, detect_re_engine

    try:
        return detect_re_engine(run_dir)
    except ReV2RunStoreError as exc:
        manifest_path = run_dir.resolve() / "v2" / "run.json"
        recorded: tuple[str, str] | None = None
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                raw = json.loads(manifest_path.read_bytes())
                if isinstance(raw, dict):
                    engine = raw.get("engine")
                    protocol = raw.get("engine_protocol_version")
                    if (
                        isinstance(engine, str)
                        and engine
                        and isinstance(protocol, str)
                        and protocol
                    ):
                        recorded = (engine, protocol)
            except (OSError, ValueError, TypeError):
                pass
        if recorded is not None:
            raise ValueError(
                "unsupported pinned RE engine/protocol "
                f"{recorded[0]!r}/{recorded[1]!r}; install an Echelon version "
                "compatible with the recorded protocol"
            ) from exc
        raise ValueError(str(exc)) from exc


def _resolve_named_re_run(project_root: Path, run_id: str) -> Path:
    """Resolve one direct child of runs without accepting path syntax."""
    if (
        not run_id
        or run_id in {".", ".."}
        or any(
            character
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in run_id
        )
    ):
        raise ValueError(f"unsafe RE run ID: {run_id!r}")
    runs = project_root.resolve() / "runs"
    run_dir = runs / run_id
    if run_dir.resolve().parent != runs.resolve():
        raise ValueError("RE run escaped the workspace run root")
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError(f"RE run does not exist: {run_id}")
    return run_dir


def _cmd_re_status(args: list[str]) -> None:
    """Show the active RE controller state and every source's quality outcome."""
    from harness.re_lifecycle import resolve_current_re_run
    from harness.re_v2.status import ReV2StatusError, render_v2_status

    as_json = False
    positional: list[str] = []
    for arg in args:
        if arg == "--json" and not as_json:
            as_json = True
        elif arg.startswith("-"):
            print(f"echelon re status: unknown argument {arg!r}", file=sys.stderr)
            raise SystemExit(2)
        else:
            positional.append(arg)
    if len(positional) > 1:
        print("Usage: echelon re status [<run-id>] [--json]", file=sys.stderr)
        raise SystemExit(2)
    try:
        run_dir = (
            _resolve_named_re_run(Path.cwd(), positional[0])
            if positional
            else resolve_current_re_run(Path.cwd())
        )
    except ValueError as exc:
        print(f"echelon re status: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if run_dir is None:
        print("echelon re status: no active RE run", file=sys.stderr)
        raise SystemExit(2)
    try:
        engine = _detect_re_engine_for_cli(run_dir)
        if engine == "v2":
            if as_json:
                print(render_v2_status(run_dir, as_json=True), end="")
            else:
                from echelon.re_ui import print_re_status_card

                document = json.loads(render_v2_status(run_dir, as_json=True))
                print_re_status_card(document)
            return
    except (ReV2StatusError, ValueError) as exc:
        from echelon.re_ui import print_re_error

        print_re_error("echelon re status", exc)
        raise SystemExit(2) from exc
    if as_json:
        print(
            "echelon re status: --json is available only for pinned v2 runs",
            file=sys.stderr,
        )
        raise SystemExit(2)
    run_re_dir = run_dir / "re"
    outer = _read_re_summary_state(run_dir / "state.json")
    inner = _read_re_summary_state(run_re_dir / "state.json")
    if not inner:
        print(f"echelon re status: missing controller state for {run_dir.name}", file=sys.stderr)
        raise SystemExit(2)
    controller_status = str(inner.get("status") or "unknown")
    display_inner = _re_status_display_state(inner, controller_status)
    lifecycle_status = str(outer.get("status") or "unknown")
    phase = str(inner.get("phase") or outer.get("phase") or "unknown")
    phase_label = _RE_PHASE_LABELS.get(phase, "current controller phase")
    source_rows = _re_status_source_rows(run_re_dir, display_inner)
    raw_source_states = display_inner.get("re_source_states")
    source_states = raw_source_states if isinstance(raw_source_states, dict) else {}
    source_statuses = [
        value.get("status")
        for value in source_states.values()
        if isinstance(value, dict)
    ]
    active_source_count = sum(status == "active" for status in source_statuses)
    partial_count = sum(
        status == "partial_quality_debt" for status in source_statuses
    )
    nonpassed_count = sum(status != "passed" for status in source_statuses)
    finalized_partial = (
        outer.get("finalized_partial") is True
        and outer.get("golddigger_status") == "partial"
    )
    publication_complete = outer.get("publication_complete") is True
    synthesis_status = (
        "complete"
        if inner.get("re_workspace_synthesis_complete") is True
        else "incomplete (accepted partial debt)"
        if finalized_partial
        else "pending"
    )
    fields = [
        ("run", run_dir.name),
        ("controller", controller_status),
        ("lifecycle", lifecycle_status),
        ("phase", f"{phase} — {phase_label}"),
        ("policy", str(outer.get("re_policy") or "unknown")),
        ("sources", _re_source_progress(display_inner)),
        ("synthesis", synthesis_status),
        ("token budget", _format_re_token_budget(inner, outer)),
    ]
    if finalized_partial:
        raw_finalization = outer.get("re_partial_finalization")
        finalization = raw_finalization if isinstance(raw_finalization, dict) else {}
        semantic_count = int(finalization.get("semantic_failure_count") or 0)
        raw_semantic_sources = finalization.get("semantic_failure_sources")
        semantic_sources = (
            [value for value in raw_semantic_sources if isinstance(value, str)]
            if isinstance(raw_semantic_sources, list)
            else []
        )
        fields.append(
            (
                "semantic debt",
                f"{semantic_count} finding{'s' if semantic_count != 1 else ''} across "
                + (", ".join(semantic_sources) or "no named source"),
            )
        )
    if publication_complete:
        fields.append(
            (
                "publication",
                f"generation {int(outer.get('generation') or 0)} "
                f"({outer.get('golddigger_status') or 'unknown'})",
            )
        )
    if controller_status == "blocked":
        fields.extend(
            (
                ("blocked reason", str(inner.get("blocked_reason") or "unknown")),
                ("detail", str(inner.get("re_agent_result_detail") or "not available")),
            )
        )
    _banner(
        "RE STATUS",
        fields,
        subtitle="Live controller state and deterministic source-quality outcomes.",
    )
    if lifecycle_status != controller_status:
        print(
            "\nNote: outer lifecycle state is "
            f"{lifecycle_status} while the live controller state is {controller_status}."
        )
    if source_rows:
        print("\nSource quality")
        print("  source                                 status                 coverage / debt")
        print("  ─────────────────────────────────────  ─────────────────────  ─────────────────")
        print("\n".join(source_rows))
    if finalized_partial and publication_complete:
        action = (
            "This run is finalized and published as partial; debt remains explicit. "
            "No continuation is required."
        )
    elif finalized_partial:
        action = (
            f"This run is finalized as partial. Publish it with `echelon re publish "
            f"{run_dir.name} --allow-partial`."
        )
    elif controller_status == "in_progress":
        action = "Do not start another continuation while the controller is active."
    elif controller_status == "blocked":
        action = (
            "The controller is stopped at the blocker shown above. Resolve it if "
            "needed, then run `echelon re continue`."
        )
    elif active_source_count:
        action = "Do not start another continuation while a source is active."
    elif partial_count:
        action = (
            f"{partial_count} source(s) have partial quality debt; this is not a full-quality outcome. "
            "Raise --re-max-inner above the current budget, then continue."
        )
    elif nonpassed_count:
        action = (
            f"{nonpassed_count} source(s) have not passed the source-quality gate. "
            "Continue the current RE run."
        )
    else:
        action = "All sources have passed the controller's source-quality gate."
    print(f"\nNext action: {action}")


def _print_re_continue_summary(
    project_root: Path,
    *,
    re_max_inner: int | None,
) -> None:
    """Print controller-owned RE orientation before any provider dispatch."""
    from harness.re_lifecycle import resolve_current_re_run

    run_dir = resolve_current_re_run(project_root)
    if run_dir is None:
        return
    run_re_dir = run_dir / "re"
    outer = _read_re_summary_state(run_dir / "state.json")
    inner = _read_re_summary_state(run_re_dir / "state.json")
    status = str(outer.get("status") or inner.get("status") or "unknown")
    phase = str(inner.get("phase") or outer.get("phase") or "unknown")
    phase_label = _RE_PHASE_LABELS.get(phase, "current controller phase")
    coverage = inner.get("coverage_threshold")
    resolution = inner.get("resolution_threshold")
    quality = (
        f"coverage {coverage}% · resolution {resolution}%"
        if isinstance(coverage, int) and isinstance(resolution, int)
        else "not initialized"
    )
    raw_budgets = inner.get("re_source_budgets")
    source_budget = (
        raw_budgets.get("max_source_cycles")
        if isinstance(raw_budgets, dict)
        else None
    )
    budget_candidates = (
        re_max_inner,
        outer.get("re_max_inner"),
        inner.get("re_max_inner"),
        source_budget,
    )
    effective_budgets = [
        value
        for value in budget_candidates
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    effective_budget = max(effective_budgets, default=None)

    fields = [
        ("run", run_dir.name),
        ("status", f"{status} → continuing"),
        ("phase", f"{phase} — {phase_label}"),
        ("policy", str(outer.get("re_policy") or "unknown")),
        ("sources", _re_source_progress(inner)),
        ("domains", _re_domain_count(run_re_dir)),
        (
            "synthesis",
            "complete"
            if inner.get("re_workspace_synthesis_complete") is True
            else "pending",
        ),
        ("quality", quality),
    ]
    if effective_budget:
        fields.append(("repair budget", f"{effective_budget} source-local attempts"))
    fields.append(("artifacts", str(run_re_dir)))
    _banner(
        "RE CONTINUE",
        fields,
        subtitle="Controller state before provider dispatch.",
    )


def _parse_re_lifecycle_options(
    args: list[str],
    *,
    allow_policy: bool,
    allow_reset: bool,
    allow_budget_overrides: bool = False,
) -> tuple[str, int | None, bool, bool, str | None, int | None, int | None, list[str]]:
    policy = "changed"
    re_max_inner: int | None = None
    reset = False
    no_reuse = False
    profile: str | None = None
    token_limit: int | None = None
    time_limit_minutes: int | None = None
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--re-policy" and allow_policy:
            if index + 1 >= len(args):
                raise ValueError("--re-policy requires a policy name")
            policy = args[index + 1].strip()
            index += 2
        elif arg.startswith("--re-policy=") and allow_policy:
            policy = arg.split("=", 1)[1].strip()
            index += 1
        elif arg == "--profile" and allow_policy:
            if index + 1 >= len(args):
                raise ValueError("--profile requires fast, balanced, or high")
            profile = args[index + 1].strip()
            index += 2
        elif arg.startswith("--profile=") and allow_policy:
            profile = arg.split("=", 1)[1].strip()
            index += 1
        elif arg in {"--re-token-limit", "--re-time-limit-minutes"} and (
            allow_policy or allow_budget_overrides
        ):
            if index + 1 >= len(args):
                raise ValueError(f"{arg} requires a positive integer")
            try:
                value = int(args[index + 1])
            except ValueError as exc:
                raise ValueError(f"{arg} requires a positive integer") from exc
            if arg == "--re-token-limit":
                token_limit = value
            else:
                time_limit_minutes = value
            index += 2
        elif arg.startswith("--re-token-limit=") and (
            allow_policy or allow_budget_overrides
        ):
            token_limit = int(arg.split("=", 1)[1])
            index += 1
        elif arg.startswith("--re-time-limit-minutes=") and (
            allow_policy or allow_budget_overrides
        ):
            time_limit_minutes = int(arg.split("=", 1)[1])
            index += 1
        elif arg == "--re-max-inner":
            if index + 1 >= len(args):
                raise ValueError("--re-max-inner requires a positive integer")
            try:
                re_max_inner = int(args[index + 1])
            except ValueError as exc:
                raise ValueError("--re-max-inner requires a positive integer") from exc
            index += 2
        elif arg.startswith("--re-max-inner="):
            try:
                re_max_inner = int(arg.split("=", 1)[1])
            except ValueError as exc:
                raise ValueError("--re-max-inner requires a positive integer") from exc
            index += 1
        elif arg == "--reset" and allow_reset:
            reset = True
            index += 1
        elif arg == "--no-reuse" and allow_policy:
            no_reuse = True
            index += 1
        elif arg.startswith("-"):
            raise ValueError(f"unknown option {arg!r}")
        else:
            positional.append(arg)
            index += 1
    if re_max_inner is not None and re_max_inner < 1:
        raise ValueError("--re-max-inner requires a positive integer")
    if token_limit is not None and token_limit < 1:
        raise ValueError("--re-token-limit requires a positive integer")
    if time_limit_minutes is not None and time_limit_minutes < 1:
        raise ValueError("--re-time-limit-minutes requires a positive integer")
    return (
        policy,
        re_max_inner,
        reset,
        no_reuse,
        profile,
        token_limit,
        time_limit_minutes,
        positional,
    )


def _re_lifecycle_controller(project_root: Path):
    from harness.config import load_config
    from harness.re_lifecycle import ReLifecycleController
    from harness.squad_provider import SquadCliProvider

    runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(project_root)
    config = load_config(project_root, squad_only=True)
    return ReLifecycleController(
        project_root=project_root,
        extension_root=runtime_root,
        prosaic_subagents_dir=prosaic_subagents_dir,
        provider_factory=lambda: SquadCliProvider(config),
    )


def _print_re_lifecycle_result(result: object) -> None:
    status = str(getattr(result, "status", "failed"))
    run_id = str(getattr(result, "run_id", ""))
    generation = int(getattr(result, "generation", 0) or 0)
    no_work = bool(getattr(result, "no_work", False))
    if status == "done":
        if no_work:
            print(f"RE publication is current (generation {generation}); no agent work required.")
            _banner(
                "RE FINAL STATE — CURRENT",
                [("run", run_id or "(not created)"), ("generation", str(generation))],
                subtitle="No reverse-engineering work was required.",
            )
        else:
            print(
                f"RE run {run_id} complete; publication is pending. "
                f"Publish explicitly with: echelon re publish {run_id}"
            )
            _banner(
                "RE FINAL STATE — COMPLETE",
                [
                    ("run", run_id),
                    ("generation", str(generation)),
                    ("next step", f"echelon re publish {run_id}"),
                ],
                subtitle="Reverse engineering completed; publication is pending.",
            )
        return
    reason = str(getattr(result, "blocked_reason", "RE lifecycle failed"))
    print(f"RE run {run_id or '(not created)'} blocked: {reason}", file=sys.stderr)
    detail = str(getattr(result, "blocked_detail", "")).strip()
    fields = [
        ("run", run_id or "(not created)"),
        ("status", "blocked"),
        ("reason", reason),
    ]
    phase = str(getattr(result, "phase", "")).strip()
    if phase:
        fields.append(("phase", phase))
    missing_workspace_artifacts = _workspace_synthesis_missing_artifacts(detail)
    if missing_workspace_artifacts:
        fields.extend(
            [
                (
                    "validation",
                    "Agent reported DONE, but deterministic artifact validation failed.",
                ),
                (
                    "missing artifacts",
                    _format_missing_workspace_artifacts(missing_workspace_artifacts),
                ),
                ("retry", "echelon re continue"),
            ]
        )
    else:
        if detail:
            fields.append(("detail", _summarize_re_lifecycle_detail(detail)))
        fields.append(("action", "Resolve the blocker, then continue or resume the run."))
    _banner(
        "RE FINAL STATE — BLOCKED",
        fields,
        subtitle="No further provider work was run after the controller gate failed.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _summarize_re_lifecycle_detail(detail: str) -> str:
    """Keep the terminal's final RE state legible when a gate reports many paths."""
    compact = " ".join(detail.split())
    return compact if len(compact) <= 300 else compact[:297] + "…"


def _workspace_synthesis_missing_artifacts(detail: str) -> list[str]:
    prefix = "workspace synthesis has missing or empty artifacts: "
    if not detail.startswith(prefix):
        return []
    return [
        path.strip()
        for path in detail.removeprefix(prefix).split(",")
        if path.strip()
    ]


def _format_missing_workspace_artifacts(paths: list[str]) -> str:
    displayed = paths[:10]
    heading = f"{len(paths)} required artifacts are absent."
    remainder = len(paths) - len(displayed)
    suffix = f"… and {remainder} more" if remainder else ""
    return "\n".join([heading, *displayed, suffix]).strip()


def _parse_re_creation_engine_options(
    args: list[str],
) -> tuple[str, bool, str, list[str]]:
    """Remove additive v2 creation switches without changing the v1 parser."""
    engine = "v1"
    engine_seen = False
    shadow = False
    goal = "baseline"
    goal_seen = False
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--engine":
            if engine_seen or index + 1 >= len(args):
                raise ValueError("--engine requires exactly one of v1 or v2")
            engine = args[index + 1].strip()
            engine_seen = True
            index += 2
        elif arg.startswith("--engine="):
            if engine_seen:
                raise ValueError("--engine requires exactly one of v1 or v2")
            engine = arg.split("=", 1)[1].strip()
            engine_seen = True
            index += 1
        elif arg == "--shadow":
            if shadow:
                raise ValueError("--shadow may be supplied only once")
            shadow = True
            index += 1
        elif arg == "--goal":
            if goal_seen or index + 1 >= len(args):
                raise ValueError("--goal requires exactly one of baseline or inventory")
            goal = args[index + 1].strip()
            goal_seen = True
            index += 2
        elif arg.startswith("--goal="):
            if goal_seen:
                raise ValueError("--goal requires exactly one of baseline or inventory")
            goal = arg.split("=", 1)[1].strip()
            goal_seen = True
            index += 1
        else:
            remaining.append(arg)
            index += 1
    if engine not in {"v1", "v2"}:
        raise ValueError("--engine requires v1 or v2")
    if shadow and engine != "v2":
        raise ValueError("--shadow is valid only with --engine v2")
    if goal not in {"baseline", "inventory"}:
        raise ValueError("--goal requires baseline or inventory")
    if goal_seen and engine != "v2":
        raise ValueError("--goal is valid only with --engine v2")
    return engine, shadow, goal, remaining


def _re_v2_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _re_v2_snapshot_root(project_root: Path) -> Path:
    configured = os.environ.get("ECHELON_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".echelon"
    destination = (base / "re-v2" / "snapshots").resolve(strict=False)
    workspace = project_root.resolve()
    if destination == workspace or destination.is_relative_to(workspace):
        raise ValueError("RE v2 snapshot storage must be outside the source workspace")
    return destination


def _re_v2_partition_manifest_id(
    workspace_manifest: object, snapshot: object
) -> str:
    from harness.re_v2.snapshot import load_snapshot_manifest
    from harness.re_v2.workspace_snapshot import composite_partition_manifest_id

    snapshot_manifest = load_snapshot_manifest(snapshot)
    components = snapshot_manifest.components
    if components is None:
        raise ValueError("RE v2 creation requires a composite source snapshot")
    expected = sorted(
        (
            str(getattr(source, "id")),
            str(getattr(source, "git_role")),
            str(getattr(source, "path")),
        )
        for source in getattr(workspace_manifest, "sources")
    )
    observed = sorted(
        (
            component.source_id,
            component.git_role,
            component.workspace_path,
        )
        for component in components
    )
    if expected != observed:
        raise ValueError(
            "workspace source set does not match the committed RE v2 snapshot"
        )
    return composite_partition_manifest_id(snapshot_manifest)


def _new_re_v2_run_id(project_root: Path) -> str:
    runs = project_root.resolve() / "runs"
    base = datetime.now(timezone.utc).strftime("re-%Y%m%d-%H%M%S-%f")
    for index in range(1_000):
        candidate = base if index == 0 else f"{base}-{index}"
        if not (runs / candidate).exists() and not (runs / candidate).is_symlink():
            return candidate
    raise ValueError("cannot allocate a unique RE v2 run id")


def _activate_re_v2_run(project_root: Path, run_id: str) -> None:
    runs = project_root.resolve() / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    gitignore = runs / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*/state.json\n*/*.tmp\n.current*\n", encoding="utf-8")
    marker = runs / ".current-re"
    temporary = runs / f".current-re.{os.getpid()}.tmp"
    try:
        temporary.write_text(run_id + "\n", encoding="utf-8")
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def _re_v22_agent_bytes(project_root: Path) -> bytes | None:
    path = (
        project_root.resolve()
        / ".echelon"
        / "prosaic"
        / "subagents"
        / "echelon.re-baseliner.md"
    )
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe echelon.re-baseliner authority: {path}")
    try:
        before = path.stat(follow_symlinks=False)
        payload = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"cannot read echelon.re-baseliner authority: {exc}") from exc
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or not payload
    ):
        raise ValueError("echelon.re-baseliner authority changed while reading")
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("echelon.re-baseliner authority must be UTF-8") from exc
    return payload


def _re_v22_implementation_digest(*modules: object) -> str:
    from harness.re_v2.protocol_22.authorities import implementation_closure_digest

    files: dict[str, bytes] = {}
    for module in modules:
        module_name = str(getattr(module, "__name__", ""))
        module_path_value = getattr(module, "__file__", None)
        if not module_name or not isinstance(module_path_value, str):
            raise ValueError("protocol-2.2 implementation authority has no source file")
        module_path = Path(module_path_value)
        if module_path.suffix == ".pyc" and module_path.with_suffix(".py").is_file():
            module_path = module_path.with_suffix(".py")
        if module_path.is_symlink() or not module_path.is_file():
            raise ValueError(
                f"protocol-2.2 implementation authority is unavailable: {module_name}"
            )
        files[module_name.replace(".", "/") + ".py"] = module_path.read_bytes()
    return implementation_closure_digest(files)


def _re_v22_partition_authorities() -> object:
    import harness.re_domain_manifest as domain_manifest_module
    import harness.re_v2.protocol_22.partition as partition_module
    from harness.re_v2.protocol_22.partition import (
        ImplementationAuthorityV1,
        PartitionAuthoritiesV1,
    )

    return PartitionAuthoritiesV1(
        partitioner=ImplementationAuthorityV1(
            id="existing-domain-partitioner",
            version="5",
            implementation_digest=_re_v22_implementation_digest(
                partition_module,
                domain_manifest_module,
            ),
        ),
        ownership_policy=ImplementationAuthorityV1(
            id="explicit-domain-ownership",
            version="1",
            implementation_digest=_re_v22_implementation_digest(
                partition_module
            ),
        ),
    )


def _re_schema2_installed_registry(
    agent: bytes | None,
    *,
    provider_mode: str = "api",
) -> tuple[object, bytes | None, dict[str, bytes]]:
    import harness.re_domain_manifest as domain_manifest_module
    import harness.re_v2.protocol_22.baseline as baseline_module
    import harness.re_v2.protocol_22.cli_provider as cli_provider_module
    import harness.re_v2.protocol_22.context as context_module
    import harness.re_v2.protocol_22.controller as controller_module
    import harness.re_v2.protocol_22.evidence as evidence_module
    import harness.re_v2.protocol_22.execution as execution_module
    import harness.re_v2.protocol_22.inventory as inventory_module
    import harness.re_v2.protocol_22.partition as partition_module
    import harness.re_v2.protocol_22.provider as provider_module
    import harness.re_v2.protocol_22.response_schemas as response_schema_module
    import harness.re_v2.protocol_22.runtime as runtime_module
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
    from harness.re_v2.protocol_22.executors import (
        BOUNDED_API_ADAPTER_ID,
        COMPACT_RENDERER_ID,
        COMPACT_VERIFIER_ID,
        CONSERVATIVE_TOKENIZER_ID,
        DISPATCH_CALCULATOR_ID,
        IN_PROCESS_ADAPTER_ID,
        IN_PROCESS_CALCULATOR_ID,
        OPENAI_USAGE_NORMALIZER_ID,
        SHARED_AI_CLI_ADAPTER_ID,
        SHARED_PROVIDER_USAGE_NORMALIZER_ID,
        ZERO_USAGE_NORMALIZER_ID,
    )
    from harness.re_v2.protocol_22.response_schemas import (
        canonical_response_schema_bytes,
    )

    schemas = {
        kind: canonical_response_schema_bytes(kind)
        for kind in ("domain-baseline", "source-overview")
    }
    registry = InstalledAuthorityRegistry(
        executor_implementations={
            BOUNDED_API_ADAPTER_ID: _re_v22_implementation_digest(provider_module),
            SHARED_AI_CLI_ADAPTER_ID: _re_v22_implementation_digest(
                cli_provider_module
            ),
            IN_PROCESS_ADAPTER_ID: _re_v22_implementation_digest(
                controller_module,
                execution_module,
                inventory_module,
                evidence_module,
                context_module,
                runtime_module,
            ),
        },
        renderer_implementations={
            COMPACT_RENDERER_ID: _re_v22_implementation_digest(
                provider_module,
                response_schema_module,
            ),
        },
        tokenizer_implementations={
            CONSERVATIVE_TOKENIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
        },
        calculator_implementations={
            DISPATCH_CALCULATOR_ID: (
                _re_v22_implementation_digest(
                    provider_module,
                    cli_provider_module,
                )
                if provider_mode == "cli"
                else _re_v22_implementation_digest(provider_module)
            ),
            IN_PROCESS_CALCULATOR_ID: _re_v22_implementation_digest(
                execution_module
            ),
        },
        normalizer_implementations={
            ZERO_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(execution_module),
            OPENAI_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
            SHARED_PROVIDER_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
        },
        verifier_implementations={
            COMPACT_VERIFIER_ID: _re_v22_implementation_digest(baseline_module),
        },
        partitioner_implementations={
            "existing-domain-partitioner": _re_v22_implementation_digest(
                partition_module,
                domain_manifest_module,
            ),
        },
        ownership_implementations={
            "explicit-domain-ownership": _re_v22_implementation_digest(
                partition_module
            ),
        },
        agent_contracts=(
            {"echelon.re-baseliner": content_digest(agent)}
            if agent is not None
            else {}
        ),
        response_schemas={
            kind: content_digest(payload) for kind, payload in schemas.items()
        },
    )
    return registry, agent, schemas


def _re_v22_installed_registry(
    project_root: Path,
) -> tuple[object, bytes | None, dict[str, bytes]]:
    """Build legacy protocol-2.2 authority from its raw Markdown contract."""
    return _re_schema2_installed_registry(_re_v22_agent_bytes(project_root))


@dataclass(frozen=True, slots=True)
class _Protocol22Creation:
    snapshot: object
    manifest: object
    inputs: object


@dataclass(frozen=True, slots=True)
class _LayerCreationAuthorityV1:
    snapshot: object
    layer_manifest: object
    layer_inputs: object
    graph: object
    direct_parent_authority: tuple[object, ...]
    authority_objects: Mapping[str, Mapping[str, bytes]]


@dataclass(frozen=True, slots=True)
class _Protocol26Creation:
    snapshot: object
    manifest: object
    inputs: object
    graph: object
    direct_parent: object | None


def _build_protocol_26_creation(
    layer_creation: _LayerCreationAuthorityV1,
    contract: object,
    bundle: object,
    direct_parent: object | None,
) -> _Protocol26Creation:
    """Build one outer schema-5 value from already-prepared layer authority."""
    from harness.re_v2.protocol_22.model import CatalogReferenceV1
    from harness.re_v2.protocol_26.inputs import Protocol26InputSet
    from harness.re_v2.protocol_26.model import (
        LayerExecutionContractV1,
        RunManifestV5,
    )

    if not isinstance(contract, LayerExecutionContractV1):
        raise ValueError("protocol-2.6 creation requires a layer contract")
    selected_objects: dict[str, bytes] = {}
    for selected in bundle.selected:
        authority_key = (
            selected.checkpoint_manifest_id
            if selected.source_kind == "workspace_checkpoint"
            else selected.expected_work_item_id
        )
        candidate_objects = layer_creation.authority_objects.get(authority_key)
        if candidate_objects is None:
            raise ValueError("selected checkpoint has no reconstructed object authority")
        for object_hash in selected.copied_object_ids:
            payload = candidate_objects.get(object_hash)
            if payload is None:
                raise ValueError("selected checkpoint object authority is incomplete")
            existing = selected_objects.get(object_hash)
            if existing is not None and existing != payload:
                raise ValueError("selected checkpoint objects conflict")
            selected_objects[object_hash] = payload

    inner = contract.layer_manifest
    outer = RunManifestV5(
        schema_version=5,
        engine="re-v2",
        engine_protocol_version="2.6",
        run_id=inner.run_id,
        created_at=inner.created_at,
        source_snapshot_id=inner.source_snapshot_id,
        source_snapshot_kind=inner.source_snapshot_kind,
        partition_manifest_id=inner.partition_manifest_id,
        target_layer=contract.target_layer,
        layer_execution_contract=CatalogReferenceV1(
            contract.identity,
            "layer-execution-contract.json",
        ),
        checkpoint_selection=CatalogReferenceV1(
            bundle.identity,
            "checkpoint-selection.json",
        ),
    )
    inputs = Protocol26InputSet(
        manifest=outer,
        layer_execution_contract=contract,
        layer_inputs=layer_creation.layer_inputs,
        checkpoint_selection=bundle,
        authority_objects=selected_objects,
    )
    return _Protocol26Creation(
        layer_creation.snapshot,
        outer,
        inputs,
        layer_creation.graph,
        direct_parent,
    )


def _prepare_re_v26_creation(
    workspace_root: Path,
    *,
    target_layer: str,
    parent_run: Path | None,
    goal: str,
    deepen_options: object | None,
    token_limit: int | None,
    time_limit_minutes: int | None,
    checkpoint_progress: Callable[[str, int, int], None] | None = None,
) -> _Protocol26Creation:
    """Compose protocol 2.6 over the existing pure layer preparation paths."""
    from types import SimpleNamespace

    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_26.cache import (
        CheckpointCacheError,
        load_checkpoint_candidates,
        rebuild_checkpoint_cache,
    )
    from harness.re_v2.protocol_26.model import LayerExecutionContractV1
    from harness.re_v2.protocol_26.reconstruction import (
        reconstruct_origin_checkpoints,
    )
    from harness.re_v2.protocol_26.selection import (
        compatibility_mismatches,
        select_checkpoints,
    )

    if target_layer == "L1":
        if parent_run is not None or deepen_options is not None:
            raise ValueError("protocol-2.6 L1 creation cannot have a direct parent")
        prepared = _prepare_re_v22_creation(
            workspace_root,
            goal=goal,
            token_limit=token_limit,
            time_limit_minutes=time_limit_minutes,
            engine_protocol_version="2.3",
        )
        graph = build_protocol_22_graph(prepared.manifest, prepared.inputs)
        layer_manifest = prepared.manifest
        layer_inputs = prepared.inputs
        snapshot = prepared.snapshot
        direct_parent = None
        direct_candidates: tuple[object, ...] = ()
        direct_objects: dict[str, Mapping[str, bytes]] = {}
    elif target_layer == "L2":
        from dataclasses import replace

        from harness.re_v2.protocol_24.adoption import validate_parent_for_deepening
        if parent_run is None or not isinstance(deepen_options, _ReDeepenOptions):
            raise ValueError("protocol-2.6 L2 creation requires deepening authority")
        direct_parent = validate_parent_for_deepening(parent_run, workspace_root)
        prepared_l2 = _prepare_re_v24_creation(
            workspace_root,
            direct_parent,
            deepen_options,
        )
        layer_manifest = replace(
            prepared_l2.manifest,
            run_id=_new_re_v2_run_id(workspace_root),
            created_at=_re_v2_now(),
        )
        layer_inputs = prepared_l2.inputs
        graph = prepared_l2.graph
        # Deepening reuses the already authenticated parent snapshot identity.
        # The runtime reconstructs its pinned snapshot only after publication;
        # preparation must not introduce a second snapshot read.
        snapshot = None
        reconstructed = reconstruct_origin_checkpoints(workspace_root, parent_run)
        direct_candidates = tuple(reconstructed.manifests)
        direct_objects = {
            checkpoint.work_item.work_item_id: reconstructed.authority_objects[
                checkpoint.identity
            ]
            for checkpoint in direct_candidates
        }
    elif target_layer == "L3":
        from dataclasses import replace

        from harness.re_v2.protocol_24.adoption import validate_parent_for_deepening
        if parent_run is None or not isinstance(deepen_options, _ReDeepenOptions):
            raise ValueError("protocol-2.6 L3 creation requires deepening authority")
        direct_parent = validate_parent_for_deepening(parent_run, workspace_root)
        prepared_l3 = _prepare_re_v25_creation(
            workspace_root,
            direct_parent,
            deepen_options,
        )
        layer_manifest = replace(
            prepared_l3.manifest,
            run_id=_new_re_v2_run_id(workspace_root),
            created_at=_re_v2_now(),
        )
        layer_inputs = prepared_l3.inputs
        graph = prepared_l3.graph
        snapshot = None
        reconstructed = reconstruct_origin_checkpoints(workspace_root, parent_run)
        direct_candidates = tuple(reconstructed.manifests)
        direct_objects = {
            checkpoint.work_item.work_item_id: reconstructed.authority_objects[
                checkpoint.identity
            ]
            for checkpoint in direct_candidates
        }
    else:
        raise ValueError(f"unsupported protocol-2.6 target layer: {target_layer!r}")
    contract = LayerExecutionContractV1.from_layer_manifest(layer_manifest)
    target_selection_id = (
        layer_manifest.selection.identity
        if hasattr(layer_manifest, "selection")
        else content_digest(
            {
                "requested_goals": list(layer_manifest.requested_goals),
                "schema_version": 1,
            }
        )
    )
    selection_templates = (
        (*graph.prerequisite_graph.templates, *graph.audit_templates)
        if target_layer == "L3"
        else graph.templates
    )
    expected_work_items = (
        _re_v25_expected_checkpoint_work_items(
            graph,
            direct_parent,
            direct_candidates,
        )
        if target_layer == "L3"
        else None
    )
    if target_layer == "L3":
        expected_ids = tuple(
            item.work_item_id for item in (expected_work_items or ())
        )
        try:
            candidate_hints = load_checkpoint_candidates(
                workspace_root,
                expected_work_item_ids=expected_ids,
            )
        except CheckpointCacheError:
            candidate_hints = ()
        expected_by_key = {
            item.output_key.identity: item for item in (expected_work_items or ())
        }
        candidate_hints = tuple(
            candidate
            for candidate in candidate_hints
            if (
                (expected := expected_by_key.get(candidate.artifact_key_id))
                is not None
                and not compatibility_mismatches(expected, candidate)
            )
        )
        hints_by_origin: dict[str, list[object]] = {}
        for candidate in candidate_hints:
            hints_by_origin.setdefault(candidate.origin_run_id, []).append(candidate)
        cache_candidates: list[object] = []
        cache_objects: dict[str, Mapping[str, bytes]] = {}
        origins = tuple(sorted(hints_by_origin))
        if checkpoint_progress is not None:
            checkpoint_progress("candidate-authentication", 0, len(origins))
        for completed, origin_run_id in enumerate(origins, start=1):
            reconstructed = reconstruct_origin_checkpoints(
                workspace_root,
                workspace_root / "runs" / origin_run_id,
            )
            authenticated = {
                item.identity: item for item in reconstructed.manifests
            }
            for hint in hints_by_origin[origin_run_id]:
                observed = authenticated.get(hint.identity)
                if observed != hint:
                    continue
                cache_candidates.append(observed)
                cache_objects[observed.identity] = reconstructed.authority_objects[
                    observed.identity
                ]
            if checkpoint_progress is not None:
                checkpoint_progress(
                    "candidate-authentication", completed, len(origins)
                )
        workspace_candidates = tuple(
            sorted(cache_candidates, key=lambda item: item.identity)
        )
        workspace_objects = cache_objects
    else:
        cache = rebuild_checkpoint_cache(
            workspace_root,
            progress=checkpoint_progress,
        )
        workspace_candidates = tuple(cache.manifests.values())
        workspace_objects = dict(cache.authority_objects)
    layer = _LayerCreationAuthorityV1(
        snapshot,
        layer_manifest,
        layer_inputs,
        graph,
        direct_candidates,
        {**workspace_objects, **direct_objects},
    )
    selection_graph = SimpleNamespace(
        templates=selection_templates,
        expected_work_items=expected_work_items,
        _inputs=layer_inputs,
        source_snapshot_id=layer_manifest.source_snapshot_id,
        partition_manifest_id=layer_manifest.partition_manifest_id,
        target_layer=target_layer,
        target_selection_id=target_selection_id,
        target_graph_id=content_digest(
            {
                "schema_version": 1,
                "template_ids": [
                    item.template_id for item in selection_templates
                ],
            }
        ),
        audit_epoch_id=(
            layer_manifest.frozen_audit_epoch.object_hash
            if target_layer == "L3"
            and layer_manifest.frozen_audit_epoch is not None
            else None
        ),
    )
    bundle = select_checkpoints(
        selection_graph,
        workspace_candidates,
        direct_parent=direct_candidates,
    )
    return _build_protocol_26_creation(layer, contract, bundle, direct_parent)


def _re_v25_expected_checkpoint_work_items(
    graph: object,
    parent: object,
    direct_candidates: tuple[object, ...],
) -> tuple[object, ...]:
    """Build L3 checkpoint expectations independently of sibling candidates."""
    accepted_parent = getattr(parent, "accepted_parent", None)
    if not isinstance(accepted_parent, Mapping):
        raise ValueError("L3 checkpoint selection requires accepted L2 parent authority")
    accepted = {
        template_id: pair[1]
        for template_id, pair in accepted_parent.items()
    }
    targets = graph.ready_audit_targets(accepted)
    templates = tuple(graph.audit_templates)
    # An L1 parent may still need to generate L2 before any L3 work can be
    # instantiated. In that case no sibling L3 checkpoint is yet exact.
    if len(targets) != len(templates):
        targets = ()
        templates = ()
    audit_items = tuple(
        graph.instantiate_audit_item(
            template,
            target,
            {
                template_id: accepted[template_id]
                for template_id in template.required_template_ids
            },
        )
        for target, template in zip(targets, templates, strict=True)
    )
    lower_items = tuple(
        candidate.work_item
        for candidate in direct_candidates
        if candidate.work_item.output_key.layer != "L3"
    )
    by_key = {
        item.output_key.identity: item
        for item in (*lower_items, *audit_items)
    }
    return tuple(by_key[key] for key in sorted(by_key))


def _prepare_re_v22_creation(
    workspace_root: Path,
    *,
    goal: str,
    token_limit: int | None,
    time_limit_minutes: int | None,
    engine_protocol_version: str | None = None,
) -> _Protocol22Creation:
    from harness.re_v2 import RE_V2_PROTOCOL
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.model import RE_V2_SCHEMA_2_PROTOCOLS
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.executors import resolve_executor_catalog
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.inputs import Protocol22InputSet
    from harness.re_v2.protocol_22.model import (
        BudgetPolicyV2,
        CatalogReferenceV1,
        RunManifestV2,
    )
    from harness.re_v2.protocol_22.partition import build_workspace_partition_catalog
    from harness.re_v2.protocol_22.policies import build_compact_v1_policy_catalog
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

    selected_protocol = (
        RE_V2_PROTOCOL
        if engine_protocol_version is None
        else engine_protocol_version
    )
    if selected_protocol not in RE_V2_SCHEMA_2_PROTOCOLS:
        raise ValueError(
            f"unsupported schema-2 RE protocol: {selected_protocol!r}"
        )

    workspace_manifest = discover_workspace(workspace_root)
    snapshot = capture_workspace_snapshot(
        workspace_root,
        workspace_manifest.sources,
        _re_v2_snapshot_root(workspace_root),
    )
    partition_authorities = _re_v22_partition_authorities()
    workspace_partition = build_workspace_partition_catalog(
        snapshot,
        workspace_manifest,
        partition_authorities,
    )
    artifact_policy = build_compact_v1_policy_catalog()
    if selected_protocol == "2.2":
        registry, agent, schemas = _re_v22_installed_registry(workspace_root)
    else:
        agent = None
        if goal == "baseline":
            try:
                artifact = ProsaicPromptLoader(workspace_root).load_subagent(
                    "echelon.re-baseliner"
                )
            except ProsaicPromptLoadError as exc:
                raise ValueError(str(exc)) from exc
            if artifact is None:
                raise ValueError(
                    "installed Prosaic agent echelon.re-baseliner is missing; run "
                    "`echelon workspace migrate-to-prosaic` before starting RE"
                )
            agent = canonical_prosaic_agent_bytes(artifact)
        registry, agent, schemas = _re_schema2_installed_registry(
            agent,
            provider_mode="cli",
        )
    if (
        registry.require("partitioner", partition_authorities.partitioner.id)
        != partition_authorities.partitioner.implementation_digest
        or registry.require(
            "ownership", partition_authorities.ownership_policy.id
        )
        != partition_authorities.ownership_policy.implementation_digest
    ):
        raise ValueError("protocol-2.2 partition authority changed during preflight")
    try:
        config = _load_cli_config(workspace_root)
    except Exception as exc:
        if exc.__class__.__module__ != "harness.config":
            raise
        raise ValueError(str(exc)) from exc
    executor_contract = resolve_executor_catalog(
        config,
        goal,
        registry,
        provider_mode="api" if selected_protocol == "2.2" else "cli",
    )
    executor_contract = _bound_re_v2_executor_active_ms(executor_contract)
    mismatches = validate_installed_authorities(executor_contract, registry)
    if mismatches:
        details = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise ValueError(f"protocol-2.2 installed authority mismatch: {details}")
    immutable_objects: dict[str, bytes] = {}
    if goal == "baseline":
        if agent is None:
            raise ValueError("missing installed agent authority echelon.re-baseliner")
        immutable_objects[content_digest(agent)] = agent
        for payload in schemas.values():
            immutable_objects[content_digest(payload)] = payload
    inputs = Protocol22InputSet(
        workspace_partition=workspace_partition,
        artifact_policy=artifact_policy,
        executor_contract=executor_contract,
        immutable_objects=immutable_objects,
    )
    run_id = _new_re_v2_run_id(workspace_root)
    partition_manifest_id = _re_v2_partition_manifest_id(
        workspace_manifest,
        snapshot,
    )
    manifest = RunManifestV2(
        schema_version=2,
        engine="re-v2",
        engine_protocol_version=selected_protocol,
        run_id=run_id,
        created_at=_re_v2_now(),
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(workspace_partition.to_json_dict())
            ),
            relative_path="workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(artifact_policy.to_json_dict())
            ),
            relative_path="artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(executor_contract.to_json_dict())
            ),
            relative_path="executor-contract.json",
        ),
        requested_goals=(goal,),
        initial_budget_policy=BudgetPolicyV2.for_goal(
            goal,
            token_limit=token_limit if token_limit is not None else 5_000_000,
            active_ms_limit=(
                time_limit_minutes * 60_000
                if time_limit_minutes is not None
                else 180 * 60_000
            ),
        ),
        parent_run_id=None,
    )
    build_protocol_22_graph(manifest, inputs)
    return _Protocol22Creation(snapshot, manifest, inputs)


class _DeterministicInventoryCertifier:
    """Controller-owned verifier for the exact deterministic L0 document."""

    verifier_id = "deterministic-inventory-verifier"
    verifier_version = "v1"

    def __init__(self, object_store: object, snapshot: object) -> None:
        self._object_store = object_store
        self._snapshot = snapshot

    def certify(self, candidate: object, work_item: object) -> object:
        from harness.re_v2.canonical import canonical_json_bytes
        from harness.re_v2.ledger import CertificationDecision
        from harness.re_v2.model import (
            ArtifactReceipt,
            CertificationKey,
            CertificationReceipt,
        )

        payload_root = Path(getattr(candidate, "payload_path"))
        artifact_hash = self._object_store.put_tree(payload_root)
        diagnostics = self._diagnostics(candidate, work_item, payload_root)
        certified_at = _re_v2_now()
        certification = CertificationReceipt(
            certification_key=CertificationKey(
                artifact_hash=artifact_hash,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                source_snapshot_id=getattr(work_item, "output_key").source_snapshot_id,
                audit_epoch_id=None,
            ),
            candidate_id=str(getattr(candidate, "candidate_id")),
            work_item_id=str(getattr(work_item, "work_item_id")),
            verdict="rejected" if diagnostics else "accepted",
            normalized_diagnostics=diagnostics,
            evidence_references=("inventory.json",),
            scope_verified=not diagnostics,
            certified_at=certified_at,
        )
        if diagnostics:
            return CertificationDecision(certification, None)
        artifact = ArtifactReceipt(
            artifact_key=getattr(work_item, "output_key"),
            artifact_hash=artifact_hash,
            certification_id=certification.identity,
            candidate_id=str(getattr(candidate, "candidate_id")),
            work_item_id=str(getattr(work_item, "work_item_id")),
            accepted_at=certified_at,
        )
        return CertificationDecision(certification, artifact)

    def _diagnostics(
        self, candidate: object, work_item: object, payload_root: Path
    ) -> tuple[str, ...]:
        from harness.re_v2.canonical import canonical_json_bytes

        observation = getattr(candidate, "observation")
        if (
            observation.provider_name != "deterministic-inventory"
            or observation.exit_code != 0
            or observation.timed_out
            or observation.output_truncated
            or not observation.result_contract_valid
        ):
            return ("deterministic-transport-invalid",)
        try:
            entries = sorted(path.name for path in payload_root.iterdir())
            document_path = payload_root / "inventory.json"
            payload = document_path.read_bytes()
            document = json.loads(payload)
            snapshot_manifest = json.loads(
                Path(getattr(self._snapshot, "manifest_path")).read_bytes()
            )
        except (OSError, ValueError, TypeError):
            return ("inventory-document-unreadable",)
        if entries != ["inventory.json"] or document_path.is_symlink() or not document_path.is_file():
            return ("inventory-output-scope-invalid",)
        try:
            if payload != canonical_json_bytes(document):
                return ("inventory-document-noncanonical",)
        except (TypeError, ValueError):
            return ("inventory-document-noncanonical",)
        expected_fields = {
            "artifact_kind",
            "dependency_hashes",
            "partition_manifest_id",
            "producer_protocol_version",
            "schema_version",
            "snapshot_entries",
            "source_snapshot_id",
            "work_item_id",
        }
        if not isinstance(document, dict) or set(document) != expected_fields:
            return ("inventory-document-schema-invalid",)
        expected_entries = [
            {
                "digest": item["digest"],
                "mode": int(item["mode"]) & ~0o222,
                "path": item["path"],
                "size": item["size"],
            }
            for item in snapshot_manifest.get("entries", [])
            if isinstance(item, dict)
        ]
        output_key = getattr(work_item, "output_key")
        expected = {
            "artifact_kind": output_key.artifact_kind,
            "dependency_hashes": list(getattr(work_item, "required_artifact_hashes")),
            "partition_manifest_id": output_key.partition_manifest_id,
            "producer_protocol_version": getattr(work_item, "producer_protocol_version"),
            "schema_version": 1,
            "snapshot_entries": sorted(expected_entries, key=lambda item: str(item["path"])),
            "source_snapshot_id": output_key.source_snapshot_id,
            "work_item_id": getattr(work_item, "work_item_id"),
        }
        return () if document == expected else ("inventory-evidence-mismatch",)


def _load_re_v2_snapshot(project_root: Path, manifest: object) -> object:
    from harness.re_v2.snapshot import CapturedSnapshot, validate_source_snapshot

    bundle = _re_v2_snapshot_root(project_root) / str(
        getattr(manifest, "source_snapshot_id")
    )
    snapshot = CapturedSnapshot(
        snapshot_id=str(getattr(manifest, "source_snapshot_id")),
        kind=getattr(manifest, "source_snapshot_kind"),
        read_root=bundle / "source",
        manifest_path=bundle / "manifest.json",
    )
    validate_source_snapshot(snapshot)
    return snapshot


def _reject_re_v22_provider_dispatch(*_args: object, **_kwargs: object) -> None:
    raise ValueError(
        "protocol 2.2 has unresolved provider work; direct provider dispatch "
        "is disabled—start a new protocol 2.3 run"
    )


def _re_v22_context(project_root: Path, run_dir: Path, manifest: object) -> object:
    from types import MappingProxyType, SimpleNamespace

    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.controller import accepted_dependencies_for
    from harness.re_v2.protocol_22.cli_provider import SquadCliBaselineExecutor
    from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1
    from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
    from harness.re_v2.protocol_22.execution import (
        DeterministicExecutionDependenciesV1,
        Protocol22ExecutionStore,
        ProviderExecutionDependenciesV1,
    )
    from harness.re_v2.protocol_22.executors import IN_PROCESS_ADAPTER_ID
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.inputs import load_protocol_22_inputs
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.model import (
        DeterministicInvocationInputV1,
        DeterministicInvocationV1,
        RunManifestV2,
    )
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from harness.re_v2.protocol_22.runtime import (
        ConservativeTokenizerV1,
        DeterministicRuntimeV1,
    )
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.snapshot import validate_source_snapshot
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5

    active_manifest = manifest
    paths = ReV2Paths.for_run(run_dir)
    if isinstance(manifest, RunManifestV5):
        if manifest.target_layer != "L1":
            raise ValueError("protocol-2.6 L1 context received another target layer")
        outer_inputs = load_protocol_26_inputs(paths, manifest)
        layer_manifest = outer_inputs.layer_execution_contract.layer_manifest
        if not isinstance(layer_manifest, RunManifestV2):
            raise ValueError("protocol-2.6 L1 contract has no schema-2 manifest")
        manifest = layer_manifest
        inputs = outer_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L1")
    elif isinstance(manifest, RunManifestV2):
        inputs = load_protocol_22_inputs(paths, manifest)
        event_protocol = PROTOCOL_22_EVENTS
    else:
        raise ValueError("protocol-2.2 context requires a schema-2 manifest")
    graph = build_protocol_22_graph(manifest, inputs)
    objects = ObjectStore(paths.objects)
    if manifest.engine_protocol_version == "2.3":
        compact = next(
            (
                entry
                for entry in inputs.executor_contract.entries
                if entry.producer_family == "compact-baseline"
            ),
            None,
        )
        renderer = None if compact is None else compact.request_renderer
        pinned_agent = (
            None
            if renderer is None
            else objects.read_blob(renderer.agent_contract_hash)
        )
        registry, _agent, _schemas = _re_schema2_installed_registry(
            pinned_agent,
            provider_mode="cli",
        )
    else:
        registry, _agent, _schemas = _re_v22_installed_registry(project_root)
    snapshot = _load_re_v2_snapshot(project_root, active_manifest)
    snapshot_reader = PinnedSnapshotReaderV1(snapshot, inputs.workspace_partition)
    ledger = Protocol22Ledger(paths, objects)
    runtime = DeterministicRuntimeV1(inputs, snapshot_reader)
    context_ref: dict[str, object] = {}
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = content_digest(workspace_bytes)

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        executor = inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        context = context_ref["context"]
        accepted = accepted_dependencies_for(context, item)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            if renderer is None:
                raise ValueError("protocol-2.2 provider executor has no renderer")
            schema_hash = next(
                (
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind
                    == getattr(getattr(item, "output_key"), "artifact_kind")
                ),
                None,
            )
            if schema_hash is None:
                raise ValueError("protocol-2.2 provider item has no response schema")
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=(
                    ConservativeTokenizerV1.for_executor(executor)
                    if executor.execution_mode == "api"
                    else None
                ),
            )
        invocation_inputs = tuple(
            DeterministicInvocationInputV1(
                role=role,
                object_hash=accepted_artifact.artifact_hash,
            )
            for role, accepted_artifact in accepted.by_role.items()
        )
        uses_workspace_partition = set(accepted.by_role) == {"workspace_partition"}
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=getattr(item, "producer_family"),
                output_key=getattr(item, "output_key"),
                artifact_policy_hash=getattr(
                    getattr(item, "output_key"), "layer_policy_hash"
                ),
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=(
                workspace_hash if uses_workspace_partition else None
            ),
            referenced_objects=(
                {workspace_hash: workspace_bytes}
                if uses_workspace_partition
                else dict(accepted.payloads_by_hash)
            ),
        )

    producer_registrations = {
        entry.producer_family: runtime
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
    }
    provider_registrations: dict[str, object] = {}
    for entry in inputs.executor_contract.entries:
        if entry.execution_mode == "api":
            provider_registrations[entry.adapter_id] = SimpleNamespace(
                execute=_reject_re_v22_provider_dispatch
            )
        elif entry.execution_mode == "cli":
            from harness.squad_provider import SquadCliProvider

            provider_registrations[entry.adapter_id] = (
                SquadCliBaselineExecutor(
                    entry,
                    provider_factory=lambda: SquadCliProvider(
                        _load_cli_config(project_root)
                    ),
                )
            )
    verifier_registrations = {
        entry.verifier.verifier_id: runtime
        for entry in inputs.executor_contract.entries
    }
    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=event_protocol),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType(provider_registrations),
        producers=MappingProxyType(producer_registrations),
        verifiers=MappingProxyType(verifier_registrations),
        snapshot_validator=lambda: validate_source_snapshot(snapshot),
    )
    context_ref["context"] = context
    return context


def _re_v24_inherited_in_process_authorities(
    catalog: object,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Recover compatible L1 accounting authority not executed by the L2 adapter."""
    from harness.re_v2.protocol_22.executors import IN_PROCESS_ADAPTER_ID

    entries = tuple(
        entry
        for entry in getattr(catalog, "entries", ())
        if getattr(entry, "adapter_id", None) == IN_PROCESS_ADAPTER_ID
    )
    executor_digests = {
        entry.executor_implementation_digest for entry in entries
    }
    if len(executor_digests) != 1:
        raise ValueError("protocol-2.4 parent in-process authority is ambiguous")

    def authority_map(
        values: tuple[tuple[str, str], ...],
        kind: str,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for authority_id, implementation_digest in values:
            previous = resolved.get(authority_id)
            if previous is not None and previous != implementation_digest:
                raise ValueError(
                    f"protocol-2.4 parent in-process {kind} authority is ambiguous"
                )
            resolved[authority_id] = implementation_digest
        return resolved

    calculators = authority_map(
        tuple(
            (
                entry.reservation_calculator.calculator_id,
                entry.reservation_calculator.implementation_digest,
            )
            for entry in entries
        ),
        "calculator",
    )
    normalizers = authority_map(
        tuple(
            (
                entry.token_accounting.normalization_id,
                entry.token_accounting.implementation_digest,
            )
            for entry in entries
        ),
        "normalizer",
    )
    return (
        {IN_PROCESS_ADAPTER_ID: next(iter(executor_digests))},
        calculators,
        normalizers,
    )


def _re_v24_context(project_root: Path, run_dir: Path, manifest: object) -> object:
    from dataclasses import replace
    from types import MappingProxyType

    import harness.re_v2.protocol_24.artifacts as artifacts_module
    import harness.re_v2.protocol_24.controller as controller_module
    import harness.re_v2.protocol_24.runtime as runtime_module
    import harness.re_v2.protocol_24.source_root_v2 as source_root_v2_module
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.controller import accepted_dependencies_for
    from harness.re_v2.protocol_22.cli_provider import SquadCliBaselineExecutor
    from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1
    from harness.re_v2.protocol_22.execution import (
        DeterministicExecutionDependenciesV1,
        Protocol22ExecutionStore,
        ProviderExecutionDependenciesV1,
    )
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.materialization import (
        validate_or_repair_materialization,
    )
    from harness.re_v2.protocol_22.model import (
        DeterministicInvocationInputV1,
        DeterministicInvocationV1,
    )
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
    )
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_24.graph import (
        build_protocol_24_graph,
        reconstruct_adopted_parent_closure,
    )
    from harness.re_v2.protocol_24.inputs import load_protocol_24_inputs
    from harness.re_v2.protocol_24.model import RunManifestV3
    from harness.re_v2.protocol_24.runtime import Protocol24DeterministicRuntime
    from harness.re_v2.protocol_24.source_root_v2 import (
        Protocol24SourceRootRuntimeV2,
        SOURCE_ROOT_V2_ADAPTER_ID,
        SOURCE_ROOT_V2_VERIFIER_ID,
    )
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.snapshot import validate_source_snapshot
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5

    active_manifest = manifest
    paths = ReV2Paths.for_run(run_dir)
    if isinstance(manifest, RunManifestV5):
        if manifest.target_layer != "L2":
            raise ValueError("protocol-2.6 L2 context received another target layer")
        outer_inputs = load_protocol_26_inputs(paths, manifest)
        layer_manifest = outer_inputs.layer_execution_contract.layer_manifest
        if not isinstance(layer_manifest, RunManifestV3):
            raise ValueError("protocol-2.6 L2 contract has no schema-3 manifest")
        manifest = layer_manifest
        inputs = outer_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L2")
    elif isinstance(manifest, RunManifestV3):
        inputs = load_protocol_24_inputs(paths, manifest)
        event_protocol = PROTOCOL_24_EVENTS
    else:
        raise ValueError("protocol-2.4 context requires a schema-3 manifest")
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    ledger_view = ledger.replay()
    accepted_parent = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle,
        ledger_view,
    )
    graph = build_protocol_24_graph(manifest, inputs, accepted_parent)
    snapshot = _load_re_v2_snapshot(project_root, active_manifest)
    snapshot_reader = PinnedSnapshotReaderV1(
        snapshot,
        inputs.workspace_partition,
    )
    adopted_payloads = {
        (
            template.scope.source_id,
            template.scope.domain_key,
            template.layer,
            template.artifact_kind,
        ): objects.read_blob(artifact.artifact_hash)
        for template, artifact in accepted_parent.values()
    }
    deepening_runtime = Protocol24DeterministicRuntime(
        inputs,
        snapshot_reader,
        adopted_payloads,
    )
    source_root_runtime = Protocol24SourceRootRuntimeV2(inputs)
    baseline_entry = inputs.executor_contract.entry_for("compact-baseline")
    (
        inherited_executors,
        inherited_calculators,
        inherited_normalizers,
    ) = _re_v24_inherited_in_process_authorities(inputs.executor_contract)
    baseline_renderer = baseline_entry.request_renderer
    if baseline_renderer is None:
        raise ValueError("protocol-2.4 parent provider renderer is missing")
    baseline_agent = objects.read_blob(baseline_renderer.agent_contract_hash)
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    deepening_entry = inputs.executor_contract.entry_for("compact-deepening")
    deepening_renderer = deepening_entry.request_renderer
    if deepening_renderer is None:
        raise ValueError("protocol-2.4 deepening provider renderer is missing")
    deepener_hash = deepening_renderer.agent_contract_hash
    objects.read_blob(deepener_hash)
    implementation_digest = _re_v22_implementation_digest(
        artifacts_module,
        runtime_module,
        controller_module,
    )
    source_root_v2_digest = _re_v22_implementation_digest(
        source_root_v2_module,
        artifacts_module,
    )
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            **inherited_executors,
            DEEPENING_IN_PROCESS_ADAPTER_ID: implementation_digest,
            SOURCE_ROOT_V2_ADAPTER_ID: source_root_v2_digest,
        },
        calculator_implementations={
            **dict(registry.calculator_implementations),
            **inherited_calculators,
        },
        normalizer_implementations={
            **dict(registry.normalizer_implementations),
            **inherited_normalizers,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: implementation_digest,
            SOURCE_ROOT_V2_VERIFIER_ID: source_root_v2_digest,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            DEEPENER_AGENT_ID: deepener_hash,
        },
    )
    context_ref: dict[str, object] = {}
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = inputs.workspace_partition.identity

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        executor = inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        accepted = accepted_dependencies_for(context_ref["context"], item)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            if renderer is None:
                raise ValueError("protocol-2.4 provider executor has no renderer")
            schema_hash = next(
                (
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind
                    == getattr(getattr(item, "output_key"), "artifact_kind")
                ),
                None,
            )
            if schema_hash is None:
                raise ValueError("protocol-2.4 provider item has no response schema")
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=None,
            )
        invocation_inputs = tuple(
            DeterministicInvocationInputV1(
                role=role,
                object_hash=accepted_artifact.artifact_hash,
            )
            for role, accepted_artifact in accepted.by_role.items()
        )
        uses_workspace_partition = set(accepted.by_role) == {"workspace_partition"}
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=getattr(item, "producer_family"),
                output_key=getattr(item, "output_key"),
                artifact_policy_hash=getattr(
                    getattr(item, "output_key"), "layer_policy_hash"
                ),
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=(
                workspace_hash if uses_workspace_partition else None
            ),
            referenced_objects=(
                {workspace_hash: workspace_bytes}
                if uses_workspace_partition
                else dict(accepted.payloads_by_hash)
            ),
        )

    l2_families = {
        "targeted-evidence-pack",
        "deepening-context-bundle",
        "deepening-source-root",
    }
    producers = {
        entry.producer_family: (
            source_root_runtime
            if entry.producer_family == "deepening-source-root"
            else deepening_runtime
        )
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
        and entry.producer_family in l2_families
    }
    from harness.squad_provider import SquadCliProvider

    provider = SquadCliBaselineExecutor(
        deepening_entry,
        provider_factory=lambda: SquadCliProvider(_load_cli_config(project_root)),
    )
    verifiers = {
        entry.verifier.verifier_id: (
            source_root_runtime
            if entry.verifier.verifier_id == SOURCE_ROOT_V2_VERIFIER_ID
            else deepening_runtime
        )
        for entry in inputs.executor_contract.entries
        if entry.verifier.verifier_id
        in {DEEPENING_VERIFIER_ID, SOURCE_ROOT_V2_VERIFIER_ID}
    }
    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=event_protocol),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({deepening_entry.adapter_id: provider}),
        producers=MappingProxyType(producers),
        verifiers=MappingProxyType(verifiers),
        snapshot_validator=lambda: validate_source_snapshot(snapshot),
        materialization_validator=lambda: validate_or_repair_materialization(
            context_ref["context"],
            layers=frozenset({"L2"}),
        ),
    )
    context_ref["context"] = context
    return context


def _re_l3_authority_mismatch_message(run_dir: Path, manifest: object) -> str:
    """Explain an immutable L3 authority mismatch without protocol jargon."""
    selection = getattr(manifest, "selection", None)
    arguments = ["echelon", "re", "deepen", "--to", "L3"]
    if bool(getattr(selection, "all_sources", False)):
        arguments.append("--all")
    else:
        for source_id in getattr(selection, "source_ids", ()):
            arguments.extend(("--source", str(source_id)))
        for domain_key in getattr(selection, "domain_keys", ()):
            arguments.extend(("--domain", str(domain_key)))
    lineage = getattr(manifest, "parent_lineage", None)
    parent_run_id = getattr(lineage, "direct_parent_run_id", None)
    if parent_run_id:
        arguments.extend(("--from-run", str(parent_run_id)))
    successor_command = " ".join(shlex.quote(argument) for argument in arguments)
    status_command = (
        "echelon re status "
        f"{shlex.quote(run_dir.name)} --json"
    )
    return (
        "This run was created with a different RE implementation and cannot "
        "be continued safely.\n"
        "Its accepted artifacts remain unchanged.\n"
        "Create a compatible successor with:\n"
        f"{successor_command}\n"
        "For internal authority details, run:\n"
        f"{status_command}"
    )


def _re_v25_context(project_root: Path, run_dir: Path, manifest: object) -> object:
    """Reconstruct schema-4 execution solely from authenticated child authority."""
    from dataclasses import replace
    from types import MappingProxyType

    import harness.re_v2.protocol_24.artifacts as l2_artifacts_module
    import harness.re_v2.protocol_24.controller as l2_controller_module
    import harness.re_v2.protocol_24.runtime as l2_runtime_module
    import harness.re_v2.protocol_24.source_root_v2 as l2_source_root_v2_module
    import harness.re_v2.protocol_25.artifacts as l3_artifacts_module
    import harness.re_v2.protocol_25.cli_provider as l3_cli_provider_module
    import harness.re_v2.protocol_25.controller as l3_controller_module
    import harness.re_v2.protocol_25.runtime as l3_runtime_module
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.cli_provider import SquadCliBaselineExecutor
    from harness.re_v2.protocol_22.controller import accepted_dependencies_for
    from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1
    from harness.re_v2.protocol_22.execution import (
        DeterministicExecutionDependenciesV1,
        Protocol22ExecutionStore,
        ProviderExecutionDependenciesV1,
    )
    from harness.re_v2.protocol_22.materialization import (
        validate_or_repair_materialization,
    )
    from harness.re_v2.protocol_22.model import (
        DeterministicInvocationInputV1,
        DeterministicInvocationV1,
    )
    from harness.re_v2.protocol_22.runtime import DeterministicRuntimeV1
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
    )
    from harness.re_v2.protocol_24.graph import reconstruct_adopted_parent_closure
    from harness.re_v2.protocol_24.runtime import Protocol24DeterministicRuntime
    from harness.re_v2.protocol_24.source_root_v2 import (
        Protocol24SourceRootRuntimeV2,
        SOURCE_ROOT_V2_ADAPTER_ID,
        SOURCE_ROOT_V2_VERIFIER_ID,
    )
    from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
    from harness.re_v2.protocol_25.graph import build_protocol_25_graph
    from harness.re_v2.protocol_25.inputs import load_protocol_25_inputs
    from harness.re_v2.protocol_25.ledger import Protocol25Ledger
    from harness.re_v2.protocol_25.model import RunManifestV4
    from harness.re_v2.protocol_25.recovery import Protocol25RunContext
    from harness.re_v2.protocol_25.runtime import Protocol25DeterministicRuntime
    from harness.re_v2.protocol_25.cli_provider import (
        Protocol25ExecutionStore,
        SquadCliSemanticRenderer,
    )
    from harness.re_v2.protocol_25.policies import SEMANTIC_RENDERER_ID
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.snapshot import validate_source_snapshot

    active_manifest = manifest
    paths = ReV2Paths.for_run(run_dir)
    if isinstance(manifest, RunManifestV5):
        if manifest.target_layer != "L3":
            raise ValueError("protocol-2.6 L3 context received another target layer")
        protocol_26_inputs = load_protocol_26_inputs(paths, manifest)
        layer_manifest = protocol_26_inputs.layer_execution_contract.layer_manifest
        if not isinstance(layer_manifest, RunManifestV4):
            raise ValueError("protocol-2.6 L3 contract has no schema-4 manifest")
        manifest = layer_manifest
        semantic_inputs = protocol_26_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L3")
    elif isinstance(manifest, RunManifestV4):
        semantic_inputs = load_protocol_25_inputs(paths, manifest)
        event_protocol = PROTOCOL_25_EVENTS
    else:
        raise ValueError("protocol-2.5 context requires a schema-4 manifest")
    objects = ObjectStore(paths.objects)
    ledger = Protocol25Ledger(paths, objects)
    ledger_view = ledger.replay()
    accepted_parent = reconstruct_adopted_parent_closure(
        semantic_inputs.parent_authority_bundle.lower_authority_bundle,
        ledger_view,
    )
    semantic_graph = build_protocol_25_graph(
        manifest,
        semantic_inputs.graph_inputs,
        accepted_parent,
    )
    inputs = semantic_graph.inputs
    graph = semantic_graph.prerequisite_graph
    snapshot = _load_re_v2_snapshot(project_root, active_manifest)
    snapshot_reader = PinnedSnapshotReaderV1(
        snapshot,
        semantic_inputs.workspace_partition,
    )
    adopted_payloads = {
        (
            template.scope.source_id,
            template.scope.domain_key,
            template.layer,
            template.artifact_kind,
        ): objects.read_blob(artifact.artifact_hash)
        for template, artifact in accepted_parent.values()
    }
    inherited_runtime = DeterministicRuntimeV1(inputs, snapshot_reader)
    deepening_runtime = Protocol24DeterministicRuntime(
        inputs,
        snapshot_reader,
        adopted_payloads,
    )
    source_root_runtime = Protocol24SourceRootRuntimeV2(inputs)
    semantic_entries = semantic_inputs.executor_contract.semantic_entries
    verifier_digests = {
        entry.verifier.implementation_digest for entry in semantic_entries
    }
    if len(verifier_digests) != 1:
        raise ValueError("protocol-2.5 semantic verifier authority is inconsistent")
    semantic_runtime = Protocol25DeterministicRuntime(
        verifier_authority_hash=next(iter(verifier_digests)),
        snapshot_reader=snapshot_reader,
        artifact_policy=semantic_inputs.artifact_policy,
    )
    (
        inherited_executors,
        inherited_calculators,
        inherited_normalizers,
    ) = _re_v24_inherited_in_process_authorities(
        semantic_inputs.executor_contract.inherited_catalog
    )

    baseline_entry = inputs.executor_contract.entry_for("compact-baseline")
    baseline_renderer = baseline_entry.request_renderer
    if baseline_renderer is None:
        raise ValueError("protocol-2.5 parent provider renderer is missing")
    baseline_agent = objects.read_blob(baseline_renderer.agent_contract_hash)
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    deepening_entry = inputs.executor_contract.entry_for("compact-deepening")
    deepening_renderer = deepening_entry.request_renderer
    if deepening_renderer is None:
        raise ValueError("protocol-2.5 deepening renderer is missing")
    deepener_hash = deepening_renderer.agent_contract_hash
    objects.read_blob(deepener_hash)
    l2_implementation = _re_v22_implementation_digest(
        l2_artifacts_module,
        l2_runtime_module,
        l2_controller_module,
    )
    l2_source_root_v2_implementation = _re_v22_implementation_digest(
        l2_source_root_v2_module,
        l2_artifacts_module,
    )
    l3_implementation = _re_v22_implementation_digest(
        l3_artifacts_module,
        l3_cli_provider_module,
        l3_runtime_module,
        l3_controller_module,
    )
    from harness.re_v2.protocol_25.compatibility import (
        compatible_installed_l3_digest,
    )

    frozen_l3_implementations = {
        implementation
        for entry in semantic_entries
        for implementation in (
            entry.verifier.implementation_digest,
            (
                entry.request_renderer.implementation_digest
                if entry.request_renderer is not None
                else None
            ),
        )
        if implementation is not None
    }
    installed_l3_implementation = compatible_installed_l3_digest(
        frozen_l3_implementations,
        l3_implementation,
    )
    role_by_family = {
        "closure-recheck": "echelon.re-validator",
        "semantic-audit": "echelon.re-validator",
        "semantic-resolution": "echelon.re-resolver",
        "source-composition-guard": "echelon.re-validator",
    }
    semantic_agents: dict[str, str] = {}
    semantic_schemas: dict[str, str] = {}
    semantic_verifiers: dict[str, str] = {}
    for entry in semantic_entries:
        renderer = entry.request_renderer
        if renderer is None or len(renderer.response_schemas) != 1:
            raise ValueError("protocol-2.5 semantic renderer authority is invalid")
        role_id = role_by_family[entry.producer_family]
        agent_hash = renderer.agent_contract_hash
        objects.read_blob(agent_hash)
        previous_agent = semantic_agents.get(role_id)
        if previous_agent is not None and previous_agent != agent_hash:
            raise ValueError("protocol-2.5 role has conflicting agent authority")
        semantic_agents[role_id] = agent_hash
        schema = renderer.response_schemas[0]
        objects.read_blob(schema.schema_hash)
        previous_schema = semantic_schemas.get(schema.artifact_kind)
        if previous_schema is not None and previous_schema != schema.schema_hash:
            raise ValueError("protocol-2.5 response schema authority conflicts")
        semantic_schemas[schema.artifact_kind] = schema.schema_hash
        semantic_verifiers[entry.verifier.verifier_id] = installed_l3_implementation
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            **inherited_executors,
            DEEPENING_IN_PROCESS_ADAPTER_ID: l2_implementation,
            SOURCE_ROOT_V2_ADAPTER_ID: l2_source_root_v2_implementation,
        },
        calculator_implementations={
            **dict(registry.calculator_implementations),
            **inherited_calculators,
        },
        normalizer_implementations={
            **dict(registry.normalizer_implementations),
            **inherited_normalizers,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: l2_implementation,
            SOURCE_ROOT_V2_VERIFIER_ID: l2_source_root_v2_implementation,
            **semantic_verifiers,
        },
        renderer_implementations={
            **dict(registry.renderer_implementations),
            SEMANTIC_RENDERER_ID: installed_l3_implementation,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            DEEPENER_AGENT_ID: deepener_hash,
            **semantic_agents,
        },
        response_schemas={
            **dict(registry.response_schemas),
            **semantic_schemas,
        },
    )
    mismatches = validate_installed_authorities(
        semantic_inputs.executor_contract,
        registry,
    )
    if mismatches:
        raise ValueError(_re_l3_authority_mismatch_message(run_dir, manifest))

    context_ref: dict[str, object] = {}
    workspace_bytes = canonical_json_bytes(
        semantic_inputs.workspace_partition.to_json_dict()
    )
    workspace_hash = semantic_inputs.workspace_partition.identity

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        executor = inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        accepted = accepted_dependencies_for(context_ref["context"], item)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            if renderer is None:
                raise ValueError("protocol-2.5 prerequisite provider has no renderer")
            schema_hash = next(
                (
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind
                    == getattr(getattr(item, "output_key"), "artifact_kind")
                ),
                None,
            )
            if schema_hash is None:
                raise ValueError("protocol-2.5 prerequisite has no response schema")
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=None,
            )
        invocation_inputs = tuple(
            DeterministicInvocationInputV1(
                role=role,
                object_hash=accepted_artifact.artifact_hash,
            )
            for role, accepted_artifact in accepted.by_role.items()
        )
        uses_workspace_partition = set(accepted.by_role) == {"workspace_partition"}
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=getattr(item, "producer_family"),
                output_key=getattr(item, "output_key"),
                artifact_policy_hash=getattr(
                    getattr(item, "output_key"), "layer_policy_hash"
                ),
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=(
                workspace_hash if uses_workspace_partition else None
            ),
            referenced_objects=(
                {workspace_hash: workspace_bytes}
                if uses_workspace_partition
                else dict(accepted.payloads_by_hash)
            ),
        )

    l2_families = {
        "targeted-evidence-pack",
        "deepening-context-bundle",
        "deepening-source-root",
    }
    producers = {
        entry.producer_family: (
            source_root_runtime
            if entry.producer_family == "deepening-source-root"
            else deepening_runtime
            if entry.producer_family in l2_families
            else inherited_runtime
        )
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
    }
    cli_entries = tuple(
        entry
        for entry in semantic_inputs.executor_contract.entries
        if entry.execution_mode == "cli"
    )
    from harness.squad_provider import SquadCliProvider

    provider = SquadCliSemanticRenderer(
        cli_entries,
        provider_factory=lambda: SquadCliProvider(_load_cli_config(project_root)),
    )
    verifiers = {
        entry.verifier.verifier_id: (
            semantic_runtime
            if entry.producer_family in role_by_family
            else source_root_runtime
            if entry.verifier.verifier_id == SOURCE_ROOT_V2_VERIFIER_ID
            else deepening_runtime
            if entry.verifier.verifier_id == DEEPENING_VERIFIER_ID
            else inherited_runtime
        )
        for entry in semantic_inputs.executor_contract.entries
    }
    context = Protocol25RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=event_protocol),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol25ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({deepening_entry.adapter_id: provider}),
        producers=MappingProxyType(producers),
        verifiers=MappingProxyType(verifiers),
        snapshot_validator=lambda: validate_source_snapshot(snapshot),
        materialization_validator=lambda: validate_or_repair_materialization(
            context_ref["context"],
            layers=frozenset({"L2"}),
        ),
        semantic_inputs=semantic_inputs,
        semantic_graph=semantic_graph,
        semantic_runtime=semantic_runtime,
    )
    context_ref["context"] = context
    return context


def _re_v2_context(project_root: Path, run_dir: Path) -> object:
    from harness.re_v2.candidates import CandidateStore
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import Ledger, ObjectStore
    from harness.re_v2.planner import build_initial_inventory_graph
    from harness.re_v2.recovery import ReV2RunContext
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest
    from harness.re_v2.status import validate_supported_v2_manifest

    manifest = load_run_manifest(run_dir)
    from harness.re_v2.protocol_22.model import RunManifestV2
    from harness.re_v2.protocol_24.model import RunManifestV3
    from harness.re_v2.protocol_25.model import RunManifestV4
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_27.model import RunManifestV6
    from harness.re_v2.protocol_28.model import (
        ExhaustiveRunManifestV7,
        L4ClosureRunManifestV7,
    )

    if isinstance(manifest, RunManifestV2):
        return _re_v22_context(project_root, run_dir, manifest)
    if isinstance(manifest, RunManifestV3):
        return _re_v24_context(project_root, run_dir, manifest)
    if isinstance(manifest, RunManifestV4):
        return _re_v25_context(project_root, run_dir, manifest)
    if isinstance(manifest, RunManifestV5):
        if manifest.target_layer == "L1":
            return _re_v22_context(project_root, run_dir, manifest)
        if manifest.target_layer == "L2":
            return _re_v24_context(project_root, run_dir, manifest)
        if manifest.target_layer == "L3":
            return _re_v25_context(project_root, run_dir, manifest)
        raise ValueError("unsupported protocol-2.6 target layer")
    if isinstance(manifest, RunManifestV6):
        from harness.re_v2.protocol_27.recovery import load_protocol_27_run_context

        return load_protocol_27_run_context(run_dir)
    if isinstance(manifest, (ExhaustiveRunManifestV7, L4ClosureRunManifestV7)):
        from harness.re_v2.protocol_28.context import load_protocol_28_run_context

        return load_protocol_28_run_context(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    graph = build_initial_inventory_graph(
        manifest.source_snapshot_id, manifest.partition_manifest_id
    )
    validate_supported_v2_manifest(manifest, graph)
    snapshot = _load_re_v2_snapshot(project_root, manifest)
    objects = ObjectStore(paths.objects)
    ledger = Ledger(
        paths,
        objects,
        supported_verifiers={
            _DeterministicInventoryCertifier.verifier_id:
            _DeterministicInventoryCertifier.verifier_version
        },
    )
    return ReV2RunContext(
        paths=paths,
        snapshot=snapshot,
        graph=graph,
        event_store=EventStore(paths),
        object_store=objects,
        ledger=ledger,
        candidate_store=CandidateStore(paths),
        certifier=_DeterministicInventoryCertifier(objects, snapshot),
    )


def _run_re_v2_shadow(context: object) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext

    if isinstance(context, Protocol22RunContext):
        _run_re_v22_shadow(context)
        return
    from harness.re_v2.budget import evaluate_budget
    from harness.re_v2.planner import plan_next
    from harness.re_v2.recovery import recover_run
    from harness.re_v2.status import render_v2_status

    recovered = recover_run(context)
    budget = evaluate_budget(
        recovered.manifest.initial_budget_policy,
        recovered.events,
        now=_re_v2_now(),
    )
    decision = plan_next(
        context.graph,
        recovered.ledger,
        budget,
        requested_goals=recovered.manifest.requested_goals,
    )
    print("RE V2 — SHADOW PLAN")
    for template_id, explanation in decision.explanations.items():
        print(
            f"{template_id}: {explanation.action} "
            f"({explanation.reason_code}) — {explanation.reason}"
        )
    print(render_v2_status(context.paths.root.parent), end="")


def _run_re_v22_shadow(context: object) -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.artifacts import AcceptedDependencySetV2
    from harness.re_v2.protocol_22.execution import (
        ProviderExecutionDependenciesV1,
        preview_dispatch_reservation,
    )
    from harness.re_v2.protocol_22.graph import (
        AcceptedArtifactV2,
        instantiate_ready_item,
    )
    from harness.re_v2.protocol_22.policies import policy_for
    from harness.re_v2.protocol_22.runtime import ConservativeTokenizerV1
    from harness.re_v2.protocol_22.status import render_protocol_22_status
    from harness.re_v2.run_store import load_run_manifest

    entries = {
        entry.producer_family: entry
        for entry in context.inputs.executor_contract.entries
    }
    provider_families = {
        entry.producer_family
        for entry in entries.values()
        if entry.execution_mode in {"api", "cli"}
    }
    provider_templates = tuple(
        template
        for template in context.graph.templates
        if template.producer_family in provider_families
    )
    deterministic_count = len(context.graph.templates) - len(provider_templates)
    maximum_shared_retries = sum(
        template.max_shared_retries for template in provider_templates
    )
    templates = {template.template_id: template for template in context.graph.templates}
    produced: dict[str, AcceptedArtifactV2] = {}
    payloads: dict[str, bytes] = {}
    exact_contexts: list[tuple[str, str | None, int]] = []
    bounded_contexts: list[tuple[str, str | None, int, int]] = []
    exact_provider_reservations: dict[str, object] = {}
    remaining = {template.template_id: template for template in context.graph.templates}
    while True:
        progressed = False
        for template_id, template in tuple(remaining.items()):
            if any(
                dependency not in produced
                for dependency in template.required_template_ids
            ):
                continue
            accepted_by_template = {
                dependency: produced[dependency]
                for dependency in template.required_template_ids
            }
            item = instantiate_ready_item(
                template,
                accepted_by_template,
                context.inputs,
            )
            by_role = {
                _re_v22_dependency_role(templates[dependency]): produced[dependency]
                for dependency in template.required_template_ids
            }
            accepted = AcceptedDependencySetV2(by_role, payloads)
            entry = entries[item.producer_family]
            if entry.execution_mode in {"api", "cli"}:
                renderer = entry.request_renderer
                if renderer is None:
                    raise ValueError("shadow provider executor has no renderer")
                schema_hash = next(
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind == item.output_key.artifact_kind
                )
                dependencies = ProviderExecutionDependenciesV1(
                    executor=entry,
                    registry=context.installed_authorities,
                    agent_bytes=context.object_store.read_blob(
                        renderer.agent_contract_hash
                    ),
                    context_bytes=accepted.payload_for_role("context_bundle"),
                    response_schema_bytes=context.object_store.read_blob(schema_hash),
                    tokenizer=(
                        ConservativeTokenizerV1.for_executor(entry)
                        if entry.execution_mode == "api"
                        else None
                    ),
                )
                exact_provider_reservations[template.template_id] = (
                    preview_dispatch_reservation(
                        item,
                        "initial_generation",
                        dependencies,
                    ).reservation
                )
                del remaining[template_id]
                progressed = True
                continue
            payload = context.producers[item.producer_family].produce(item, accepted)
            artifact_hash = content_digest(payload)
            produced[template.template_id] = AcceptedArtifactV2(
                item.output_key.identity,
                artifact_hash,
            )
            payloads[artifact_hash] = payload
            if template.artifact_kind.endswith("context-bundle"):
                exact_contexts.append(
                    (
                        template.scope.source_id,
                        template.scope.domain_key,
                        len(payload),
                    )
                )
            del remaining[template_id]
            progressed = True
        if not progressed:
            break
    for template in remaining.values():
        if template.artifact_kind != "source-overview-context-bundle":
            continue
        policy = policy_for(
            context.inputs.artifact_policy,
            template.layer,
            template.artifact_kind,
        )
        byte_bound = min(
            value
            for value in (
                policy.max_canonical_json_bytes,
                policy.max_context_bundle_bytes,
            )
            if value is not None
        )
        token_bound = policy.max_conservative_input_tokens or byte_bound
        bounded_contexts.append(
            (
                template.scope.source_id,
                template.scope.domain_key,
                byte_bound,
                token_bound,
            )
        )

    initial_tokens = 0
    initial_active_ms = 0
    retry_tokens = 0
    retry_active_ms = 0
    for template in context.graph.templates:
        entry = entries[template.producer_family]
        initial_active_ms += entry.limits.max_active_ms_per_dispatch
        if entry.execution_mode not in {"api", "cli"}:
            continue
        context_limit = entry.limits.provider_context_tokens
        hard_tokens = entry.limits.max_billable_tokens_per_dispatch
        if context_limit is not None:
            hard_tokens = min(hard_tokens, context_limit)
        exact = exact_provider_reservations.get(template.template_id)
        initial_tokens += (
            exact.billable_tokens if exact is not None else hard_tokens
        )
        retry_tokens += template.max_shared_retries * hard_tokens
        retry_active_ms += (
            template.max_shared_retries
            * entry.limits.max_active_ms_per_dispatch
        )

    active_manifest = load_run_manifest(context.paths.root.parent)
    manifest = active_manifest
    if getattr(active_manifest, "engine_protocol_version", None) == "2.6":
        from harness.re_v2.protocol_26.authority import resolve_run_authority

        manifest = resolve_run_authority(context).layer_manifest
    print(
        "RE V2 — PROTOCOL "
        f"{active_manifest.engine_protocol_version} SHADOW PLAN"
    )
    print(f"deterministic initial dispatches: {deterministic_count}")
    print(f"provider initial dispatches: {len(provider_templates)}")
    print(f"maximum shared-retry dispatches: {maximum_shared_retries}")
    for source_id, domain_key, byte_count in sorted(
        exact_contexts,
        key=lambda value: (value[0], value[1] or ""),
    ):
        scope = f"{source_id}/{domain_key}" if domain_key else source_id
        print(
            "context exact: "
            f"scope={scope} canonical_bytes={byte_count} "
            f"conservative_input_tokens={byte_count}"
        )
    for source_id, domain_key, byte_bound, token_bound in sorted(
        bounded_contexts,
        key=lambda value: (value[0], value[1] or ""),
    ):
        scope = f"{source_id}/{domain_key}" if domain_key else source_id
        print(
            "context worst-case bound: "
            f"scope={scope} canonical_bytes<={byte_bound} "
            f"conservative_input_tokens<={token_bound}"
        )
    for entry in sorted(
        (
            value
            for value in entries.values()
            if value.execution_mode in {"api", "cli"}
        ),
        key=lambda value: value.producer_family,
    ):
        print(
            "per-dispatch hard limits: "
            f"executor={entry.adapter_id} "
            f"context_tokens={entry.limits.provider_context_tokens} "
            f"completion_tokens={entry.limits.max_completion_tokens_per_call} "
            f"billable_tokens={entry.limits.max_billable_tokens_per_dispatch} "
            f"active_ms={entry.limits.max_active_ms_per_dispatch}"
        )
    print(
        "whole-run initial reservation: "
        f"tokens={initial_tokens} active_ms={initial_active_ms}"
    )
    print(
        "whole-run shared-retry reservation: "
        f"tokens={retry_tokens} active_ms={retry_active_ms}"
    )
    token_limit = manifest.initial_budget_policy.token_limit
    active_limit = manifest.initial_budget_policy.active_ms_limit
    print(
        "authorized ceilings: "
        f"tokens={token_limit if token_limit is not None else 'unlimited'} "
        f"active_ms={active_limit if active_limit is not None else 'unlimited'}"
    )
    insufficient: list[str] = []
    if token_limit is not None and token_limit < initial_tokens + retry_tokens:
        insufficient.append("tokens")
    if active_limit is not None and active_limit < initial_active_ms + retry_active_ms:
        insufficient.append("active_ms")
    if insufficient:
        print(
            "warning: authorized ceilings cannot cover the whole-run worst case "
            f"({', '.join(insufficient)})"
        )
    else:
        print("authorization: ceilings cover the whole-run worst case")
    print("provider requests issued: 0")
    if getattr(active_manifest, "engine_protocol_version", None) == "2.6":
        checkpoint_events = tuple(
            event
            for event in context.event_store.replay()
            if event.type == "checkpoint_artifact_adopted"
        )
        print(f"checkpoint artifacts adopted: {len(checkpoint_events)}")
        return
    print(render_protocol_22_status(context.paths.root.parent, context=context), end="")


def _re_v22_dependency_role(template: object) -> str:
    kind = str(getattr(template, "artifact_kind"))
    domain_key = getattr(getattr(template, "scope"), "domain_key")
    static = {
        "source-inventory": "source_inventory",
        "source-partition": "source_partition",
        "source-evidence-pack": "source_evidence_pack",
        "domain-inventory": "domain_inventory",
        "domain-evidence-pack": "domain_evidence_pack",
        "domain-context-bundle": "context_bundle",
        "source-overview-context-bundle": "context_bundle",
        "source-overview": "source_overview",
    }
    if kind in static:
        return static[kind]
    if kind == "domain-baseline" and domain_key is not None:
        return f"domain:{domain_key}"
    raise ValueError(f"unsupported protocol-2.2 dependency role: {kind}")


def _run_re_v2_live(context: object) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from echelon.re_ui import print_re_status_card, re_progress_session

    if isinstance(context, Protocol22RunContext):
        from harness.re_v2.protocol_24.model import RunManifestV3
        from harness.re_v2.protocol_25.model import RunManifestV4
        from harness.re_v2.protocol_26.model import RunManifestV5
        from harness.re_v2.run_store import load_run_manifest

        manifest = load_run_manifest(context.paths.root.parent)
        target_layer = (
            manifest.target_layer if isinstance(manifest, RunManifestV5) else None
        )
        if isinstance(manifest, RunManifestV4) or target_layer == "L3":
            from harness.re_v2.protocol_25.controller import Protocol25Controller
            from harness.re_v2.protocol_25.materialization import (
                materialize_accepted_l3,
            )
            from harness.re_v2.protocol_25.status import protocol_25_status_document

            controller_type = Protocol25Controller
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.controller import Protocol26L3Controller

                controller_type = Protocol26L3Controller
            run_dir = context.paths.root.parent
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.status import protocol_26_status_document

                initial_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                initial_document = protocol_25_status_document(
                    run_dir,
                    context=context,
                )
            with re_progress_session(run_dir, initial_document):
                controller_type(context).run_until_stopped()
            materialize_accepted_l3(context)
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.status import protocol_26_status_document

                final_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                final_document = protocol_25_status_document(
                    run_dir,
                    context=context,
                )
            print_re_status_card(final_document)
        elif isinstance(manifest, RunManifestV3) or target_layer == "L2":
            from harness.re_v2.protocol_24.controller import Protocol24Controller
            from harness.re_v2.protocol_24.status import protocol_24_status_document

            controller_type = Protocol24Controller
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.controller import Protocol26L2Controller

                controller_type = Protocol26L2Controller
            run_dir = context.paths.root.parent
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.status import protocol_26_status_document

                initial_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                initial_document = protocol_24_status_document(
                    run_dir,
                    context=context,
                )
            with re_progress_session(run_dir, initial_document):
                controller_type(context).run_until_stopped()
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.status import protocol_26_status_document

                final_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                final_document = protocol_24_status_document(
                    run_dir,
                    context=context,
                )
            print_re_status_card(final_document)
        else:
            from harness.re_v2.protocol_22.controller import Protocol22Controller
            from harness.re_v2.protocol_22.status import protocol_22_status_document

            controller_type = Protocol22Controller
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.controller import Protocol26L1Controller

                controller_type = Protocol26L1Controller
            run_dir = context.paths.root.parent
            if isinstance(manifest, RunManifestV5):
                from harness.re_v2.protocol_26.status import protocol_26_status_document

                initial_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                initial_document = protocol_22_status_document(
                    run_dir,
                    context=context,
                )
            with re_progress_session(run_dir, initial_document):
                controller_type(context).run_until_stopped()
            if isinstance(manifest, RunManifestV5):
                final_document = protocol_26_status_document(
                    run_dir,
                    context=context,
                )
            else:
                final_document = protocol_22_status_document(
                    run_dir,
                    context=context,
                )
            print_re_status_card(final_document)
        return
    from harness.re_v2.controller import ReV2Controller
    from harness.re_v2.status import render_v2_status

    ReV2Controller(context).run_until_stopped()
    print(render_v2_status(context.paths.root.parent), end="")


def _run_re_v2_create(
    project_root: Path,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    shadow: bool,
    goal: str,
) -> None:
    from harness.re_v2.protocol_26.adoption import initialize_protocol_26_run
    from harness.re_v2.protocol_26.inputs import create_protocol_26_run_store

    if goal not in {"baseline", "inventory"}:
        raise ValueError("protocol-2.2 goal must be baseline or inventory")
    workspace_root = project_root.resolve()
    prepared = _prepare_re_v26_creation(
        workspace_root,
        target_layer="L1",
        parent_run=None,
        goal=goal,
        deepen_options=None,
        token_limit=token_limit,
        time_limit_minutes=time_limit_minutes,
    )
    run_id = str(getattr(prepared.manifest, "run_id"))
    run_dir = workspace_root / "runs" / run_id
    create_protocol_26_run_store(
        run_dir,
        prepared.manifest,
        prepared.inputs,
    )
    context = _re_v2_context(workspace_root, run_dir)
    initialize_protocol_26_run(context)
    _activate_re_v2_run(workspace_root, run_id)
    if shadow:
        _run_re_v2_shadow(context)
    else:
        _run_re_v2_live(context)


def _re_v2_is_paused(events: tuple[object, ...]) -> bool:
    paused = False
    for event in events:
        if getattr(event, "type") == "run_paused":
            paused = True
        elif getattr(event, "type") == "run_resumed":
            paused = False
    return paused


def _run_re_v2_continue(
    run_dir: Path,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    semantic_token_limit: int | None = None,
    semantic_time_limit_minutes: int | None = None,
) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from harness.re_v2.protocol_25.recovery import Protocol25RunContext
    from harness.re_v2.protocol_27.recovery import Protocol27RunContext
    from harness.re_v2.protocol_28.context import (
        Protocol28ClosureRunContext,
        Protocol28RunContext,
    )

    project_root = run_dir.resolve().parent.parent
    context = _re_v2_context(project_root, run_dir)
    if isinstance(context, Protocol28ClosureRunContext):
        if any(
            value is not None
            for value in (
                token_limit,
                time_limit_minutes,
                semantic_token_limit,
                semantic_time_limit_minutes,
            )
        ):
            raise ValueError(
                "protocol-2.8 closure continuation rejects resource authorization"
            )
        from harness.re_v2.protocol_28.closure import (
            complete_l4_closure_successor,
        )
        from harness.re_v2.protocol_28.status import protocol_28_status_document
        from echelon.re_ui import print_re_status_card

        complete_l4_closure_successor(run_dir)
        if not _advance_re_v28_open_intent(project_root, run_dir.name):
            print_re_status_card(protocol_28_status_document(run_dir))
        return
    if isinstance(context, Protocol28RunContext):
        if semantic_token_limit is not None or semantic_time_limit_minutes is not None:
            raise ValueError(
                "semantic resource authorization is valid only for protocol 2.5"
            )
        if _is_reviewed_analysis_run(run_dir):
            from harness.config import load_config
            from harness.re_v2.knowledge_workflow import run_knowledge_workflow
            from harness.squad_provider import SquadCliProvider

            _installed_re_runtime_or_exit(project_root)
            config = load_config(project_root, squad_only=True)
            depths = _reviewed_run_depths(run_dir)
            frozen = tuple(sorted(set(depths.values())))
            effective_depth = frozen[0] if len(frozen) == 1 else "mixed"
            result = run_knowledge_workflow(
                project_root,
                run_dir.name,
                lambda: SquadCliProvider(config),
                token_limit=token_limit,
                active_ms_limit=(
                    time_limit_minutes * 60_000
                    if time_limit_minutes is not None
                    else None
                ),
            )
            _render_re_knowledge_result("continue", effective_depth, result)
            return
        from harness.config import load_config
        from harness.re_v2.protocol_28.lifecycle import continue_protocol_28_run
        from harness.re_v2.protocol_28.status import protocol_28_status_document
        from harness.squad_provider import SquadCliProvider
        from echelon.re_ui import print_re_status_card, re_progress_session

        _installed_re_runtime_or_exit(project_root)
        config = load_config(project_root, squad_only=True)
        initial_document = protocol_28_status_document(run_dir)
        with re_progress_session(run_dir, initial_document):
            result = continue_protocol_28_run(
                run_dir,
                token_limit=token_limit,
                active_ms_limit=(
                    time_limit_minutes * 60_000
                    if time_limit_minutes is not None
                    else None
                ),
                provider_factory=lambda: SquadCliProvider(config),
            )
        if result.run_root_id is not None:
            from harness.re_v2.protocol_28.materialization import (
                materialize_l4_closure,
            )

            materialize_l4_closure(context)
            if not context.inputs.parent_authority_bundle.unresolved_deeper_finding_ids:
                context.controller.complete_run(
                    result.run_root_id, closure_required=False
                )
            if _advance_re_v28_open_intent(project_root, result.run_id):
                return
        print_re_status_card(protocol_28_status_document(run_dir))
        return
    if isinstance(context, Protocol27RunContext):
        if any(
            value is not None
            for value in (
                token_limit,
                time_limit_minutes,
                semantic_token_limit,
                semantic_time_limit_minutes,
            )
        ):
            raise ValueError(
                "protocol-2.7 continuation uses its immutable synthesis budget"
            )
        from harness.config import load_config
        from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis
        from harness.re_v2.protocol_27.status import protocol_27_status_document
        from harness.squad_provider import SquadCliProvider
        from echelon.re_ui import print_re_status_card, re_progress_session

        _installed_re_runtime_or_exit(project_root)
        config = load_config(project_root, squad_only=True)
        initial_document = protocol_27_status_document(run_dir)
        with re_progress_session(run_dir, initial_document):
            run_protocol_27_synthesis(
                run_dir,
                lambda: SquadCliProvider(config),
            )
        print_re_status_card(protocol_27_status_document(run_dir))
        return
    if isinstance(context, Protocol25RunContext):
        _run_re_v25_continue(
            context,
            token_limit=token_limit,
            time_limit_minutes=time_limit_minutes,
            semantic_token_limit=semantic_token_limit,
            semantic_time_limit_minutes=semantic_time_limit_minutes,
        )
        events = context.event_store.replay()
        if events and events[-1].type in {"run_completed", "run_failed"}:
            _advance_re_v28_open_intent(
                project_root, context.paths.root.parent.name
            )
        return
    if semantic_token_limit is not None or semantic_time_limit_minutes is not None:
        raise ValueError("semantic resource authorization is valid only for protocol 2.5")
    if isinstance(context, Protocol22RunContext):
        _run_re_v22_continue(
            context,
            token_limit=token_limit,
            time_limit_minutes=time_limit_minutes,
        )
        return
    from harness.re_v2.budget import (
        BudgetDimension,
        authorize_resource_increase,
        evaluate_budget,
    )
    from harness.re_v2.recovery import recover_run

    recovered = recover_run(context)
    terminal_types = {"run_completed", "run_finalized_partial", "run_failed"}
    if recovered.events and recovered.events[-1].type in terminal_types:
        if token_limit is not None or time_limit_minutes is not None:
            raise ValueError("terminal v2 runs cannot receive budget authorization")
        _run_re_v2_live(context)
        return
    paused = _re_v2_is_paused(recovered.events)
    requested = (
        (BudgetDimension.TOKENS, token_limit),
        (
            BudgetDimension.ACTIVE_MS,
            time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else None,
        ),
    )
    authorized = False
    for dimension, new_value in requested:
        if new_value is None:
            continue
        history = context.event_store.replay()
        if not _re_v2_is_paused(history):
            raise ValueError("v2 budget authorization requires a paused run")
        budget = evaluate_budget(
            context.manifest.initial_budget_policy,
            history,
            now=_re_v2_now(),
        )
        old_value = (
            budget.token_limit
            if dimension is BudgetDimension.TOKENS
            else budget.active_ms_limit
        )
        event = authorize_resource_increase(
            context.manifest.initial_budget_policy,
            history,
            dimension=dimension,
            old_value=old_value,
            new_value=new_value,
            actor="echelon-cli",
            reason="CLI resource ceiling increase",
        )
        context.event_store.append(
            str(event["type"]),
            event["payload"],
            occurred_at=_re_v2_now(),
        )
        authorized = True
    if paused:
        if not authorized:
            context.event_store.append(
                "operator_pause_requested",
                {
                    "reason": "CLI continuation requested",
                    "requested_by": "echelon-cli",
                },
                occurred_at=_re_v2_now(),
            )
        context.event_store.append(
            "run_resumed",
            {
                "reason": (
                    "CLI continuation after resource authorization"
                    if authorized
                    else "CLI continuation requested"
                )
            },
            occurred_at=_re_v2_now(),
        )
    _run_re_v2_live(context)


def _extract_re_semantic_budget_options(
    args: list[str],
) -> tuple[list[str], int | None, int | None]:
    fields = {
        "--re-semantic-token-limit": "tokens",
        "--re-semantic-time-limit-minutes": "minutes",
    }
    values: dict[str, int | None] = {"tokens": None, "minutes": None}
    remaining: list[str] = []
    index = 0
    while index < len(args):
        raw = args[index]
        name, separator, inline = raw.partition("=")
        field = fields.get(name)
        if field is None:
            remaining.append(raw)
            index += 1
            continue
        if values[field] is not None:
            raise ValueError(f"{name} may be supplied only once")
        if separator:
            value_text = inline
            index += 1
        else:
            if index + 1 >= len(args):
                raise ValueError(f"{name} requires a positive integer")
            value_text = args[index + 1]
            index += 2
        try:
            value = int(value_text)
        except ValueError as exc:
            raise ValueError(f"{name} requires a positive integer") from exc
        if value <= 0:
            raise ValueError(f"{name} requires a positive integer")
        values[field] = value
    return remaining, values["tokens"], values["minutes"]


def _run_re_v22_continue(
    context: object,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    active_ms_limit: int | None = None,
) -> None:
    from harness.re_v2.protocol_22.recovery import (
        protocol_22_run_lock,
        recover_protocol_22_run,
        recover_protocol_22_run_locked,
    )

    requested = {
        "tokens": token_limit,
        "active_ms": (
            active_ms_limit
            if active_ms_limit is not None
            else time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else None
        ),
    }

    def validate(recovered: object) -> list[tuple[str, int, int | None]]:
        state = str(getattr(recovered, "operational_state"))
        changes = [
            (dimension, value)
            for dimension, value in requested.items()
            if value is not None
        ]
        if state == "terminal":
            if changes:
                raise ValueError(
                    "terminal protocol-2.2 runs cannot receive budget authorization"
                )
            return []
        if state == "pinned_authority_unavailable":
            if changes:
                raise ValueError(
                    "protocol-2.2 budget authorization requires restored pinned authority"
                )
            return []
        if state == "paused":
            if not changes:
                raise ValueError(
                    "paused protocol-2.2 continuation requires a strictly higher "
                    "token or active-time ceiling"
                )
            budget = getattr(recovered, "budget", None)
            if budget is None:
                raise ValueError("paused protocol-2.2 recovery omitted budget authority")
            validated: list[tuple[str, int, int | None]] = []
            for dimension, new_value in changes:
                old_value = (
                    budget.token_limit
                    if dimension == "tokens"
                    else budget.active_ms_limit
                )
                if old_value is not None and new_value <= old_value:
                    raise ValueError(
                        f"protocol-2.2 {dimension} ceiling must be strictly higher "
                        f"than {old_value}"
                    )
                validated.append((dimension, new_value, old_value))
            return validated
        if changes:
            raise ValueError(
                "protocol-2.2 budget authorization requires a paused run"
            )
        return []

    recovered = recover_protocol_22_run(context)
    changes = validate(recovered)
    if str(recovered.operational_state) in {
        "terminal",
        "pinned_authority_unavailable",
    }:
        _run_re_v2_live(context)
        return
    if not changes:
        _run_re_v2_live(context)
        return

    with protocol_22_run_lock(context.paths):
        recovered = recover_protocol_22_run_locked(context)
        changes = validate(recovered)
        for dimension, new_value, old_value in changes:
            context.event_store.append(
                "budget_authorized",
                {
                    "authorized_by": "echelon-cli",
                    "dimension": dimension,
                    "new_value": new_value,
                    "old_value": old_value,
                    "reason": "CLI resource ceiling increase",
                },
                occurred_at=_re_v2_now(),
            )
        context.event_store.append(
            "run_resumed",
            {"reason": "CLI continuation after resource authorization"},
            occurred_at=_re_v2_now(),
        )
    _run_re_v2_live(context)


def _run_re_v25_continue(
    context: object,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    semantic_token_limit: int | None,
    semantic_time_limit_minutes: int | None,
) -> None:
    """Authorize independent run-wide/semantic resources on one paused L3 run."""
    from harness.re_v2.protocol_22.budget import evaluate_budget_v22
    from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
    from harness.re_v2.protocol_25.budget import evaluate_semantic_budget
    from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_25.recovery import (
        Protocol25RunContext,
        recover_protocol_25_run,
    )
    from harness.re_v2.run_store import load_run_manifest

    if not isinstance(context, Protocol25RunContext):
        raise ValueError("protocol-2.5 continuation requires Protocol25RunContext")
    requested = {
        ("run", "tokens"): token_limit,
        ("run", "active_ms"): (
            time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else None
        ),
        ("semantic", "tokens"): semantic_token_limit,
        ("semantic", "active_ms"): (
            semantic_time_limit_minutes * 60_000
            if semantic_time_limit_minutes is not None
            else None
        ),
    }

    def budget_decisions(recovered: object) -> tuple[object, object]:
        active_manifest = load_run_manifest(context.paths.root.parent)
        manifest = (
            context.semantic_graph.manifest
            if isinstance(active_manifest, RunManifestV5)
            else active_manifest
        )
        event_protocol = (
            protocol_26_events_for("L3")
            if isinstance(active_manifest, RunManifestV5)
            else PROTOCOL_25_EVENTS
        )
        return (
            evaluate_budget_v22(
                manifest.initial_budget_policy,
                recovered.events,
                (),
                _re_v2_now(),
                event_protocol=event_protocol,
            ),
            evaluate_semantic_budget(
                manifest.semantic_closure_policy,
                recovered.events,
                event_protocol=event_protocol,
            ),
        )

    def stale_accounting_pause(recovered: object) -> bool:
        last_control = next(
            (
                event
                for event in reversed(recovered.events)
                if event.type in {"run_paused", "run_resumed"}
            ),
            None,
        )
        if (
            last_control is None
            or last_control.type != "run_paused"
            or last_control.payload["reason_code"]
            != "semantic_budget_authorization_required"
        ):
            return False
        run_budget, semantic_budget = budget_decisions(recovered)
        return not any(
            (
                run_budget.resources_exhausted,
                run_budget.reservation_breaches,
                semantic_budget.resources_exhausted,
                semantic_budget.reservation_breaches,
            )
        )

    def validate(recovered: object) -> list[tuple[str, str, int, int | None]]:
        state = recovered.controller_state
        changes = [
            (pool, dimension, value)
            for (pool, dimension), value in requested.items()
            if value is not None
        ]
        if state.terminal_state is not None:
            if changes:
                raise ValueError(
                    "terminal protocol-2.5 runs cannot receive resource authorization"
                )
            return []
        if not state.paused_resource:
            if changes:
                raise ValueError(
                    "protocol-2.5 resource authorization requires a paused run"
                )
            return []
        if not changes:
            if stale_accounting_pause(recovered):
                return []
            raise ValueError(
                "paused protocol-2.5 continuation requires a strictly higher "
                "run-wide or semantic ceiling"
            )
        run_budget, semantic_budget = budget_decisions(recovered)
        validated: list[tuple[str, str, int, int | None]] = []
        for pool, dimension, value in changes:
            if pool == "run":
                old_value = (
                    run_budget.token_limit
                    if dimension == "tokens"
                    else run_budget.active_ms_limit
                )
            else:
                old_value = (
                    semantic_budget.token_limit
                    if dimension == "tokens"
                    else semantic_budget.active_ms_limit
                )
            if old_value is not None and value <= old_value:
                raise ValueError(
                    f"protocol-2.5 {pool} {dimension} ceiling must be "
                    f"strictly higher than {old_value}"
                )
            validated.append((pool, dimension, value, old_value))
        return validated

    recovered = recover_protocol_25_run(context)
    changes = validate(recovered)
    if recovered.controller_state.terminal_state is not None:
        from harness.re_v2.protocol_25.status import render_protocol_25_status

        print(
            render_protocol_25_status(
                context.paths.root.parent,
                context=context,
            ),
            end="",
        )
        return
    if not changes:
        if not recovered.controller_state.paused_resource:
            _run_re_v2_live(context)
            return
        with protocol_22_run_lock(context.paths):
            recovered = recover_protocol_25_run(context)
            changes = validate(recovered)
            if changes:
                raise ValueError(
                    "stale protocol-2.5 accounting pause unexpectedly requires "
                    "resource authorization"
                )
            context.event_store.append(
                "operator_pause_requested",
                {
                    "reason": "CLI accounting-pause revalidation requested",
                    "requested_by": "echelon-cli",
                },
                occurred_at=_re_v2_now(),
            )
            context.event_store.append(
                "run_resumed",
                {"reason": "CLI continuation after accounting-pause revalidation"},
                occurred_at=_re_v2_now(),
            )
        _run_re_v2_live(context)
        return
    with protocol_22_run_lock(context.paths):
        recovered = recover_protocol_25_run(context)
        changes = validate(recovered)
        for pool, dimension, new_value, old_value in changes:
            context.event_store.append(
                "budget_authorized" if pool == "run" else "semantic_budget_authorized",
                {
                    "authorized_by": "echelon-cli",
                    "dimension": dimension,
                    "new_value": new_value,
                    "old_value": old_value,
                    "reason": "CLI resource ceiling increase",
                },
                occurred_at=_re_v2_now(),
            )
        context.event_store.append(
            "run_resumed",
            {"reason": "CLI continuation after resource authorization"},
            occurred_at=_re_v2_now(),
        )
    _run_re_v2_live(context)


def _cmd_re_run(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError

    try:
        engine, shadow, goal, lifecycle_args = _parse_re_creation_engine_options(args)
        (
            policy,
            re_max_inner,
            reset,
            no_reuse,
            profile,
            token_limit,
            time_limit_minutes,
            positional,
        ) = _parse_re_lifecycle_options(
            lifecycle_args,
            allow_policy=True,
            allow_reset=True,
        )
        if positional:
            raise ValueError("echelon re run does not accept positional arguments")
        if engine == "v2":
            if re_max_inner is not None:
                raise ValueError(
                    "v2 has independent attempt budgets; this option is valid only for v1"
                )
            if policy != "changed" or reset or no_reuse or profile is not None:
                raise ValueError(
                    "v2 creation does not accept v1 policy, reset, reuse, or profile options"
                )
            try:
                _run_re_v2_create(
                    Path.cwd(),
                    token_limit=token_limit,
                    time_limit_minutes=time_limit_minutes,
                    shadow=shadow,
                    goal=goal,
                )
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            return
        result = _re_lifecycle_controller(Path.cwd()).run(
            policy=policy,
            re_max_inner=re_max_inner,
            reset=reset,
            reuse_published=not no_reuse,
            profile_name=profile,
            hard_token_limit=token_limit,
            hard_active_minutes=time_limit_minutes,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_refresh(args: list[str]) -> None:
    """Refresh and publish one declared source through the normal RE transaction."""
    from harness.re_lifecycle import ReLifecycleError

    source = ""
    index = 0
    try:
        while index < len(args):
            arg = args[index]
            if arg == "--source":
                if index + 1 >= len(args) or source:
                    raise ValueError("--source requires exactly one source ID")
                source = args[index + 1].strip()
                index += 2
            elif arg.startswith("--source="):
                if source:
                    raise ValueError("--source requires exactly one source ID")
                source = arg.split("=", 1)[1].strip()
                index += 1
            else:
                raise ValueError(f"unknown option {arg!r}")
        if not source:
            raise ValueError("--source requires exactly one source ID")
        result = _re_lifecycle_controller(Path.cwd()).run(
            policy="target-only",
            target_source=source,
            force_selected_refresh=True,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re refresh: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if str(getattr(result, "status", "failed")) != "done":
        _print_re_lifecycle_result(result)
        return
    run_id = str(getattr(result, "run_id", ""))
    if bool(getattr(result, "no_work", False)) or not run_id:
        raise SystemExit("echelon re refresh: targeted refresh produced no publishable run")
    _cmd_re_publish([run_id])


@dataclass(frozen=True, slots=True)
class _ReKnowledgeActionOptions:
    source_ids: tuple[str, ...]
    depth: str | None
    token_limit: int | None
    active_ms_limit: int | None


def _parse_re_knowledge_action_options(
    args: list[str], *, allow_sources: bool
) -> _ReKnowledgeActionOptions:
    """Parse the intentionally small normal RE action surface."""
    from harness.re_v2.protocol_22.schema import safe_id

    sources: list[str] = []
    depth: str | None = None
    token_limit: int | None = None
    time_limit_minutes: int | None = None
    index = 0
    while index < len(args):
        argument = args[index]
        if argument in {
            "--source",
            "--depth",
            "--re-token-limit",
            "--re-time-limit-minutes",
        }:
            if index + 1 >= len(args):
                raise ValueError(f"{argument} requires a value")
            value = args[index + 1].strip()
            index += 2
        elif any(
            argument.startswith(prefix)
            for prefix in (
                "--source=",
                "--depth=",
                "--re-token-limit=",
                "--re-time-limit-minutes=",
            )
        ):
            option, value = argument.split("=", 1)
            value = value.strip()
            argument = option
            index += 1
        else:
            raise ValueError(f"unknown option {argument!r}")
        if argument == "--source":
            if not allow_sources:
                raise ValueError("--source is valid only with echelon re refresh")
            safe_id(value, "source")
            sources.append(value)
        elif argument == "--depth":
            if depth is not None:
                raise ValueError("--depth may be supplied only once")
            from echelon.re_cli_options import resolve_knowledge_depth

            depth = resolve_knowledge_depth(
                explicit=value, published=None, workspace_default=None
            )
        elif argument == "--re-token-limit":
            try:
                token_limit = int(value)
            except ValueError:
                raise ValueError("--re-token-limit requires a positive integer") from None
            if token_limit <= 0:
                raise ValueError("--re-token-limit requires a positive integer")
        else:
            try:
                time_limit_minutes = int(value)
            except ValueError:
                raise ValueError(
                    "--re-time-limit-minutes requires a positive integer"
                ) from None
            if time_limit_minutes <= 0:
                raise ValueError(
                    "--re-time-limit-minutes requires a positive integer"
                )
    if len(sources) != len(set(sources)):
        raise ValueError("--source values must be unique")
    return _ReKnowledgeActionOptions(
        tuple(sources),
        depth,
        token_limit,
        None if time_limit_minutes is None else time_limit_minutes * 60_000,
    )


def _resolve_re_knowledge_action_options(
    workspace: Path,
    options: _ReKnowledgeActionOptions,
) -> _ReKnowledgeActionOptions:
    """Apply configured RE authorization before freezing an ordinary request."""
    from dataclasses import replace

    from harness.re_profiles import resolve_re_execution_profile

    profile = resolve_re_execution_profile(
        workspace,
        hard_token_limit=options.token_limit,
        hard_active_minutes=(
            None
            if options.active_ms_limit is None
            else options.active_ms_limit // 60_000
        ),
    )
    if profile.hard_token_limit is None or profile.hard_active_minutes is None:
        raise ValueError("ordinary RE requires finite token and active-time ceilings")
    return replace(
        options,
        token_limit=profile.hard_token_limit,
        active_ms_limit=profile.hard_active_minutes * 60_000,
    )


def _reviewed_run_depths(run_dir: Path) -> dict[str, str]:
    """Read the frozen per-source depth labels from reviewed run authority."""
    import json

    from harness.re_v2.knowledge_activation import ReviewedDiscoveryAuthorityV1
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.inputs import (
        ReviewedProtocol28CreationInputs,
        ValidatedReviewedProtocol28Inputs,
    )

    context = load_protocol_28_run_context(Path(run_dir).resolve())
    if not isinstance(
        context.inputs,
        (ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs),
    ):
        raise ValueError("the active RE run is not a repaired reviewed analysis")
    result: dict[str, str] = {}
    for authority_id in context.inputs.reviewed_discovery_catalog.authority_ids:
        authority = ReviewedDiscoveryAuthorityV1.from_json_dict(
            json.loads(context.objects.read_blob(authority_id))
        )
        result[authority.source_id] = authority.depth
    return dict(sorted(result.items()))


def _is_reviewed_analysis_run(run_dir: Path | None) -> bool:
    if run_dir is None:
        return False
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.inputs import (
        ReviewedProtocol28CreationInputs,
        ValidatedReviewedProtocol28Inputs,
    )

    manifest = Path(run_dir) / "v2" / "run.json"
    if manifest.is_symlink() or not manifest.is_file():
        return False
    try:
        context = load_protocol_28_run_context(Path(run_dir).resolve())
    except (OSError, RuntimeError, ValueError):
        raise ValueError("invalid active RE run manifest") from None
    return isinstance(
        context.inputs,
        (ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs),
    )


def _render_re_knowledge_result(action: str, depth: str, result: object) -> None:
    state = str(getattr(result, "state", "needs-attention"))
    generation = getattr(result, "publication_generation", None)
    reason = getattr(result, "reason_code", None)
    label = state.replace("complete", "completed", 1)
    print(f"[re] {action} {label} · depth {depth}")
    if generation is not None:
        print(f"[re] published generation {generation}")
    if reason:
        print(f"[re] reason: {reason}")


def _capture_re_knowledge_authority(workspace: Path) -> tuple[object, object, tuple[str, ...]]:
    """Freeze all declared sources for one ordinary reviewed request."""
    from harness.re_v2.protocol_22.partition import build_workspace_partition_catalog
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

    manifest = discover_workspace(workspace)
    source_ids = tuple(sorted(source.id for source in manifest.sources))
    if not source_ids:
        raise ValueError("needs attention: the workspace declares no sources to analyze")
    snapshot = capture_workspace_snapshot(
        workspace,
        manifest.sources,
        _re_v2_snapshot_root(workspace),
    )
    partition = build_workspace_partition_catalog(
        snapshot,
        manifest,
        _re_v22_partition_authorities(),
    )
    return snapshot, partition, source_ids


def _resume_creation_depths(intent: dict[str, object]) -> tuple[tuple[str, str], ...]:
    raw = intent.get("source_depths")
    if not isinstance(raw, list):
        raise ValueError("invalid active reviewed-analysis creation intent")
    rows: list[tuple[str, str]] = []
    for row in raw:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not all(isinstance(value, str) for value in row)
        ):
            raise ValueError("invalid active reviewed-analysis creation intent")
        rows.append((row[0], row[1]))
    return tuple(rows)


def _create_or_resume_re_knowledge_analysis(
    workspace: Path,
    active: Path | None,
    options: _ReKnowledgeActionOptions,
    config: object,
) -> tuple[Path, str]:
    """Create or recover the reviewed analysis prerequisite for ordinary run."""
    from harness.re_registry import load_published_index
    from harness.re_v2.knowledge_creation import (
        ReviewedAnalysisCreationOptions,
        create_or_resume_reviewed_analysis,
        load_reviewed_analysis_creation_intent,
    )
    from harness.re_v2.protocol_24.model import SelectionScopeV1

    intent = (
        load_reviewed_analysis_creation_intent(active)
        if active is not None
        else None
    )
    snapshot, partition, source_ids = _capture_re_knowledge_authority(workspace)
    if intent is not None and (
        intent.get("snapshot_id") != getattr(snapshot, "snapshot_id", None)
        or intent.get("workspace_partition_id") != getattr(partition, "identity", None)
    ):
        # The old immutable request remains available for diagnosis; changed
        # source authority starts a new request and never rewrites it.
        intent = None

    if intent is None:
        from echelon.re_cli_options import (
            configured_workspace_depth,
            resolve_source_depths,
        )

        published = load_published_index(workspace)
        established = (
            {
                source_id: published.sources[source_id].depth
                if source_id in published.sources
                else None
                for source_id in source_ids
            }
            if published is not None
            else {}
        )
        depths = resolve_source_depths(
            source_ids,
            explicit=options.depth,
            published=established,
            workspace_default=configured_workspace_depth(workspace),
        )
        request_run_id = _new_re_v2_run_id(workspace)
        analysis_run_id = f"{request_run_id}-analysis"
        created_at = _re_v2_now()
        token_limit = options.token_limit
        active_ms_limit = options.active_ms_limit
        _activate_re_v2_run(workspace, request_run_id)
    else:
        request_run_id = str(intent.get("request_run_id", ""))
        analysis_run_id = str(intent.get("analysis_run_id", ""))
        created_at = str(intent.get("created_at", ""))
        depths = dict(_resume_creation_depths(intent))
        token_limit = intent.get("token_limit")
        active_ms_limit = intent.get("active_ms_limit")
        if (
            request_run_id != active.name
            or not analysis_run_id.startswith("re-")
            or type(token_limit) is not int
            or type(active_ms_limit) is not int
        ):
            raise ValueError("invalid active reviewed-analysis creation intent")
        if options.depth is not None and set(depths.values()) != {options.depth}:
            raise ValueError(
                "needs attention: requested depth differs from the active immutable "
                "analysis request"
            )

    depth_label = (
        next(iter(set(depths.values())))
        if len(set(depths.values())) == 1
        else "mixed"
    )
    provider_id = str(getattr(getattr(config, "llm", None), "cli", "configured"))
    print(
        f"[re] run starting · depth {depth_label} · provider {provider_id}",
        flush=True,
    )
    print(
        f"[re] scope {len(source_ids)} source(s) · aggregate ceiling "
        f"{token_limit} tokens / {active_ms_limit // 60_000} minutes",
        flush=True,
    )
    creation = create_or_resume_reviewed_analysis(
        workspace,
        ReviewedAnalysisCreationOptions(
            request_run_id=request_run_id,
            analysis_run_id=analysis_run_id,
            created_at=created_at,
            snapshot=snapshot,
            workspace_partition=partition,
            selection=SelectionScopeV1(1, True, (), ()),
            source_depths=tuple(sorted(depths.items())),
            token_limit=token_limit,
            active_ms_limit=active_ms_limit,
            config=config,
        ),
    )
    if creation.state != "ready" or creation.analysis_run_id is None:
        _render_re_knowledge_result("run", depth_label, creation)
        raise SystemExit(2)
    _activate_re_v2_run(workspace, creation.analysis_run_id)
    return workspace / "runs" / creation.analysis_run_id, depth_label


def _cmd_re_knowledge_run(args: list[str]) -> None:
    """Resume reviewed analysis through synthesis and atomic publication."""
    try:
        options = _parse_re_knowledge_action_options(args, allow_sources=False)
        from harness.config import load_config
        from harness.re_lifecycle import resolve_current_re_run
        from harness.re_v2.knowledge_workflow import run_knowledge_workflow
        from harness.squad_provider import SquadCliProvider

        workspace = Path.cwd().resolve()
        options = _resolve_re_knowledge_action_options(workspace, options)
        run_dir = resolve_current_re_run(workspace)
        config = load_config(workspace, squad_only=True)
        depths = (
            _reviewed_run_depths(run_dir)
            if _is_reviewed_analysis_run(run_dir)
            else None
        )
        if depths is None:
            run_dir, effective_depth = _create_or_resume_re_knowledge_analysis(
                workspace, run_dir, options, config
            )
            depths = _reviewed_run_depths(run_dir)
        else:
            frozen = tuple(sorted(set(depths.values())))
            if options.depth is not None and frozen != (options.depth,):
                raise ValueError(
                    "needs attention: requested depth differs from the active immutable "
                    "analysis; run echelon re refresh with the requested depth"
                )
            effective_depth = options.depth or (
                frozen[0] if len(frozen) == 1 else "mixed"
            )
        result = run_knowledge_workflow(
            workspace,
            run_dir.name,
            lambda: SquadCliProvider(config),
            token_limit=options.token_limit,
            active_ms_limit=options.active_ms_limit,
        )
        _render_re_knowledge_result("run", effective_depth, result)
        if str(result.state) == "needs-attention":
            raise SystemExit(2)
    except SystemExit:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"echelon re run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _cmd_re_knowledge_refresh(args: list[str]) -> None:
    """Plan and resume one source-granular reviewed refresh transaction."""
    try:
        options = _parse_re_knowledge_action_options(args, allow_sources=True)
        options = _resolve_re_knowledge_action_options(Path.cwd().resolve(), options)
        _run_re_knowledge_refresh_action(
            Path.cwd().resolve(),
            options.source_ids,
            options.depth,
            options.token_limit,
            options.active_ms_limit,
        )
    except SystemExit:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"echelon re refresh: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run_re_knowledge_refresh_action(
    workspace: Path,
    source_ids: tuple[str, ...],
    explicit_depth: str | None,
    token_limit: int,
    active_ms_limit: int,
) -> None:
    """Create or resume changed-source analysis and publish one refresh."""
    from harness.config import load_config
    from harness.re_lifecycle import resolve_current_re_run
    from harness.re_registry import load_published_index
    from harness.re_v2.knowledge_refresh import (
        plan_knowledge_refresh,
        snapshots_from_partition,
    )
    from harness.re_v2.knowledge_workflow import run_knowledge_refresh
    from harness.squad_provider import SquadCliProvider

    published = load_published_index(workspace)
    if published is None:
        raise ValueError("needs attention: no published knowledge exists; run echelon re run")
    from dataclasses import replace
    from harness.re_v2.protocol_22.partition import build_workspace_partition_catalog
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

    workspace_manifest = discover_workspace(workspace)
    declared = tuple(source.id for source in workspace_manifest.sources)
    selected = source_ids or declared
    unknown = tuple(sorted(set(selected) - set(declared)))
    if unknown:
        raise ValueError(
            "unknown declared source" + ("s" if len(unknown) > 1 else "")
            + ": " + ", ".join(unknown)
        )
    selected_roots = tuple(
        source for source in workspace_manifest.sources if source.id in set(selected)
    )
    snapshot = capture_workspace_snapshot(
        workspace,
        selected_roots,
        _re_v2_snapshot_root(workspace),
    )
    selected_manifest = replace(workspace_manifest, sources=selected_roots)
    partition = build_workspace_partition_catalog(
        snapshot,
        selected_manifest,
        _re_v22_partition_authorities(),
    )
    snapshots = tuple(
        snapshot
        for snapshot in snapshots_from_partition(partition)
    )
    from echelon.re_cli_options import configured_workspace_depth

    plan = plan_knowledge_refresh(
        declared_source_ids=declared,
        selected_snapshots=snapshots,
        selected_source_ids=None if not source_ids else selected,
        published=published,
        explicit_depth=explicit_depth,
        workspace_default=configured_workspace_depth(workspace),
    )
    config = load_config(workspace, squad_only=True)
    analysis_run_id: str | None = None
    if plan.reanalyze_source_ids:
        from harness.re_v2.knowledge_creation import (
            ReviewedAnalysisCreationOptions,
            create_or_resume_reviewed_analysis,
            load_reviewed_analysis_creation_intent,
        )
        from harness.re_v2.protocol_24.model import SelectionScopeV1

        depth_by_source = {
            item.source_id: item.depth
            for item in plan.sources
            if item.source_id in set(plan.reanalyze_source_ids)
        }
        if set(depth_by_source) != set(plan.reanalyze_source_ids):
            raise ValueError("refresh analysis depth closure is incomplete")
        selection = SelectionScopeV1(
            1,
            False,
            plan.reanalyze_source_ids,
            (),
        )
        active = resolve_current_re_run(workspace)
        intent = (
            load_reviewed_analysis_creation_intent(active)
            if active is not None
            else None
        )
        if intent is not None and (
            intent.get("snapshot_id") != snapshot.snapshot_id
            or intent.get("workspace_partition_id") != partition.identity
            or intent.get("selection")
            != {
                "schema_version": 1,
                "all_sources": False,
                "source_ids": list(plan.reanalyze_source_ids),
                "domain_keys": [],
            }
            or tuple(_resume_creation_depths(intent))
            != tuple(sorted(depth_by_source.items()))
        ):
            intent = None
        if intent is None:
            request_run_id = _new_re_v2_run_id(workspace)
            analysis_run_id = f"{request_run_id}-analysis"
            created_at = _re_v2_now()
            analysis_token_limit = token_limit
            analysis_active_ms_limit = active_ms_limit
            _activate_re_v2_run(workspace, request_run_id)
        else:
            request_run_id = str(intent.get("request_run_id", ""))
            analysis_run_id = str(intent.get("analysis_run_id", ""))
            created_at = str(intent.get("created_at", ""))
            analysis_token_limit = intent.get("token_limit")
            analysis_active_ms_limit = intent.get("active_ms_limit")
            if (
                active is None
                or request_run_id != active.name
                or not analysis_run_id.startswith("re-")
                or type(analysis_token_limit) is not int
                or type(analysis_active_ms_limit) is not int
            ):
                raise ValueError("invalid active refresh analysis creation intent")
        provider_id = str(getattr(getattr(config, "llm", None), "cli", "configured"))
        print(
            f"[re] refresh analysis starting · provider {provider_id} · "
            f"{len(plan.reanalyze_source_ids)} source(s)",
            flush=True,
        )
        print(
            f"[re] aggregate ceiling {analysis_token_limit} tokens / "
            f"{analysis_active_ms_limit // 60_000} minutes",
            flush=True,
        )
        creation = create_or_resume_reviewed_analysis(
            workspace,
            ReviewedAnalysisCreationOptions(
                request_run_id=request_run_id,
                analysis_run_id=analysis_run_id,
                created_at=created_at,
                snapshot=snapshot,
                workspace_partition=partition,
                selection=selection,
                source_depths=tuple(sorted(depth_by_source.items())),
                token_limit=analysis_token_limit,
                active_ms_limit=analysis_active_ms_limit,
                config=config,
            ),
        )
        if creation.state != "ready" or creation.analysis_run_id is None:
            _render_re_knowledge_result(
                "refresh",
                explicit_depth or "established",
                creation,
            )
            raise SystemExit(2)
        analysis_run_id = creation.analysis_run_id
        _activate_re_v2_run(workspace, analysis_run_id)
    result = run_knowledge_refresh(
        workspace,
        plan,
        analysis_run_id,
        lambda: SquadCliProvider(config),
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
    )
    depth_label = explicit_depth or "established"
    _render_re_knowledge_result("refresh", depth_label, result)
    if str(result.state) == "needs-attention":
        raise SystemExit(2)


@dataclass(frozen=True, slots=True)
class _ReDeepenOptions:
    target_layer: str
    all_sources: bool
    source_ids: tuple[str, ...]
    domain_ids: tuple[str, ...]
    from_run: str | None
    token_limit: int | None
    active_ms_limit: int | None
    semantic_token_limit: int | None
    semantic_active_ms_limit: int | None
    new_audit_epoch: bool
    shadow: bool


@dataclass(frozen=True, slots=True)
class _ReResumeOptions:
    guidance: str | None
    recommended: bool
    banzai: bool
    token_limit: int | None
    time_limit_minutes: int | None
    semantic_token_limit: int | None
    semantic_time_limit_minutes: int | None


def _parse_re_resume_options(
    args: list[str],
) -> tuple[_ReResumeOptions, int | None]:
    """Parse one explicit guidance mode plus optional absolute resource ceilings."""
    recommended = False
    banzai = False
    remaining: list[str] = []
    for arg in args:
        if arg == "--recommended":
            if recommended:
                raise ValueError("--recommended may be supplied only once")
            recommended = True
        elif arg == "--banzai":
            if banzai:
                raise ValueError("--banzai may be supplied only once")
            banzai = True
        else:
            remaining.append(arg)
    (
        lifecycle_args,
        semantic_token_limit,
        semantic_time_limit_minutes,
    ) = _extract_re_semantic_budget_options(remaining)
    (
        _policy,
        re_max_inner,
        _reset,
        _no_reuse,
        _profile,
        token_limit,
        time_limit_minutes,
        positional,
    ) = _parse_re_lifecycle_options(
        lifecycle_args,
        allow_policy=False,
        allow_reset=False,
        allow_budget_overrides=True,
    )
    guidance = positional[0] if len(positional) == 1 else None
    selected = int(guidance is not None) + int(recommended) + int(banzai)
    if selected != 1 or len(positional) > 1:
        raise ValueError(
            "exactly one resume mode is required: \"<guidance>\", "
            "--recommended, or --banzai"
        )
    return (
        _ReResumeOptions(
            guidance=guidance,
            recommended=recommended,
            banzai=banzai,
            token_limit=token_limit,
            time_limit_minutes=time_limit_minutes,
            semantic_token_limit=semantic_token_limit,
            semantic_time_limit_minutes=semantic_time_limit_minutes,
        ),
        re_max_inner,
    )


def _advance_re_v28_open_intent(workspace_root: Path, child_run_id: str) -> bool:
    """Advance the unique durable L4 intent linked to a continued child."""
    from harness.re_v2.protocol_28.orchestration import (
        DeepenOrchestrationController,
        find_open_orchestrations_for_child,
        load_orchestration,
    )

    matches = find_open_orchestrations_for_child(
        workspace_root,
        child_run_id,
        require_unique=True,
    )
    if not matches:
        return False
    intent = load_orchestration(matches[0])
    projection = DeepenOrchestrationController(
        intent,
        clock=_re_v2_now,
    ).rebuild_projection()
    selection = intent.request.selection
    _run_re_v28_deepen(
        workspace_root,
        _ReDeepenOptions(
            target_layer="L4",
            all_sources=selection.all_sources,
            source_ids=selection.source_ids,
            domain_ids=selection.domain_keys,
            from_run=intent.request.input_run_id,
            token_limit=projection.token_limit,
            active_ms_limit=projection.active_ms_limit,
            semantic_token_limit=None,
            semantic_active_ms_limit=None,
            new_audit_epoch=False,
            shadow=False,
        ),
    )
    return True


def _parse_re_deepen_options(args: list[str]) -> _ReDeepenOptions:
    values: dict[str, object] = {
        "target_layer": None,
        "all_sources": False,
        "source_ids": [],
        "domain_ids": [],
        "from_run": None,
        "token_limit": None,
        "active_ms_limit": None,
        "semantic_token_limit": None,
        "semantic_active_ms_limit": None,
        "new_audit_epoch": False,
        "shadow": False,
    }
    scalar = {
        "--to": "target_layer",
        "--from-run": "from_run",
        "--token-limit": "token_limit",
        "--active-ms-limit": "active_ms_limit",
        "--semantic-token-limit": "semantic_token_limit",
        "--semantic-active-ms-limit": "semantic_active_ms_limit",
    }
    repeatable = {"--source": "source_ids", "--domain": "domain_ids"}
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--all":
            if values["all_sources"]:
                raise ValueError("--all may be supplied only once")
            values["all_sources"] = True
            index += 1
            continue
        if option == "--new-audit-epoch":
            if values["new_audit_epoch"]:
                raise ValueError("--new-audit-epoch may be supplied only once")
            values["new_audit_epoch"] = True
            index += 1
            continue
        if option == "--shadow":
            if values["shadow"]:
                raise ValueError("--shadow may be supplied only once")
            values["shadow"] = True
            index += 1
            continue
        name = option
        inline: str | None = None
        if "=" in option:
            name, inline = option.split("=", 1)
        if name not in scalar and name not in repeatable:
            raise ValueError(f"unknown option {option!r}")
        if inline is None:
            if index + 1 >= len(args):
                raise ValueError(f"{name} requires a value")
            inline = args[index + 1]
            index += 2
        else:
            index += 1
        value = inline.strip()
        if not value:
            raise ValueError(f"{name} requires a nonempty value")
        if name in repeatable:
            collection = values[repeatable[name]]
            assert isinstance(collection, list)
            if value in collection:
                raise ValueError(f"duplicate {name} selector {value!r}")
            collection.append(value)
            continue
        field = scalar[name]
        if values[field] is not None:
            raise ValueError(f"{name} may be supplied only once")
        if name in {
            "--token-limit",
            "--active-ms-limit",
            "--semantic-token-limit",
            "--semantic-active-ms-limit",
        }:
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a positive integer") from exc
            if parsed <= 0:
                raise ValueError(f"{name} must be a positive integer")
            values[field] = parsed
        else:
            values[field] = value
    target = values["target_layer"]
    if target not in {"L2", "L3", "L4"}:
        raise ValueError("--to requires one of L2, L3, or L4")
    sources = tuple(values["source_ids"])
    domains = tuple(values["domain_ids"])
    all_sources = bool(values["all_sources"])
    if all_sources and (sources or domains):
        raise ValueError("--all cannot be combined with --source or --domain")
    if not all_sources and not sources:
        raise ValueError("exactly one selector form is required: --all or --source")
    if domains and len(sources) != 1:
        raise ValueError("--domain requires exactly one --source")
    if target != "L3" and (
        values["semantic_token_limit"] is not None
        or values["semantic_active_ms_limit"] is not None
        or bool(values["new_audit_epoch"])
    ):
        raise ValueError("semantic limits and --new-audit-epoch are valid only for L3")
    if bool(values["shadow"]) and target != "L4":
        raise ValueError("--shadow is valid only for L4")
    if bool(values["shadow"]) and (
        values["token_limit"] is not None or values["active_ms_limit"] is not None
    ):
        raise ValueError("L4 --shadow cannot be combined with resource authorization")
    return _ReDeepenOptions(
        target_layer=target,
        all_sources=all_sources,
        source_ids=tuple(sorted(sources)),
        domain_ids=tuple(sorted(domains)),
        from_run=values["from_run"] if isinstance(values["from_run"], str) else None,
        token_limit=values["token_limit"] if isinstance(values["token_limit"], int) else None,
        active_ms_limit=(
            values["active_ms_limit"]
            if isinstance(values["active_ms_limit"], int)
            else None
        ),
        semantic_token_limit=(
            values["semantic_token_limit"]
            if isinstance(values["semantic_token_limit"], int)
            else None
        ),
        semantic_active_ms_limit=(
            values["semantic_active_ms_limit"]
            if isinstance(values["semantic_active_ms_limit"], int)
            else None
        ),
        new_audit_epoch=bool(values["new_audit_epoch"]),
        shadow=bool(values["shadow"]),
    )


def _resolve_re_v24_selection(
    workspace_partition: object,
    options: _ReDeepenOptions,
) -> object:
    from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
    from harness.re_v2.protocol_24.model import SelectionScopeV1

    if not isinstance(workspace_partition, WorkspacePartitionCatalogV1):
        raise ValueError("deepening requires an authenticated workspace partition")
    if not isinstance(options, _ReDeepenOptions):
        raise ValueError("deepening selection options are invalid")
    by_source = {
        source.source_id: source for source in workspace_partition.sources
    }
    if options.all_sources:
        if not by_source:
            raise ValueError("workspace partition contains no sources")
        return SelectionScopeV1(1, True, (), ())
    unknown_sources = tuple(
        source_id for source_id in options.source_ids if source_id not in by_source
    )
    if unknown_sources:
        raise ValueError(
            "unknown source selector(s): " + ", ".join(unknown_sources)
        )
    resolved_domains: list[str] = []
    if options.domain_ids:
        source = by_source[options.source_ids[0]]
        for selector in options.domain_ids:
            matches = tuple(
                domain
                for domain in source.domains
                if selector in {domain.domain_key, domain.presentation_domain_id}
            )
            if not matches:
                raise ValueError(
                    f"unknown domain selector {selector!r} for source {source.source_id!r}"
                )
            if len(matches) != 1:
                raise ValueError(
                    f"ambiguous domain selector {selector!r} for source {source.source_id!r}"
                )
            resolved_domains.append(matches[0].domain_key)
    if len(resolved_domains) != len(set(resolved_domains)):
        raise ValueError("domain selectors resolve to duplicate domains")
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=tuple(sorted(options.source_ids)),
        domain_keys=tuple(sorted(resolved_domains)),
    )


def semantic_request_id_for(
    lineage_root_run_id: str,
    lineage_root_manifest_hash: str,
    source_snapshot_id: str,
    selection: object,
    target_layer: str,
    artifact_policy_hash: str,
) -> str:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.schema import digest_value, safe_id
    from harness.re_v2.protocol_24.model import SelectionScopeV1

    if not isinstance(selection, SelectionScopeV1):
        raise ValueError("semantic request requires SelectionScopeV1")
    safe_id(lineage_root_run_id, "lineage_root_run_id")
    digest_value(lineage_root_manifest_hash, "lineage_root_manifest_hash")
    digest_value(source_snapshot_id, "source_snapshot_id")
    digest_value(artifact_policy_hash, "artifact_policy_hash")
    if target_layer != "L2":
        raise ValueError("semantic request target must be L2")
    return content_digest(
        {
            "artifact_policy_hash": artifact_policy_hash,
            "lineage_root_manifest_hash": lineage_root_manifest_hash,
            "lineage_root_run_id": lineage_root_run_id,
            "selection": selection.to_json_dict(),
            "source_snapshot_id": source_snapshot_id,
            "target_layer": target_layer,
        }
    )


@dataclass(frozen=True, slots=True)
class _Protocol24Creation:
    parent: object
    manifest: object
    inputs: object
    graph: object


def _prepare_re_v24_creation(
    workspace_root: Path,
    parent: object,
    options: _ReDeepenOptions,
) -> _Protocol24Creation:
    from dataclasses import replace

    import harness.re_v2.protocol_24.artifacts as artifacts_module
    import harness.re_v2.protocol_24.controller as controller_module
    import harness.re_v2.protocol_24.runtime as runtime_module
    import harness.re_v2.protocol_24.source_root_v2 as source_root_v2_module
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
    )
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
        build_deepening_executor_catalog,
    )
    from harness.re_v2.protocol_24.graph import build_protocol_24_graph
    from harness.re_v2.protocol_24.inputs import Protocol24InputSet
    from harness.re_v2.protocol_24.model import ParentLineageV1, RunManifestV3
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
    from harness.re_v2.protocol_24.source_root_v2 import (
        SOURCE_ROOT_V2_ADAPTER_ID,
        SOURCE_ROOT_V2_VERIFIER_ID,
        upgrade_source_root_executor_catalog_v2,
    )

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("deepening parent validation returned no closed authority")
    selection = _resolve_re_v24_selection(
        parent.inputs.workspace_partition,
        options,
    )
    try:
        artifact = ProsaicPromptLoader(workspace_root).load_subagent(
            DEEPENER_AGENT_ID
        )
    except ProsaicPromptLoadError as exc:
        raise ValueError(str(exc)) from exc
    if artifact is None:
        raise ValueError(
            "installed Prosaic agent echelon.re-deepener is missing; run "
            "`echelon workspace migrate-to-prosaic` before deepening RE"
        )
    deepener_bytes = canonical_prosaic_agent_bytes(artifact)
    deepener_hash = content_digest(deepener_bytes)
    implementation_digest = _re_v22_implementation_digest(
        artifacts_module,
        runtime_module,
        controller_module,
    )
    source_root_v2_digest = _re_v22_implementation_digest(
        source_root_v2_module,
        artifacts_module,
    )
    policy = build_deepening_v1_policy_catalog()
    executors = _bound_re_v2_executor_active_ms(
        upgrade_source_root_executor_catalog_v2(
            build_deepening_executor_catalog(
                parent.inputs.executor_contract,
                deepener_hash,
                implementation_digest,
            ),
            source_root_v2_digest,
        ),
        preserve_contract_hashes={
            entry.executor_contract_hash
            for entry in parent.inputs.executor_contract.entries
        },
    )
    compact = parent.inputs.executor_contract.entry_for("compact-baseline")
    (
        inherited_executors,
        inherited_calculators,
        inherited_normalizers,
    ) = _re_v24_inherited_in_process_authorities(
        parent.inputs.executor_contract
    )
    renderer = compact.request_renderer
    if renderer is None:
        raise ValueError("completed parent has no pinned shared provider renderer")
    baseline_agent = parent.inputs.immutable_objects.get(renderer.agent_contract_hash)
    if baseline_agent is None:
        raise ValueError("completed parent has no pinned Prosaic baseliner authority")
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            **inherited_executors,
            DEEPENING_IN_PROCESS_ADAPTER_ID: implementation_digest,
            SOURCE_ROOT_V2_ADAPTER_ID: source_root_v2_digest,
        },
        calculator_implementations={
            **dict(registry.calculator_implementations),
            **inherited_calculators,
        },
        normalizer_implementations={
            **dict(registry.normalizer_implementations),
            **inherited_normalizers,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: implementation_digest,
            SOURCE_ROOT_V2_VERIFIER_ID: source_root_v2_digest,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            DEEPENER_AGENT_ID: deepener_hash,
        },
    )
    mismatches = validate_installed_authorities(executors, registry)
    if mismatches:
        details = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise ValueError(f"protocol-2.4 installed authority mismatch: {details}")

    bundle, authority_objects = build_parent_authority_bundle(parent)
    parent_manifest_hash = content_digest(parent.manifest_bytes)
    if (
        isinstance(parent.manifest, RunManifestV5)
        and parent.manifest.target_layer == "L2"
    ):
        from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs

        lineage_manifest = load_protocol_26_inputs(
            parent.paths,
            parent.manifest,
        ).layer_execution_contract.layer_manifest
    else:
        lineage_manifest = parent.manifest
    if isinstance(lineage_manifest, RunManifestV3):
        lineage_root_run_id = lineage_manifest.parent_lineage.lineage_root_run_id
        lineage_root_manifest_hash = (
            lineage_manifest.parent_lineage.lineage_root_manifest_hash
        )
    else:
        lineage_root_run_id = parent.manifest.run_id
        lineage_root_manifest_hash = parent_manifest_hash
    lineage = ParentLineageV1(
        schema_version=1,
        direct_parent_run_id=parent.manifest.run_id,
        direct_parent_manifest_hash=parent_manifest_hash,
        direct_parent_terminal_event_hash=parent.events[-1].event_hash,
        lineage_root_run_id=lineage_root_run_id,
        lineage_root_manifest_hash=lineage_root_manifest_hash,
    )
    semantic_id = semantic_request_id_for(
        lineage.lineage_root_run_id,
        lineage.lineage_root_manifest_hash,
        parent.manifest.source_snapshot_id,
        selection,
        "L2",
        policy.identity,
    )
    manifest = RunManifestV3(
        schema_version=3,
        engine="re-v2",
        engine_protocol_version="2.4",
        # Allocation happens only while holding the workspace creation lock.
        run_id="re-pending-deepening",
        created_at=_re_v2_now(),
        source_snapshot_id=parent.manifest.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=parent.manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            parent.inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executors.identity,
            "executor-contract.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority.json",
        ),
        parent_lineage=lineage,
        requested_goals=("selective-deepening",),
        target_layer="L2",
        selection=selection,
        semantic_request_id=semantic_id,
        initial_budget_policy=BudgetPolicyV2(
            token_limit=options.token_limit or 5_000_000,
            active_ms_limit=options.active_ms_limit or 180 * 60_000,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=1,
            shared_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
    )
    immutable_objects = {
        **dict(parent.inputs.immutable_objects),
        **dict(authority_objects),
        deepener_hash: deepener_bytes,
    }
    inputs = Protocol24InputSet(
        workspace_partition=parent.inputs.workspace_partition,
        artifact_policy=policy,
        executor_contract=executors,
        immutable_objects=immutable_objects,
        parent_authority_bundle=bundle,
    )
    graph = build_protocol_24_graph(manifest, inputs, parent.accepted_parent)
    # Canonical construction here catches accidental non-JSON metadata before
    # the manifest-last publisher creates any child path.
    canonical_json_bytes(manifest.to_json_dict())
    return _Protocol24Creation(parent, manifest, inputs, graph)


@contextmanager
def _re_v24_creation_lock(workspace_root: Path):
    runs = workspace_root.resolve() / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(runs, flags)
    lock_fd: int | None = None
    try:
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        lock_flags |= getattr(os, "O_NOFOLLOW", 0)
        for attempt in range(3):
            try:
                lock_fd = os.open(
                    ".re-v24-create.lock",
                    lock_flags,
                    0o600,
                    dir_fd=root_fd,
                )
                break
            except FileNotFoundError:
                if attempt == 2:
                    raise
        if lock_fd is None:
            raise ValueError("cannot open RE deepening creation lock")
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("RE deepening creation lock is not a regular file")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(root_fd)


def _find_re_v24_semantic_child(
    workspace_root: Path,
    semantic_request_id: str,
    executor_contract_catalog_id: str,
) -> Path | None:
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_24.model import RunManifestV3
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    runs = workspace_root.resolve() / "runs"
    for candidate in sorted(runs.iterdir(), key=lambda path: path.name):
        if (
            not candidate.name.startswith("re-")
            or candidate.is_symlink()
            or not candidate.is_dir()
            or not (candidate / "v2" / "run.json").is_file()
        ):
            continue
        manifest = load_run_manifest(candidate)
        candidate_manifest = manifest
        if isinstance(manifest, RunManifestV5) and manifest.target_layer == "L2":
            protocol_26_inputs = load_protocol_26_inputs(
                ReV2Paths.for_run(candidate), manifest
            )
            candidate_manifest = (
                protocol_26_inputs.layer_execution_contract.layer_manifest
            )
        if (
            isinstance(candidate_manifest, RunManifestV3)
            and candidate_manifest.semantic_request_id == semantic_request_id
            and candidate_manifest.executor_contract_catalog.identity
            == executor_contract_catalog_id
        ):
            event_protocol = (
                protocol_26_events_for("L2")
                if isinstance(manifest, RunManifestV5)
                else PROTOCOL_24_EVENTS
            )
            events = EventStore(
                ReV2Paths.for_run(candidate),
                protocol=event_protocol,
            ).replay()
            if events and events[-1].type == "run_failed":
                continue
            return candidate
    return None


def _resolve_re_v24_parent_path(
    workspace_root: Path,
    from_run: str | None,
) -> Path:
    from harness.re_lifecycle import resolve_current_re_run
    from harness.re_v2.protocol_22.schema import safe_id

    if from_run is not None:
        safe_id(from_run, "from_run")
        return workspace_root.resolve() / "runs" / from_run
    current = resolve_current_re_run(workspace_root)
    if current is None:
        raise ValueError("no active RE parent; use --from-run RUN_ID")
    return current


def _run_re_v24_deepen(
    workspace_root: Path,
    options: _ReDeepenOptions,
    *,
    creation_fault_hook: Callable[[str], None] | None = None,
) -> Path:
    from harness.re_v2.protocol_24.adoption import (
        validate_parent_for_deepening,
    )
    from harness.re_v2.protocol_26.adoption import initialize_protocol_26_run_store
    from harness.re_v2.protocol_26.inputs import create_protocol_26_run_store
    from harness.re_v2.run_store import load_run_manifest

    workspace = workspace_root.resolve()
    parent_path = _resolve_re_v24_parent_path(workspace, options.from_run)
    # Clean/exact-source validation deliberately precedes every child mutation.
    parent = validate_parent_for_deepening(parent_path, workspace)
    request = _prepare_re_v24_creation(workspace, parent, options)
    created = False
    with _re_v24_creation_lock(workspace):
        existing = _find_re_v24_semantic_child(
            workspace,
            request.manifest.semantic_request_id,
            request.manifest.executor_contract_catalog.identity,
        )
        if existing is None:
            prepared = _prepare_re_v26_creation(
                workspace,
                target_layer="L2",
                parent_run=parent_path,
                goal="baseline",
                deepen_options=options,
                token_limit=options.token_limit,
                time_limit_minutes=(
                    options.active_ms_limit // 60_000
                    if options.active_ms_limit is not None
                    else None
                ),
            )
            run_dir = workspace / "runs" / prepared.manifest.run_id
            create_protocol_26_run_store(
                run_dir,
                prepared.manifest,
                prepared.inputs,
                fault_hook=creation_fault_hook,
            )
            _initialize_re_v24_child(
                run_dir,
                parent,
                creation_fault_hook=creation_fault_hook,
            )
            initialize_protocol_26_run_store(
                run_dir,
                fault_hook=creation_fault_hook,
            )
            created = True
        else:
            run_dir = existing
            _initialize_re_v24_child(
                run_dir,
                parent,
                creation_fault_hook=creation_fault_hook,
            )
            manifest = load_run_manifest(run_dir)
            from harness.re_v2.protocol_26.model import RunManifestV5

            if isinstance(manifest, RunManifestV5):
                initialize_protocol_26_run_store(
                    run_dir,
                    fault_hook=creation_fault_hook,
                )
        _activate_re_v2_run(workspace, run_dir.name)
        _re_v24_creation_fault(creation_fault_hook, "active_pointer_published")
    context = _re_v2_context(workspace, run_dir)
    if created:
        _run_re_v2_live(context)
    else:
        _continue_re_v24_semantic_child(context, options)
    return run_dir


def _run_or_report_re_v25_child(
    workspace: Path,
    run_dir: Path,
    *,
    execute: bool,
    report_existing: bool = True,
) -> None:
    """Execute a new child or report an exact immutable child without execution."""
    if execute:
        _run_re_v2_live(_re_v2_context(workspace, run_dir))
        return
    if not report_existing:
        return
    from harness.re_v2.status import render_v2_status

    print(render_v2_status(run_dir), end="")


def _run_re_v25_deepen(
    workspace_root: Path,
    options: _ReDeepenOptions,
    *,
    report_existing: bool = True,
    checkpoint_progress: Callable[[str, int, int], None] | None = None,
) -> Path:
    """Create or reuse an authenticated protocol-2.5 semantic child."""
    from harness.re_v2.protocol_24.adoption import validate_parent_for_deepening
    from harness.re_v2.protocol_25.lifecycle import (
        find_exact_protocol_25_child,
        initialize_protocol_25_child,
    )
    from harness.re_v2.protocol_26.adoption import initialize_protocol_26_run_store
    from harness.re_v2.protocol_26.inputs import create_protocol_26_run_store

    workspace = workspace_root.resolve()
    parent_path = _resolve_re_v24_parent_path(workspace, options.from_run)
    from harness.re_v2.protocol_25.model import RunManifestV4
    from harness.re_v2.run_store import load_run_manifest

    parent_manifest = (
        load_run_manifest(parent_path)
        if (parent_path / "v2" / "run.json").is_file()
        else None
    )
    if isinstance(parent_manifest, RunManifestV4):
        if not options.new_audit_epoch:
            raise ValueError(
                "terminal L3 parents require explicit --new-audit-epoch"
            )
        return _run_re_v25_next_epoch(workspace, parent_path, options)
    parent = validate_parent_for_deepening(parent_path, workspace)
    request = _prepare_re_v25_creation(workspace, parent, options)
    created = False
    with _re_v24_creation_lock(workspace):
        existing = find_exact_protocol_25_child(
            workspace,
            request.manifest.semantic_request_id,
        )
        if existing is None:
            prepared = _prepare_re_v26_creation(
                workspace,
                target_layer="L3",
                parent_run=parent_path,
                goal="baseline",
                deepen_options=options,
                token_limit=options.token_limit,
                time_limit_minutes=(
                    options.active_ms_limit // 60_000
                    if options.active_ms_limit is not None
                    else None
                ),
                checkpoint_progress=checkpoint_progress,
            )
            run_dir = workspace / "runs" / prepared.manifest.run_id
            create_protocol_26_run_store(
                run_dir,
                prepared.manifest,
                prepared.inputs,
            )
            initialize_protocol_25_child(run_dir, parent)
            initialize_protocol_26_run_store(run_dir)
            created = True
        else:
            run_dir = existing
            initialize_protocol_25_child(run_dir, parent)
            existing_manifest = load_run_manifest(run_dir)
            from harness.re_v2.protocol_26.model import RunManifestV5

            if isinstance(existing_manifest, RunManifestV5):
                initialize_protocol_26_run_store(run_dir)
        _activate_re_v2_run(workspace, run_dir.name)
    _run_or_report_re_v25_child(
        workspace,
        run_dir,
        execute=created,
        report_existing=report_existing,
    )
    return run_dir


def _re_v28_analysis_parent_path(workspace: Path, input_run: Path) -> Path:
    """Traverse synthesis envelopes to the immutable analysis run."""
    from harness.re_v2.protocol_27.model import RunManifestV6
    from harness.re_v2.run_store import load_run_manifest

    current = input_run.resolve()
    seen: set[str] = set()
    while True:
        manifest = load_run_manifest(current)
        if manifest.run_id in seen:
            raise ValueError("L4 input lineage contains a cycle")
        seen.add(manifest.run_id)
        if not isinstance(manifest, RunManifestV6):
            return current
        current = workspace / "runs" / manifest.parent_run_id
        if current.is_symlink() or not current.is_dir():
            raise ValueError("synthesis analysis parent is unavailable")


def _re_v28_orchestration_input_path(workspace: Path, input_run: Path) -> Path:
    """Resolve a completed L4 anchor to its authenticated orchestration input."""
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_28.model import (
        ExhaustiveRunManifestV7,
        L4ClosureRunManifestV7,
    )
    from harness.re_v2.protocol_28.orchestration import (
        load_orchestration,
        recover_orchestration,
    )
    from harness.re_v2.run_store import load_run_manifest

    manifest = load_run_manifest(input_run)
    if not isinstance(
        manifest, (ExhaustiveRunManifestV7, L4ClosureRunManifestV7)
    ):
        return input_run
    namespace = workspace.resolve() / "runs" / ".re-v2-orchestrations"
    if not namespace.is_dir() or namespace.is_symlink():
        raise ValueError(
            "L4 input has no authenticated orchestration origin; "
            "use --from-run with its lower analysis input"
        )
    manifest_hash = content_digest(canonical_json_bytes(manifest.to_json_dict()))
    matches: list[tuple[object, object]] = []
    for path in sorted(namespace.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_dir():
            continue
        intent = load_orchestration(path)
        projection = recover_orchestration(path)
        expected_hash = (
            projection.l4_manifest_hash
            if manifest.run_id == projection.l4_run_id
            else projection.closure_manifest_hash
            if manifest.run_id == projection.closure_run_id
            else None
        )
        if expected_hash is None:
            continue
        if expected_hash != manifest_hash:
            raise ValueError("L4 orchestration child manifest binding is invalid")
        matches.append((intent, projection))
    if len(matches) != 1:
        raise ValueError(
            "L4 input has no unique authenticated orchestration origin; "
            "use --from-run with its lower analysis input"
        )
    intent, _projection = matches[0]
    origin = workspace.resolve() / "runs" / intent.request.input_run_id
    if origin.is_symlink() or not origin.is_dir():
        raise ValueError("L4 orchestration analysis input is unsafe or missing")
    origin_manifest = load_run_manifest(origin)
    origin_hash = content_digest(
        canonical_json_bytes(origin_manifest.to_json_dict())
    )
    if origin_hash != intent.request.input_manifest_hash:
        raise ValueError("L4 orchestration analysis input binding is invalid")
    return origin


def _re_v28_event_boundary(context: object) -> object:
    store = getattr(context, "events", None)
    if store is None:
        store = getattr(context, "event_store", None)
    if store is None or not callable(getattr(store, "replay", None)):
        raise ValueError("L4 input run has no authenticated event store")
    events = store.replay()
    if not events or getattr(events[-1], "type", None) not in {
        "run_completed",
        "run_failed",
        "run_finalized_partial",
    }:
        raise ValueError("L4 input run has no terminal boundary")
    return events[-1]


def _re_v28_l3_options(
    options: _ReDeepenOptions,
    parent_run: Path,
) -> _ReDeepenOptions:
    """Map an L4 request to the fixed-default automatic L3 prerequisite."""
    from dataclasses import replace

    return replace(
        options,
        target_layer="L3",
        from_run=parent_run.name,
        token_limit=None,
        active_ms_limit=None,
        semantic_token_limit=None,
        semantic_active_ms_limit=None,
        new_audit_epoch=False,
        shadow=False,
    )


def _re_v28_semantic_authority(
    workspace: Path,
    analysis_run: Path,
    options: _ReDeepenOptions,
) -> tuple[object, object, bytes, object]:
    """Return partition, semantic manifest, executor bytes, and optional prep."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_25.recovery import Protocol25RunContext

    context = _re_v2_context(workspace, analysis_run)
    if isinstance(context, Protocol25RunContext):
        manifest = context.semantic_graph.manifest
        return (
            context.semantic_inputs.workspace_partition,
            manifest,
            canonical_json_bytes(
                context.semantic_inputs.executor_contract.to_json_dict()
            ),
            None,
        )

    from harness.re_v2.protocol_24.adoption import validate_parent_for_deepening

    parent = validate_parent_for_deepening(analysis_run, workspace)
    l3_options = _re_v28_l3_options(options, analysis_run)
    prepared = _prepare_re_v25_creation(workspace, parent, l3_options)
    return (
        prepared.inputs.workspace_partition,
        prepared.manifest,
        canonical_json_bytes(prepared.inputs.executor_contract.to_json_dict()),
        prepared,
    )


def _re_v28_preparation_options(
    workspace: Path,
    resolved: object,
    options: _ReDeepenOptions,
    *,
    producer_agent_bytes: bytes,
    verifier_agent_bytes: bytes,
) -> object:
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_25.recovery import Protocol25RunContext
    from harness.re_v2.protocol_28.orchestration import ResolvedL4ParentV1
    from harness.re_v2.protocol_28.preparation import Protocol28PreparationOptions
    from harness.re_v2.run_store import load_run_manifest

    if not isinstance(resolved, ResolvedL4ParentV1) or resolved.selected_l3 is None:
        raise ValueError("L4 preparation requires eligible L3 authority")
    context = _re_v2_context(workspace, resolved.analysis_run_dir)
    if not isinstance(context, Protocol25RunContext):
        raise ValueError("L4 analysis parent has no protocol-2.5 authority")
    semantic_manifest = context.semantic_graph.manifest
    lineage = semantic_manifest.parent_lineage
    active_manifest = load_run_manifest(resolved.analysis_run_dir)
    return Protocol28PreparationOptions(
        run_id=_new_re_v2_run_id(workspace),
        created_at=_re_v2_now(),
        snapshot=_load_re_v2_snapshot(workspace, active_manifest),
        workspace_partition=context.semantic_inputs.workspace_partition,
        inherited_executor_contract_bytes=canonical_json_bytes(
            context.semantic_inputs.executor_contract.to_json_dict()
        ),
        lineage_root_run_id=lineage.lineage_root_run_id,
        lineage_root_manifest_hash=lineage.lineage_root_manifest_hash,
        authority_objects=resolved.authority_objects,
        token_limit=options.token_limit,
        active_ms_limit=options.active_ms_limit,
        producer_agent_bytes=producer_agent_bytes,
        verifier_agent_bytes=verifier_agent_bytes,
    )


def _re_v28_checkpoint_adoption(
    workspace: Path,
    inputs: object,
) -> tuple[object | None, frozenset[str], int]:
    """Select authenticated immediately-realizable V2 checkpoints read-only."""
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_28.checkpoint_cache import (
        load_checkpoint_cache_v2,
        select_checkpoints_v2,
    )
    from harness.re_v2.protocol_28.checkpoints import (
        L4CheckpointExpectationV1,
        Protocol28CheckpointError,
    )
    from harness.re_v2.protocol_28.lifecycle import Protocol28CheckpointAdoptionV1
    from harness.re_v2.protocol_28.planning import realize_slice
    from harness.re_v2.run_store import ReV2Paths

    try:
        index, manifests, _quarantine = load_checkpoint_cache_v2(workspace)
    except Protocol28CheckpointError:
        return None, frozenset(), 0
    plan = getattr(inputs, "exhaustive_plan")
    manifest = getattr(inputs, "manifest")
    policy = getattr(inputs, "exhaustive_policy")
    entries = tuple(
        entry for target in plan.target_plans for entry in target.entries
    )
    immediate = tuple(
        entry for entry in entries if not entry.planned_dependency_root_ids
    )
    deferred = tuple(entry for entry in entries if entry.planned_dependency_root_ids)
    expectations = tuple(
        L4CheckpointExpectationV1(
            1,
            realize_slice(entry, {}),
            entry,
            policy.identity,
            manifest.inherited_artifact_policy_catalog_id,
        )
        for entry in immediate
    )
    immediate_output_ids = {
        expectation.output_artifact_key_id for expectation in expectations
    }
    authority: dict[str, dict[str, bytes]] = {}
    for checkpoint in manifests.values():
        object_root = ReV2Paths.for_run(
            workspace / "runs" / checkpoint.origin_run_id
        ).objects
        if not object_root.is_dir() or object_root.is_symlink():
            continue
        store = ObjectStore(object_root)
        try:
            authority[checkpoint.identity] = {
                object_id: store.read_blob(object_id)
                for object_id in checkpoint.immutable_object_hashes
            }
        except Exception:
            continue
    selection = select_checkpoints_v2(
        expectations,
        tuple(
            checkpoint
            for checkpoint in manifests.values()
            if checkpoint.slice_spec.output_artifact_key_id in immediate_output_ids
        ),
        authority,
    )
    deferred_ids = {entry.identity for entry in deferred}
    conditional = frozenset(
        {
            checkpoint.slice_spec.output_artifact_key_id
            for checkpoint in manifests.values()
            if checkpoint.plan_entry.identity in deferred_ids
            and checkpoint.exhaustive_policy_id == policy.identity
            and checkpoint.artifact_policy_catalog_id
            == manifest.inherited_artifact_policy_catalog_id
            and checkpoint.identity in authority
        }
    )
    adoption = Protocol28CheckpointAdoptionV1(selection, manifests, authority)
    return adoption, conditional, len(index.entries)


def _render_re_v28_shadow(
    inputs: object,
    *,
    checkpoint_adoption: object | None,
    conditional_checkpoint_ids: frozenset[str],
    checkpoint_candidates: int,
) -> str:
    plan = getattr(inputs, "exhaustive_plan")
    entries = tuple(
        entry for target in plan.target_plans for entry in target.entries
    )
    immediately_realizable = sum(
        not entry.planned_dependency_root_ids for entry in entries
    )
    deferred = len(entries) - immediately_realizable
    selected_checkpoints = (
        len(checkpoint_adoption.selection.selected)
        if checkpoint_adoption is not None
        else 0
    )
    selected_ids = (
        {
            item.output_artifact_key_id
            for item in checkpoint_adoption.selection.selected
        }
        if checkpoint_adoption is not None
        else set()
    )
    from harness.re_v2.canonical import content_digest

    output_id = lambda entry: content_digest(  # noqa: E731
        {"plan_entry_id": entry.identity, "kind": "l4-evidence-slice"}
    )
    minimum_entries = tuple(
        entry
        for entry in entries
        if output_id(entry) not in selected_ids | set(conditional_checkpoint_ids)
    )
    maximum_entries = tuple(
        entry for entry in entries if output_id(entry) not in selected_ids
    )
    maximum_dispatches = len(maximum_entries) * 9
    minimum_dispatches = len(minimum_entries) * 2
    minimum_tokens = sum(entry.conservative_tokens * 2 for entry in minimum_entries)
    maximum_tokens = sum(entry.conservative_tokens * 9 for entry in maximum_entries)
    return (
        "RE V2 — PROTOCOL 2.8 SHADOW\n"
        f"targets: {len(plan.target_plans)}\n"
        f"entries: {len(entries)}\n"
        f"immediately realizable: {immediately_realizable}\n"
        f"deferred source-composition entries: {deferred}\n"
        f"checkpoint reuse: realized={selected_checkpoints} "
        f"conditional={len(conditional_checkpoint_ids)} "
        f"candidates={checkpoint_candidates}\n"
        f"dispatch interval: {minimum_dispatches}..{maximum_dispatches}\n"
        f"conservative token interval: {minimum_tokens}..{maximum_tokens}\n"
        "mutation: none\n"
    )


def _run_re_v28_deepen(
    workspace_root: Path,
    options: _ReDeepenOptions,
) -> object:
    """Create/reuse and advance one durable L3 -> L4 -> closure intent."""
    from harness.config import load_config
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_28.closure import prepare_l4_closure_inputs
    from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
    from harness.re_v2.protocol_28.orchestration import (
        DeepenOrchestrationRequestV1,
        Protocol28OrchestrationOptions,
        execute_deepen_orchestration,
        resolve_l4_parent,
    )
    from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
    from harness.re_v2.protocol_28.preparation import (
        load_protocol_28_role_bytes,
        prepare_protocol_28_request,
    )
    from harness.re_v2.run_store import load_run_manifest
    from harness.squad_provider import SquadCliProvider

    if options.target_layer != "L4":
        raise ValueError("protocol-2.8 deepening requires --to L4")
    scope_label = "all-scope" if options.all_sources else "selected-scope"
    print(
        f"[re] preparing L4 {scope_label} request; provider dispatch has not started",
        file=sys.stderr,
        flush=True,
    )
    workspace = workspace_root.resolve()
    selected_input = _resolve_re_v24_parent_path(workspace, options.from_run)
    if selected_input.is_symlink() or not selected_input.is_dir():
        raise ValueError("L4 input run is unsafe or missing")
    input_run = _re_v28_orchestration_input_path(workspace, selected_input)
    analysis_run = _re_v28_analysis_parent_path(workspace, input_run)
    partition, semantic_manifest, inherited_bytes, _prepared_l3 = (
        _re_v28_semantic_authority(workspace, analysis_run, options)
    )
    selection = _resolve_re_v24_selection(partition, options)
    resolved = resolve_l4_parent(workspace, input_run, selection)

    if options.shadow and resolved.prerequisite_required:
        print(
            "RE V2 — PROTOCOL 2.8 SHADOW\n"
            "status: L3 prerequisite required\n"
            f"analysis parent: {analysis_run.name}\n"
            f"L3 prerequisite request: {semantic_manifest.semantic_request_id}\n"
            "mutation: none\n"
        )
        return None

    producer_agent, verifier_agent = load_protocol_28_role_bytes(workspace)
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(inherited_bytes),
        producer_agent_contract_hash=content_digest(producer_agent),
        verifier_agent_contract_hash=content_digest(verifier_agent),
    )
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer_agent),
        verifier_contract_hash=content_digest(verifier_agent),
    )
    input_manifest = load_run_manifest(input_run)
    input_manifest_bytes = canonical_json_bytes(input_manifest.to_json_dict())
    terminal = _re_v28_event_boundary(_re_v2_context(workspace, input_run))
    request = DeepenOrchestrationRequestV1(
        1,
        input_manifest.run_id,
        content_digest(input_manifest_bytes),
        terminal.event_hash,
        input_manifest.source_snapshot_id,
        input_manifest.partition_manifest_id,
        selection,
        policy.identity,
        executors.identity,
        semantic_manifest.semantic_request_id,
    )

    def create_l4(parent, intent):  # type: ignore[no-untyped-def]
        prepared = _re_v28_preparation_options(
            workspace,
            parent,
            options,
            producer_agent_bytes=producer_agent,
            verifier_agent_bytes=verifier_agent,
        )
        assert parent.selected_l3 is not None
        return prepare_protocol_28_request(
            workspace, intent.request, parent.selected_l3, prepared
        )

    if options.shadow:
        if resolved.selected_l3 is None:
            raise ValueError("L4 shadow cannot resolve selected L3 authority")
        prepared = _re_v28_preparation_options(
            workspace,
            resolved,
            options,
            producer_agent_bytes=producer_agent,
            verifier_agent_bytes=verifier_agent,
        )
        preview = prepare_protocol_28_request(
            workspace,
            request,
            resolved.selected_l3,
            prepared,
        )
        adoption, conditional_ids, candidates = _re_v28_checkpoint_adoption(
            workspace, preview
        )
        print(
            _render_re_v28_shadow(
                preview,
                checkpoint_adoption=adoption,
                conditional_checkpoint_ids=conditional_ids,
                checkpoint_candidates=candidates,
            ),
            end="",
        )
        return preview

    def create_l3(root, parent_run, requested_selection):  # type: ignore[no-untyped-def]
        del requested_selection
        print(
            "[re] preparing automatic L3 prerequisite and reusable checkpoints",
            file=sys.stderr,
            flush=True,
        )

        def report_checkpoint_progress(
            stage: str,
            completed: int,
            total: int,
        ) -> None:
            if stage != "origin-reconstruction":
                return
            interval = max(1, total // 10)
            if completed not in {0, total} and completed % interval:
                return
            print(
                "[re] checkpoint reconstruction: "
                f"{completed}/{total} prior RE runs inspected",
                file=sys.stderr,
                flush=True,
            )

        return _run_re_v25_deepen(
            root,
            _re_v28_l3_options(options, Path(parent_run)),
            report_existing=False,
            checkpoint_progress=report_checkpoint_progress,
        )

    def create_closure(parent, l4_run):  # type: ignore[no-untyped-def]
        if parent.selected_l3 is None:
            raise ValueError("closure preparation lost selected L3 authority")
        return prepare_l4_closure_inputs(
            parent.selected_l3,
            l4_run,
            run_id=_new_re_v2_run_id(workspace),
            created_at=_re_v2_now(),
        )

    @contextmanager
    def show_l4_progress(l4_run: Path):
        from echelon.re_ui import re_progress_session
        from harness.re_v2.protocol_28.status import protocol_28_status_document

        with re_progress_session(l4_run, protocol_28_status_document(l4_run)):
            yield

    _installed_re_runtime_or_exit(workspace)
    config = load_config(workspace, squad_only=True)
    result = execute_deepen_orchestration(
        workspace,
        Protocol28OrchestrationOptions(
            from_run=input_run,
            selection=selection,
            request=request,
            l4_inputs_factory=create_l4,
            l3_prerequisite_factory=create_l3,
            closure_inputs_factory=create_closure,
            checkpoint_adoption_factory=lambda inputs: (
                _re_v28_checkpoint_adoption(workspace, inputs)[0]
            ),
            l4_progress_factory=show_l4_progress,
            token_limit=options.token_limit,
            active_ms_limit=options.active_ms_limit,
            clock=_re_v2_now,
        ),
        lambda: SquadCliProvider(config),
    )
    from harness.re_v2.protocol_28.orchestration import find_exact_orchestration
    from echelon.re_ui import print_re_status_card
    from harness.re_v2.protocol_28.status import (
        protocol_28_orchestration_status_document,
        protocol_28_status_document,
    )

    intent_path = find_exact_orchestration(workspace, result.request_id)
    if intent_path is None:
        raise ValueError("protocol-2.8 orchestration authority disappeared")
    final_run_id = result.closure_run_id or result.l4_run_id
    if final_run_id is None:
        orchestration_document = protocol_28_orchestration_status_document(
            intent_path
        )
        state = str(orchestration_document["state"])
        print_re_status_card(
            {
                **orchestration_document,
                "engine_protocol_version": "2.8",
                "run_id": str(orchestration_document["request_id"]),
                "status": (
                    "complete"
                    if state == "complete"
                    else "blocked"
                    if state == "blocked"
                    else "in_progress"
                ),
            }
        )
    else:
        print_re_status_card(
            protocol_28_status_document(
                workspace / "runs" / final_run_id, intent_path
            )
        )
    return result


def _run_re_v25_next_epoch(
    workspace: Path,
    parent_run: Path,
    options: _ReDeepenOptions,
) -> Path:
    """Create or reuse an explicit independent epoch from terminal L3 authority."""
    from dataclasses import replace

    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from harness.re_v2.protocol_25.lifecycle import (
        export_protocol_25_parent,
        find_exact_protocol_25_child,
        initialize_protocol_25_successor,
        prepare_next_audit_epoch,
    )
    from harness.re_v2.protocol_25.policies import (
        build_semantic_v1_policy_catalog,
        with_current_semantic_executor_capacities,
    )

    context = _re_v2_context(workspace, parent_run)
    exported = export_protocol_25_parent(context, mode="new-audit-epoch")
    requested_selection = _resolve_re_v24_selection(
        exported.inputs.workspace_partition,
        options,
    )
    if requested_selection != exported.manifest.selection:
        raise ValueError(
            "next audit epoch selection must exactly match the terminal L3 parent"
        )
    parent_manifest = exported.manifest
    prepared = prepare_next_audit_epoch(
        parent=exported.parent,
        parent_manifest=parent_manifest,
        parent_inputs=exported.inputs,
        accepted_parent=exported.accepted_parent,
        parent_objects=exported.immutable_objects,
        created_at=_re_v2_now(),
        token_limit=(
            options.token_limit
            if options.token_limit is not None
            else parent_manifest.initial_budget_policy.token_limit
        ),
        active_ms_limit=(
            options.active_ms_limit
            if options.active_ms_limit is not None
            else parent_manifest.initial_budget_policy.active_ms_limit
        ),
        semantic_token_limit=(
            options.semantic_token_limit
            if options.semantic_token_limit is not None
            else parent_manifest.semantic_closure_policy.token_limit
        ),
        semantic_active_ms_limit=(
            options.semantic_active_ms_limit
            if options.semantic_active_ms_limit is not None
            else parent_manifest.semantic_closure_policy.active_ms_limit
        ),
        successor_artifact_policy=build_semantic_v1_policy_catalog(),
        successor_executor_contract=with_current_semantic_executor_capacities(
            exported.inputs.executor_contract
        ),
    )
    created = False
    with _re_v24_creation_lock(workspace):
        existing = find_exact_protocol_25_child(
            workspace,
            prepared.manifest.semantic_request_id,
        )
        if existing is None:
            manifest = replace(
                prepared.manifest,
                run_id=_new_re_v2_run_id(workspace),
                created_at=_re_v2_now(),
            )
            run_dir = workspace / "runs" / manifest.run_id
            create_protocol_25_run_store(run_dir, manifest, prepared.inputs)
            initialize_protocol_25_successor(run_dir, exported)
            created = True
        else:
            run_dir = existing
            initialize_protocol_25_successor(run_dir, exported)
        _activate_re_v2_run(workspace, run_dir.name)
    _run_or_report_re_v25_child(workspace, run_dir, execute=created)
    return run_dir


def _run_re_v25_resume(
    workspace_root: Path,
    parent_run: Path,
    guidance_policy: object,
    token_limit: int | None,
    time_limit_minutes: int | None,
    semantic_token_limit: int | None = None,
    semantic_time_limit_minutes: int | None = None,
) -> Path:
    """Create or exactly reuse one immutable guided protocol-2.5 successor."""
    from harness.re_v2.protocol_25.guidance import GuidancePolicyV1

    workspace = workspace_root.resolve()
    parent_dir = parent_run.resolve()
    if not isinstance(guidance_policy, GuidancePolicyV1):
        raise ValueError("immutable guidance resume policy is invalid")
    create_successor = lambda blocked: _create_or_reuse_re_v25_guided_successor(
        workspace,
        blocked,
        guidance_policy,
        token_limit,
        time_limit_minutes,
        semantic_token_limit,
        semantic_time_limit_minutes,
    )
    if guidance_policy.kind == "banzai":
        from echelon.re_ui import print_re_status_card
        from harness.re_v2.protocol_25.convergence import run_banzai_resume
        from harness.re_v2.protocol_25.status import protocol_25_status_document

        result = run_banzai_resume(
            project_root=workspace,
            blocked_run_dir=parent_dir,
            create_or_reuse_successor=create_successor,
            execute_successor=lambda child: _run_re_v2_live(
                _re_v2_context(workspace, child)
            ),
        )
        run_dir = workspace / "runs" / result.run_id
        _activate_re_v2_run(workspace, result.run_id)
        document = protocol_25_status_document(run_dir)
        document["banzai"] = result.to_json_dict()
        print_re_status_card(document, title="RE BANZAI")
        return run_dir

    run_dir, created = create_successor(parent_dir)
    _run_or_report_re_v25_child(workspace, run_dir, execute=created)
    return run_dir


def _create_or_reuse_re_v25_guided_successor(
    workspace: Path,
    parent_dir: Path,
    guidance_policy: object,
    token_limit: int | None,
    time_limit_minutes: int | None,
    semantic_token_limit: int | None,
    semantic_time_limit_minutes: int | None,
) -> tuple[Path, bool]:
    """Create/reuse one guided child without deciding how it is executed."""
    from dataclasses import replace

    from harness.re_v2.protocol_25.guidance import GuidancePolicyV1
    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from harness.re_v2.protocol_25.lifecycle import (
        export_protocol_25_parent,
        find_exact_protocol_25_child,
        initialize_protocol_25_successor,
        prepare_guided_successor,
    )
    from harness.re_v2.protocol_25.policies import (
        build_semantic_v1_policy_catalog,
        with_current_semantic_executor_capacities,
    )

    if not isinstance(guidance_policy, GuidancePolicyV1):
        raise ValueError("immutable guidance resume policy is invalid")
    context = _re_v2_context(workspace, parent_dir)
    exported = export_protocol_25_parent(context)
    parent_manifest = exported.manifest
    prepared = prepare_guided_successor(
        parent=exported.parent,
        parent_manifest=parent_manifest,
        parent_inputs=exported.inputs,
        accepted_parent=exported.accepted_parent,
        parent_objects=exported.immutable_objects,
        guidance_policy=guidance_policy,
        created_at=_re_v2_now(),
        token_limit=(
            token_limit
            if token_limit is not None
            else parent_manifest.initial_budget_policy.token_limit
        ),
        active_ms_limit=(
            time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else parent_manifest.initial_budget_policy.active_ms_limit
        ),
        semantic_token_limit=(
            semantic_token_limit
            if semantic_token_limit is not None
            else parent_manifest.semantic_closure_policy.token_limit
        ),
        semantic_active_ms_limit=(
            semantic_time_limit_minutes * 60_000
            if semantic_time_limit_minutes is not None
            else parent_manifest.semantic_closure_policy.active_ms_limit
        ),
        successor_artifact_policy=build_semantic_v1_policy_catalog(),
        successor_executor_contract=with_current_semantic_executor_capacities(
            exported.inputs.executor_contract
        ),
    )
    created = False
    with _re_v24_creation_lock(workspace):
        existing = find_exact_protocol_25_child(
            workspace,
            prepared.manifest.semantic_request_id,
        )
        if existing is None:
            manifest = replace(
                prepared.manifest,
                run_id=_new_re_v2_run_id(workspace),
                created_at=_re_v2_now(),
            )
            run_dir = workspace / "runs" / manifest.run_id
            create_protocol_25_run_store(run_dir, manifest, prepared.inputs)
            initialize_protocol_25_successor(run_dir, exported)
            created = True
        else:
            run_dir = existing
            initialize_protocol_25_successor(run_dir, exported)
        _activate_re_v2_run(workspace, run_dir.name)
    return run_dir, created


def _prepare_re_v25_creation(
    workspace_root: Path,
    parent: object,
    options: _ReDeepenOptions,
) -> object:
    """Compose installed Prosaic authority, then delegate schema-4 preparation."""
    from dataclasses import replace

    import harness.re_v2.protocol_24.artifacts as l2_artifacts_module
    import harness.re_v2.protocol_24.controller as l2_controller_module
    import harness.re_v2.protocol_24.runtime as l2_runtime_module
    import harness.re_v2.protocol_24.source_root_v2 as l2_source_root_v2_module
    import harness.re_v2.protocol_25.artifacts as l3_artifacts_module
    import harness.re_v2.protocol_25.cli_provider as l3_cli_provider_module
    import harness.re_v2.protocol_25.controller as l3_controller_module
    import harness.re_v2.protocol_25.runtime as l3_runtime_module
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
        build_deepening_executor_catalog,
    )
    from harness.re_v2.protocol_24.source_root_v2 import (
        SOURCE_ROOT_V2_ADAPTER_ID,
        SOURCE_ROOT_V2_VERIFIER_ID,
        upgrade_source_root_executor_catalog_v2,
    )
    from harness.re_v2.protocol_25.lifecycle import prepare_new_audit_epoch
    from harness.re_v2.protocol_25.policies import (
        SEMANTIC_EXECUTOR_FAMILIES,
        SEMANTIC_RENDERER_ID,
        SemanticExecutorAuthorityV1,
        build_semantic_executor_catalog,
        build_semantic_v1_policy_catalog,
    )
    from harness.re_v2.protocol_25.runtime import semantic_response_schema

    if options.target_layer != "L3":
        raise ValueError("protocol-2.5 preparation requires --to L3")
    selection = _resolve_re_v24_selection(parent.inputs.workspace_partition, options)
    role_ids = (
        DEEPENER_AGENT_ID,
        "echelon.re-validator",
        "echelon.re-resolver",
    )
    role_bytes: dict[str, bytes] = {}
    loader = ProsaicPromptLoader(workspace_root)
    for role_id in role_ids:
        try:
            artifact = loader.load_subagent(role_id)
        except ProsaicPromptLoadError as exc:
            raise ValueError(str(exc)) from exc
        if artifact is None:
            raise ValueError(
                f"installed Prosaic agent {role_id} is missing; run "
                "`echelon workspace migrate-to-prosaic` before deepening RE"
            )
        role_bytes[role_id] = canonical_prosaic_agent_bytes(artifact)

    l2_implementation = _re_v22_implementation_digest(
        l2_artifacts_module,
        l2_runtime_module,
        l2_controller_module,
    )
    l2_source_root_v2_implementation = _re_v22_implementation_digest(
        l2_source_root_v2_module,
        l2_artifacts_module,
    )
    l2_executors = _bound_re_v2_executor_active_ms(
        upgrade_source_root_executor_catalog_v2(
            build_deepening_executor_catalog(
                parent.inputs.executor_contract,
                content_digest(role_bytes[DEEPENER_AGENT_ID]),
                l2_implementation,
            ),
            l2_source_root_v2_implementation,
        ),
        preserve_contract_hashes={
            entry.executor_contract_hash
            for entry in parent.inputs.executor_contract.entries
        },
    )
    l3_implementation = _re_v22_implementation_digest(
        l3_artifacts_module,
        l3_cli_provider_module,
        l3_runtime_module,
        l3_controller_module,
    )
    schema_kind_by_family = {
        "closure-recheck": "semantic-closure-assessment",
        "semantic-audit": "semantic-audit-findings",
        "semantic-resolution": "semantic-resolution-overlay",
        "source-composition-guard": "semantic-closure-assessment",
    }
    role_by_family = {
        "closure-recheck": "echelon.re-validator",
        "semantic-audit": "echelon.re-validator",
        "semantic-resolution": "echelon.re-resolver",
        "source-composition-guard": "echelon.re-validator",
    }
    schema_bytes = {
        kind: canonical_json_bytes(semantic_response_schema(kind))
        for kind in sorted(set(schema_kind_by_family.values()))
    }
    authorities = tuple(
        SemanticExecutorAuthorityV1(
            schema_version=1,
            producer_family=family,
            agent_contract_hash=content_digest(role_bytes[role_by_family[family]]),
            response_schema_kind=schema_kind_by_family[family],
            response_schema_hash=content_digest(schema_bytes[schema_kind_by_family[family]]),
            verifier_id=f"{family}-verifier-v1",
            verifier_implementation_digest=l3_implementation,
            result_contract_id=f"{family}-candidate-ready-v1",
        )
        for family in SEMANTIC_EXECUTOR_FAMILIES
    )
    executors = _bound_re_v2_executor_active_ms(
        build_semantic_executor_catalog(
            l2_executors,
            authorities,
            l3_implementation,
        ),
        preserve_contract_hashes={
            entry.executor_contract_hash for entry in l2_executors.entries
        },
    )
    (
        inherited_executors,
        inherited_calculators,
        inherited_normalizers,
    ) = _re_v24_inherited_in_process_authorities(
        parent.inputs.executor_contract
    )
    baseline = parent.inputs.executor_contract.entry_for("compact-baseline")
    renderer = baseline.request_renderer
    if renderer is None:
        raise ValueError("completed parent has no pinned shared provider renderer")
    baseline_agent = parent.inputs.immutable_objects.get(renderer.agent_contract_hash)
    if baseline_agent is None:
        raise ValueError("completed parent has no pinned Prosaic baseliner authority")
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            **inherited_executors,
            DEEPENING_IN_PROCESS_ADAPTER_ID: l2_implementation,
            SOURCE_ROOT_V2_ADAPTER_ID: l2_source_root_v2_implementation,
        },
        calculator_implementations={
            **dict(registry.calculator_implementations),
            **inherited_calculators,
        },
        normalizer_implementations={
            **dict(registry.normalizer_implementations),
            **inherited_normalizers,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: l2_implementation,
            SOURCE_ROOT_V2_VERIFIER_ID: l2_source_root_v2_implementation,
            **{
                authority.verifier_id: l3_implementation
                for authority in authorities
            },
        },
        renderer_implementations={
            **dict(registry.renderer_implementations),
            SEMANTIC_RENDERER_ID: l3_implementation,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            **{
                role_id: content_digest(payload)
                for role_id, payload in role_bytes.items()
            },
        },
        response_schemas={
            **dict(registry.response_schemas),
            **{
                kind: content_digest(payload)
                for kind, payload in schema_bytes.items()
            },
        },
    )
    mismatches = validate_installed_authorities(executors, registry)
    if mismatches:
        details = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise ValueError(f"protocol-2.5 installed authority mismatch: {details}")
    semantic_objects = {
        **{
            content_digest(payload): payload for payload in role_bytes.values()
        },
        **{
            content_digest(payload): payload for payload in schema_bytes.values()
        },
    }
    return prepare_new_audit_epoch(
        parent=parent,
        selection=selection,
        artifact_policy=build_semantic_v1_policy_catalog(),
        executor_contract=executors,
        semantic_objects=semantic_objects,
        created_at=_re_v2_now(),
        token_limit=options.token_limit or 5_000_000,
        active_ms_limit=options.active_ms_limit or 180 * 60_000,
        semantic_token_limit=options.semantic_token_limit or 1_000_000,
        semantic_active_ms_limit=(
            options.semantic_active_ms_limit or 30 * 60_000
        ),
        engine_protocol_version="2.5.1",
    )


def _initialize_re_v24_child(
    run_dir: Path,
    parent: object,
    *,
    creation_fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Idempotently bridge manifest publication to complete adoption authority."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
        import_parent_acceptance_closure,
    )
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_24.inputs import load_protocol_24_inputs
    from harness.re_v2.protocol_24.model import (
        AdoptedArtifactAuthorityV1,
        RunManifestV3,
    )
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("deepening child initialization requires validated parent")
    active_manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    if isinstance(active_manifest, RunManifestV5):
        if active_manifest.target_layer != "L2":
            raise ValueError("deepening child initialization requires target L2")
        protocol_26_inputs = load_protocol_26_inputs(paths, active_manifest)
        manifest = protocol_26_inputs.layer_execution_contract.layer_manifest
        if not isinstance(manifest, RunManifestV3):
            raise ValueError("protocol-2.6 L2 contract has no schema-3 manifest")
        inputs = protocol_26_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L2")
    elif isinstance(active_manifest, RunManifestV3):
        manifest = active_manifest
        inputs = load_protocol_24_inputs(paths, manifest)
        event_protocol = PROTOCOL_24_EVENTS
    else:
        raise ValueError("deepening child initialization requires schema 3 or 5")
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    events = EventStore(paths, protocol=event_protocol)
    if _re_v24_child_adoption_complete(
        active_manifest, inputs, objects, ledger, events
    ):
        return
    if manifest.parent_lineage.direct_parent_run_id != parent.manifest.run_id:
        raise ValueError(
            "incomplete deepening child requires its exact direct parent"
        )
    expected_bundle, _objects = build_parent_authority_bundle(parent)
    if inputs.parent_authority_bundle != expected_bundle:
        raise ValueError("existing deepening child parent authority does not match")

    import_parent_acceptance_closure(parent, objects, ledger)
    _re_v24_creation_fault(creation_fault_hook, "parent_closure_imported")

    replayed_events = events.replay()
    if not replayed_events:
        events.append(
            "run_created",
            {"run_manifest_id": active_manifest.run_manifest_id},
            occurred_at=active_manifest.created_at,
        )
        _re_v24_creation_fault(creation_fault_hook, "run_created")
        replayed_events = events.replay()
    elif (
        replayed_events[0].type != "run_created"
        or replayed_events[0].payload.get("run_manifest_id")
        != active_manifest.run_manifest_id
    ):
        raise ValueError("existing deepening child has invalid creation authority")

    adopted_by_key: dict[str, object] = {}
    for event in replayed_events:
        if event.type != "artifact_adopted":
            continue
        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            event.payload["adopted_artifact_authority"]
        )
        adopted_by_key[authority.artifact_key_id] = event
    replayed_ledger = ledger.replay()
    by_certification = {
        value.certification_receipt_id: value
        for value in inputs.parent_authority_bundle.artifacts
    }
    for certification_id, authority in sorted(by_certification.items()):
        work_item = replayed_ledger.certification_work_items.get(certification_id)
        if work_item is None:
            raise ValueError("imported parent work item is missing")
        existing = adopted_by_key.get(authority.artifact_key_id)
        payload = {
            "adopted_artifact_authority": authority.to_json_dict(),
            "parent_authority_bundle_hash": inputs.parent_authority_bundle.identity,
            "work_item_id": work_item.work_item_id,
        }
        if existing is not None:
            existing_authority = AdoptedArtifactAuthorityV1.from_json_dict(
                existing.payload["adopted_artifact_authority"]
            )
            if (
                existing_authority != authority
                or existing.payload.get("parent_authority_bundle_hash")
                != inputs.parent_authority_bundle.identity
                or existing.payload.get("work_item_id") != work_item.work_item_id
            ):
                raise ValueError("existing adoption event conflicts with parent authority")
            continue
        events.append("artifact_adopted", payload, occurred_at=_re_v2_now())
        _re_v24_creation_fault(
            creation_fault_hook,
            f"artifact_adopted:{authority.artifact_key_id}",
        )
    if not _re_v24_child_adoption_complete(
        active_manifest,
        inputs,
        objects,
        ledger,
        events,
    ):
        raise ValueError("deepening child adoption initialization is incomplete")


def _re_v24_child_adoption_complete(
    manifest: object,
    inputs: object,
    objects: object,
    ledger: object,
    events: object,
) -> bool:
    """Validate the complete imported authority without consulting the parent."""
    from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1

    replayed_events = events.replay()
    if not replayed_events:
        return False
    if (
        replayed_events[0].type != "run_created"
        or replayed_events[0].payload.get("run_manifest_id")
        != manifest.run_manifest_id
    ):
        raise ValueError("existing deepening child has invalid creation authority")
    adopted: dict[str, tuple[object, object]] = {}
    for event in replayed_events:
        if event.type != "artifact_adopted":
            continue
        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            event.payload["adopted_artifact_authority"]
        )
        adopted[authority.artifact_key_id] = (authority, event)
    expected = {
        authority.artifact_key_id: authority
        for authority in inputs.parent_authority_bundle.artifacts
    }
    if set(adopted) != set(expected):
        return False

    replayed_ledger = ledger.replay()
    for artifact_key_id, authority in expected.items():
        adopted_authority, event = adopted[artifact_key_id]
        if adopted_authority != authority:
            raise ValueError("existing adoption event conflicts with parent authority")
        acceptance = replayed_ledger.accepted_artifacts.get(artifact_key_id)
        certification = replayed_ledger.certifications.get(
            authority.certification_receipt_id
        )
        work_item = replayed_ledger.certification_work_items.get(
            authority.certification_receipt_id
        )
        if acceptance is None or certification is None or work_item is None:
            return False
        if (
            acceptance.identity != authority.artifact_acceptance_receipt_id
            or acceptance.artifact_hash != authority.artifact_hash
            or certification.identity != authority.certification_receipt_id
            or work_item.output_key.identity != artifact_key_id
            or event.payload.get("parent_authority_bundle_hash")
            != inputs.parent_authority_bundle.identity
            or event.payload.get("work_item_id") != work_item.work_item_id
        ):
            raise ValueError("imported child authority conflicts with parent bundle")
        if authority.candidate_assessment_id is not None and (
            authority.candidate_assessment_id
            not in replayed_ledger.candidate_assessments
        ):
            return False
        objects.read_blob(authority.artifact_hash)
    return True


def _re_v24_creation_fault(
    hook: Callable[[str], None] | None,
    boundary: str,
) -> None:
    if hook is None:
        return
    hook(boundary)


def _continue_re_v24_semantic_child(
    context: object,
    options: _ReDeepenOptions,
) -> None:
    from harness.re_v2.protocol_22.budget import evaluate_budget_v22
    from harness.re_v2.protocol_26.authority import resolve_run_authority

    if options.token_limit is None and options.active_ms_limit is None:
        _run_re_v2_live(context)
        return
    events = context.event_store.replay()
    if events and events[-1].type in {"run_completed", "run_failed"}:
        _run_re_v2_live(context)
        return
    if not _re_v2_is_paused(events):
        # A concurrent or crash-recovered child keeps its existing authority;
        # the shared controller will either progress it or expose a pause.
        _run_re_v2_live(context)
        return
    manifest = resolve_run_authority(context).layer_manifest
    budget = evaluate_budget_v22(
        manifest.initial_budget_policy,
        events,
        (),
        _re_v2_now(),
        event_protocol=context.event_store.protocol,
    )
    token_limit = (
        options.token_limit
        if options.token_limit is not None
        and budget.token_limit is not None
        and options.token_limit > budget.token_limit
        else None
    )
    active_ms_limit = (
        options.active_ms_limit
        if options.active_ms_limit is not None
        and budget.active_ms_limit is not None
        and options.active_ms_limit > budget.active_ms_limit
        else None
    )
    if token_limit is None and active_ms_limit is None:
        _run_re_v2_live(context)
        return
    _run_re_v22_continue(
        context,
        token_limit=token_limit,
        time_limit_minutes=None,
        active_ms_limit=active_ms_limit,
    )


def _cmd_re_deepen(args: list[str]) -> None:
    try:
        options = _parse_re_deepen_options(args)
        if options.target_layer == "L2":
            _run_re_v24_deepen(Path.cwd(), options)
        elif options.target_layer == "L3":
            _run_re_v25_deepen(Path.cwd(), options)
        else:
            _run_re_v28_deepen(Path.cwd(), options)
    except (RuntimeError, ValueError) as exc:
        from echelon.re_ui import print_re_error

        print_re_error("echelon re deepen", exc)
        raise SystemExit(2) from exc


def _cmd_re_continue(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError, resolve_current_re_run

    try:
        (
            lifecycle_args,
            semantic_token_limit,
            semantic_time_limit_minutes,
        ) = _extract_re_semantic_budget_options(args)
        _policy, re_max_inner, _reset, _no_reuse, _profile, token_limit, time_limit_minutes, positional = _parse_re_lifecycle_options(
            lifecycle_args,
            allow_policy=False,
            allow_reset=False,
            allow_budget_overrides=True,
        )
        project_root = Path.cwd()
        if len(positional) > 1:
            raise ValueError("usage: echelon re continue [<run-id>]")
        run_dir = (
            _resolve_named_re_run(project_root, positional[0])
            if positional
            else resolve_current_re_run(project_root)
        )
        if run_dir is not None and _detect_re_engine_for_cli(run_dir) == "v2":
            if re_max_inner is not None:
                raise ValueError(
                    "v2 has independent attempt budgets; this option is valid only for v1"
                )
            try:
                continuation_options = {
                    "token_limit": token_limit,
                    "time_limit_minutes": time_limit_minutes,
                }
                if semantic_token_limit is not None:
                    continuation_options["semantic_token_limit"] = semantic_token_limit
                if semantic_time_limit_minutes is not None:
                    continuation_options["semantic_time_limit_minutes"] = (
                        semantic_time_limit_minutes
                    )
                _run_re_v2_continue(run_dir, **continuation_options)
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            return
        if positional:
            raise ValueError(
                "an explicit RE run ID is supported only for RE v2 runs"
            )
        if semantic_token_limit is not None or semantic_time_limit_minutes is not None:
            raise ValueError(
                "semantic resource authorization is valid only for protocol 2.5"
            )
        _print_re_continue_summary(project_root, re_max_inner=re_max_inner)
        overrides: dict[str, int] = {}
        if token_limit is not None:
            overrides["hard_token_limit"] = token_limit
        if time_limit_minutes is not None:
            overrides["hard_active_minutes"] = time_limit_minutes
        result = _re_lifecycle_controller(project_root).continue_run(
            re_max_inner,
            **overrides,
        )
    except (ReLifecycleError, ValueError) as exc:
        from echelon.re_ui import print_re_error

        print_re_error("echelon re continue", exc)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_resume(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError, resolve_current_re_run

    try:
        options, re_max_inner = _parse_re_resume_options(args)
        project_root = Path.cwd()
        run_dir = resolve_current_re_run(project_root)
        if run_dir is not None and _detect_re_engine_for_cli(run_dir) == "v2":
            if re_max_inner is not None:
                raise ValueError(
                    "v2 has independent attempt budgets; this option is valid only for v1"
                )
            from harness.re_v2.protocol_25.model import RunManifestV4
            from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
            from harness.re_v2.protocol_26.model import RunManifestV5
            from harness.re_v2.run_store import ReV2Paths, load_run_manifest

            manifest = load_run_manifest(run_dir)
            semantic_manifest = manifest
            if isinstance(manifest, RunManifestV5) and manifest.target_layer == "L3":
                semantic_manifest = load_protocol_26_inputs(
                    ReV2Paths.for_run(run_dir),
                    manifest,
                ).layer_execution_contract.layer_manifest
            if not isinstance(semantic_manifest, RunManifestV4):
                raise ValueError(
                    "immutable guidance resume requires an L3 RE run"
                )
            from harness.re_v2.protocol_25.guidance import (
                banzai_guidance_policy,
                custom_guidance_policy,
                recommended_guidance_policy,
            )

            guidance_policy = (
                recommended_guidance_policy()
                if options.recommended
                else banzai_guidance_policy(semantic_manifest.run_manifest_id)
                if options.banzai
                else custom_guidance_policy(options.guidance or "")
            )
            _run_re_v25_resume(
                project_root,
                run_dir,
                guidance_policy,
                options.token_limit,
                options.time_limit_minutes,
                options.semantic_token_limit,
                options.semantic_time_limit_minutes,
            )
            return
        if options.recommended or options.banzai:
            raise ValueError(
                "--recommended and --banzai require an immutable RE v2 L3 run"
            )
        if (
            options.semantic_token_limit is not None
            or options.semantic_time_limit_minutes is not None
        ):
            raise ValueError(
                "semantic resource authorization requires an immutable RE v2 L3 run"
            )
        overrides: dict[str, int] = {}
        if options.token_limit is not None:
            overrides["hard_token_limit"] = options.token_limit
        if options.time_limit_minutes is not None:
            overrides["hard_active_minutes"] = options.time_limit_minutes
        result = _re_lifecycle_controller(project_root).resume(
            options.guidance or "",
            re_max_inner,
            **overrides,
        )
    except (ReLifecycleError, RuntimeError, ValueError) as exc:
        from echelon.re_ui import print_re_error

        print_re_error("echelon re resume", exc)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_finalize(args: list[str]) -> None:
    """Explicitly acknowledge debt and terminalize a blocked RE run as partial."""
    from harness.re_finalization import ReFinalizationError, finalize_partial_re_run
    from harness.re_v2.protocol_25.debt import Protocol25DebtError

    allow_partial = False
    positional: list[str] = []
    for arg in args:
        if arg == "--allow-partial":
            allow_partial = True
        elif arg.startswith("-"):
            print(f"echelon re finalize: unknown argument '{arg}'", file=sys.stderr)
            raise SystemExit(2)
        else:
            positional.append(arg)
    if not allow_partial:
        print(
            "echelon re finalize: --allow-partial is required; "
            "this transition accepts unresolved RE debt",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if len(positional) > 1:
        print(
            "Usage: echelon re finalize [<run-id>] --allow-partial",
            file=sys.stderr,
        )
        raise SystemExit(2)
    project_root = Path.cwd()
    try:
        from harness.re_lifecycle import resolve_current_re_run

        run_dir = (
            _resolve_named_re_run(project_root, positional[0])
            if positional
            else resolve_current_re_run(project_root)
        )
        if _detect_re_engine_for_cli(run_dir) == "v2":
            from echelon.re_ui import print_re_status_card
            from harness.re_v2.protocol_25.debt import (
                finalize_protocol_25_debt,
            )
            from harness.re_v2.protocol_25.model import RunManifestV4
            from harness.re_v2.protocol_25.status import protocol_25_status_document
            from harness.re_v2.protocol_26.model import RunManifestV5
            from harness.re_v2.run_store import load_run_manifest

            manifest = load_run_manifest(run_dir)
            is_l3 = isinstance(manifest, RunManifestV4) or (
                isinstance(manifest, RunManifestV5) and manifest.target_layer == "L3"
            )
            if not is_l3:
                raise Protocol25DebtError(
                    "immutable residual-debt finalization is supported only for L3"
                )
            acceptance = finalize_protocol_25_debt(
                project_root=project_root,
                run_dir=run_dir,
                require_banzai=True,
            )
            document = protocol_25_status_document(run_dir)
            if document.get("debt_manifest_hash") != acceptance.identity:
                raise Protocol25DebtError(
                    "finalized debt is absent from replayed status"
                )
            print_re_status_card(document, title="RE FINAL STATE")
            return
    except Protocol25DebtError as exc:
        print(f"echelon re finalize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (OSError, ValueError) as exc:
        print(f"echelon re finalize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        result = finalize_partial_re_run(
            project_root,
            run_id=positional[0] if positional else None,
        )
    except (ReFinalizationError, OSError, ValueError) as exc:
        print(f"echelon re finalize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    publish_command = f"echelon re publish {result.run_id} --allow-partial"
    print(
        f"RE run {result.run_id} finalized as partial; unresolved debt remains."
    )
    _banner(
        "RE FINAL STATE — PARTIAL",
        [
            ("run", result.run_id),
            ("status", "partial (debt accepted, not full quality)"),
            ("stopped because", result.blocked_reason),
            ("partial sources", ", ".join(result.partial_sources) or "workspace-level only"),
            ("semantic findings", str(result.semantic_failure_count)),
            (
                "workspace synthesis",
                "incomplete" if result.workspace_synthesis_incomplete else "present",
            ),
            ("debt manifest", str(result.debt_manifest)),
            ("next step", publish_command),
        ],
        subtitle="The run is terminal and publishable only with --allow-partial.",
    )


@dataclass(frozen=True, slots=True)
class _ReSynthesizeV2Options:
    from_run: str
    accepted_partial_sources: tuple[str, ...]
    token_limit: int | None
    active_ms_limit: int | None


def _parse_re_synthesize_v2_options(args: list[str]) -> _ReSynthesizeV2Options:
    values: dict[str, object] = {
        "from_run": None,
        "accepted_partial_sources": [],
        "token_limit": None,
        "active_ms_limit": None,
    }
    scalar = {
        "--from-run": "from_run",
        "--token-limit": "token_limit",
        "--active-ms-limit": "active_ms_limit",
    }
    repeatable = {"--accept-partial": "accepted_partial_sources"}
    index = 0
    while index < len(args):
        option = args[index]
        name, separator, inline = option.partition("=")
        if name not in scalar and name not in repeatable:
            raise ValueError(f"unknown option {option!r}")
        if not separator:
            if index + 1 >= len(args):
                raise ValueError(f"{name} requires a value")
            inline = args[index + 1]
            index += 2
        else:
            index += 1
        value = inline.strip()
        if not value:
            raise ValueError(f"{name} requires a nonempty value")
        if name in repeatable:
            selected = values[repeatable[name]]
            assert isinstance(selected, list)
            if value in selected:
                raise ValueError(f"duplicate {name} selector {value!r}")
            selected.append(value)
            continue
        field = scalar[name]
        if values[field] is not None:
            raise ValueError(f"{name} may be supplied only once")
        if name in {"--token-limit", "--active-ms-limit"}:
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a positive integer") from exc
            if parsed <= 0:
                raise ValueError(f"{name} must be a positive integer")
            values[field] = parsed
        else:
            values[field] = value
    if not isinstance(values["from_run"], str):
        raise ValueError("--from-run is required for RE v2 synthesis")
    selected = values["accepted_partial_sources"]
    assert isinstance(selected, list)
    return _ReSynthesizeV2Options(
        from_run=values["from_run"],
        accepted_partial_sources=tuple(sorted(selected)),
        token_limit=(values["token_limit"] if isinstance(values["token_limit"], int) else None),
        active_ms_limit=(
            values["active_ms_limit"]
            if isinstance(values["active_ms_limit"], int)
            else None
        ),
    )


def _cmd_re_synthesize_v2(args: list[str]) -> None:
    from harness.config import load_config
    from harness.re_v2.protocol_27.authority import Protocol27AuthorityError
    from harness.re_v2.protocol_27.lifecycle import (
        Protocol27LifecycleError,
        run_synthesis_child,
    )
    from harness.re_v2.protocol_27.status import render_protocol_27_status
    from harness.re_lifecycle import resolve_current_re_run
    from harness.squad_provider import SquadCliProvider

    try:
        project_root = Path.cwd()
        options = _parse_re_synthesize_v2_options(args)
        _installed_re_runtime_or_exit(project_root)
        config = load_config(project_root, squad_only=True)
        run_synthesis_child(
            project_root,
            options,
            lambda: SquadCliProvider(config),
        )
        run_dir = resolve_current_re_run(project_root)
        if run_dir is None:
            raise Protocol27LifecycleError(
                "protocol-2.7 synthesis did not activate its child"
            )
        print(render_protocol_27_status(run_dir), end="")
    except (OSError, Protocol27AuthorityError, Protocol27LifecycleError, ValueError) as exc:
        print(f"echelon re synthesize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cmd_re_synthesize(args: list[str]) -> None:
    """Regenerate only workspace synthesis from accepted partial source results."""
    if any(arg == "--from-run" or arg.startswith("--from-run=") for arg in args):
        _cmd_re_synthesize_v2(args)
        return
    from harness.config import load_config
    from harness.re_finalization import (
        ReFinalizationError,
        synthesize_partial_re_run,
    )
    from harness.squad_provider import SquadCliProvider

    allow_partial = False
    token_limit: int | None = None
    time_limit_minutes: int | None = None
    positional: list[str] = []
    index = 0
    try:
        while index < len(args):
            arg = args[index]
            if arg == "--allow-partial":
                allow_partial = True
                index += 1
            elif arg in {"--re-token-limit", "--re-time-limit-minutes"}:
                if index + 1 >= len(args):
                    raise ValueError(f"{arg} requires a positive integer")
                try:
                    value = int(args[index + 1])
                except ValueError as exc:
                    raise ValueError(f"{arg} requires a positive integer") from exc
                if value < 1:
                    raise ValueError(f"{arg} requires a positive integer")
                if arg == "--re-token-limit":
                    token_limit = value
                else:
                    time_limit_minutes = value
                index += 2
            elif arg.startswith("--re-token-limit="):
                token_limit = int(arg.split("=", 1)[1])
                index += 1
            elif arg.startswith("--re-time-limit-minutes="):
                time_limit_minutes = int(arg.split("=", 1)[1])
                index += 1
            elif arg.startswith("-"):
                raise ValueError(f"unknown argument {arg!r}")
            else:
                positional.append(arg)
                index += 1
        if not allow_partial:
            raise ValueError(
                "--allow-partial is required; synthesis will use sources with accepted debt"
            )
        if len(positional) > 1:
            raise ValueError(
                "usage: echelon re synthesize [<run-id>] --allow-partial "
                "[--re-token-limit <n>]"
            )
        project_root = Path.cwd()
        runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(
            project_root
        )
        config = load_config(project_root, squad_only=True)
        result = synthesize_partial_re_run(
            project_root,
            run_id=positional[0] if positional else None,
            provider=SquadCliProvider(config),
            extension_root=runtime_root,
            prosaic_subagents_dir=prosaic_subagents_dir,
            hard_token_limit=token_limit,
            hard_active_minutes=time_limit_minutes,
        )
    except (ReFinalizationError, OSError, ValueError) as exc:
        print(f"echelon re synthesize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    publish_command = f"echelon re publish {result.run_id} --allow-partial"
    print(f"Workspace synthesis completed for partial RE run {result.run_id}.")
    _banner(
        "RE WORKSPACE SYNTHESIS — COMPLETE",
        [
            ("run", result.run_id),
            ("source quality", "partial debt accepted"),
            ("workspace synthesis", "complete"),
            ("token usage", str(result.token_usage)),
            ("next step", publish_command),
        ],
        subtitle="Only workspace synthesis ran; source repair and semantic revalidation stayed closed.",
    )


def _cmd_re_publish(args: list[str]) -> None:
    """Publish one validated run into the canonical workspace RE registry."""
    import json
    import re

    from echelon.git_helpers import GitHelperError, run_git
    from harness.re_artifacts import ReArtifactCatalogError
    from harness.re_lock import (
        RePublicationActiveRun,
        RePublishLocked,
        RePublishRecoveryRequired,
    )
    from harness.re_migration import import_legacy_re_cache
    from harness.re_finalization import mark_re_run_published
    from harness.re_publication import RePublicationError, publish_re_run

    allow_partial = False
    commit = False
    positional: list[str] = []
    for arg in args:
        if arg == "--allow-partial":
            allow_partial = True
        elif arg == "--commit":
            commit = True
        elif arg.startswith("-"):
            print(f"echelon re publish: unknown argument '{arg}'", file=sys.stderr)
            raise SystemExit(1)
        else:
            positional.append(arg)

    if len(positional) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", positional[0]):
        print(
            "Usage: echelon re publish <run-id> [--allow-partial] [--commit]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    run_id = positional[0]
    if run_id in {".", ".."}:
        print(f"echelon re publish: unsafe run id '{run_id}'", file=sys.stderr)
        raise SystemExit(1)
    project_root = Path.cwd().resolve()
    run_dir = project_root / "runs" / run_id
    if not run_dir.is_dir():
        print(
            f"echelon re publish: run not found under runs/: {run_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        imported = import_legacy_re_cache(project_root)
        lifecycle_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        result = publish_re_run(
            project_root,
            run_dir,
            allow_partial=allow_partial,
            expected_generation=int(lifecycle_state.get("expected_generation") or 0),
            allow_same_run_republish=True,
        )
        mark_re_run_published(
            run_dir,
            status=result.status,
            generation=result.generation,
        )
        if commit:
            _commit_re_publication(project_root, result.generation, run_git)
    except (
        RePublicationError,
        ReArtifactCatalogError,
        RePublicationActiveRun,
        RePublishLocked,
        RePublishRecoveryRequired,
        GitHelperError,
        OSError,
        ValueError,
    ) as exc:
        print(f"echelon re publish: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Published RE generation {result.generation} ({result.status})")
    if result.changed_sources:
        print("Changed sources: " + ", ".join(result.changed_sources))
    if result.removed_sources:
        print("Removed sources: " + ", ".join(result.removed_sources))
    if imported:
        print(f"Imported {len(imported)} legacy RE cache entr{'y' if len(imported) == 1 else 'ies'}")
    if not commit:
        print("Git commit: not requested")


def _cmd_re_execute_run(args: list[str]) -> None:
    """Run active workspace RE phases under the deterministic controller."""
    import json
    import re

    from harness.re_controller import ReExtractionController
    from harness.squad_provider import SquadCliProvider

    if len(args) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", args[0]):
        print("Usage: echelon re execute-run <run-id>", file=sys.stderr)
        raise SystemExit(1)
    run_id = args[0]
    project_root = Path.cwd().resolve()
    current_path = project_root / "runs" / ".current"
    run_dir = project_root / "runs" / run_id
    if not run_dir.is_dir() or not current_path.is_file() or current_path.read_text().strip() != run_id:
        print(
            f"echelon re execute-run: {run_id!r} is not the active workspace run",
            file=sys.stderr,
        )
        raise SystemExit(1)
    runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(project_root)
    try:
        provider = SquadCliProvider(_load_cli_config(project_root))
        result = ReExtractionController(
            provider=provider,
            project_root=project_root,
            run_dir=run_dir,
            extension_root=runtime_root,
            prosaic_subagents_dir=prosaic_subagents_dir,
        ).run()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"echelon re execute-run: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    payload = {
        "run_id": run_id,
        "status": "complete" if result.completed else "blocked",
        "blocked_reason": result.blocked_reason,
    }
    print(json.dumps(payload, sort_keys=True))
    if not result.completed:
        raise SystemExit(1)


def _cmd_re_check_domain(args: list[str]) -> None:
    """Check one staged domain against the deterministic deep-spec contract."""
    import json
    import re

    from harness.re_planner import ReExecutionPlan
    from harness.re_quality_gate import validate_staged_re_domain_quality

    if len(args) != 3 or any(
        not re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in args
    ):
        print(
            "Usage: echelon re check-domain <run-id> <source-id> <domain-id>",
            file=sys.stderr,
        )
        raise SystemExit(1)
    run_id, source_id, domain_id = args
    project_root = Path.cwd().resolve()
    run_dir = project_root / "runs" / run_id
    plan_path = run_dir / "re" / "re-execution-plan.json"
    if not plan_path.is_file():
        print(
            f"echelon re check-domain: run not found under runs/: {run_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        plan = ReExecutionPlan.from_json_dict(
            json.loads(plan_path.read_text(encoding="utf-8"))
        )
        report = validate_staged_re_domain_quality(
            run_dir / "re", plan, source_id, domain_id
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"echelon re check-domain: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(report.to_json_dict(), sort_keys=True))
    if not report.passed:
        raise SystemExit(1)


def _commit_re_publication(project_root: Path, generation: int, run_git) -> None:
    """Commit exactly the durable published RE surface."""
    pre_staged = run_git(
        project_root,
        "diff",
        "--cached",
        "--name-only",
    ).stdout.splitlines()
    if pre_staged:
        raise ValueError(
            "cannot commit RE publication while other staged changes exist: "
            + ", ".join(pre_staged)
        )

    run_git(
        project_root,
        "add",
        "--",
        "re/.gitignore",
        "re/index.json",
        "re/sources",
        "re/workspace",
    )
    staged = run_git(
        project_root,
        "diff",
        "--cached",
        "--name-only",
    ).stdout.splitlines()
    forbidden = (
        "re/.cache/",
        "re/.staging/",
        "re/.locks/",
    )
    invalid = [
        path
        for path in staged
        if path.startswith(forbidden)
        or not (
            path in {"re/.gitignore", "re/index.json"}
            or path.startswith("re/sources/")
            or path.startswith("re/workspace/")
        )
    ]
    if invalid:
        raise ValueError(
            "refusing RE commit with non-durable staged paths: " + ", ".join(invalid)
        )
    if not staged:
        return
    run_git(
        project_root,
        "commit",
        "-m",
        f"docs(re): publish workspace reverse engineering generation {generation}",
    )


# ── spec subcommands ──────────────────────────────────────────────────────────



def _installed_extension_or_exit(project_root: Path) -> Path:
    runtime = project_root / ".echelon" / "runtime"
    if not (runtime / "workflow" / "definition.yaml").is_file():
        print(
            f"✗ Echelon runtime not installed: {runtime}\n"
            "  Run: echelon workspace migrate-to-prosaic",
            file=sys.stderr,
        )
        sys.exit(1)
    return runtime




def _installed_re_runtime_or_exit(project_root: Path) -> tuple[Path, Path | None]:
    """Return deployed RE runtime assets and Prosaic agents."""
    runtime = project_root / ".echelon" / "runtime"
    prose = project_root / ".echelon" / "prosaic" / "subagents"
    if (runtime / "workflow" / "definition.yaml").is_file() and prose.is_dir():
        return runtime, prose
    print(
        "✗ Echelon runtime not installed.\n"
        "  Run: echelon workspace migrate-to-prosaic\n"
            "  Or, for a new workspace: echelon workspace init",
        file=sys.stderr,
    )
    sys.exit(1)




































from harness.stacks import provisioning_statuses, resolve_stacks  # noqa: E402
from harness.stacks.errors import StackError  # noqa: E402
from echelon.stack_selection import (  # noqa: E402
    StackSelectionError,
    get_stack_selection,
)


def _load_stack_definitions_for_project(project_root: Path):
    from echelon.stack_service import load_stack_catalog

    return load_stack_catalog(project_root)


# ── Entry point

def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["help"]:
        args = ["--help"]
    if args[:1] in (["-v"], ["--version"]):
        print(f"echelon {CLI_VERSION}")
        return
    if args[:1] == ["version"]:
        print(f"echelon {CLI_VERSION}")
        return

    from click import ClickException
    from echelon.cli_app import run as run_typer_cli

    click_exceptions: tuple[type[BaseException], ...] = (ClickException,)
    try:
        from typer._click.exceptions import ClickException as TyperClickException

        click_exceptions = (ClickException, TyperClickException)
    except Exception:
        pass

    try:
        exit_code = run_typer_cli(args)
    except click_exceptions as exc:
        exc.show()
        sys.exit(exc.exit_code)
    if exit_code:
        sys.exit(exit_code)

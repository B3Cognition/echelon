"""Typed application-service boundary for Delivery commands."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from harness.gitops import copy_prosaic_runtime_tree, copy_runtime_tree
from harness.provider_capability import ProviderCapability
from harness.runtime_surface import prune_delivery_workflow_definition


@dataclass(frozen=True)
class LocalVerificationRequest:
    spec_id: str
    target_id: str | None = None
    engine: str = "auto"
    assume_yes: bool = False
    keep_on_failure: bool = False


@dataclass(frozen=True)
class LocalActionPlan:
    """The exact host-local action that an operator confirms before it runs."""

    spec_id: str
    target_id: str
    engine: str
    candidate_fingerprint: str
    planned_actions: tuple[str, ...]
    digest: str
    workspace_root: Path | None = field(default=None, repr=False)
    target_root: Path | None = field(default=None, repr=False)
    candidate: object | None = field(default=None, repr=False)


@dataclass(frozen=True)
class HarnessWorkspaceTarget:
    workspace_root: Path
    workspace_git_role: str
    source_root: Path
    source_id: str
    source_git_role: str


def _block_if_spec_task_targets_mismatch(
    spec_dir: Path,
    declared_targets: list[str],
    spec_id: str,
) -> None:
    """Fail before delivery spends tokens on tasks owned by other source repos."""
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file() or not declared_targets:
        return

    from harness.task_targets import validate_task_targets

    result = validate_task_targets(
        tasks_path.read_text(encoding="utf-8", errors="replace"),
        declared_targets=declared_targets,
    )
    if result.valid:
        return

    lines = [
        "✗ Task ownership does not match the spec delivery targets.",
        "",
        "  Delivery is stopping before launching a build agent.",
        "  declared: " + ", ".join(declared_targets),
    ]
    if result.missing_targets:
        lines.append("  missing targets: " + ", ".join(result.missing_targets))
    if result.unreferenced_targets:
        lines.append(
            "  unreferenced targets: " + ", ".join(result.unreferenced_targets)
        )
    if result.unowned_tasks:
        lines.append(
            "  tasks without explicit target= ownership: "
            + ", ".join(result.unowned_tasks)
        )
    if result.cross_target_tasks:
        rendered = ", ".join(
            f"{task_id} ({' + '.join(targets)})"
            for task_id, targets in result.cross_target_tasks.items()
        )
        lines.append("  tasks spanning multiple targets: " + rendered)
    if result.path_target_mismatches:
        rendered = ", ".join(
            f"{task_id} (target={declared}; paths={' + '.join(paths)})"
            for task_id, (declared, paths) in result.path_target_mismatches.items()
        )
        lines.append("  task target/path mismatches: " + rendered)

    lines.extend(
        [
            "",
            "  Every task must declare exactly one target=<source-path> from targets.yml.",
            "  File paths validate ownership but never infer or replace it.",
        ]
    )
    lines.append(
        "  Regenerate target-dependent plan/tasks artifacts from a correctly targeted spec run."
    )
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(2)


def initialize_delivery(
    project_root: Path,
    *,
    extra_args: Sequence[str] = (),
) -> None:
    import logging

    from echelon.cli import (
        _banner,
        _command_display,
        _project_echelon_config,
        _require_provider_capability,
        _workspace_git_preflight,
    )
    from echelon.workspace_service import (
        _assert_local_config_untracked,
        _ensure_local_config_ignored,
    )

    command_prefix = "echelon delivery init"
    args = list(extra_args)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args:
        print(
            f"✗ {command_prefix} no longer accepts a target repository.\n\n"
            "  Implementation targets are declared when Phase A begins:\n"
            "    echelon spec run <description> --target <source-path> "
            "[--target <source-path> ...]\n\n"
            f"  Then rerun: {command_prefix}",
            file=sys.stderr,
        )
        sys.exit(1)

    _require_provider_capability(
        command_prefix,
        ProviderCapability.BUILD,
        project_dir=project_root,
    )

    target_repo = "."
    base_dir = str(project_root)
    _workspace_git_preflight(
        project_root,
        command_name=_command_display(command_prefix, args),
    )
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in (
        "true",
        "1",
        "yes",
    )
    try:
        _assert_local_config_untracked(project_root)
    except ValueError as exc:
        print(f"✗ {command_prefix} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    from harness.init import InitError, init_harness

    try:
        config = init_harness(
            target_repo=target_repo,
            base_dir=base_dir,
            bind_mount_ack=bind_mount_ack,
        )
    except InitError as exc:
        print(f"✗ {command_prefix} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    _ensure_local_config_ignored(project_root)

    config_file = _project_echelon_config(project_root)
    from harness.paths import mirror_path as _mirror_path_fn

    mirror_dir = _mirror_path_fn(project_root)

    image_note = ""
    if config.base_image is None:
        try:
            import yaml as _yaml

            raw = _yaml.safe_load(config_file.read_text())
            harness_raw = raw.get("harness", raw)
            detected = harness_raw.get("detected_image", "ubuntu:22.04")
            source = harness_raw.get("detected_image_source", "fallback")
            if source == "fallback":
                image_note = (
                    "\n  ⚠  base_image not detected — using ubuntu:22.04 as fallback.\n"
                    f"     Set base_image in {config_file}\n"
                    "     once you know your stack (e.g. node:20, python:3.12-slim).\n"
                )
            else:
                image_note = (
                    f"\n  base_image    → {detected} (auto-detected: {source})\n"
                )
        except Exception:
            pass

    fields = [
        ("Config", str(config_file)),
        ("Mirror", str(mirror_dir)),
        ("Provider", config.provider),
        ("PR host", config.pr_host),
    ]
    if image_note.strip():
        fields.append(("Base image", image_note.strip()))
    fields.extend(_harness_init_detection_fields(config_file))
    fields.append(("Next step", _harness_init_next_step(config_file)))
    _banner("HARNESS INIT — COMPLETE", fields)


def prepare_target(project_root: Path, *, spec_id: str) -> None:
    from echelon.cli import _banner, _require_provider_capability
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_target_entries,
        write_target_delivery,
    )

    _require_provider_capability(
        "echelon delivery target",
        ProviderCapability.BUILD,
        project_dir=project_root,
    )
    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        print(
            f"✗ Spec {spec_id!r} not found (searched from {project_root})",
            file=sys.stderr,
        )
        sys.exit(1)

    targets = read_target_entries(spec_dir)
    if not targets:
        print(
            f"✗ Spec {spec_dir.name} has no delivery target.\n"
            "  Delivery will not infer or mutate targets. Regenerate the spec with "
            "echelon spec run <description> --target <source-path>.",
            file=sys.stderr,
        )
        sys.exit(1)

    _block_if_spec_task_targets_mismatch(
        spec_dir,
        [str(entry.get("path") or "").strip() for entry in targets],
        spec_dir.name,
    )

    spec_root = spec_dir.parent.parent
    fields: list[tuple[str, str]] = [("Spec", spec_dir.name)]
    for entry in targets:
        target_rel = str(entry.get("path") or "").strip()
        if not target_rel:
            continue
        target_path = Path(target_rel).expanduser()
        if not target_path.is_absolute():
            target_path = (spec_root / target_path).resolve()
        if not target_path.exists():
            print(
                f"✗ Target repo not found: {target_rel}\n"
                "  Restore the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target_path / ".git").exists():
            print(
                f"✗ Target is not a Git repo: {target_rel}\n"
                "  Initialize the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)

        delivery = _detect_target_verify_delivery(target_path, spec_dir.name)
        write_target_delivery(spec_dir, target_rel, delivery)
        fields.append(("Target", target_rel))
        fields.append(("Branch", str(entry.get("branch") or spec_dir.name)))
        verify = delivery.get("verify_command")
        if verify:
            fields.append(("Verify", str(verify)))
        else:
            reason = (
                delivery.get("verify_reason")
                or "no high-confidence verify command detected"
            )
            fields.append(("Verify", f"not configured - {reason}"))

    fields.append(("Metadata", str(spec_dir / "targets.yml")))
    fields.append(("Next", f"echelon delivery run {spec_dir.name} --mode=banzai"))
    _banner("DELIVERY TARGET", fields)


def _harness_verify_status(config_file: Path) -> tuple[str, str, str]:
    """Return (verify_command, detection_status, detection_reason)."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", "", ""

    if not isinstance(raw, dict):
        return "", "", ""
    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    return (
        str(raw.get("verify_command") or ""),
        str(harness_raw.get("verify_command_detection") or ""),
        str(harness_raw.get("verify_command_reason") or ""),
    )


def _harness_init_next_step(config_file: Path) -> str:
    """Return the init banner next step without suggesting an invalid delivery run."""
    verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    if verify_command:
        return 'echelon spec run "<feature>"\n  echelon delivery run <spec_id>'

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "set top-level verify_command before delivery build\n"
            f"  detection: {detail}\n"
            "  examples:\n"
            "    verify_command: pytest\n"
            "    verify_command: npm test\n"
            "    verify_command: go test ./...\n"
            "  then: echelon delivery continue <spec_id>  # if recovering a blocked run\n"
            "        echelon delivery run <spec_id>     # for a new build"
        )

    return (
        'echelon spec run "<feature>"\n'
        "  echelon delivery run <spec_id>\n"
        "  if verification blocks: echelon delivery init or set verify_command manually"
    )


def _harness_init_detection_fields(config_file: Path) -> list[tuple[str, str]]:
    """Summarize auto-detected harness commands for the init banner."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    fields: list[tuple[str, str]] = []
    verify_command = raw.get("verify_command")
    verify_detection = harness_raw.get("verify_command_detection")
    verify_reason = harness_raw.get("verify_command_reason")
    if verify_command:
        source = "auto-detected" if verify_detection == "high" else "configured"
        fields.append(("Verify", f"{verify_command} ({source})"))
    elif verify_detection or verify_reason:
        status = str(verify_detection or "none")
        detail = f"{status}: {verify_reason}" if verify_reason else status
        fields.append(("Verify", f"not configured - {detail}"))

    app_raw = harness_raw.get("app")
    app_detection = harness_raw.get("app_detection")
    app_reason = harness_raw.get("app_reason")
    if isinstance(app_raw, dict) and app_raw:
        mode = app_raw.get("mode", "manual")
        app_name = (
            app_raw.get("app")
            or app_raw.get("service")
            or app_raw.get("compose_file")
            or "app"
        )
        url = app_raw.get("url")
        source = "auto-detected" if app_detection == "high" else "configured"
        detail = f"{app_name} via {mode}"
        if url:
            detail += f" at {url}"
        fields.append(("App runtime", f"{detail} ({source})"))
    elif app_detection or app_reason:
        status = str(app_detection or "none")
        detail = f"{status}: {app_reason}" if app_reason else status
        fields.append(("App runtime", f"not configured - {detail}"))

    sandbox_raw = harness_raw.get("sandbox_suggestion")
    if isinstance(sandbox_raw, dict) and sandbox_raw:
        confidence = sandbox_raw.get("confidence", "unknown")
        score = sandbox_raw.get("confidence_score", 0.0)
        strategy = sandbox_raw.get(
            "suggested_strategy", "review sandbox suggestion"
        )
        approval = sandbox_raw.get(
            "human_approval_point", "review before execution"
        )
        fields.append(
            (
                "Sandbox",
                f"{confidence} ({float(score):.2f}) - {strategy} Approval: {approval}",
            )
        )
        fields.append(
            ("Sandbox report", str(config_file.with_name("sandbox-suggestion.md")))
        )

    return fields


def _format_missing_verify_command_resume_message(
    config_file: Path,
    spec_id: str,
) -> str:
    """Format actionable resume guidance when verify_command is still missing."""
    _verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    examples = (
        "    verify_command: swift test --package-path Packages/MyLib\n"
        "    verify_command: pytest\n"
        "    verify_command: npm test\n"
        "    verify_command: go test ./..."
    )

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "✗ verify_command is still not set in echelon-config.yml.\n\n"
            "  Auto-detection already ran and did not configure a command.\n"
            f"  detection: {detail}\n\n"
            f"  Add a top-level verify_command to {config_file}, for example:\n"
            f"{examples}\n\n"
            f"  Then re-run:  echelon delivery continue {spec_id}"
        )

    return (
        "✗ verify_command is still not set in echelon-config.yml.\n\n"
        "  Option 1 — auto-detect once:  echelon delivery init\n"
        "  Option 2 — manual:            add a top-level verify_command to echelon-config.yml:\n"
        f"{examples}\n\n"
        f"  Then re-run:  echelon delivery continue {spec_id}"
    )


def _run_git_quiet(
    args: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _clean_git_branch_name(line: str) -> str:
    return line.strip().removeprefix("*").strip()


def _target_feature_branch_candidates(target_repo: Path, spec_id: str) -> list[str]:
    if not (target_repo / ".git").exists():
        return []
    result = _run_git_quiet(
        ["branch", "--list", spec_id, f"{spec_id}-*"],
        cwd=target_repo,
    )
    if result.returncode != 0:
        return []
    branches: list[str] = []
    for line in result.stdout.splitlines():
        branch = _clean_git_branch_name(line)
        if branch and branch not in branches:
            branches.append(branch)
    return branches


def _detect_verify_result_from_git_ref(
    target_repo: Path,
    git_ref: str,
) -> object | None:
    import tempfile

    from harness.verify_detection import detect_verify_command

    rev = _run_git_quiet(
        ["rev-parse", "--verify", f"{git_ref}^{{commit}}"],
        cwd=target_repo,
    )
    if rev.returncode != 0:
        return None

    with tempfile.TemporaryDirectory(prefix="echelon-verify-detect-") as tmp:
        worktree = Path(tmp) / "worktree"
        added = _run_git_quiet(
            ["worktree", "add", "--detach", str(worktree), rev.stdout.strip()],
            cwd=target_repo,
        )
        if added.returncode != 0:
            return None
        try:
            detected = detect_verify_command(worktree)
            if detected.confidence == "high" and detected.command:
                return detected
            return None
        finally:
            _run_git_quiet(
                ["worktree", "remove", "--force", str(worktree)],
                cwd=target_repo,
            )
            _run_git_quiet(["worktree", "prune"], cwd=target_repo)


def _detect_verify_command_from_git_ref(
    target_repo: Path,
    git_ref: str,
) -> str | None:
    detected = _detect_verify_result_from_git_ref(target_repo, git_ref)
    command = getattr(detected, "command", None)
    return str(command) if command else None


def _detect_target_verify_delivery(
    target_repo: Path,
    spec_id: str,
) -> dict[str, object]:
    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    source = "target_checkout"
    if detected.confidence != "high" or not detected.command:
        for branch in _target_feature_branch_candidates(target_repo, spec_id):
            branch_detected = _detect_verify_result_from_git_ref(target_repo, branch)
            if branch_detected is not None:
                detected = branch_detected  # type: ignore[assignment]
                source = f"branch:{branch}"
                break

    result: dict[str, object] = {
        "verify_detection": str(getattr(detected, "confidence", "none")),
        "verify_source": source,
    }
    command = getattr(detected, "command", None)
    if command:
        result["verify_command"] = str(command)
    evidence = getattr(detected, "evidence", None)
    if isinstance(evidence, list) and evidence:
        result["verify_evidence"] = [str(item) for item in evidence]
    reason = getattr(detected, "reason", None)
    if reason:
        result["verify_reason"] = str(reason)
    return result


def _apply_target_verify_command_detection(
    config: object,
    *,
    target_repo: Path | None,
    spec_id: str,
) -> None:
    """Populate runtime verify_command from the actual delivery target."""
    if getattr(config, "verify_command", None) or target_repo is None:
        return
    if not target_repo.exists():
        return

    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    if detected.confidence == "high" and detected.command:
        config.verify_command = detected.command
        print(
            f"Detected verify_command from delivery target: {detected.command}",
            file=sys.stderr,
        )
        return

    for branch in _target_feature_branch_candidates(target_repo, spec_id):
        command = _detect_verify_command_from_git_ref(target_repo, branch)
        if command:
            config.verify_command = command
            print(
                f"Detected verify_command from delivery target branch {branch}: {command}",
                file=sys.stderr,
            )
            return


def _sync_polyrepo_runtime_extension(
    polyrepo_root: Path,
    harness_base_dir: Path,
) -> None:
    """Copy deployed Prosaic and runtime bundles into a target harness base."""
    prose_source = polyrepo_root / ".echelon" / "prosaic"
    runtime_source = polyrepo_root / ".echelon" / "runtime"
    prose_dest = harness_base_dir / ".echelon" / "prosaic"
    runtime_dest = harness_base_dir / ".echelon" / "runtime"
    required = (
        prose_source / "commands",
        prose_source / "subagents",
        runtime_source / "workflow" / "definition.yaml",
    )
    if not all(path.exists() for path in required):
        print(
            "✗ Echelon Prosaic/runtime bundle is not installed in polyrepo root.\n"
            f"  Expected: {prose_source} and {runtime_source}\n"
            "  Fix: run 'echelon workspace migrate-to-prosaic' from the polyrepo root.",
            file=sys.stderr,
        )
        sys.exit(1)
    copy_prosaic_runtime_tree(prose_source, prose_dest)
    copy_runtime_tree(runtime_source, runtime_dest)
    prune_delivery_workflow_definition(runtime_dest / "workflow" / "definition.yaml")


def _target_candidate_lines(candidates: list[object]) -> str:
    lines: list[str] = []
    for candidate in candidates:
        repo = str(getattr(candidate, "repo", ""))
        evidence = [str(item) for item in getattr(candidate, "evidence", [])]
        source_path = None
        for item in evidence:
            prefix = "workspace source path `"
            if item.startswith(prefix) and item.endswith("`"):
                source_path = item[len(prefix) : -1]
                break
        if source_path and source_path != repo:
            lines.append(f"  - {repo} (path: {source_path})")
        elif repo:
            lines.append(f"  - {repo}")
    return "\n".join(lines)


def _source_dispatch_metadata(
    *,
    target: Path,
    polyrepo_root: Path,
    source_id: str | None,
) -> dict[str, object]:
    resolved_target = target.resolve()
    resolved_workspace = polyrepo_root.resolve()
    resolved_source_id = source_id or (
        "." if resolved_target == resolved_workspace else target.name
    )
    workspace_git_role = (
        "source"
        if resolved_target == resolved_workspace and resolved_source_id == "."
        else "orchestration"
    )
    return {
        "workspace_root": resolved_workspace,
        "workspace_git_role": workspace_git_role,
        "source_ids": {str(resolved_target): resolved_source_id},
        "source_git_roles": {str(resolved_target): "source"},
    }


def _resolve_harness_workspace_target(
    project_root: Path,
    explicit_target: str | None,
    *,
    spec_dir: Path | None = None,
    spec_id: str | None = None,
    rerun_command: str | None = None,
) -> HarnessWorkspaceTarget:
    from echelon.target_detection import detect_target
    from echelon.workspace_model import SourceRoot, discover_workspace

    manifest = discover_workspace(project_root)
    if explicit_target == ".":
        return HarnessWorkspaceTarget(
            workspace_root=manifest.workspace.root,
            workspace_git_role="source",
            source_root=manifest.workspace.root,
            source_id=".",
            source_git_role="source",
        )

    result = detect_target(
        spec_dir=spec_dir or project_root,
        polyrepo_root=project_root,
        workspace_manifest=manifest,
        explicit_target=explicit_target,
    )

    def _candidate_lines() -> str:
        return _target_candidate_lines(result.candidates)

    command_label = (
        "delivery"
        if (rerun_command or "").startswith("echelon delivery ")
        else "harness"
    )
    new_repo_hint = (
        "\n\n"
        "  For a new implementation repo:\n"
        "    echelon spec run <description> --target sources/<new-repo> --init"
    )

    if result.decision == "no_source_roots":
        print(
            "✗ No source roots found; harness build needs at least one implementation source root.\n\n"
            "  Add or checkout the source repo(s), or add source project markers to this workspace."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "multiple_source_roots_need_target":
        print(
            f"✗ Multiple source roots found; choose one before running {command_label}.\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: start Phase A with repeatable "
            "'echelon spec run <description> --target <source-path>' options."
            + new_repo_hint
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "invalid_target":
        configured = (
            f"\n  Configured target: {explicit_target}" if explicit_target else ""
        )
        print(
            "✗ Configured implementation target does not match a workspace source root.\n"
            f"{configured}\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: regenerate with 'echelon spec run <description> "
            "--target <source-path>'.\n"
            "       For a new repo, add --init."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not result.recommended_target:
        print(
            "✗ No implementation target configured and target detection was ambiguous.\n"
            "  Fix: start Phase A with 'echelon spec run <description> "
            "--target <source-path>'.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    source_root = (
        manifest.workspace.root
        if result.recommended_target == "."
        else (manifest.workspace.root / result.recommended_target).resolve()
    )
    source: SourceRoot | None = None
    for candidate in manifest.sources:
        candidate_root = (
            manifest.workspace.root
            if candidate.path == "."
            else (manifest.workspace.root / candidate.path).resolve()
        )
        if candidate_root == source_root:
            source = candidate
            break
    if source is None:
        print(
            "✗ Recommended implementation target does not match a workspace source root.\n"
            f"  Target: {result.recommended_target}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return HarnessWorkspaceTarget(
        workspace_root=manifest.workspace.root,
        workspace_git_role=manifest.workspace.git_role,
        source_root=source_root,
        source_id=source.id,
        source_git_role=source.git_role,
    )


def _workspace_target_dispatch_metadata(
    target: HarnessWorkspaceTarget,
) -> dict[str, object]:
    return {
        "workspace_root": target.workspace_root,
        "workspace_git_role": target.workspace_git_role,
        "source_ids": {str(target.source_root.resolve()): target.source_id},
        "source_git_roles": {
            str(target.source_root.resolve()): target.source_git_role
        },
    }


def _local_delivery_workspace_root(project_dir: Path) -> Path:
    configured = os.environ.get("ECHELON_POLYREPO_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else Path(project_dir)
    if root.is_symlink():
        raise ValueError("local verification workspace root is symlinked")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("local verification workspace root is unavailable") from exc
    if not root.is_dir():
        raise ValueError("local verification workspace root is unavailable")
    return root


def _resolve_local_delivery_target(
    project_dir: Path,
    spec_id: str,
    requested_target: str | None,
) -> tuple[Path, Path, str, str]:
    """Resolve one declared target; local verification never guesses a target."""
    from harness.spec_frontmatter import find_spec_dir, read_target_entries

    workspace = _local_delivery_workspace_root(project_dir)
    spec_dir = find_spec_dir(spec_id, workspace)
    if spec_dir is None:
        raise ValueError(f"spec {spec_id!r} was not found in this workspace")
    entries = read_target_entries(spec_dir)
    if not entries:
        raise ValueError("spec has no declared delivery target")
    selector = (requested_target or "").strip()
    matches = []
    for entry in entries:
        entry_id = str(entry.get("id") or "").strip()
        path_value = str(entry.get("path") or "").strip()
        if not path_value:
            continue
        if not selector or selector in {entry_id, path_value, Path(path_value).name}:
            matches.append((entry_id, path_value))
    if len(matches) != 1:
        if selector:
            raise ValueError(
                "--target must identify exactly one declared delivery target"
            )
        raise ValueError(
            "spec has multiple delivery targets; rerun with --target <target-id>"
        )
    target_id, target_value = matches[0]
    target = Path(target_value).expanduser()
    if not target.is_absolute():
        target = workspace / target
    if target.is_symlink():
        raise ValueError("local verification target is symlinked")
    try:
        target = target.resolve(strict=True)
    except OSError as exc:
        raise ValueError("local verification target is unavailable") from exc
    if not target.is_dir():
        raise ValueError("local verification target is unavailable")
    return workspace, target, target_id or target.name, spec_dir.name


def _select_local_engine(engine: str) -> str:
    requested = engine.strip().lower()
    if requested not in {"auto", "docker", "podman"}:
        raise ValueError("--engine must be auto, docker, or podman")
    if requested != "auto":
        return requested
    if shutil.which("docker"):
        return "docker"
    if shutil.which("podman"):
        return "podman"
    raise ValueError(
        "no supported local engine found; install Docker Desktop or Podman"
    )


def _local_candidate_fingerprint(candidate: object) -> str:
    fields = (
        "product_fingerprint",
        "contract_hash",
        "stack_hash",
        "observer_plan_hash",
        "sandbox_receipt_sha256",
    )
    payload = {name: str(getattr(candidate, name, "")) for name in fields}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_local_action_plan(
    project_dir: Path,
    spec_id: str,
    target_id: str | None,
    engine: str,
    *,
    build_id: str | None = None,
) -> LocalActionPlan:
    """Resolve immutable sandbox evidence before any host resource is created."""
    from harness.local_runner_candidate import (
        LocalCandidateRequest,
        resolve_effective_local_candidate,
    )

    workspace, target, resolved_target_id, resolved_spec_id = (
        _resolve_local_delivery_target(project_dir, spec_id, target_id)
    )
    candidate = resolve_effective_local_candidate(
        LocalCandidateRequest(
            workspace_root=workspace,
            target_root=target,
            spec_id=resolved_spec_id,
            target_id=resolved_target_id,
            build_id=build_id,
        )
    )
    selected_engine = _select_local_engine(engine)
    actions = (
        "materialize the sandbox-approved candidate in a managed detached worktree",
        "start a run-ID-labelled PostgreSQL container on a generated loopback port",
        "run the declared lifecycle in a scrubbed, run-local host environment",
        "observe the browser, restart persistence, and PostgreSQL boundary independently",
        "record a redacted immutable attestation and remove only journalled resources",
    )
    fingerprint = _local_candidate_fingerprint(candidate)
    digest = hashlib.sha256(
        json.dumps(
            {
                "spec_id": resolved_spec_id,
                "target_id": resolved_target_id,
                "engine": selected_engine,
                "candidate_fingerprint": fingerprint,
                "planned_actions": actions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return LocalActionPlan(
        spec_id=resolved_spec_id,
        target_id=resolved_target_id,
        engine=selected_engine,
        candidate_fingerprint=fingerprint,
        planned_actions=actions,
        digest=digest,
        workspace_root=workspace,
        target_root=target,
        candidate=candidate,
    )


def _confirm_local_action_plan(action_plan: LocalActionPlan) -> None:
    from echelon.cli import _banner

    _banner(
        "LOCAL DELIVERY VERIFICATION",
        [
            ("spec", action_plan.spec_id),
            ("target", action_plan.target_id),
            ("engine", action_plan.engine),
            ("candidate", action_plan.candidate_fingerprint[:12]),
            ("action", "; ".join(action_plan.planned_actions)),
            (
                "authority",
                "opt-in macOS evidence only; delivery landing remains sandbox-authoritative",
            ),
        ],
        subtitle="Trusted candidate code will run in a managed worktree.",
    )
    answer = input("Start this explicit host-local verification? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("No host-local resources were started.")
        raise SystemExit(1)


def _run_local_delivery_verification(
    project_dir: Path,
    action_plan: LocalActionPlan,
    keep_on_failure: bool,
):
    """Run the exact candidate that the operator approved, without landing authority."""
    from harness.local_runner import (
        LocalRunnabilityRunner,
        LocalRunnerOptions,
        LocalVerificationRequest as RunnerLocalVerificationRequest,
    )
    from harness.local_runner_candidate import LocalCandidateRequest

    if (
        action_plan.workspace_root is None
        or action_plan.target_root is None
        or action_plan.candidate is None
    ):
        raise ValueError("local action plan is incomplete")
    candidate = action_plan.candidate
    mirror = Path(getattr(candidate, "mirror_path"))
    build_id = str(getattr(candidate, "build_id"))
    browser_helper = (
        Path(project_dir)
        / ".echelon"
        / "runtime"
        / "scripts"
        / "user-runnability-browser.mjs"
    )
    if not browser_helper.is_file():
        browser_helper = (
            Path(__file__).resolve().parents[2]
            / "runtime"
            / "scripts"
            / "user-runnability-browser.mjs"
        )
    request = RunnerLocalVerificationRequest(
        workspace_root=action_plan.workspace_root,
        target_root=action_plan.target_root,
        spec_id=action_plan.spec_id,
        target_id=action_plan.target_id,
        candidate_request=LocalCandidateRequest(
            workspace_root=action_plan.workspace_root,
            target_root=action_plan.target_root,
            spec_id=action_plan.spec_id,
            target_id=action_plan.target_id,
            build_id=build_id,
        ),
        local_run_root=mirror.parent / build_id / "local-runs",
    )
    runner = LocalRunnabilityRunner(
        candidate_resolver=lambda _request: candidate,
        browser_helper=browser_helper,
        recovery_workspace_root=action_plan.workspace_root,
    )
    return runner.verify(
        request,
        LocalRunnerOptions(
            engine=action_plan.engine,
            action_confirmed=True,
            keep_on_failure=keep_on_failure,
        ),
    )


def _print_local_verification_result(result: object) -> None:
    from echelon.cli import _banner

    status = str(getattr(result, "status", "failed"))
    fields = [
        ("status", status),
        ("local run", str(getattr(result, "local_run_id", "-"))),
        (
            "cleanup",
            "complete"
            if getattr(result, "cleanup_complete", False)
            else "recovery required",
        ),
    ]
    attestation = getattr(result, "attestation_path", None)
    if attestation is not None:
        fields.append(("local evidence", str(attestation)))
    summary = str(getattr(result, "summary", "")).strip()
    if summary:
        fields.append(("summary", summary))
    if not getattr(result, "cleanup_complete", False):
        fields.append(
            (
                "recovery",
                "echelon delivery cleanup-local "
                f"{getattr(result, 'local_run_id', '<local-run-id>')}",
            )
        )
    _banner(
        "LOCAL DELIVERY VERIFICATION",
        fields,
        subtitle=(
            "Separate local evidence; it never changes delivery landing authority."
        ),
    )


def verify_local(project_root: Path, request: LocalVerificationRequest) -> None:
    if request.keep_on_failure and request.assume_yes:
        raise ValueError("--keep-on-failure cannot be combined with --yes")
    if sys.platform != "darwin":
        raise ValueError("local verification is supported on macOS only")
    try:
        action_plan = _build_local_action_plan(
            project_root,
            request.spec_id,
            request.target_id,
            request.engine,
        )
        if not request.assume_yes:
            _confirm_local_action_plan(action_plan)
        result = _run_local_delivery_verification(
            project_root,
            action_plan,
            request.keep_on_failure,
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    _print_local_verification_result(result)
    if str(getattr(result, "status", "")) != "passed":
        raise SystemExit(1)


def cleanup_local(project_root: Path, *, local_run_id: str) -> None:
    from harness.local_runner import LocalRunnabilityRunner

    root = _local_delivery_workspace_root(project_root)
    try:
        result = LocalRunnabilityRunner(recovery_workspace_root=root).cleanup(
            local_run_id
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    _print_local_verification_result(result)
    if str(result.status) != "cleanup_complete":
        raise SystemExit(1)


def _find_harness_checkpoint_state(
    project_root: Path,
    spec_id: str,
    strategy_id: str = "",
) -> dict | None:
    from echelon.cli import _iter_harness_build_states

    for state in _iter_harness_build_states(project_root):
        if str(state.get("spec_id") or "") != spec_id:
            continue
        if strategy_id and str(state.get("strategy_id") or "") != strategy_id:
            continue
        return state
    return None


def list_checkpoints(
    project_root: Path,
    *,
    spec_id: str,
    strategy: str | None,
    extra_args: Sequence[str] = (),
) -> None:
    from echelon.cli import _require_provider_capability

    strategy_id = strategy or ""
    for raw in extra_args:
        if raw.startswith("strategy="):
            strategy_id = raw.split("=", 1)[1]

    _require_provider_capability(
        "echelon delivery checkpoint",
        ProviderCapability.BUILD,
        project_dir=project_root,
    )
    state = _find_harness_checkpoint_state(project_root, spec_id, strategy_id)
    if state is None:
        strategy_suffix = f" strategy {strategy_id!r}" if strategy_id else ""
        print(
            f"No delivery checkpoint state found for {spec_id!r}{strategy_suffix}.",
            file=sys.stderr,
        )
        sys.exit(1)

    strategy_label = str(state.get("strategy_id") or strategy_id or "default")
    print(f"CHECKPOINTS - delivery {spec_id} (strategy {strategy_label})\n")
    rows: list[tuple[str, str, str, str, str]] = []
    checkpoints = state.get("checkpoint_commits")
    if isinstance(checkpoints, list):
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            commit = str(checkpoint.get("commit") or "").strip()
            if not commit:
                continue
            phase = str(checkpoint.get("phase") or "").strip() or "-"
            phase_group = str(checkpoint.get("phase_group") or "").strip()
            task_ids = checkpoint.get("task_ids")
            tasks = (
                ",".join(str(item) for item in task_ids)
                if isinstance(task_ids, list)
                else "-"
            )
            label = phase_group or phase
            rows.append(
                (commit[:7], "checkpoint", phase, tasks or "-", label or "-")
            )

    for key, kind in (("salvage_commit", "salvage"), ("target_commit", "target")):
        commit = str(state.get(key) or "").strip()
        if commit:
            rows.append(
                (
                    commit[:7],
                    kind,
                    "-",
                    "-",
                    str(
                        state.get("target_branch")
                        or state.get("salvage_branch")
                        or "-"
                    ),
                )
            )

    if not rows:
        print("(none)")
        return

    print("COMMIT   KIND        PHASE      TASKS                 CONTEXT")
    for commit, kind, phase, tasks, context in rows:
        print(f"{commit:<8} {kind:<11} {phase:<10} {tasks:<21} {context}")

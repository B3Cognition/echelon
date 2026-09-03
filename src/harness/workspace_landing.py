"""Finalize workspace-owned specification state after product landing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, run_git
from echelon.phase_a_git import PhaseAGitError, resolve_phase_a_default_branch
from echelon.spec_publish import (
    SpecPublishError,
    publish_specs,
    resolve_publication_sources,
)
from harness.config import get_full_resolved_config
from harness.secret_scan import scan_git_staged
from harness.spec_frontmatter import find_spec_dir, write_status


@dataclass(frozen=True)
class WorkspaceLandingResult:
    """Outcome of the bounded orchestration-workspace landing transaction."""

    ok: bool
    reason: str = ""
    detail: str = ""
    paths: tuple[str, ...] = ()
    source_commit: str | None = None
    published_commit: str | None = None
    default_branch: str | None = None


def _default_branch(project_root: Path) -> tuple[str, str]:
    resolved = get_full_resolved_config(project_root)
    configured = resolved.get("target_default_branch", "")
    if not configured and isinstance(resolved.get("harness"), dict):
        configured = resolved["harness"].get("target_default_branch", "")
    return resolve_phase_a_default_branch(project_root, str(configured or ""))


def _status_lines(project_root: Path) -> tuple[str, ...]:
    output = run_git(
        project_root,
        "-c",
        "core.quotePath=false",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).stdout
    return tuple(line for line in output.splitlines() if line)


def _status_path(line: str) -> str:
    payload = line[3:] if len(line) >= 3 else line
    if " -> " in payload:
        payload = payload.rsplit(" -> ", 1)[1]
    return payload.strip()


def _outside_spec_status(
    status: tuple[str, ...],
    spec_relpath: str,
) -> tuple[str, ...]:
    prefix = spec_relpath.rstrip("/") + "/"
    return tuple(
        line
        for line in status
        if _status_path(line) != spec_relpath
        and not _status_path(line).startswith(prefix)
    )


def _commit_terminal_spec(
    workspace_root: Path,
    spec_relpath: str,
    spec_id: str,
) -> str:
    run_git(workspace_root, "add", "-A", "--", spec_relpath)
    secret_scan = scan_git_staged(workspace_root)
    if not secret_scan.ok:
        raise RuntimeError(
            "secret scan blocked terminal spec commit: "
            f"{secret_scan.format_summary()}"
        )

    changed = run_git(
        workspace_root,
        "diff",
        "--cached",
        "--quiet",
        "--",
        spec_relpath,
        check=False,
    )
    if changed.returncode not in {0, 1}:
        raise RuntimeError(changed.stderr.strip() or "git diff --cached failed")
    if changed.returncode == 1:
        message = build_echelon_commit_message(
            f"chore: finalize landed spec {spec_id}",
            EchelonCommitMetadata(
                origin="delivery",
                action="workspace-spec-land",
                spec_id=spec_id,
            ),
        )
        run_git(
            workspace_root,
            "commit",
            "-m",
            message,
            "--",
            spec_relpath,
        )
    return run_git(workspace_root, "rev-parse", "HEAD^{commit}").stdout.strip()


def finalize_workspace_landing(
    spec_id: str,
    *,
    workspace_root: Path,
    target_root: Path,
) -> WorkspaceLandingResult:
    """Commit and publish terminal spec state, leaving owned checkouts clean.

    The function is deliberately non-destructive. It refuses unrelated dirty
    paths rather than deleting or stashing them.
    """

    workspace = Path(workspace_root).resolve()
    target = Path(target_root).resolve()
    polyrepo = workspace != target

    try:
        default_branch, _default_commit = _default_branch(workspace)

        if polyrepo:
            target_status = _status_lines(target)
            if target_status:
                return WorkspaceLandingResult(
                    ok=False,
                    reason="target_dirty",
                    detail="implementation target has remaining changes",
                    paths=target_status,
                    default_branch=default_branch,
                )

            sources = resolve_publication_sources(
                workspace,
                identity=spec_id,
                publish_all=False,
                default_branch=default_branch,
            )
            source = sources[0]
            current_branch = run_git(
                workspace, "branch", "--show-current"
            ).stdout.strip()
            if current_branch != source.branch:
                status = _status_lines(workspace)
                if status:
                    return WorkspaceLandingResult(
                        ok=False,
                        reason="workspace_dirty",
                        detail=(
                            f"workspace must be clean before switching from "
                            f"{current_branch or '(detached)'} to {source.branch}"
                        ),
                        paths=status,
                        default_branch=default_branch,
                    )
                run_git(workspace, "switch", source.branch)

        spec_dir = find_spec_dir(spec_id, workspace)
        if spec_dir is None:
            return WorkspaceLandingResult(
                ok=False,
                reason="spec_not_found",
                detail=f"canonical spec directory for {spec_id} was not found",
                default_branch=default_branch,
            )
        try:
            spec_relpath = spec_dir.resolve().relative_to(workspace).as_posix()
        except ValueError:
            return WorkspaceLandingResult(
                ok=False,
                reason="spec_outside_workspace",
                detail=f"spec directory {spec_dir} is outside {workspace}",
                default_branch=default_branch,
            )

        unrelated = _outside_spec_status(_status_lines(workspace), spec_relpath)
        if unrelated:
            return WorkspaceLandingResult(
                ok=False,
                reason="workspace_dirty",
                detail="workspace has changes outside the canonical spec",
                paths=unrelated,
                default_branch=default_branch,
            )

        write_status(spec_dir, "landed")
        source_commit = _commit_terminal_spec(
            workspace,
            spec_relpath,
            spec_id,
        )

        residual = _status_lines(workspace)
        if residual:
            return WorkspaceLandingResult(
                ok=False,
                reason="workspace_dirty",
                detail="terminal spec commit left workspace changes",
                paths=residual,
                source_commit=source_commit,
                default_branch=default_branch,
            )

        published_commit: str | None = None
        if polyrepo:
            publication = publish_specs(workspace, identity=spec_id)
            published_commit = publication.default_commit
            run_git(workspace, "switch", default_branch)

        final_workspace_status = _status_lines(workspace)
        if final_workspace_status:
            return WorkspaceLandingResult(
                ok=False,
                reason="workspace_dirty",
                detail="workspace default checkout has remaining changes",
                paths=final_workspace_status,
                source_commit=source_commit,
                published_commit=published_commit,
                default_branch=default_branch,
            )
        final_target_status = _status_lines(target)
        if final_target_status:
            return WorkspaceLandingResult(
                ok=False,
                reason="target_dirty",
                detail="implementation target has remaining changes",
                paths=final_target_status,
                source_commit=source_commit,
                published_commit=published_commit,
                default_branch=default_branch,
            )

        return WorkspaceLandingResult(
            ok=True,
            source_commit=source_commit,
            published_commit=published_commit,
            default_branch=default_branch,
        )
    except (GitHelperError, PhaseAGitError, SpecPublishError, OSError, RuntimeError) as exc:
        return WorkspaceLandingResult(
            ok=False,
            reason="workspace_finalize_failed",
            detail=str(exc),
        )

"""Finalize workspace-owned specification state after product landing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, run_git
from echelon.phase_a_git import PhaseAGitError, resolve_phase_a_default_branch
from echelon.spec_publish import (
    SpecPublishError,
    publish_specs,
    resolve_publication_sources,
)
from harness.config import get_full_resolved_config
from harness.fulfillment_runner import SCOPE_INPUT_FILENAMES, _spec_input_hash
from harness.secret_scan import scan_git_staged, scan_paths
from harness.spec_frontmatter import (
    find_spec_dir,
    read_frontmatter,
    spec_content_ignoring_status,
    write_status,
    write_text_atomic,
)


LANDING_TRANSITION_FILENAME = "landing-transition.json"


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


def landing_transition_covers_hashes(
    spec_dir: Path,
    *,
    recorded_hash: object,
    current_hash: object,
) -> bool:
    """Return whether a sealed terminal transition explains a hash change."""
    if not isinstance(recorded_hash, str) or not recorded_hash:
        return False
    if not isinstance(current_hash, str) or not current_hash:
        return False
    path = spec_dir / LANDING_TRANSITION_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == 1
        and payload.get("spec_id") == spec_dir.name
        and payload.get("pre_land_spec_input_hash") == recorded_hash
        and payload.get("landed_spec_input_hash") == current_hash
    )


def landing_transition_allows_retry(
    spec_dir: Path,
    *,
    workspace_root: Path,
    recorded_hash: object,
    current_hash: object,
) -> bool:
    """Accept a seal or recover a terminal status write interrupted before sealing."""
    if landing_transition_covers_hashes(
        spec_dir,
        recorded_hash=recorded_hash,
        current_hash=current_hash,
    ):
        return True
    if not isinstance(recorded_hash, str) or not recorded_hash:
        return False
    if not isinstance(current_hash, str) or not current_hash:
        return False
    transition = spec_dir / LANDING_TRANSITION_FILENAME
    if transition.exists() or transition.is_symlink():
        return False
    try:
        if str(read_frontmatter(spec_dir).get("status") or "") != "landed":
            return False
        spec_relpath = spec_dir.relative_to(workspace_root).as_posix()
    except (OSError, ValueError, TypeError):
        return False
    recovered_hash = _head_spec_input_hash_for_status_only_transition(
        workspace_root,
        spec_dir,
        spec_relpath,
    )
    return recovered_hash == recorded_hash


def _sealed_transition_pre_hash(
    spec_dir: Path,
    *,
    current_hash: str,
) -> str | None:
    path = spec_dir / LANDING_TRANSITION_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    pre_hash = payload.get("pre_land_spec_input_hash") if isinstance(payload, dict) else None
    if (
        not isinstance(pre_hash, str)
        or not pre_hash
        or payload.get("schema_version") != 1
        or payload.get("spec_id") != spec_dir.name
        or payload.get("landed_spec_input_hash") != current_hash
    ):
        return None
    return pre_hash


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


def _git_file_at_head(workspace_root: Path, relpath: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relpath}"],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _head_spec_input_hash_for_status_only_transition(
    workspace_root: Path,
    spec_dir: Path,
    spec_relpath: str,
) -> str | None:
    """Recover the verified pre-land hash from a status-only working change."""
    current_spec = spec_dir / "spec.md"
    head_spec = _git_file_at_head(workspace_root, f"{spec_relpath}/spec.md")
    if head_spec is None or not current_spec.is_file():
        return None
    try:
        head_content = spec_content_ignoring_status(head_spec.decode("utf-8"))
        current_content = spec_content_ignoring_status(
            current_spec.read_text(encoding="utf-8")
        )
        if head_content is None or current_content is None or head_content != current_content:
            return None
    except (OSError, UnicodeDecodeError):
        return None

    digest = hashlib.sha256()
    for filename in SCOPE_INPUT_FILENAMES:
        path = spec_dir / filename
        head_content = _git_file_at_head(
            workspace_root,
            f"{spec_relpath}/{filename}",
        )
        if filename != "spec.md":
            current_content = path.read_bytes() if path.is_file() else None
            if current_content != head_content:
                return None
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        if head_content is None:
            digest.update(b"0\0")
        else:
            digest.update(b"1\0")
            digest.update(head_content)
    return digest.hexdigest()


def _record_landing_transition(
    spec_dir: Path,
    *,
    pre_land_hash: str,
    landed_hash: str,
) -> None:
    path = spec_dir / LANDING_TRANSITION_FILENAME
    if landing_transition_covers_hashes(
        spec_dir,
        recorded_hash=pre_land_hash,
        current_hash=landed_hash,
    ):
        return
    payload = {
        "schema_version": 1,
        "spec_id": spec_dir.name,
        "pre_land_spec_input_hash": pre_land_hash,
        "landed_spec_input_hash": landed_hash,
    }
    write_text_atomic(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _is_recognized_landing_transition(spec_dir: Path) -> bool:
    path = spec_dir / LANDING_TRANSITION_FILENAME
    if not path.is_file() or path.is_symlink():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == 1
        and payload.get("spec_id") == spec_dir.name
        and isinstance(payload.get("pre_land_spec_input_hash"), str)
        and payload.get("pre_land_spec_input_hash")
        and isinstance(payload.get("landed_spec_input_hash"), str)
        and payload.get("landed_spec_input_hash")
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


def finalize_landed_topology(spec_id: str, workspace_root: Path) -> WorkspaceLandingResult:
    """Commit only the hash-validated files of a published topology registry.

    Also serves as recovery for older landings that published the registry after
    the final cleanliness check. Unknown files and broken receipts remain intact.
    """
    from harness.gitops import GitOpsManager
    from harness.re_lock import RePublishLock

    workspace = Path(workspace_root).resolve()
    topology = workspace / "re/topology"
    if not topology.exists() and not topology.is_symlink():
        return WorkspaceLandingResult(ok=True)
    owner_id = "land-finalize-" + hashlib.sha256(spec_id.encode()).hexdigest()[:20]
    try:
        # The lock's persistent guard must stay ignored when switching to an
        # older spec branch that predates re/.gitignore. Never ignore topology.
        exclude = Path(run_git(workspace, "rev-parse", "--git-path", "info/exclude").stdout.strip())
        if not exclude.is_absolute():
            exclude = workspace / exclude
        GitOpsManager._append_unique_line(exclude, "/re/.locks/.publish-claim.guard")
        with RePublishLock.acquire(workspace, owner_id, None):
            return _commit_landed_topology(spec_id, workspace)
    except (GitHelperError, OSError, RuntimeError) as exc:
        return WorkspaceLandingResult(ok=False, reason="topology_finalize_failed", detail=str(exc))


def _commit_landed_topology(spec_id: str, workspace: Path) -> WorkspaceLandingResult:
    """Validate and commit one registry while holding its publication lock."""
    from echelon.topology_registry import (
        TopologyRegistryError, load_topology_index, load_published_topology_from_index,
    )

    try:
        changed = set()
        for args in (
            ("diff", "--name-only", "-z", "HEAD", "--", "re/topology"),
            ("ls-files", "--others", "--exclude-standard", "-z", "--", "re/topology"),
        ):
            changed.update(filter(None, run_git(workspace, *args).stdout.split("\0")))
        if not changed:
            return WorkspaceLandingResult(ok=True)
        default_branch, _ = _default_branch(workspace)
        if run_git(workspace, "branch", "--show-current").stdout.strip() != default_branch:
            raise RuntimeError("topology publication must be finalized on the workspace default branch")
        index = load_topology_index(workspace)
        if index is None:
            raise RuntimeError("topology publication has no registry")
        load_published_topology_from_index(workspace, index)
        owned = {"re/topology/index.json"}
        for source in index.sources.values():
            owned.add(source.receipt.path)
            for provider in source.providers.values():
                owned.update(artifact.path for artifact in provider.artifacts.values())
        deleted = set(filter(None, run_git(
            workspace, "diff", "--name-only", "--diff-filter=D", "-z",
            "HEAD", "--", "re/topology",
        ).stdout.split("\0")))
        if deleted:
            # A valid replacement can retire providers/sources. Only accept
            # removals explicitly owned by the previously committed registry.
            previous_bytes = _git_file_at_head(workspace, "re/topology/index.json")
            try:
                previous = json.loads(previous_bytes or b"{}")
                previous_owned = set()
                for source in previous.get("sources", {}).values():
                    previous_owned.add(source["receipt"]["path"])
                    for provider in source["providers"].values():
                        previous_owned.update(
                            artifact["path"] for artifact in provider["artifacts"].values()
                        )
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise RuntimeError("cannot establish ownership of removed topology files") from exc
            owned.update(deleted & previous_owned)
        if changed - owned:
            raise RuntimeError("topology has files outside its validated registry: " + ", ".join(sorted(changed - owned)))
        paths = sorted(changed)
        scan = scan_paths(workspace / path for path in paths)
        if not scan.ok:
            raise RuntimeError("secret scan blocked topology commit: " + scan.format_summary())
        run_git(workspace, "add", "--", *paths)
        message = build_echelon_commit_message(
            f"chore: finalize landed topology {spec_id}",
            EchelonCommitMetadata(origin="delivery", action="workspace-topology-land", spec_id=spec_id),
        )
        # --only preserves any unrelated staged user changes.
        run_git(workspace, "commit", "--only", "-m", message, "--", *paths)
        return WorkspaceLandingResult(ok=True)
    except (GitHelperError, PhaseAGitError, TopologyRegistryError, OSError, RuntimeError) as exc:
        return WorkspaceLandingResult(ok=False, reason="topology_finalize_failed", detail=str(exc))


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

        # Older successful landings left topology uncommitted on main. Recover
        # that bounded publication before switching back to the spec branch.
        if run_git(workspace, "branch", "--show-current").stdout.strip() == default_branch:
            topology = finalize_landed_topology(spec_id, workspace)
            if not topology.ok:
                return topology

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
        specs_root = workspace / "specs"
        expected_spec_dir = specs_root / spec_dir.name
        spec_md = spec_dir / "spec.md"
        if (
            spec_dir.absolute() != expected_spec_dir.absolute()
            or specs_root.is_symlink()
            or spec_dir.is_symlink()
            or spec_md.is_symlink()
        ):
            return WorkspaceLandingResult(
                ok=False,
                reason="unsafe_spec_path",
                detail=(
                    f"canonical spec path must be a non-symlinked child of "
                    f"{specs_root}"
                ),
                default_branch=default_branch,
            )
        spec_relpath = f"specs/{spec_dir.name}"

        unrelated = _outside_spec_status(_status_lines(workspace), spec_relpath)
        if unrelated:
            return WorkspaceLandingResult(
                ok=False,
                reason="workspace_dirty",
                detail="workspace has changes outside the canonical spec",
                paths=unrelated,
                default_branch=default_branch,
            )

        pre_land_hash = _spec_input_hash(spec_dir)
        if pre_land_hash is None:
            return WorkspaceLandingResult(
                ok=False,
                reason="spec_hash_unavailable",
                detail="could not hash canonical spec inputs before landing",
                default_branch=default_branch,
            )
        existing_status = str(read_frontmatter(spec_dir).get("status") or "")
        existing_transition = spec_dir / LANDING_TRANSITION_FILENAME
        if (
            existing_transition.exists() or existing_transition.is_symlink()
        ) and not _is_recognized_landing_transition(spec_dir):
            return WorkspaceLandingResult(
                ok=False,
                reason="workspace_file_collision",
                detail=(
                    "refusing to replace an unrecognized landing transition: "
                    f"{existing_transition}"
                ),
                paths=(str(existing_transition),),
                default_branch=default_branch,
            )
        if existing_status == "landed":
            sealed_pre_hash = _sealed_transition_pre_hash(
                spec_dir,
                current_hash=pre_land_hash,
            )
            if sealed_pre_hash is not None:
                pre_land_hash = sealed_pre_hash
            elif not existing_transition.is_file():
                recovered_hash = _head_spec_input_hash_for_status_only_transition(
                    workspace,
                    spec_dir,
                    spec_relpath,
                )
                if recovered_hash is not None:
                    pre_land_hash = recovered_hash

        write_status(spec_dir, "landed")
        landed_hash = _spec_input_hash(spec_dir)
        if landed_hash is None:
            return WorkspaceLandingResult(
                ok=False,
                reason="spec_hash_unavailable",
                detail="could not hash canonical spec inputs after landing",
                default_branch=default_branch,
            )
        if not landing_transition_covers_hashes(
            spec_dir,
            recorded_hash=pre_land_hash,
            current_hash=landed_hash,
        ):
            _record_landing_transition(
                spec_dir,
                pre_land_hash=pre_land_hash,
                landed_hash=landed_hash,
            )
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

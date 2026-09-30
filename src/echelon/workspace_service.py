"""Typed application services for Echelon workspace commands."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from echelon.workspace_git_migration import (
    WorkspaceDoctorResult,
    WorkspaceGitMigrationResult,
    doctor_workspace,
    migrate_workspace,
)
from echelon.workspace_sources import WorkspaceSourcesSyncResult, sync_sources_config
from echelon.workspace_model import discover_workspace
from echelon.ui import banner

try:
    from codegen.memory.collision import check_wing_collision
except ImportError:
    try:
        from src.codegen.memory.collision import check_wing_collision  # type: ignore
    except ImportError:

        def check_wing_collision(*_args, **_kwargs):  # type: ignore[assignment]
            return []


def inspect_workspace(project_root: Path) -> WorkspaceDoctorResult:
    """Validate workspace, source, runtime, and Git ownership contracts."""
    return doctor_workspace(project_root)


def migrate_workspace_layout(
    project_root: Path,
    *,
    write: bool,
    commit: bool,
    commit_message: str,
) -> WorkspaceGitMigrationResult:
    """Plan or apply the canonical workspace Git layout migration."""
    return migrate_workspace(
        project_root,
        write=write or commit,
        commit=commit,
        commit_message=commit_message,
    )


def sync_workspace_sources(
    project_root: Path,
    *,
    write: bool,
) -> WorkspaceSourcesSyncResult:
    """Discover canonical source roots and reconcile workspace configuration."""
    return sync_sources_config(project_root, write=write)


def _workspace_git_present(project_root: Path) -> bool:
    return discover_workspace(project_root).workspace.git_present


def _workspace_git_has_head(project_root: Path) -> bool:
    if not _workspace_git_present(project_root):
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _workspace_git_has_only_init_owned_drift(project_root: Path) -> bool:
    if not _workspace_git_present(project_root):
        return False
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    allowed = {".echelon/config.yml", ".gitignore"}
    for line in result.stdout.splitlines():
        path = line[3:] if len(line) > 3 else ""
        if path not in allowed:
            return False
    return True


def _workspace_source_scaffold_needs_repair(project_root: Path) -> bool:
    readme = project_root / "sources" / "README.md"
    if not readme.exists():
        return True
    gitignore = project_root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "/sources/*" not in text or "!/sources/README.md" not in text:
        return True
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "sources/README.md"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return tracked.returncode != 0


def bootstrap_workspace_git(project_root: Path) -> None:
    """Initialize lightweight workspace Git after workspace init when possible."""
    has_head = _workspace_git_has_head(project_root)
    if has_head:
        if not _workspace_source_scaffold_needs_repair(project_root):
            return
        from echelon.workspace_git_migration import migrate_workspace

        commit_repair = _workspace_git_has_only_init_owned_drift(project_root)
        result = migrate_workspace(project_root, write=True, commit=commit_repair)
        if result.source_roots_scaffolded:
            print("✓ source roots scaffolded: sources/ (clone/copy implementation repos there)")
        if result.gitignore_updated or result.staged_paths:
            staged = ", ".join(result.staged_paths) or "(none)"
            print(f"✓ workspace contract repaired; staged: {staged}")
        if result.committed:
            print("✓ committed initial workspace contract")
        elif result.staged_paths:
            print("  workspace repair left staged because the worktree was not clean")
        return
    if not (
        (project_root / ".specify").exists()
        or (project_root / "specs").exists()
        or (project_root / ".echelon" / "config.yml").exists()
    ):
        return

    from echelon.workspace_git_migration import migrate_workspace

    result = migrate_workspace(project_root, write=True, commit=True)
    if result.source_roots_scaffolded:
        print("✓ source roots scaffolded: sources/ (clone/copy implementation repos there)")
    if result.git_initialized:
        staged = ", ".join(result.staged_paths) or "(none)"
        print(f"✓ workspace Git initialized; staged: {staged}")
    if result.committed:
        print("✓ committed initial workspace contract")

def _derive_wing_suggestion(project_dir: Path) -> str:
    """Suggest a wing name: git remote slug if available, else dirname-hash6."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            slug = url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
            if slug:
                return slug
    except Exception:
        pass
    abs_hash = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:6]
    return f"{project_dir.name}-{abs_hash}"


def _provision_wing(project_dir: Path, echelon_yml: Path) -> str:
    """
    Interactively provision wing name into echelon-config.yml.
    Idempotent: if wing already set, returns existing value immediately.
    Returns the confirmed wing name.
    """
    try:
        import yaml as _yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    config = _yaml.safe_load(echelon_yml.read_text()) or {}
    existing_wing = config.get("mempalace", {}).get("wing", "")
    if existing_wing:
        print(f"✓ wing: {existing_wing!r} already configured")
        return existing_wing

    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        palace_path = MempalaceConfig().palace_path
    except ImportError:
        palace_path = os.path.expanduser("~/.mempalace/palace")

    suggestion = _derive_wing_suggestion(project_dir)
    last_entered: str = ""

    if not sys.stdin.isatty():
        chosen = suggestion
        foreign = check_wing_collision(chosen, project_dir, palace_path)
        if foreign:
            print(
                f"✗ Suggested MemPalace wing {chosen!r} belongs to another project. "
                "Re-run interactively and choose a different wing.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✓ wing: {chosen!r} selected for non-interactive initialization")
    else:
        while True:
            raw = input(f"Wing name for MemPalace memory [{suggestion}]: ").strip()
            chosen = raw or suggestion

            foreign = check_wing_collision(chosen, project_dir, palace_path)
            if foreign:
                if chosen == last_entered:
                    print(f"  ⚠  Sharing memory with other project intentionally — wing: {chosen!r}")
                    break
                print(f"\n  ⚠  Wing {chosen!r} already has drawers from a different project:")
                for path in foreign[:5]:
                    print(f"       {path}")
                print("  Enter a different name, or re-enter the same name to share memory intentionally.\n")
                last_entered = chosen
                suggestion = chosen
                continue

            break

    if "mempalace" not in config:
        config["mempalace"] = {}
    config["mempalace"]["wing"] = chosen
    echelon_yml.write_text(_yaml.dump(config, default_flow_style=False, allow_unicode=True))
    print(f"✓ wing: {chosen!r} written to echelon-config.yml")
    return chosen


def _print_http_deploy_runtime_warning(
    *,
    reason: str,
    detail: str | None = None,
) -> None:
    print(
        "⚠ HTTP deploy initialization skipped because Docker is not ready.\n"
        f"  reason   {reason}",
        file=sys.stderr,
    )
    if detail:
        print(f"  detail   {detail}", file=sys.stderr)
    print(
        "\n"
        "  workspace init will continue without provisioning local HTTP deploy infra.\n"
        "  Echelon will set deploy.enabled: false in .echelon/config.yml for this workspace.\n"
        "\n"
        "  next\n"
        "  ────\n"
        "  To enable HTTP deploy later, install/start Docker and rerun:\n"
        "    echelon workspace init\n"
        "\n"
        "  To disable local deploy for this project, set in .echelon/config.yml:\n"
        "    deploy.enabled: false\n"
        "\n"
        "  To initialize delivery sandboxing with Podman after workspace init:\n"
        "    ECHELON_CONTAINER_CLI=podman echelon delivery init\n"
        "\n"
        "  note\n"
        "  ────\n"
        "  Podman is supported for Echelon delivery sandboxing. The HTTP deploy\n"
        "  Traefik setup currently expects Docker and the Docker socket.",
        file=sys.stderr,
    )


def _preflight_deploy_runtime(
    deploy: dict,
    *,
    which=shutil.which,
    run=subprocess.run,
) -> bool:
    if deploy.get("type", "http") != "http":
        return True

    docker_bin = which("docker")
    if not docker_bin:
        _print_http_deploy_runtime_warning(reason="docker command not found on PATH")
        return False

    try:
        result = run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        _print_http_deploy_runtime_warning(reason="docker info timed out")
        return False
    except OSError as exc:
        _print_http_deploy_runtime_warning(
            reason="docker info could not run",
            detail=str(exc),
        )
        return False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _print_http_deploy_runtime_warning(
            reason="Docker CLI found, but the Docker daemon is not reachable",
            detail=detail or None,
        )
        return False

    return True


UNSAFE_HOST_EXECUTION_APPROVAL_REASON = (
    "Operator approved echelon workspace init to allow local AI CLI host tool execution."
)


def wants_unsafe_host_execution_interactively() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    answer = input(
        "Allow local AI CLI subprocesses to bypass host tool approvals for this workspace? [y/N] "
    ).strip().lower()
    return answer in {"y", "yes"}


def _ensure_local_config_ignored(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    entry = "/.echelon/local.yml"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    normalized = {line.strip().strip("/") for line in existing.splitlines()}
    if ".echelon/local.yml" in normalized:
        return
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(f"{existing}{suffix}{entry}\n", encoding="utf-8")


def _assert_local_config_untracked(project_dir: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".echelon/local.yml"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise ValueError(
            ".echelon/local.yml is tracked; remove it from Git before storing "
            "developer-local LLM settings"
        )


def _write_unsafe_host_execution_local_override(project_dir: Path, yaml_module) -> Path:
    local_cfg = project_dir / ".echelon" / "local.yml"
    local_cfg.parent.mkdir(parents=True, exist_ok=True)
    if local_cfg.exists():
        loaded = yaml_module.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"local config must be a mapping: {local_cfg}")
    else:
        loaded = {}

    harness = loaded.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise ValueError("local config harness section must be a mapping")
    llm = harness.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("local config harness.llm section must be a mapping")
    tool_policy = llm.setdefault("tool_policy", {})
    if not isinstance(tool_policy, dict):
        raise ValueError("local config harness.llm.tool_policy section must be a mapping")

    tool_policy["allow_unsafe_host_execution"] = True
    tool_policy["approval_reason"] = UNSAFE_HOST_EXECUTION_APPROVAL_REASON
    local_cfg.write_text(
        yaml_module.dump(loaded, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _ensure_local_config_ignored(project_dir)
    return local_cfg


def _apply_workspace_llm_selection(
    config: dict,
    llm_cli: str | None = None,
    *,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    openai_api_key_file: str | None = None,
    openai_api_key_env: str | None = None,
) -> str:
    from harness.config import VALID_LLM_CLIS
    from harness.init import _detect_llm_cli

    harness = config.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise ValueError("config harness section must be a mapping")
    llm = harness.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("config harness.llm section must be a mapping")

    existing = llm.get("cli")
    openai_options = {
        "base_url": openai_base_url,
        "model": openai_model,
        "api_key_file": openai_api_key_file,
        "api_key_env": openai_api_key_env,
    }

    if llm_cli:
        if llm_cli not in VALID_LLM_CLIS:
            raise ValueError(
                f"invalid --llm {llm_cli!r}; expected one of: "
                f"{', '.join(sorted(VALID_LLM_CLIS))}"
            )
        llm["cli"] = llm_cli
        for key, value in openai_options.items():
            if value:
                llm[key] = value
        return llm_cli

    selected = _detect_llm_cli()
    if os.environ.get("ECHELON_LLM", "").strip() or not existing:
        llm["cli"] = selected
        for key, value in openai_options.items():
            if value:
                llm[key] = value
        return selected
    for key, value in openai_options.items():
        if value:
            llm[key] = value
    return str(existing)


def initialize_workspace(
    project_dir: Path,
    *,
    allow_unsafe_host_execution: bool = False,
    llm_cli: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    openai_api_key_file: str | None = None,
    openai_api_key_env: str | None = None,
) -> None:
    echelon_cfg = project_dir / ".echelon" / "config.yml"
    runtime_dir = project_dir / ".echelon" / "runtime"
    from echelon.owned_output_commit import OwnedOutputCommit

    setup_commit = OwnedOutputCommit(
        project_dir, [echelon_cfg, project_dir / ".gitignore"],
        "chore: record Echelon workspace setup", preserve_dirty=True,
    )

    from echelon.prosaic_packages import ProsaicBundleInstallError, install_prosaic_bundle

    try:
        install_prosaic_bundle(project_dir)
    except ProsaicBundleInstallError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"✓ Prosaic prose deployed: {project_dir / '.echelon/prosaic'}")
    print(f"✓ Prosaic runtime deployed: {runtime_dir}")
    _ensure_prosaic_workspace_ignores(project_dir)

    # Step 1: Confirm project config exists, seeded from the Echelon runtime.
    runtime_config = runtime_dir / "echelon-config.yml"
    config_template = runtime_dir / "config-template.yml"
    config_source = runtime_config if runtime_config.exists() else config_template
    if not echelon_cfg.exists():
        if config_source.exists():
            echelon_cfg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(config_source, echelon_cfg)
            print(f"✓ Project config created: {echelon_cfg}")
        else:
            print(
                f"✗ Project config not found: {echelon_cfg}\n"
                f"  Runtime config also missing: {runtime_config}\n"
                f"  Config template also missing: {config_template}\n"
                "  Run: echelon workspace init",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"✓ Project config found: {echelon_cfg}")

    # Step 2: Validate deploy config
    try:
        import yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    try:
        config = yaml.safe_load(echelon_cfg.read_text())
    except Exception as e:
        print(f"✗ Cannot parse .echelon/config.yml: {e}", file=sys.stderr)
        sys.exit(1)

    deploy = config.get("deploy", {})
    deploy_type = deploy.get("type", "http")
    if deploy_type not in ("http", "cli"):
        print(f"✗ deploy.type must be 'http' or 'cli', got: {deploy_type!r}", file=sys.stderr)
        sys.exit(1)
    if deploy_type == "http":
        missing = [k for k in ("blue_port", "green_port") if k not in deploy]
        if missing:
            print(
                f"✗ deploy config incomplete in .echelon/config.yml.\n"
                f"  HTTP type requires: {missing}\n"
                f"  See .echelon/runtime/config-template.yml for reference.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"✓ deploy config valid (type={deploy_type})")
    deploy_enabled = deploy.get("enabled", True) is not False
    deploy_runtime_ready = _preflight_deploy_runtime(deploy) if deploy_enabled else False
    if deploy_enabled and not deploy_runtime_ready:
        deploy["enabled"] = False
        config["deploy"] = deploy
        echelon_cfg.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
        deploy_enabled = False
        print("✓ deploy.enabled=false written to .echelon/config.yml")

    try:
        selected_llm_cli = _apply_workspace_llm_selection(
            config,
            llm_cli=llm_cli,
            openai_base_url=openai_base_url,
            openai_model=openai_model,
            openai_api_key_file=openai_api_key_file,
            openai_api_key_env=openai_api_key_env,
        )
    except Exception as e:
        print(f"✗ Cannot configure LLM provider: {e}", file=sys.stderr)
        sys.exit(1)
    echelon_cfg.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"✓ LLM provider configured: {selected_llm_cli}")

    if allow_unsafe_host_execution:
        try:
            local_cfg = _write_unsafe_host_execution_local_override(project_dir, yaml)
        except Exception as e:
            print(f"✗ Cannot write local host tool policy approval: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ host tool execution approval written to {local_cfg}")

    # Step 2b: Provision MemPalace wing
    print("\n▶ Configuring MemPalace wing...")
    _provision_wing(project_dir, echelon_cfg)

    # Step 3: Run deploy-init.sh
    init_script = runtime_dir / "scripts" / "bash" / "deploy-init.sh"
    deploy_state_label = str(project_dir / "runs" / "deploy-state.json")
    if not deploy_enabled:
        deploy_state_label = "skipped (deploy.enabled=false)"
    elif not deploy_runtime_ready:
        deploy_state_label = "skipped (Docker unavailable)"
    elif not init_script.exists():
        print(
            f"✗ deploy-init.sh not found at {init_script}\n"
            "  Ensure the selected Echelon runtime is installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    else:
        result = subprocess.run(
            ["bash", str(init_script), str(project_dir), str(echelon_cfg)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            sys.exit(result.returncode)

    setup_commit.commit()
    # Step 4: Confirm
    banner("ECHELON INIT — COMPLETE", [
        ("Config",       str(echelon_cfg)),
        ("Deploy state", deploy_state_label),
        ("Next step",    "echelon spec run <description>"),
    ])


def migrate_to_prosaic(project_root: Path) -> None:
    """Deploy and validate Prosaic without deleting legacy workspace state."""
    from echelon.prosaic_packages import ProsaicBundleInstallError, install_prosaic_bundle
    from echelon.constitution import migrate_legacy_constitution
    from echelon.deploy_state_migration import (
        DeployStateMigrationError,
        migrate_legacy_deploy_state,
    )
    from harness.phase_graph import load_workspace_phase_graph
    from echelon.owned_output_commit import OwnedOutputCommit

    config_path = project_root / ".echelon" / "config.yml"
    setup_commit = OwnedOutputCommit(
        project_root, [config_path, project_root / ".gitignore", project_root / ".echelon/constitution.md"],
        "chore: record Echelon workspace migration", preserve_dirty=True,
    )
    legacy_config = project_root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not config_path.exists():
        if not legacy_config.is_file():
            print(
                f"✗ Project config not found: {config_path}\n"
                f"  Legacy config also missing: {legacy_config}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, config_path)
        print(f"✓ copied canonical config from {legacy_config}")

    if _normalize_legacy_re_output_directory(config_path):
        print("✓ normalized standalone RE output: .echelon/re")

    try:
        install_prosaic_bundle(project_root)
    except ProsaicBundleInstallError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        from echelon.speckit_git import disable_speckit_git

        legacy_git = disable_speckit_git(project_root)
    except Exception as exc:
        print(f"✗ Could not disable legacy Spec-Kit Git integration: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        graph, runtime_root = load_workspace_phase_graph(project_root)
    except Exception as exc:
        print(f"✗ Prosaic bundle validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not graph.all_phase_ids():
        print("✗ Prosaic bundle validation failed: workflow has no phases", file=sys.stderr)
        raise SystemExit(1)
    _ensure_prosaic_workspace_ignores(project_root)
    migrated_constitution = migrate_legacy_constitution(project_root)
    try:
        migrated_deploy_state = migrate_legacy_deploy_state(project_root)
    except DeployStateMigrationError as exc:
        print(f"✗ Could not migrate deployment state: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    setup_commit.commit()
    print("✓ Prosaic migration complete")
    print(f"  prose:   {project_root / '.echelon' / 'prosaic'}")
    print(f"  runtime: {runtime_root}")
    print(f"  phases:  {len(graph.all_phase_ids())}")
    if migrated_constitution is not None:
        print(f"  constitution: {migrated_constitution}")
    if migrated_deploy_state.migrated:
        print(f"  deployment state: {migrated_deploy_state.global_state_path}")
    if legacy_git.installed:
        print("  legacy Git integration: disabled")
    print("  legacy .specify/extensions/echelon was left unchanged")


def _normalize_legacy_re_output_directory(config_path: Path) -> bool:
    """Move only the former default RE state path into Echelon ownership."""
    text = config_path.read_text(encoding="utf-8")
    normalized, replacements = re.subn(
        r"(?m)^(\s*directory:\s*)(['\"]?)\.specify/echelon/re\2(\s*(?:#.*)?)$",
        r"\1\2.echelon/re\2\3",
        text,
    )
    if replacements == 0:
        return False
    config_path.write_text(normalized, encoding="utf-8")
    return True


def _ensure_prosaic_workspace_ignores(project_root: Path) -> None:
    """Ignore generated Prosaic deployment state without rewriting user rules."""
    ignore_path = project_root / ".gitignore"
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    lines = existing.splitlines()
    required = (
        "/.echelon/re/",
        "/.echelon/re-v2/",
        "/.echelon/runtime/",
        "/.echelon/packages/",
        "/.echelon/prosaic/",
        "/.echelon/.banzai-default-protocol.lock",
        "/.prosaic-manifest.json",
        "/.prosaic-backups/",
    )
    missing = [line for line in required if line not in lines]
    if not missing:
        return
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    ignore_path.write_text(
        f"{existing}{suffix}" + "".join(f"{line}\n" for line in missing),
        encoding="utf-8",
    )

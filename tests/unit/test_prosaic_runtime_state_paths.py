"""State-location contracts for the deployed Prosaic/runtime bundle."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
PROSAIC = ROOT / "prosaic"


def test_prosaic_bundle_does_not_reference_legacy_extension_installation() -> None:
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify/extensions/echelon" in line:
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_prosaic_bundle_does_not_invoke_spec_kit_commands() -> None:
    legacy_command = re.compile(r"/?speckit\.[A-Za-z0-9_.-]+")
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_command.search(line):
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_prosaic_bundle_does_not_describe_spec_kit_storage_or_runtime() -> None:
    legacy_reference = re.compile(r"\.specify|speckit", re.IGNORECASE)
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_reference.search(line):
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_runtime_workflow_does_not_describe_spec_kit_fallbacks() -> None:
    legacy_reference = re.compile(r"\.specify|speckit|spec-kit", re.IGNORECASE)
    findings = []
    for workflow_file in (RUNTIME / "workflow").rglob("*"):
        if workflow_file.suffix not in {".md", ".yaml", ".yml"}:
            continue
        for line_number, line in enumerate(
            workflow_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_reference.search(line):
                findings.append(
                    f"{workflow_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_active_harness_config_resolution_does_not_use_legacy_extension_config() -> None:
    findings = []
    active_modules = (
        ROOT / "src" / "harness" / "config.py",
        ROOT / "src" / "harness" / "quality_scores.py",
        ROOT / "src" / "harness" / "squad.py",
        ROOT / "src" / "harness" / "squad_executors.py",
    )
    for module in active_modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "echelon-config.yml" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_active_prompt_assembly_does_not_rewrite_legacy_squad_paths() -> None:
    findings = []
    active_modules = (
        ROOT / "src" / "echelon" / "cli.py",
        ROOT / "src" / "harness" / "squad_executors.py",
    )
    for module in active_modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify/squad" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_active_run_lookup_ignores_top_level_squad_storage(tmp_path: Path) -> None:
    from echelon.cli import _find_current_run_dir

    legacy_run = tmp_path / "squad" / "legacy-run"
    legacy_run.mkdir(parents=True)
    (legacy_run.parent / ".current").write_text("legacy-run\n", encoding="utf-8")

    assert _find_current_run_dir(tmp_path) is None


def test_container_runtime_uses_echelon_owned_labels() -> None:
    modules = (
        ROOT / "src" / "harness" / "docker_provider.py",
        ROOT / "src" / "harness" / "gc.py",
        ROOT / "src" / "harness" / "visual_ralph.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in modules)

    assert "spec-kit-harness" not in combined
    assert '"speckit.' not in combined
    assert "echelon-harness.session_id" in combined


def test_active_delivery_modules_use_echelon_owned_names() -> None:
    modules = (
        ROOT / "src" / "echelon" / "cli.py",
        ROOT / "src" / "echelon" / "artifact_index.py",
        ROOT / "src" / "harness" / "config.py",
        ROOT / "src" / "harness" / "errors.py",
        ROOT / "src" / "harness" / "gitops.py",
        ROOT / "src" / "harness" / "init.py",
        ROOT / "src" / "harness" / "run_intent.py",
        ROOT / "src" / "harness" / "skills" / "run_skill.py",
        ROOT / "src" / "harness" / "skills" / "resume_skill.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in modules)

    assert "spec-kit harness" not in combined.lower()
    assert "spec-kit-harness" not in combined.lower()
    assert "/speckit-harness" not in combined.lower()
    assert ".specify/extensions/echelon/harness" not in combined


def test_active_journal_validation_uses_runtime_schema() -> None:
    modules = (
        ROOT / "src" / "harness" / "journal_entry_validator.py",
        ROOT / "src" / "harness" / "journal_prompt_validator.py",
        ROOT / "src" / "harness" / "squad.py",
        ROOT / "src" / "harness" / "squad_completion.py",
        ROOT / "src" / "harness" / "squad_executors.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in modules)

    assert "extension/workflow/journal-entry-types" not in combined


def test_deployment_scripts_have_one_runtime_source_of_truth() -> None:
    duplicate_names = (
        "deploy.sh",
        "deploy-init.sh",
        "deploy-status.sh",
        "validate-deploy.sh",
    )

    assert all((RUNTIME / "scripts" / "bash" / name).is_file() for name in duplicate_names)
    assert not any((ROOT / "scripts" / "bash" / name).exists() for name in duplicate_names)


def test_obsolete_speckit_integration_smoke_script_is_absent() -> None:
    assert not (ROOT / "scripts" / "bash" / "integration-smoke-test.sh").exists()


def test_shared_runtime_helpers_are_not_duplicated_at_repository_root() -> None:
    helper_names = (
        "post-execution-audit.sh",
        "pre-dispatch-gate.sh",
        "setup-worktree.sh",
    )

    assert all((RUNTIME / "scripts" / "bash" / name).is_file() for name in helper_names)
    assert not any((ROOT / "scripts" / "bash" / name).exists() for name in helper_names)


def test_kb_helpers_have_one_runtime_source_of_truth() -> None:
    helper_names = (
        "kb-lock.sh",
        "kb-pending-merge.sh",
        "kb-pending-write.sh",
        "kb-recover.sh",
        "kb-validate-evolution.sh",
        "kb-write.sh",
    )

    assert all((RUNTIME / "scripts" / "bash" / name).is_file() for name in helper_names)
    assert not any((ROOT / "scripts" / "bash" / name).exists() for name in helper_names)


def test_phase_timing_has_one_runtime_source_of_truth() -> None:
    assert (RUNTIME / "scripts" / "bash" / "phase-timing.sh").is_file()
    assert not (ROOT / "scripts" / "bash" / "phase-timing.sh").exists()


def test_prompt_budget_reads_prosaic_subagents_from_runtime_bundle() -> None:
    script = RUNTIME / "scripts" / "bash" / "prompt-budget.sh"
    text = script.read_text(encoding="utf-8")

    assert 'AGENTS_DIR="$REPO_ROOT/prosaic/subagents"' in text
    assert "extension/agents" not in text
    assert not (ROOT / "scripts" / "bash" / "prompt-budget.sh").exists()


def test_runtime_init_uses_controller_owned_project_mode() -> None:
    prose = (RUNTIME / "workflow" / "phases" / "init.md").read_text(
        encoding="utf-8"
    )

    assert "controller initializes `state.json.mode`" in prose
    assert "$SH_OUTPUT" not in prose
    assert "startup-banner.sh" not in prose


def test_legacy_startup_banner_is_not_part_of_active_runtime() -> None:
    assert not (RUNTIME / "scripts" / "bash" / "startup-banner.sh").exists()
    assert not (ROOT / "scripts" / "bash" / "startup-banner.sh").exists()


def test_build_light_gates_have_one_runtime_source_of_truth() -> None:
    assert (RUNTIME / "scripts" / "bash" / "build-light-gates.sh").is_file()
    assert not (ROOT / "scripts" / "bash" / "build-light-gates.sh").exists()


def test_belief_freshness_gate_has_one_runtime_source_of_truth() -> None:
    assert (RUNTIME / "scripts" / "bash" / "belief-freshness-check.sh").is_file()
    assert not (ROOT / "scripts" / "bash" / "belief-freshness-check.sh").exists()


def test_land_and_recovery_do_not_special_case_legacy_storage() -> None:
    modules = (
        ROOT / "src" / "harness" / "land.py",
        ROOT / "src" / "harness" / "recovery.py",
    )
    findings = []
    for module in modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify/" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_build_runtime_does_not_inject_or_ignore_speckit_state() -> None:
    from harness.ralph import _has_target_delivery_changes

    modules = (
        ROOT / "src" / "harness" / "llm_build_runner.py",
        ROOT / "src" / "harness" / "ralph.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in modules)

    assert "SPEC_KIT_ROOT" not in combined
    assert _has_target_delivery_changes([".specify/legacy-file.md"]) is True


def test_mempalace_runtime_reads_only_canonical_echelon_config() -> None:
    modules = (
        ROOT / "src" / "codegen" / "memory" / "context.py",
        ROOT / "src" / "echelon" / "mempalace_requirements.py",
        ROOT / "src" / "echelon" / "mempalace_retarget.py",
    )
    findings = []
    for module in modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify" in line or "specify extension" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_runtime_uses_echelon_owned_standalone_re_state() -> None:
    config = (RUNTIME / "config-template.yml").read_text(encoding="utf-8")
    discovery = (RUNTIME / "scripts" / "bash" / "re" / "discover-repos.sh").read_text(
        encoding="utf-8"
    )
    analysis = (RUNTIME / "scripts" / "bash" / "re" / "run-analysis.sh").read_text(
        encoding="utf-8"
    )
    bridge = (RUNTIME / "scripts" / "node" / "codegraph" / "codegraph-bridge.js").read_text(
        encoding="utf-8"
    )

    for text in (config, discovery, analysis, bridge):
        assert ".echelon/re" in text
        assert ".specify/echelon/re" not in text


def test_prosaic_re_commands_describe_echelon_owned_standalone_state() -> None:
    command = (PROSAIC / "commands" / "echelon.re-extract.md").read_text(
        encoding="utf-8"
    )

    assert "standalone `re-*`: `.echelon/re/state.json`" in command
    assert ".specify/echelon/re" not in command


def test_prosaic_runtime_does_not_direct_agents_to_legacy_squad_storage() -> None:
    commander = (PROSAIC / "subagents" / "echelon.commander.md").read_text(
        encoding="utf-8"
    )
    init = (PROSAIC / "commands" / "echelon.init.md").read_text(encoding="utf-8")
    veteran = (PROSAIC / "subagents" / "echelon.veteran.md").read_text(
        encoding="utf-8"
    )

    assert ".specify/squad" not in commander
    assert ".specify/squad" not in init
    assert ".specify/squad-global" not in veteran
    assert "~/.echelon/knowledge-base/" in veteran


def _run_cli_deploy_init(project: Path, home: Path, install_path: Path | None = None) -> dict:
    fake_bin = home / "bin"
    fake_bin.mkdir(parents=True)
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)

    config = project / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "deploy:\n"
        "  type: cli\n"
        "  health_check: 'true'\n"
        f"  install_path: '{install_path or ''}'\n",
        encoding="utf-8",
    )
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{fake_bin}:{Path(sys.executable).parent}:{os.environ['PATH']}",
    }
    subprocess.run(
        ["bash", str(RUNTIME / "scripts" / "bash" / "deploy-init.sh"), str(project)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    return json.loads((project / "runs" / "deploy-state.json").read_text(encoding="utf-8"))


def test_fresh_cli_deploy_init_uses_echelon_infrastructure(tmp_path: Path) -> None:
    project = tmp_path / "fresh-project"
    state = _run_cli_deploy_init(project, tmp_path / "home")

    assert state["global_state_dir"] == str(tmp_path / "home" / ".echelon" / "deploy")
    assert state["traefik_name"] == "echelon-traefik"
    assert state["deploy_network"] == "echelon-deploy"
    assert (tmp_path / "home" / ".echelon" / "deploy" / "fresh-project.json").exists()


def test_fresh_cli_deploy_init_ignores_unmigrated_legacy_global_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "legacy-project"
    home = tmp_path / "home"
    legacy_state = home / ".speckit-deploy" / "legacy-project.json"
    legacy_state.parent.mkdir(parents=True)
    legacy_state.write_text("{}", encoding="utf-8")

    state = _run_cli_deploy_init(project, home)

    assert state["global_state_dir"] == str(home / ".echelon" / "deploy")
    assert state["traefik_name"] == "echelon-traefik"
    assert state["deploy_network"] == "echelon-deploy"


def test_deploy_runtime_does_not_discover_or_default_to_speckit_resources() -> None:
    findings = []
    for script in (RUNTIME / "scripts" / "bash").glob("deploy*.sh"):
        for line_number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "speckit" in line.lower():
                findings.append(
                    f"{script.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )
    validate = RUNTIME / "scripts" / "bash" / "validate-deploy.sh"
    for line_number, line in enumerate(
        validate.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if "speckit" in line.lower():
            findings.append(
                f"{validate.relative_to(ROOT)}:{line_number}: {line.strip()}"
            )

    assert not findings, "\n".join(findings)


def test_cli_deploy_wrapper_reads_the_selected_global_state_directory(tmp_path: Path) -> None:
    project = tmp_path / "wrapper-project"
    home = tmp_path / "home"
    install_path = tmp_path / "bin"

    state = _run_cli_deploy_init(project, home, install_path)

    wrapper = (install_path / "wrapper-project").read_text(encoding="utf-8")
    assert f'_state_file="{state["global_state_dir"]}/wrapper-project.json"' in wrapper

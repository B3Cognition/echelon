"""Tests for polyrepo delivery runtime extension sync."""
from __future__ import annotations

from pathlib import Path
from shutil import copytree
import subprocess

import yaml

from echelon.cli import _sync_polyrepo_runtime_extension
from harness.runtime_surface import (
    DELIVERY_AGENT_DIRS,
    DELIVERY_BASH_FILES,
    DELIVERY_COMMAND_FILES,
    DELIVERY_TEMPLATE_FILES,
    is_delivery_workflow_phase_path,
)


def test_polyrepo_runtime_extension_copies_resolvable_codegraph_runtime(
    tmp_path: Path,
) -> None:
    """Target harness roots retain the CodeGraph SDK needed by delivery worktrees."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    runtime = source / "scripts" / "node" / "re"
    package = runtime / "node_modules" / "@colbymchenry" / "codegraph"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    package.mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (package / "package.json").write_text(
        '{"name":"@colbymchenry/codegraph","version":"1.4.1","main":"index.js"}\n',
        encoding="utf-8",
    )
    (package / "index.js").write_text("module.exports = { version: '1.4.1' };\n", encoding="utf-8")

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"
    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    deployed_runtime = harness_base / ".specify" / "extensions" / "echelon" / "scripts" / "node" / "re"
    resolved = subprocess.run(
        ["node", "-e", "require('@colbymchenry/codegraph')"],
        cwd=deployed_runtime,
        check=False,
        capture_output=True,
        text=True,
    )

    assert resolved.returncode == 0, resolved.stderr


def test_polyrepo_runtime_extension_excludes_python_migration_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose workspace migration helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "python").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "python" / "migrate_workspace_git.py").write_text(
        "print('migration helper')\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "workflow" / "definition.yaml").exists()
    assert not (runtime / "agents" / "control" / "commander.md").exists()
    assert not (runtime / "scripts" / "python").exists()


def test_polyrepo_runtime_extension_excludes_reverse_engineering_bash_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose RE shell helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "bash" / "re").mkdir(parents=True)
    (source / "scripts" / "bash").mkdir(exist_ok=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "bash" / "echelon-config-get.sh").write_text(
        "#!/usr/bin/env bash\n", encoding="utf-8"
    )
    (source / "scripts" / "bash" / "re" / "discover-repos.sh").write_text(
        "#!/usr/bin/env bash\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "scripts" / "bash" / "echelon-config-get.sh").exists()
    assert not (runtime / "scripts" / "bash" / "re").exists()


def test_polyrepo_runtime_extension_excludes_learning_and_journal_bash_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose learning/journal helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "bash").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    for name in [
        "belief-freshness-check.sh",
        "finalize-run.sh",
        "kb-write.sh",
        "kb-read-init.sh",
        "journal-append.sh",
        "phase-timing.sh",
        "post-execution-audit.sh",
        "pre-dispatch-gate.sh",
        "prompt-budget.sh",
        "state-backup.sh",
        "validate-journal-entry.sh",
        "echelon-config-get.sh",
    ]:
        (source / "scripts" / "bash" / name).write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    bash_dir = harness_base / ".specify" / "extensions" / "echelon" / "scripts" / "bash"
    assert (bash_dir / "echelon-config-get.sh").exists()
    assert not (bash_dir / "kb-write.sh").exists()
    assert not (bash_dir / "kb-read-init.sh").exists()
    assert not (bash_dir / "journal-append.sh").exists()
    assert not (bash_dir / "validate-journal-entry.sh").exists()
    assert not (bash_dir / "belief-freshness-check.sh").exists()
    assert not (bash_dir / "finalize-run.sh").exists()
    assert not (bash_dir / "phase-timing.sh").exists()
    assert not (bash_dir / "post-execution-audit.sh").exists()
    assert not (bash_dir / "pre-dispatch-gate.sh").exists()
    assert not (bash_dir / "prompt-budget.sh").exists()
    assert not (bash_dir / "state-backup.sh").exists()


def test_polyrepo_runtime_extension_exposes_only_delivery_safe_bash_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should expose only delivery bash helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "bash").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    for name in [
        "build-light-gates.sh",
        "cicd-fingerprint.sh",
        "context7-docs.sh",
        "deploy.sh",
        "detect-project.sh",
        "echelon-config-get.sh",
        "endocrine.sh",
        "fix-spa-base.sh",
        "preflight-speckit.sh",
        "python-detect.sh",
        "setup-worktree.sh",
        "startup-banner.sh",
        "state-lock.sh",
        "validate-deploy.sh",
    ]:
        (source / "scripts" / "bash" / name).write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    bash_dir = harness_base / ".specify" / "extensions" / "echelon" / "scripts" / "bash"
    assert (bash_dir / "echelon-config-get.sh").exists()
    assert (bash_dir / "endocrine.sh").exists()
    assert (bash_dir / "fix-spa-base.sh").exists()
    assert (bash_dir / "setup-worktree.sh").exists()
    assert (bash_dir / "startup-banner.sh").exists()
    assert (bash_dir / "validate-deploy.sh").exists()
    assert not (bash_dir / "build-light-gates.sh").exists()
    assert not (bash_dir / "cicd-fingerprint.sh").exists()
    assert not (bash_dir / "context7-docs.sh").exists()
    assert not (bash_dir / "deploy.sh").exists()
    assert not (bash_dir / "detect-project.sh").exists()
    assert not (bash_dir / "preflight-speckit.sh").exists()
    assert not (bash_dir / "python-detect.sh").exists()
    assert not (bash_dir / "state-lock.sh").exists()


def test_polyrepo_runtime_extension_excludes_phase_a_presets(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose preset seed material."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "presets" / "echelon-brownfield-cloud-native" / "templates").mkdir(
        parents=True
    )
    (source / "templates").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (
        source
        / "presets"
        / "echelon-brownfield-cloud-native"
        / "templates"
        / "spec-template.md"
    ).write_text("# preset spec template\n", encoding="utf-8")
    (source / "templates" / "tasks-template.md").write_text(
        "# runtime task template\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / "presets").exists()


def test_polyrepo_runtime_extension_excludes_phase_a_config_registers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose config belief registers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "config" / "belief-registers").mkdir(parents=True)
    (source / "templates").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "config" / "belief-registers" / "guardian.yaml").write_text(
        "beliefs: []\n", encoding="utf-8"
    )
    (source / ".extensionignore").write_text("presets/\n", encoding="utf-8")
    (source / "config-template.yml").write_text("config: template\n", encoding="utf-8")
    (source / "echelon-config.yml").write_text("config: defaults\n", encoding="utf-8")
    (source / "extension.yml").write_text("extension: {}\n", encoding="utf-8")
    (source / "templates" / "tasks-template.md").write_text(
        "# runtime task template\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / ".extensionignore").exists()
    assert not (runtime / "config").exists()
    assert not (runtime / "config-template.yml").exists()
    assert not (runtime / "echelon-config.yml").exists()
    assert not (runtime / "extension.yml").exists()


def test_polyrepo_runtime_extension_excludes_stack_playbooks(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose stack playbook context."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "stacks" / "example-stack").mkdir(parents=True)
    (source / "templates").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "stacks" / "example-stack" / "context.md").write_text(
        "# stack context\n", encoding="utf-8"
    )
    (source / "templates" / "tasks-template.md").write_text(
        "# runtime task template\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / "stacks").exists()


def test_polyrepo_runtime_extension_exposes_only_delivery_safe_templates(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose Phase A templates."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "templates").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "templates" / "tasks-template.md").write_text(
        "# runtime task template\n", encoding="utf-8"
    )
    (source / "templates" / "schema-consolidation-template.md").write_text(
        "# build finalize template\n", encoding="utf-8"
    )
    (source / "templates" / "strategic-overview-template.md").write_text(
        "# phase a template\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    templates = harness_base / ".specify" / "extensions" / "echelon" / "templates"
    assert (templates / "tasks-template.md").exists()
    assert (templates / "schema-consolidation-template.md").exists()
    assert not (templates / "strategic-overview-template.md").exists()


def test_polyrepo_runtime_extension_excludes_non_delivery_agent_prompts(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should expose only delivery-safe agents."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    for agent_dir in [
        "control",
        "build",
        "exploration",
        "solution",
        "re",
        "learning",
        "feasibility",
        "specialists",
    ]:
        (source / "agents" / agent_dir).mkdir(parents=True)
        (source / "agents" / agent_dir / f"{agent_dir}.md").write_text(
            f"# {agent_dir}\n", encoding="utf-8"
        )
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    agents = harness_base / ".specify" / "extensions" / "echelon" / "agents"
    assert not (agents / "control" / "commander.md").exists()
    assert (agents / "build" / "build.md").exists()
    assert not (agents / "exploration").exists()
    assert not (agents / "solution").exists()
    assert not (agents / "re").exists()
    assert not (agents / "learning").exists()
    assert not (agents / "feasibility").exists()
    assert not (agents / "specialists").exists()


def test_polyrepo_runtime_extension_excludes_non_delivery_command_docs(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should expose only delivery command docs."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "commands").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    for name in [
        "echelon.build.md",
        "echelon.verify-spec.md",
        "echelon.run.md",
        "echelon.re-extract.md",
    ]:
        (source / "commands" / name).write_text(f"# {name}\n", encoding="utf-8")

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    commands = harness_base / ".specify" / "extensions" / "echelon" / "commands"
    assert (commands / "echelon.build.md").exists()
    assert (commands / "echelon.verify-spec.md").exists()
    assert not (commands / "echelon.run.md").exists()
    assert not (commands / "echelon.re-extract.md").exists()


def test_polyrepo_runtime_extension_excludes_phase_a_and_re_workflow_phase_docs(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should expose only delivery phase contracts."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow" / "phases" / "appendices").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    for name in [
        "build-1-init.md",
        "verify-spec-1-init.md",
        "bugfix-1-init.md",
        "codegen-0-preflight.md",
        "codegen-A-preamble.md",
        "codegen-resume.md",
        "codegenlight-0-preflight.md",
        "codegenlight-resume.md",
        "phase1-what.md",
        "phase3-plan.md",
        "phase4-document.md",
        "re-extract-0-preflight.md",
        "re-planning-1-plan.md",
        "phase-exp-tasks-quality.md",
        "init.md",
    ]:
        (source / "workflow" / "phases" / name).write_text(
            f"# {name}\n", encoding="utf-8"
        )
    (source / "workflow" / "phases" / "appendices" / "build-8-verify-gates.md").write_text(
        "# appendix\n", encoding="utf-8"
    )
    (source / "workflow" / "phases" / "appendices" / "phase1-what-reference.md").write_text(
        "# phase-a appendix\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    phases = harness_base / ".specify" / "extensions" / "echelon" / "workflow" / "phases"
    assert (phases / "build-1-init.md").exists()
    assert (phases / "verify-spec-1-init.md").exists()
    assert (phases / "appendices" / "build-8-verify-gates.md").exists()
    assert not (phases / "appendices" / "phase1-what-reference.md").exists()
    assert not (phases / "bugfix-1-init.md").exists()
    assert not (phases / "codegen-0-preflight.md").exists()
    assert not (phases / "codegen-A-preamble.md").exists()
    assert not (phases / "codegen-resume.md").exists()
    assert not (phases / "codegenlight-0-preflight.md").exists()
    assert not (phases / "codegenlight-resume.md").exists()
    assert not (phases / "phase1-what.md").exists()
    assert not (phases / "phase3-plan.md").exists()
    assert not (phases / "phase4-document.md").exists()
    assert not (phases / "re-extract-0-preflight.md").exists()
    assert not (phases / "re-planning-1-plan.md").exists()
    assert not (phases / "phase-exp-tasks-quality.md").exists()
    assert not (phases / "init.md").exists()


def test_polyrepo_runtime_extension_prunes_workflow_definition_to_delivery_surface(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose Phase A/RE graph metadata."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow" / "phases").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "phases": [
                    {"id": "init", "spec_file": "workflow/phases/init.md"},
                    {"id": "phase1-what", "spec_file": "workflow/phases/phase1-what.md"},
                    {"id": "build-1-init", "spec_file": "workflow/phases/build-1-init.md"},
                    {
                        "id": "verify-spec-1-init",
                        "spec_file": "workflow/phases/verify-spec-1-init.md",
                    },
                ],
                "build": {"task_loop": {}},
                "verify_spec": {"phases": []},
                "re_extraction": {"phases": []},
                "re_planning": {"phases": []},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    definition = yaml.safe_load(
        (
            harness_base
            / ".specify"
            / "extensions"
            / "echelon"
            / "workflow"
            / "definition.yaml"
        ).read_text(encoding="utf-8")
    )
    assert [phase["id"] for phase in definition["phases"]] == [
        "build-1-init",
        "verify-spec-1-init",
    ]
    assert "build" in definition
    assert "verify_spec" in definition
    assert "re_extraction" not in definition
    assert "re_planning" not in definition


def test_polyrepo_runtime_extension_real_tree_matches_delivery_surface_policy(
    tmp_path: Path,
) -> None:
    """Workspace-target harness roots must not leak non-delivery runtime surface."""
    repo_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    source = workspace / ".specify" / "extensions" / "echelon"
    copytree(repo_root / "extension", source)
    harness_base = workspace / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(workspace, harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"

    commands = {p.name for p in (runtime / "commands").iterdir() if p.is_file()}
    assert commands == DELIVERY_COMMAND_FILES

    agent_dirs = {p.name for p in (runtime / "agents").iterdir() if p.is_dir()}
    assert agent_dirs == DELIVERY_AGENT_DIRS

    bash_files = {p.name for p in (runtime / "scripts" / "bash").iterdir() if p.is_file()}
    assert bash_files <= DELIVERY_BASH_FILES

    template_files = {p.name for p in (runtime / "templates").iterdir() if p.is_file()}
    assert template_files == DELIVERY_TEMPLATE_FILES

    phases_root = runtime / "workflow" / "phases"
    for path in phases_root.rglob("*.md"):
        relative = Path("workflow") / "phases" / path.relative_to(phases_root)
        assert is_delivery_workflow_phase_path(relative), relative
        assert not path.name.startswith(("bugfix-", "codegen-", "codegenlight-"))
        assert not path.name.startswith(("phase", "re-", "init"))

    for forbidden in [
        ".extensionignore",
        "config",
        "config-template.yml",
        "echelon-config.yml",
        "extension.yml",
        "presets",
        "scripts/bash/re",
        "scripts/node/context7",
        "scripts/node/codegraph/vendor",
        "scripts/python",
        "stacks",
    ]:
        assert not (runtime / forbidden).exists(), forbidden

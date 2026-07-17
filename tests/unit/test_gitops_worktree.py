"""Tests for GitOpsManager.get_latest_worktree."""
from __future__ import annotations

from pathlib import Path
from shutil import copytree
import time
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from harness.config import HarnessConfig
from harness.errors import GitOpsError
from harness.gitops import (
    GitOpsManager,
    _clean_branch_listing,
    prepare_codegraph_runtime,
    prepare_perlgraph_runtime,
)
from harness.runtime_surface import (
    DELIVERY_AGENT_DIRS,
    DELIVERY_BASH_FILES,
    DELIVERY_COMMAND_FILES,
    DELIVERY_TEMPLATE_FILES,
    is_delivery_workflow_phase_path,
)


def _make_gitops(tmp_path, *, llm_cli: str = "claude"):
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    config.llm.cli = llm_cli
    return GitOpsManager(config=config, base_dir=str(tmp_path))


def test_get_latest_worktree_returns_most_recent(tmp_path):
    """get_latest_worktree returns highest-mtime worktree dir for strategy."""
    gitops = _make_gitops(tmp_path)

    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
    iter1 = wt_base / "iter-1"
    iter2 = wt_base / "iter-2"
    iter1.mkdir(parents=True)
    time.sleep(0.02)
    iter2.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result == str(iter2)


def test_get_latest_worktree_returns_none_when_no_dir(tmp_path):
    """get_latest_worktree returns None when strategy directory does not exist."""
    gitops = _make_gitops(tmp_path)
    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_get_latest_worktree_returns_none_when_empty(tmp_path):
    """get_latest_worktree returns None when strategy dir exists but has no children."""
    gitops = _make_gitops(tmp_path)
    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
    wt_base.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_sync_runtime_extension_copies_untracked_project_extension(tmp_path):
    """Harness worktrees get the local Echelon extension even when it is untracked."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "workflow" / "definition.yaml").read_text(encoding="utf-8") == "workflow\n"
    assert not (runtime / "agents" / "control" / "commander.md").exists()
    assert ".specify/extensions/echelon/" in exclude.read_text(encoding="utf-8")


def test_prepare_codegraph_runtime_runs_locked_npm_ci(tmp_path, monkeypatch):
    """Delivery worktrees install the locked CodeGraph SDK without source copies."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    runtime = source / "scripts" / "node" / "codegraph"
    runtime.mkdir(parents=True)
    (runtime / "package-lock.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "harness.gitops.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    with patch("harness.gitops.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        prepare_codegraph_runtime(source)

    assert run.call_args.args[0] == [
        "/usr/bin/npm",
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--prefer-offline",
    ]
    assert run.call_args.kwargs["cwd"] == str(runtime)


def test_prepare_perlgraph_runtime_runs_locked_npm_ci_and_build(tmp_path, monkeypatch):
    """Delivery worktrees install and build the locked PerlGraph runtime."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    runtime = source / "scripts" / "node" / "perlgraph"
    runtime.mkdir(parents=True)
    (runtime / "package-lock.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "harness.gitops.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    with patch("harness.gitops.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        prepare_perlgraph_runtime(source)

    assert run.call_args_list[0].args[0] == [
        "/usr/bin/npm",
        "ci",
        "--include=dev",
        "--no-audit",
        "--no-fund",
        "--prefer-offline",
    ]
    assert run.call_args_list[0].kwargs["env"]["CXXFLAGS"] == "-std=c++20"
    assert run.call_args_list[1].args[0] == [
        "/usr/bin/npm",
        "run",
        "build",
    ]
    assert run.call_args_list[0].kwargs["cwd"] == str(runtime)
    assert run.call_args_list[1].kwargs["cwd"] == str(runtime)


def test_sync_runtime_extension_copies_codegraph_source_without_node_modules(tmp_path):
    """Delivery worktrees keep CodeGraph source but never copied dependencies."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "node" / "codegraph" / "node_modules" / "picomatch").mkdir(
        parents=True
    )
    (source / "scripts" / "node" / "context7").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "node" / "codegraph" / "codegraph-bridge.js").write_text(
        "console.log('bridge')\n", encoding="utf-8"
    )
    (source / "scripts" / "node" / "codegraph" / "package.json").write_text(
        '{"name":"codegraph"}\n', encoding="utf-8"
    )
    (source / "scripts" / "node" / "codegraph" / "package-lock.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (source / "scripts" / "node" / "codegraph" / "vendor").mkdir()
    (source / "scripts" / "node" / "codegraph" / "vendor" / "legacy.js").write_text(
        "legacy\n", encoding="utf-8"
    )
    (source / "scripts" / "node" / "context7" / "package.json").write_text(
        '{"name":"context7"}\n', encoding="utf-8"
    )
    (
        source
        / "scripts"
        / "node"
        / "codegraph"
        / "node_modules"
        / "picomatch"
        / "package.json"
    ).write_text('{"name":"picomatch"}\n', encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime_node = worktree / ".specify" / "extensions" / "echelon" / "scripts" / "node"
    assert (runtime_node / "codegraph" / "codegraph-bridge.js").exists()
    assert (runtime_node / "codegraph" / "package.json").exists()
    assert (runtime_node / "codegraph" / "package-lock.json").exists()
    assert not (runtime_node / "codegraph" / "vendor").exists()
    assert not (runtime_node / "context7").exists()
    assert not (runtime_node / "codegraph" / "node_modules").exists()


def test_sync_runtime_extension_copies_perlgraph_source_without_build_artifacts(tmp_path):
    """Delivery worktrees keep PerlGraph source but never copied dependencies/build output."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "node" / "perlgraph" / "node_modules" / "commander").mkdir(
        parents=True
    )
    (source / "scripts" / "node" / "perlgraph" / "dist" / "cli").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "node" / "perlgraph" / "package.json").write_text(
        '{"name":"perlgraph"}\n', encoding="utf-8"
    )
    (source / "scripts" / "node" / "perlgraph" / "package-lock.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (source / "scripts" / "node" / "perlgraph" / "src").mkdir()
    (source / "scripts" / "node" / "perlgraph" / "src" / "index.ts").write_text(
        "export {}\n", encoding="utf-8"
    )
    (
        source
        / "scripts"
        / "node"
        / "perlgraph"
        / "node_modules"
        / "commander"
        / "package.json"
    ).write_text('{"name":"commander"}\n', encoding="utf-8")
    (
        source / "scripts" / "node" / "perlgraph" / "dist" / "cli" / "perlgraph.js"
    ).write_text("#!/usr/bin/env node\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime_node = worktree / ".specify" / "extensions" / "echelon" / "scripts" / "node"
    assert (runtime_node / "perlgraph" / "package.json").exists()
    assert (runtime_node / "perlgraph" / "package-lock.json").exists()
    assert (runtime_node / "perlgraph" / "src" / "index.ts").exists()
    assert not (runtime_node / "perlgraph" / "node_modules").exists()
    assert not (runtime_node / "perlgraph" / "dist").exists()


def test_sync_runtime_extension_refreshes_codegraph_source_when_runtime_ready(tmp_path):
    """Ready worktrees still receive an updated CodeGraph bridge and lockfile."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "node" / "codegraph").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n",
        encoding="utf-8",
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (
        source / "scripts" / "node" / "codegraph" / "codegraph-bridge.js"
    ).write_text("fresh bridge\n", encoding="utf-8")
    (source / "scripts" / "node" / "codegraph" / "package-lock.json").write_text(
        "fresh lock\n", encoding="utf-8"
    )

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    dest = worktree / ".specify" / "extensions" / "echelon"
    (dest / "agents" / "control").mkdir(parents=True)
    (dest / "workflow").mkdir(parents=True)
    (dest / "agents" / "control" / "commander.md").write_text(
        "stale commander\n",
        encoding="utf-8",
    )
    (dest / "workflow" / "definition.yaml").write_text(
        "stale workflow\n",
        encoding="utf-8",
    )
    (dest / "scripts" / "node" / "codegraph").mkdir(parents=True)
    (dest / "scripts" / "node" / "codegraph" / "codegraph-bridge.js").write_text(
        "stale bridge\n", encoding="utf-8"
    )
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    assert (
        dest / "scripts" / "node" / "codegraph" / "codegraph-bridge.js"
    ).read_text(encoding="utf-8") == "fresh bridge\n"
    assert (
        dest / "scripts" / "node" / "codegraph" / "package-lock.json"
    ).read_text(encoding="utf-8") == "fresh lock\n"
    assert not (dest / "agents" / "control" / "commander.md").exists()


def test_sync_runtime_extension_excludes_python_migration_helpers(tmp_path):
    """Delivery worktrees should not expose workspace migration helper source."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "workflow" / "definition.yaml").exists()
    assert not (runtime / "agents" / "control" / "commander.md").exists()
    assert not (runtime / "scripts" / "python").exists()


def test_sync_runtime_extension_excludes_reverse_engineering_bash_helpers(tmp_path):
    """Delivery worktrees should not expose reverse-engineering shell helpers."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "scripts" / "bash" / "echelon-config-get.sh").exists()
    assert not (runtime / "scripts" / "bash" / "re").exists()


def test_sync_runtime_extension_excludes_learning_and_journal_bash_helpers(tmp_path):
    """Delivery worktrees should not expose Phase A learning/journal helpers."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    bash_dir = worktree / ".specify" / "extensions" / "echelon" / "scripts" / "bash"
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


def test_sync_runtime_extension_exposes_only_delivery_safe_bash_helpers(tmp_path):
    """Delivery worktrees should expose only bash helpers used by delivery contracts."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    bash_dir = worktree / ".specify" / "extensions" / "echelon" / "scripts" / "bash"
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


def test_sync_runtime_extension_excludes_phase_a_presets(tmp_path):
    """Delivery worktrees should not expose Phase A preset seed material."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / "presets").exists()


def test_sync_runtime_extension_excludes_phase_a_config_registers(tmp_path):
    """Delivery worktrees should not expose Phase A/config belief registers."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / ".extensionignore").exists()
    assert not (runtime / "config").exists()
    assert not (runtime / "config-template.yml").exists()
    assert not (runtime / "echelon-config.yml").exists()
    assert not (runtime / "extension.yml").exists()


def test_sync_runtime_extension_excludes_stack_playbooks(tmp_path):
    """Delivery worktrees should not expose Phase A stack playbook context."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / "stacks").exists()


def test_sync_runtime_extension_exposes_only_delivery_safe_templates(tmp_path):
    """Delivery worktrees should not expose Phase A planning templates."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    templates = worktree / ".specify" / "extensions" / "echelon" / "templates"
    assert (templates / "tasks-template.md").exists()
    assert (templates / "schema-consolidation-template.md").exists()
    assert not (templates / "strategic-overview-template.md").exists()


def test_sync_runtime_extension_excludes_non_delivery_agent_prompts(tmp_path):
    """Delivery worktrees should expose only delivery-safe raw agent prompts."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    agents = worktree / ".specify" / "extensions" / "echelon" / "agents"
    assert not (agents / "control" / "commander.md").exists()
    assert (agents / "build" / "build.md").exists()
    assert not (agents / "exploration").exists()
    assert not (agents / "solution").exists()
    assert not (agents / "re").exists()
    assert not (agents / "learning").exists()
    assert not (agents / "feasibility").exists()
    assert not (agents / "specialists").exists()


def test_sync_runtime_extension_excludes_non_delivery_command_docs(tmp_path):
    """Delivery worktrees should expose only delivery-safe command contracts."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    commands = worktree / ".specify" / "extensions" / "echelon" / "commands"
    assert (commands / "echelon.build.md").exists()
    assert (commands / "echelon.verify-spec.md").exists()
    assert not (commands / "echelon.run.md").exists()
    assert not (commands / "echelon.re-extract.md").exists()


def test_sync_runtime_extension_excludes_phase_a_and_re_workflow_phase_docs(tmp_path):
    """Delivery worktrees should expose only delivery workflow phase contracts."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow" / "phases" / "appendices").mkdir(parents=True)
    (source / "commands").mkdir()
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    phases = worktree / ".specify" / "extensions" / "echelon" / "workflow" / "phases"
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


def test_sync_runtime_extension_prunes_workflow_definition_to_delivery_surface(tmp_path):
    """Delivery worktrees should not expose Phase A/RE workflow graph metadata."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow" / "phases").mkdir(parents=True)
    (source / "commands").mkdir()
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

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    definition = yaml.safe_load(
        (
            worktree
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


def test_sync_runtime_extension_real_tree_matches_delivery_surface_policy(tmp_path):
    """The installed extension tree must not leak non-delivery runtime surface."""
    repo_root = Path(__file__).resolve().parents[2]
    source = tmp_path / ".specify" / "extensions" / "echelon"
    copytree(repo_root / "extension", source)

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path, llm_cli="codex")
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    runtime = worktree / ".specify" / "extensions" / "echelon"

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


def test_sync_runtime_extension_materializes_claude_command_skills(tmp_path):
    """Harness worktrees get ignored Claude skill wrappers from runtime commands."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "commands").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "commands" / "echelon.verify-spec.md").write_text(
        "---\n"
        "name: speckit.echelon.verify-spec\n"
        "description: Verify spec\n"
        "---\n\n"
        "Read `agents/control/commander.md` and `workflow/definition.yaml`.\n\n"
        "$ARGUMENTS\n",
        encoding="utf-8",
    )

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    skill = worktree / ".claude" / "skills" / "speckit-echelon-verify-spec" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "name: speckit-echelon-verify-spec" in text
    assert "agents/control/commander.md" not in text
    assert "workflow/definition.yaml" not in text
    assert "$ARGUMENTS" in text
    assert ".claude/skills/speckit-echelon-verify-spec/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_skips_claude_command_skills_for_codex(tmp_path):
    """Provider-specific Claude skill wrappers must not appear for Codex delivery."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "commands").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "commands" / "echelon.verify-spec.md").write_text(
        "---\n"
        "name: speckit.echelon.verify-spec\n"
        "description: Verify spec\n"
        "---\n\n"
        "$ARGUMENTS\n",
        encoding="utf-8",
    )

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path, llm_cli="codex")
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    assert not (worktree / ".claude" / "skills").exists()
    assert ".claude/skills" not in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_materializes_claude_agents(tmp_path):
    """Harness worktrees get ignored Claude agent registry files from runtime agents."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "agents" / "build").mkdir(parents=True)
    (source / "agents" / "exploration").mkdir(parents=True)
    (source / "agents" / "solution").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "agents" / "build" / "spec-guard.md").write_text(
        "# SPEC GUARD\n\nguard\n",
        encoding="utf-8",
    )
    (source / "agents" / "exploration" / "scout.md").write_text(
        "# SCOUT\n\nscout\n",
        encoding="utf-8",
    )
    (source / "agents" / "solution" / "architect.md").write_text(
        "# ARCHITECT\n\narchitect\n",
        encoding="utf-8",
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    commander = worktree / ".claude" / "agents" / "speckit-echelon-commander.md"
    spec_guard = worktree / ".claude" / "agents" / "speckit-echelon-spec-guard.md"
    scout = worktree / ".claude" / "agents" / "speckit-echelon-scout.md"
    architect = worktree / ".claude" / "agents" / "speckit-echelon-architect.md"
    assert not commander.exists()
    spec_guard_text = spec_guard.read_text(encoding="utf-8")
    assert spec_guard_text.startswith("---\nname: speckit-echelon-spec-guard\n")
    assert "description: SPEC GUARD" in spec_guard_text
    assert "# SPEC GUARD\n\nguard\n" in spec_guard_text
    assert not scout.exists()
    assert not architect.exists()
    assert ".claude/agents/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_skips_claude_agents_for_codex(tmp_path):
    """Provider-specific Claude agent wrappers must not appear for Codex delivery."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "agents" / "build").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "agents" / "build" / "spec-guard.md").write_text(
        "# SPEC GUARD\n\nguard\n",
        encoding="utf-8",
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path, llm_cli="codex")
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    assert not (worktree / ".claude" / "agents").exists()
    assert ".claude/agents" not in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_fails_before_llm_when_extension_missing(tmp_path):
    """Missing runtime prompts fail deterministically instead of inviting global search."""
    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)

    try:
        gitops.sync_runtime_extension(worktree)
    except Exception as exc:
        assert ".specify/extensions/echelon" in str(exc)
        assert "Run `echelon workspace init`" in str(exc)
    else:
        raise AssertionError("expected missing runtime extension to fail")


def test_create_worktree_removes_stale_runs_checkout_before_retry(tmp_path):
    """Feature-branch mode must not reuse old harness worktrees from prior builds."""
    mirror = tmp_path / "runs" / "mirror.git"
    mirror.mkdir(parents=True)
    stale = tmp_path / "runs" / "build-old" / "worktrees" / "default" / "iter-0"
    stale.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)

    add_error = GitOpsError(
        f"fatal: '001-feature' is already used by worktree at '{stale}'",
        command="git worktree add",
    )

    calls: list[tuple[list[str], str | None]] = []

    def fake_run_git(args, cwd=None, **_kwargs):
        calls.append((args, cwd))
        if args[:2] == ["worktree", "add"] and len(
            [call for call in calls if call[0][:2] == ["worktree", "add"]]
        ) == 1:
            raise add_error
        return SimpleNamespace(stdout="")

    with patch("harness.gitops._run_git", side_effect=fake_run_git), patch.object(
        gitops, "sync_runtime_extension"
    ) as sync_runtime:
        result = gitops.create_worktree(
            "001-feature",
            "default",
            0,
            base_branch="001-feature",
            build_id="build-new",
        )

    expected = tmp_path / "runs" / "build-new" / "worktrees" / "default" / "iter-0"
    assert result == str(expected)
    assert (
        ["worktree", "remove", "--force", str(stale)],
        str(mirror),
    ) in calls
    assert (
        ["worktree", "add", str(expected), "001-feature"],
        str(mirror),
    ) in calls
    sync_runtime.assert_called_once_with(expected, prepare_codegraph=False)


def test_create_worktree_removes_stale_legacy_runs_checkout_before_retry(tmp_path):
    """Legacy harness/* branches must not be blocked by stale prior worktrees."""
    mirror = tmp_path / "runs" / "mirror.git"
    mirror.mkdir(parents=True)
    stale = tmp_path / "runs" / "build-old" / "worktrees" / "default" / "iter-1"
    stale.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)
    branch_name = "harness/905-import-prose/default/iter-1"
    add_error = GitOpsError(
        f"fatal: '{branch_name}' is already used by worktree at '{stale}'",
        command="git worktree add",
    )

    calls: list[tuple[list[str], str | None]] = []

    def fake_run_git(args, cwd=None, **_kwargs):
        calls.append((args, cwd))
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return SimpleNamespace(stdout="main\n", returncode=0)
        if args[:2] == ["rev-parse", "--verify"]:
            return SimpleNamespace(stdout="", returncode=0)
        if args[:2] == ["worktree", "add"] and len(
            [call for call in calls if call[0][:2] == ["worktree", "add"]]
        ) == 1:
            raise add_error
        return SimpleNamespace(stdout="", returncode=0)

    with patch("harness.gitops._run_git", side_effect=fake_run_git), patch.object(
        gitops, "sync_runtime_extension"
    ) as sync_runtime:
        result = gitops.create_worktree(
            "905-import-prose",
            "default",
            1,
            base_branch=None,
            build_id="build-new",
        )

    expected = tmp_path / "runs" / "build-new" / "worktrees" / "default" / "iter-1"
    assert result == str(expected)
    assert (
        ["worktree", "remove", "--force", str(stale)],
        str(mirror),
    ) in calls
    assert calls.count((["worktree", "add", str(expected), branch_name], str(mirror))) == 2
    sync_runtime.assert_called_once_with(expected, prepare_codegraph=False)


def test_create_worktree_bases_legacy_iteration_on_previous_iteration_branch(tmp_path):
    """Legacy harness/* iterations continue from the prior iteration branch."""
    mirror = tmp_path / "runs" / "mirror.git"
    mirror.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)
    calls: list[tuple[list[str], str | None]] = []
    new_branch = "harness/905-import-prose/default/iter-2"
    previous_branch = "harness/905-import-prose/default/iter-1"

    def fake_run_git(args, cwd=None, **_kwargs):
        calls.append((args, cwd))
        if args == ["symbolic-ref", "HEAD"]:
            return SimpleNamespace(stdout="refs/heads/main\n", returncode=0)
        if args == ["rev-parse", "--verify", f"refs/heads/{new_branch}"]:
            return SimpleNamespace(stdout="", returncode=1)
        if args == ["rev-parse", "--verify", f"refs/heads/{previous_branch}"]:
            return SimpleNamespace(stdout=previous_branch + "\n", returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    with patch("harness.gitops._run_git", side_effect=fake_run_git), patch.object(
        gitops, "sync_runtime_extension"
    ):
        gitops.create_worktree(
            "905-import-prose",
            "default",
            2,
            base_branch=None,
            build_id="build-new",
        )

    assert (
        ["branch", new_branch, previous_branch],
        str(mirror),
    ) in calls


def test_clean_branch_listing_strips_git_worktree_marker():
    """`git branch --list` prefixes branches checked out in worktrees with `+`."""
    assert _clean_branch_listing("+ 001-feature") == "001-feature"
    assert _clean_branch_listing("* main") == "main"
    assert _clean_branch_listing("  002-other") == "002-other"

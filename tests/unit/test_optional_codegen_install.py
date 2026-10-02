from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install.sh"


def _installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_has_no_codegen_opt_in() -> None:
    script = _installer()

    parser = script.index('case "$1" in')
    uv_check = script.index("# ── uv check")

    assert parser < uv_check
    assert "--help" in script[parser:uv_check]
    assert "WITH_CODEGEN" not in script
    assert "SOAR_VERSION" not in script
    assert "SOAR_DIR" not in script
    assert "CODEGEN_LAUNCHER" not in script
    assert "exit 2" in script[parser:uv_check]


def test_installer_preserves_python_prosaic_without_node(tmp_path: Path) -> None:
    """The old Node-optional branch deleted the Python-installed entry point."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    (isolated_home / ".bashrc").touch()
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "runtime/workflow").mkdir(parents=True)
    installer = checkout / "scripts/install.sh"
    shutil.copy2(INSTALLER, installer)
    shutil.copy2(
        ROOT / "runtime/workflow/journal-entry-types.yaml",
        checkout / "runtime/workflow/journal-entry-types.yaml",
    )
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("bash", "dirname", "grep", "mkdir", "chmod", "rm"):
        executable = shutil.which(name)
        assert executable is not None
        (commands / name).symlink_to(executable)
    # Model the package manager's entry-point installation, without fetching
    # Echelon's heavy dependencies or warming the real shared memory store.
    python_code = (
        f"#!{sys.executable}\nimport os, sys\n"
        'if "import chromadb" in sys.argv[-1]: sys.exit(1)\n'
        f"os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
    )
    fake_uv = commands / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1] == 'venv': sys.exit(0)\n"
        "assert sys.argv[1:3] == ['pip', 'install']\n"
        "bin_dir = pathlib.Path(os.environ['HOME']) / '.echelon/venv/bin'\n"
        "bin_dir.mkdir(parents=True, exist_ok=True)\n"
        f"(bin_dir / 'python').write_text({python_code!r})\n"
        "(bin_dir / 'python').chmod(0o755)\n"
        "for name, version in [('echelon', '4.1.1'), ('prosaic', '0.3.0')]:\n"
        f"    (bin_dir / name).write_text('#!{sys.executable}\\nprint(' + repr(version) + ')\\n')\n"
        "    (bin_dir / name).chmod(0o755)\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = {
        **os.environ,
        "HOME": str(isolated_home),
        "SHELL": "/bin/bash",
        "PATH": str(commands),
        "ECHELON_HOME": str(isolated_home / ".echelon"),
    }
    assert shutil.which("node", path=environment["PATH"]) is None
    result = subprocess.run(
        [str(commands / "bash"), str(installer)],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prosaic = isolated_home / ".echelon/venv/bin/prosaic"
    assert prosaic.is_file(), "installer removed the Python Prosaic entry point"
    checked = subprocess.run([str(prosaic), "--version"], capture_output=True, text=True)
    assert checked.returncode == 0 and checked.stdout.strip() == "0.3.0"
    assert not (isolated_home / ".echelon/node/prosaic").exists()


def test_installer_finishes_with_prosaic_first_workspace_setup() -> None:
    script = _installer()

    assert "specify extension add" not in script
    assert "Register the spec-kit extension" not in script
    assert "echelon workspace init" in script
    assert "Prosaic and runtime bundles" in script


@pytest.mark.parametrize(
    ("argument", "expected_code", "expected_text"),
    [
        ("--help", 0, "Usage: bash scripts/install.sh [--help]"),
        ("--unknown", 2, "Unknown option: --unknown"),
    ],
)
def test_read_only_installer_options_exit_before_environment_checks(
    tmp_path: Path,
    argument: str,
    expected_code: int,
    expected_text: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        ["bash", str(INSTALLER), argument],
        cwd=ROOT,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code
    assert expected_text in result.stdout + result.stderr
    assert list(home.iterdir()) == []


def test_mempalace_setup_remains_unconditional() -> None:
    script = _installer()

    memory = script.index("# ── 4. Memory directory")
    warmup = script.index("# ── 5. Warm up embedding model")

    assert memory < warmup
    assert "chromadb.PersistentClient" in script[warmup:]


def test_installer_has_no_codegen_launcher() -> None:
    script = _installer()

    assert "codegen" not in script.lower()


def test_installer_recommends_poppler_without_installing_it() -> None:
    script = _installer()

    install = script.index('uv pip install -q --reinstall --python "$VENV_DIR" -e "$ECHELON_DIR"')
    done = script.index("# ── Done")

    assert "pdftotext (Poppler) is recommended for higher-fidelity PDF extraction" in script[install:done]
    assert "brew install poppler" not in script
    assert "apt install poppler-utils" not in script


def test_packaging_keeps_mempalace_but_not_codegen_entry_point() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = metadata["project"]["dependencies"]
    scripts = metadata["project"]["scripts"]

    assert any(dependency.startswith("mempalace ") for dependency in dependencies)
    assert "codegen" not in scripts


def test_installation_guide_does_not_recommend_rejected_legacy_init_flag() -> None:
    installation = (ROOT / "INSTALLATION.md").read_text(encoding="utf-8")

    assert "--legacy-spec-kit" not in installation
    assert "echelon workspace migrate-to-prosaic" in installation


def test_readme_describes_prosaic_first_provider_dispatch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    execution = readme.split("## Execution Paths", 1)[1].split(
        "## Delivery Harness", 1
    )[0]

    assert ".echelon/prosaic" in execution
    assert "prosaic inspect" in execution
    assert "AICodingCliProvider" in execution
    assert "specify extension add" not in execution
    assert "speckit.echelon" not in execution


def test_readme_command_catalog_lists_only_echelon_cli_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = readme.split("## Commands", 1)[1].split("## Codegen Pipeline", 1)[0]

    assert "Spec-kit skill" not in commands
    assert "speckit.echelon" not in commands
    assert "*(spec-kit only)*" not in commands
    assert "| Terminal | Purpose |" in commands


def test_current_user_docs_do_not_describe_speckit_runtime() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    fallback = (ROOT / "docs" / "fallback-mode.md").read_text(encoding="utf-8")

    assert "speckit" not in readme.lower()
    assert "spec-kit" not in readme.lower()
    assert "speckit" not in fallback.lower()
    assert "spec-kit" not in fallback.lower()
    assert "provider invocation" in fallback.lower()


def test_active_repository_guidance_and_root_templates_are_speckit_free() -> None:
    active_text_surfaces = [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "knowledge-base" / "confidence-thresholds.yaml",
    ]
    root_templates = sorted((ROOT / "templates").glob("*.md"))

    offenders = []
    for path in [*active_text_surfaces, *root_templates]:
        text = path.read_text(encoding="utf-8").lower()
        if "speckit" in text or "spec-kit" in text or ".specify" in text:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []

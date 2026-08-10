from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install.sh"


def _installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_parses_codegen_opt_in_before_environment_checks() -> None:
    script = _installer()

    parser = script.index('case "$1" in')
    uv_check = script.index("# ── uv check")

    assert parser < uv_check
    assert "--with-codegen" in script[parser:uv_check]
    assert "--help" in script[parser:uv_check]
    assert 'WITH_CODEGEN="1"' in script[parser:uv_check]
    assert "exit 2" in script[parser:uv_check]


def test_installer_provisions_pinned_prosaic_runtime_and_launcher() -> None:
    script = _installer()

    assert 'PROSAIC_GIT_SPEC="git+ssh://git@github.com/B3Cognition/prosaic.git#b6c9701"' in script
    assert 'PROSAIC_NODE_DIR="$NODE_RUNTIME_ROOT/prosaic"' in script
    assert 'npm install --prefix "$PROSAIC_NODE_DIR" --no-audit --no-fund "$PROSAIC_GIT_SPEC"' in script
    assert 'PROSAIC_LAUNCHER="$VENV_DIR/bin/prosaic"' in script
    assert 'exec node "$PROSAIC_NODE_DIR/node_modules/prosaic/dist/cli/index.js" "\\$@"' in script


def test_installer_finishes_with_prosaic_first_workspace_setup() -> None:
    script = _installer()

    assert "specify extension add" not in script
    assert "Register the spec-kit extension" not in script
    assert "echelon workspace init" in script
    assert "Prosaic and runtime bundles" in script


@pytest.mark.parametrize(
    ("argument", "expected_code", "expected_text"),
    [
        ("--help", 0, "Usage: bash scripts/install.sh [--with-codegen]"),
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


def test_soar_installation_is_inside_codegen_opt_in_branch() -> None:
    script = _installer()

    opt_in = script.index('if [ "$WITH_CODEGEN" = "1" ]; then')
    download = script.index("_download_soar", opt_in)
    memory = script.index("# ── 4. Memory directory")

    assert opt_in < download < memory
    assert script.index('printf \'\\n# SOAR binary', opt_in) < memory


def test_mempalace_setup_remains_unconditional() -> None:
    script = _installer()

    memory = script.index("# ── 4. Memory directory")
    warmup = script.index("# ── 5. Warm up embedding model")

    assert memory < warmup
    assert "if [ \"$WITH_CODEGEN\"" not in script[memory:warmup]
    assert "chromadb.PersistentClient" in script[warmup:]


def test_installer_manages_codegen_launcher_by_mode() -> None:
    script = _installer()

    assert 'CODEGEN_LAUNCHER="$VENV_DIR/bin/codegen"' in script
    assert "from codegen.cli.codegen_cli import main" in script
    assert 'rm -f "$CODEGEN_LAUNCHER"' in script
    assert "bash scripts/install.sh --with-codegen" in script


def test_installer_recommends_poppler_without_installing_it() -> None:
    script = _installer()

    install = script.index('uv pip install -q --python "$VENV_DIR" -e "$ECHELON_DIR"')
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


def test_codegen_guard_exits_with_install_instruction_when_launcher_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli

    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(cli.sys, "executable", str(python))

    with pytest.raises(SystemExit) as exc_info:
        cli._require_codegen_installation()

    assert exc_info.value.code == 2
    assert "bash scripts/install.sh --with-codegen" in capsys.readouterr().err


def test_codegen_guard_accepts_executable_sibling_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli

    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.touch()
    launcher = bin_dir / "codegen"
    launcher.touch()
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(cli.sys, "executable", str(python))

    cli._require_codegen_installation()


def test_installation_docs_describe_codegen_as_opt_in() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "INSTALLATION.md").read_text(encoding="utf-8")
    guidance = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("AGENTS.md", "CLAUDE.md")
    )

    assert "bash ~/echelon/scripts/install.sh --with-codegen" in readme
    assert "installs four CLI tools" not in readme
    assert "SOAR binary are bundled" not in readme
    assert "all four CLIs" not in installation
    assert "Reinstall the four CLIs" not in guidance


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

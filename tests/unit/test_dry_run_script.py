import subprocess
from pathlib import Path
import shutil


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bash" / "dry-run.sh"


def _run_dry_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _mutated_dry_run(
    tmp_path: Path,
    *,
    replace: tuple[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run the checked-in validator against one deliberately broken CLI tree."""
    root = tmp_path / "mutated-repository"
    (root / "scripts" / "bash").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "bash" / "dry-run.sh")
    shutil.copytree(REPO_ROOT / "src", root / "src", symlinks=True)
    (root / "prosaic").symlink_to(REPO_ROOT / "prosaic", target_is_directory=True)
    (root / "runtime").symlink_to(REPO_ROOT / "runtime", target_is_directory=True)

    cli_path = root / "src" / "echelon" / "cli_app.py"
    original, replacement = replace
    source = cli_path.read_text(encoding="utf-8")
    assert source.count(original) == 1
    cli_path.write_text(source.replace(original, replacement), encoding="utf-8")
    return subprocess.run(
        ["bash", str(root / "scripts" / "bash" / "dry-run.sh")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_successful_dry_run(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Bundle validation failed" not in output
    assert "Repository root:" in output
    assert "Prosaic root:" in output
    assert "Runtime root:" in output
    assert "workflow definition contract is valid" in output


def test_dry_run_accepts_repo_root_default() -> None:
    _assert_successful_dry_run(_run_dry_run())


def test_dry_run_accepts_prosaic_root_argument() -> None:
    _assert_successful_dry_run(_run_dry_run("prosaic"))


def test_dry_run_accepts_runtime_root_argument() -> None:
    _assert_successful_dry_run(_run_dry_run("runtime"))


def test_dry_run_does_not_require_legacy_extension_tree(tmp_path: Path) -> None:
    (tmp_path / "prosaic").symlink_to(REPO_ROOT / "prosaic", target_is_directory=True)
    (tmp_path / "runtime").symlink_to(REPO_ROOT / "runtime", target_is_directory=True)

    result = _run_dry_run(str(tmp_path))

    _assert_successful_dry_run(result)
    assert "extension" not in (result.stdout + result.stderr).lower()


def test_dry_run_rejects_detached_re_root(tmp_path: Path) -> None:
    result = _mutated_dry_run(
        tmp_path,
        replace=(
            'app.add_typer(re_app, name="re")',
            'app.add_typer(re_app, name="reverse-engineering")',
        ),
    )

    assert result.returncode != 0
    assert "RE Typer root attachment is missing" in result.stdout + result.stderr


def test_dry_run_rejects_removed_hidden_re_command(tmp_path: Path) -> None:
    result = _mutated_dry_run(
        tmp_path,
        replace=(
            '@re_app.command("analyze", hidden=True)',
            '@app.command("analyze", hidden=True)',
        ),
    )

    assert result.returncode != 0
    assert "RE commands are missing: analyze" in result.stdout + result.stderr


def test_dry_run_rejects_engine_option_owned_by_shadow_parameter(
    tmp_path: Path,
) -> None:
    result = _mutated_dry_run(
        tmp_path,
        replace=(
            '''    engine: ReEngine = typer.Option(
        ReEngine.V1,
        "--engine",''',
            '''    engine: ReEngine = typer.Option(
        ReEngine.V1,
        "--v2-engine",''',
        ),
    )
    cli_path = tmp_path / "mutated-repository" / "src" / "echelon" / "cli_app.py"
    source = cli_path.read_text(encoding="utf-8")
    original = '''    shadow: bool = typer.Option(
        False,
        "--shadow",'''
    replacement = '''    shadow: bool = typer.Option(
        False,
        "--shadow",
        "--engine",'''
    assert source.count(original) == 1
    cli_path.write_text(source.replace(original, replacement), encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            str(
                tmp_path
                / "mutated-repository"
                / "scripts"
                / "bash"
                / "dry-run.sh"
            ),
        ],
        cwd=tmp_path / "mutated-repository",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "RE run option ownership is invalid: engine -> --engine" in (
        result.stdout + result.stderr
    )

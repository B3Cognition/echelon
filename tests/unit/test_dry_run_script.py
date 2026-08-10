import subprocess
from pathlib import Path


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

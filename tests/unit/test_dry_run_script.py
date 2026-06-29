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
    assert "FAILURES detected" not in output
    assert "Repository root:" in output
    assert "Extension root:" in output
    assert "workflow definition contract is valid" in output


def test_dry_run_accepts_repo_root_default() -> None:
    _assert_successful_dry_run(_run_dry_run())


def test_dry_run_accepts_extension_root_argument() -> None:
    _assert_successful_dry_run(_run_dry_run("extension"))

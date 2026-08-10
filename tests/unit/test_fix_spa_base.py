"""Behavior contracts for the deployed SPA base-path helper."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runtime" / "scripts" / "bash" / "fix-spa-base.sh"


def _run(
    project_root: Path,
    app_name: str,
    app_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(project_root), app_name, str(app_dir)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_vite_base_is_added_in_monorepo_app_directory(tmp_path: Path) -> None:
    app_dir = tmp_path / "apps" / "web"
    app_dir.mkdir(parents=True)
    config = app_dir / "vite.config.ts"
    config.write_text(
        "import { defineConfig } from 'vite'\n"
        "export default defineConfig({ plugins: [] })\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, "console", app_dir)

    assert "base: '/console/'" in config.read_text(encoding="utf-8")
    assert "added base '/console/'" in result.stdout


def test_next_base_path_is_idempotent(tmp_path: Path) -> None:
    app_dir = tmp_path / "apps" / "portal"
    app_dir.mkdir(parents=True)
    config = app_dir / "next.config.js"
    config.write_text(
        "module.exports = { reactStrictMode: true }\n",
        encoding="utf-8",
    )

    first = _run(tmp_path, "portal", app_dir)
    after_first = config.read_text(encoding="utf-8")
    second = _run(tmp_path, "portal", app_dir)

    assert "basePath: '/portal'" in after_first
    assert config.read_text(encoding="utf-8") == after_first
    assert "added basePath '/portal'" in first.stdout
    assert "basePath already '/portal'" in second.stdout

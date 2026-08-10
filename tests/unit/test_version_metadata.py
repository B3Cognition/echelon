from pathlib import Path
import tomllib

from echelon.cli import CLI_VERSION


ROOT = Path(__file__).resolve().parents[2]


def test_release_metadata_uses_current_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    expected_version = pyproject["project"]["version"]

    assert CLI_VERSION == expected_version
    assert f"**Version {expected_version}**" in readme
    assert f'name = "echelon"\nversion = "{expected_version}"' in lock

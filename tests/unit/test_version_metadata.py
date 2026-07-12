from pathlib import Path
import tomllib

import yaml

from echelon.cli import CLI_VERSION


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_VERSION = "3.0.59"


def test_release_metadata_uses_current_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extension = yaml.safe_load((ROOT / "extension" / "extension.yml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == EXPECTED_VERSION
    assert extension["extension"]["version"] == EXPECTED_VERSION
    assert CLI_VERSION == EXPECTED_VERSION
    assert f"**Version {EXPECTED_VERSION}**" in readme
    assert f'name = "echelon"\nversion = "{EXPECTED_VERSION}"' in lock

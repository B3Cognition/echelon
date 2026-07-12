from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare-release.py"


def load_module():
    spec = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_project(root: Path, version: str) -> None:
    (root / "scripts").mkdir()
    (root / "src" / "echelon").mkdir(parents=True)
    (root / "extension").mkdir()
    (root / "tests" / "unit").mkdir(parents=True)

    (root / "pyproject.toml").write_text(
        f'[project]\nname = "echelon"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "echelon"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# Echelon\n\n**Version {version}** - release notes\n",
        encoding="utf-8",
    )
    (root / "extension" / "extension.yml").write_text(
        "extension:\n"
        '  id: "echelon"\n'
        f'  version: "{version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "echelon" / "cli.py").write_text(
        f'CLI_VERSION = "{version}"\n',
        encoding="utf-8",
    )


def read_pyproject_version(root: Path) -> str:
    line = next(
        line
        for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version = ")
    )
    return line.split('"')[1]


def test_next_minor_version_examples() -> None:
    module = load_module()

    assert module.next_minor_version(module.Version.parse("3.0.81")).text == "3.1.0"
    assert module.next_minor_version(module.Version.parse("3.1.5")).text == "3.2.0"
    assert module.next_minor_version(module.Version.parse("3.9.6")).text == "4.0.0"


def test_next_minor_rejects_minor_greater_than_nine() -> None:
    module = load_module()

    with pytest.raises(module.ReleaseError, match="minor component greater than 9"):
        module.next_minor_version(module.Version.parse("3.10.0"))


def test_require_next_minor_release_accepts_only_computed_boundary() -> None:
    module = load_module()

    module.require_next_minor_release("3.0.80", "3.1.0")

    with pytest.raises(module.ReleaseError, match="closest next minor"):
        module.require_next_minor_release("3.0.80", "3.5.0")


def test_dry_run_does_not_write_files(tmp_path: Path) -> None:
    module = load_module()
    write_project(tmp_path, "3.0.81")

    result = module.prepare_release(tmp_path, dry_run=True)

    assert result.old_version == "3.0.81"
    assert result.new_version == "3.1.0"
    assert read_pyproject_version(tmp_path) == "3.0.81"


def test_prepare_release_updates_all_metadata(tmp_path: Path) -> None:
    module = load_module()
    write_project(tmp_path, "3.0.81")

    result = module.prepare_release(tmp_path, dry_run=False)

    assert result.old_version == "3.0.81"
    assert result.new_version == "3.1.0"
    assert read_pyproject_version(tmp_path) == "3.1.0"
    assert '**Version 3.1.0**' in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert 'version = "3.1.0"' in (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert 'CLI_VERSION = "3.1.0"' in (
        tmp_path / "src" / "echelon" / "cli.py"
    ).read_text(encoding="utf-8")

    assert '  version: "3.1.0"' in (
        tmp_path / "extension" / "extension.yml"
    ).read_text(encoding="utf-8")


def test_validate_release_metadata_rejects_mismatch(tmp_path: Path) -> None:
    module = load_module()
    write_project(tmp_path, "3.0.81")
    (tmp_path / "README.md").write_text(
        "# Echelon\n\n**Version 3.0.82** - release notes\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ReleaseError, match="README.md"):
        module.validate_release_metadata(tmp_path, "3.0.81")


def test_prepare_release_fails_when_expected_surface_is_missing(tmp_path: Path) -> None:
    module = load_module()
    write_project(tmp_path, "3.0.81")
    (tmp_path / "README.md").write_text("# Echelon\n", encoding="utf-8")

    with pytest.raises(module.ReleaseError, match="README.md"):
        module.prepare_release(tmp_path, dry_run=False)

    assert read_pyproject_version(tmp_path) == "3.0.81"

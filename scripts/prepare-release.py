#!/usr/bin/env python3
"""Prepare Echelon metadata for the next GitHub release."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tomllib


VERSION_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


class ReleaseError(RuntimeError):
    """Raised when release metadata cannot be prepared safely."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        match = VERSION_RE.match(text.strip())
        if not match:
            raise ReleaseError(f"invalid version: {text!r}")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
        )

    @property
    def text(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleaseResult:
    old_version: str
    new_version: str
    changed_files: tuple[Path, ...]
    dry_run: bool


@dataclass(frozen=True)
class VersionSurface:
    path: Path
    pattern: re.Pattern[str]
    replacement: str
    validation_pattern: str


def next_minor_version(version: Version) -> Version:
    if version.minor > 9:
        raise ReleaseError(
            f"current version {version.text} has a minor component greater than 9"
        )
    if version.minor == 9:
        return Version(version.major + 1, 0, 0)
    return Version(version.major, version.minor + 1, 0)


def next_patch_version(version: Version) -> Version:
    return Version(version.major, version.minor, version.patch + 1)


def require_next_minor_release(previous_version: str, release_version: str) -> None:
    expected = next_minor_version(Version.parse(previous_version)).text
    if release_version != expected:
        raise ReleaseError(
            f"release version {release_version} is not the closest next minor "
            f"after {previous_version}; expected {expected}"
        )


def require_next_release(previous_version: str, release_version: str) -> None:
    previous = Version.parse(previous_version)
    expected = {
        next_patch_version(previous).text,
        next_minor_version(previous).text,
    }
    if release_version not in expected:
        choices = " or ".join(sorted(expected))
        raise ReleaseError(
            f"release version {release_version} is not the next patch or minor "
            f"after {previous_version}; expected {choices}"
        )


def _read_package_version(root: Path) -> str:
    pyproject_path = root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"missing file: {pyproject_path}") from exc
    try:
        return str(data["project"]["version"])
    except KeyError as exc:
        raise ReleaseError("pyproject.toml is missing project.version") from exc


def _surfaces(old_version: str, new_version: str) -> tuple[VersionSurface, ...]:
    old = re.escape(old_version)
    return (
        VersionSurface(
            path=Path("pyproject.toml"),
            pattern=re.compile(rf'(?m)^(version = "){old}(")$'),
            replacement=rf"\g<1>{new_version}\2",
            validation_pattern=rf'(?m)^version = "{re.escape(new_version)}"$',
        ),
        VersionSurface(
            path=Path("uv.lock"),
            pattern=re.compile(
                rf'(?m)^(name = "echelon"\nversion = "){old}(")$'
            ),
            replacement=rf"\g<1>{new_version}\2",
            validation_pattern=(
                rf'(?m)^name = "echelon"\nversion = "{re.escape(new_version)}"$'
            ),
        ),
        VersionSurface(
            path=Path("README.md"),
            pattern=re.compile(rf"(\*\*Version ){old}(\*\*)"),
            replacement=rf"\g<1>{new_version}\2",
            validation_pattern=rf"\*\*Version {re.escape(new_version)}\*\*",
        ),
        VersionSurface(
            path=Path("src/echelon/cli.py"),
            pattern=re.compile(rf'(?m)^(CLI_VERSION = "){old}(")$'),
            replacement=rf"\g<1>{new_version}\2",
            validation_pattern=rf'(?m)^CLI_VERSION = "{re.escape(new_version)}"$',
        ),
    )


def _replacement_for(root: Path, surface: VersionSurface) -> tuple[Path, str, bool]:
    path = root / surface.path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ReleaseError(f"missing file: {surface.path}") from exc

    new_text, count = surface.pattern.subn(surface.replacement, text)
    if count != 1:
        raise ReleaseError(
            f"{surface.path}: expected exactly one version match, found {count}"
        )
    return path, new_text, new_text != text


def validate_release_metadata(root: Path, expected_version: str) -> None:
    for surface in _surfaces(expected_version, expected_version):
        path = root / surface.path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ReleaseError(f"missing file: {surface.path}") from exc
        if not re.search(surface.validation_pattern, text):
            raise ReleaseError(
                f"{surface.path}: expected release version {expected_version}"
            )

    package_version = _read_package_version(root)
    if package_version != expected_version:
        raise ReleaseError(
            f"pyproject.toml project.version is {package_version}, "
            f"expected {expected_version}"
        )


def prepare_release(
    root: Path,
    dry_run: bool = False,
    *,
    bump: str = "minor",
) -> ReleaseResult:
    root = root.resolve()
    old_version = _read_package_version(root)
    version = Version.parse(old_version)
    if bump == "minor":
        new_version = next_minor_version(version).text
    elif bump == "patch":
        new_version = next_patch_version(version).text
    else:
        raise ReleaseError(f"unsupported release bump: {bump}")
    replacements: list[tuple[Path, str, bool]] = []
    changed: list[Path] = []

    for surface in _surfaces(old_version, new_version):
        path, new_text, did_change = _replacement_for(root, surface)
        replacements.append((path, new_text, did_change))
        if did_change:
            changed.append(surface.path)

    if not dry_run:
        for path, new_text, _did_change in replacements:
            path.write_text(new_text, encoding="utf-8")

    if not dry_run:
        validate_release_metadata(root, new_version)

    return ReleaseResult(
        old_version=old_version,
        new_version=new_version,
        changed_files=tuple(changed),
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare Echelon metadata for the next minor-boundary release."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned release version without writing files",
    )
    parser.add_argument(
        "--patch",
        action="store_true",
        help="prepare the next patch release instead of the next minor release",
    )
    args = parser.parse_args(argv)

    try:
        result = prepare_release(
            Path(__file__).resolve().parents[1],
            dry_run=args.dry_run,
            bump="patch" if args.patch else "minor",
        )
    except ReleaseError as exc:
        print(f"prepare-release: {exc}", file=sys.stderr)
        return 1

    action = "Would update" if result.dry_run else "Updated"
    print(f"{action} Echelon {result.old_version} -> {result.new_version}")
    for path in result.changed_files:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

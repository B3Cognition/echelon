from pathlib import Path

from echelon.constitution import (
    canonical_constitution_path,
    migrate_legacy_constitution,
)


def test_canonical_constitution_prefers_echelon_location(tmp_path: Path) -> None:
    legacy = tmp_path / ".specify" / "memory" / "constitution.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    canonical = tmp_path / ".echelon" / "constitution.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("canonical", encoding="utf-8")

    assert canonical_constitution_path(tmp_path) == canonical


def test_canonical_constitution_does_not_fall_back_to_legacy_storage(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".specify" / "memory" / "constitution.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")

    assert canonical_constitution_path(tmp_path) == (
        tmp_path / ".echelon" / "constitution.md"
    )


def test_migrate_legacy_constitution_copies_without_removing_source(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".specify" / "memory" / "constitution.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy constitution", encoding="utf-8")

    migrated = migrate_legacy_constitution(tmp_path)

    canonical = tmp_path / ".echelon" / "constitution.md"
    assert migrated == canonical
    assert canonical.read_text(encoding="utf-8") == "legacy constitution"
    assert legacy.read_text(encoding="utf-8") == "legacy constitution"


def test_migrate_legacy_constitution_preserves_existing_canonical_file(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".specify" / "memory" / "constitution.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    canonical = tmp_path / ".echelon" / "constitution.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("canonical", encoding="utf-8")

    migrated = migrate_legacy_constitution(tmp_path)

    assert migrated == canonical
    assert canonical.read_text(encoding="utf-8") == "canonical"


def test_migrate_legacy_constitution_normalizes_obsolete_amendment_instruction(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".specify" / "memory" / "constitution.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "# Project Constitution\n\n"
        "<!-- Generated after Phase A. Human must review and amend via "
        "/speckit.constitution -->\n\n"
        "## Core Principles\n\n"
        "The system MUST preserve its governance rules.\n",
        encoding="utf-8",
    )

    migrate_legacy_constitution(tmp_path)

    canonical = (tmp_path / ".echelon" / "constitution.md").read_text(
        encoding="utf-8"
    )
    assert "speckit.constitution" not in canonical
    assert "amendments are handled by Echelon CHIEF during Phase A" in canonical
    assert "The system MUST preserve its governance rules." in canonical
    assert "/speckit.constitution" in legacy.read_text(encoding="utf-8")

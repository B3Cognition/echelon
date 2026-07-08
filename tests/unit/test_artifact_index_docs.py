"""README coverage for spec artifact index UX."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def test_readme_points_humans_to_artifacts_md() -> None:
    text = README.read_text(encoding="utf-8")

    assert "ARTIFACTS.md" in text
    assert "How to read a spec folder" in text


def test_readme_documents_artifacts_command() -> None:
    text = README.read_text(encoding="utf-8")

    assert "echelon spec artifacts <id>" in text
    assert "Generate or refresh" in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"


def test_runtime_prose_uses_deployed_runtime_template_paths() -> None:
    """Deployed workflow prose must not rely on the retired extension namespace."""
    stale_references = []
    for path in RUNTIME.rglob("*.md"):
        if "extension/templates/" in path.read_text(encoding="utf-8"):
            stale_references.append(path.relative_to(ROOT))

    assert not stale_references, "\n".join(map(str, stale_references))


def test_canonical_bundles_do_not_reference_retired_extension_assets() -> None:
    stale_references = []
    retired_prefixes = (
        "extension/agents/",
        "extension/commands/",
        "extension/scripts/",
        "extension/templates/",
        "extension/workflow/",
    )
    for bundle in (ROOT / "prosaic", ROOT / "runtime"):
        for path in bundle.rglob("*"):
            if path.suffix not in {".md", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            if any(prefix in text for prefix in retired_prefixes):
                stale_references.append(path.relative_to(ROOT))

    assert not stale_references, "\n".join(map(str, stale_references))


def test_scout_prose_names_the_deployed_runtime_presets_directory() -> None:
    prose = (ROOT / "prosaic" / "subagents" / "echelon.scout.md").read_text(
        encoding="utf-8"
    )

    assert ".echelon/runtime/presets/" in prose
    assert "extension/presets/" not in prose

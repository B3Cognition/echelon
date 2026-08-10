from pathlib import Path

from scripts.python.prompt_lint import (
    DEFAULT_AGENTS_ROOT,
    DEFAULT_DEFINITION,
    REPO_ROOT,
)


def test_prompt_lint_defaults_to_canonical_prosaic_runtime() -> None:
    assert DEFAULT_AGENTS_ROOT == REPO_ROOT / "prosaic"
    assert DEFAULT_DEFINITION == REPO_ROOT / "runtime" / "workflow" / "definition.yaml"
    assert DEFAULT_AGENTS_ROOT.is_dir()
    assert DEFAULT_DEFINITION.is_file()
    assert Path("extension") not in DEFAULT_AGENTS_ROOT.parents

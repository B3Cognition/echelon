from pathlib import Path

import pytest

from echelon.target_detection import detect_target


def _git_marker(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


def _git_file_marker(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").write_text("gitdir: ../.git/modules/repo\n", encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.unit
def test_detect_target_scores_repo_with_referenced_source_paths(tmp_path: Path) -> None:
    root = tmp_path
    spec_dir = root / "specs" / "001-opta-points-perf-fix"
    spec_dir.mkdir(parents=True)
    _write(
        spec_dir / "tasks.md",
        "- [ ] T-002 complexity=complex phase=foundation req=FR-001 depends=none "
        "Fix `src/lib/sdapi/services/shared-promise.ts`\n",
    )
    _write(spec_dir / "spec.md", "# OptaPoints Performance Stabilization\n")

    target = root / "rbf-opta-points"
    target.mkdir()
    _git_marker(target)
    _write(target / "src/lib/sdapi/services/shared-promise.ts", "export {}\n")

    other = root / "qag-load-testing-framework"
    other.mkdir()
    _git_marker(other)
    _write(other / "README.md", "# load tests\n")

    result = detect_target(spec_dir=spec_dir, polyrepo_root=root)

    assert result.recommended_target == "rbf-opta-points"
    assert result.confidence >= 0.80
    assert result.decision == "recommend"
    assert any("shared-promise.ts" in item for item in result.candidates[0].evidence)


@pytest.mark.unit
def test_detect_target_blocks_on_tie(tmp_path: Path) -> None:
    root = tmp_path
    spec_dir = root / "specs" / "001-cache"
    spec_dir.mkdir(parents=True)
    _write(spec_dir / "tasks.md", "Fix `src/cache/index.ts`\n")

    for name in ["repo-a", "repo-b"]:
        repo = root / name
        repo.mkdir()
        _git_marker(repo)
        _write(repo / "src/cache/index.ts", "export {}\n")

    result = detect_target(spec_dir=spec_dir, polyrepo_root=root)

    assert result.recommended_target is None
    assert result.decision == "ambiguous"
    assert result.confidence < 0.80


@pytest.mark.unit
def test_detect_target_treats_git_file_children_as_polyrepo_repos(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _git_marker(root)
    spec_dir = root / "specs" / "001-web-fix"
    spec_dir.mkdir(parents=True)
    _write(spec_dir / "tasks.md", "Fix `src/app/page.tsx`\n")

    target = root / "web-app"
    _git_file_marker(target)
    _write(target / "src/app/page.tsx", "export default function Page() {}\n")

    other = root / "api"
    _git_file_marker(other)
    _write(other / "README.md", "# api\n")

    result = detect_target(spec_dir=spec_dir, polyrepo_root=root)

    assert result.recommended_target == "web-app"
    assert result.decision == "recommend"


@pytest.mark.unit
def test_detect_target_returns_not_polyrepo_for_single_repo(tmp_path: Path) -> None:
    root = tmp_path
    _git_marker(root)
    spec_dir = root / "specs" / "001-local"
    spec_dir.mkdir(parents=True)
    _write(spec_dir / "tasks.md", "Fix local code\n")

    result = detect_target(spec_dir=spec_dir, polyrepo_root=root)

    assert result.decision == "not_polyrepo"
    assert result.recommended_target is None

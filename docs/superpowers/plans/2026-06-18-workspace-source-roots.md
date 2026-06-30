# Workspace Source Roots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Echelon treat every project as a Git-backed workspace with zero or more deterministic source roots, so single-repo and polyrepo workflows use the same model.

**Architecture:** Add a Python-owned workspace model first, then teach reverse engineering and harness preflight to consume it. Keep existing single-repo behavior as `sources: [.]`, keep `repos-manifest.json` compatibility while introducing `workspace-manifest.json`, and make branchless polyrepo workspaces fail early with an actionable setup recipe.

**Tech Stack:** Python dataclasses, pathlib, JSON, Bash integration scripts, pytest, shell integration tests, existing Echelon harness and RE scripts.

---

## Design Source

Implement the design in `docs/superpowers/specs/2026-06-18-workspace-source-roots-design.md`.

Key invariants:

- Workspace root owns `.specify/`, `specs/`, `runs/`, and Echelon state.
- Source roots own implementation files.
- A single-repo checkout is modeled as one workspace whose only source is `.`.
- A polyrepo workspace is a lightweight Git repo whose child directories are source roots.
- `.git` is evidence, not identity. The workspace/source manifest is identity.
- Branchless workspace support is migration-only. New normal operation should require workspace Git.

## File Structure

Create or modify these files:

- Create `src/echelon/workspace_model.py`: Python-owned discovery, manifest types, JSON serialization, and CLI writer.
- Create `tests/unit/test_workspace_model.py`: unit tests for single-repo, polyrepo, planning-only, and `.git` file cases.
- Modify `extension/scripts/bash/re/discover-repos.sh`: keep writing `repos-manifest.json`; additionally write `workspace-manifest.json`.
- Modify `extension/scripts/bash/re/run-analysis.sh`: prefer `workspace-manifest.json`, fall back to `repos-manifest.json`.
- Modify `tests/integration/re/test-discover-repos.sh`: assert the new manifest exists and has correct source-root semantics.
- Modify `tests/integration/re/test-run-analysis-polyrepo.sh`: assert analysis runs per source root and does not treat orchestration workspace scripts as implementation code.
- Modify RE prompt contracts:
  - `extension/agents/re/analyzer.md`
  - `extension/agents/re/specifier.md`
  - `extension/agents/re/verifier.md`
  - `extension/agents/re/constituter.md`
  - `extension/agents/re/golddigger.md`
  - `extension/agents/exploration/scout.md`
- Modify docs:
  - `docs/re-overview.md`
  - `docs/re-config.md`
  - Create `docs/workspace-model.md`
- Modify `src/echelon/target_detection.py`: consume `WorkspaceManifest` for target candidates.
- Modify `tests/unit/test_target_detection.py`: cover source-root-only target detection.
- Modify `src/echelon/cli.py`: workspace Git preflight for run/continue/harness entrypoints and clearer commands.
- Modify `tests/unit/test_cli_harness_run.py`: cover branchless polyrepo block and single-repo pass-through.
- Modify `src/harness/target_state.py`: persist workspace/source metadata in target state.
- Modify `tests/unit/test_harness_target_state.py`: assert workspace/source fields round-trip.
- Modify `src/harness/ralph.py`: ensure harness prompts use known workspace/source paths, not filesystem search.
- Modify `tests/unit/test_ralph_outer.py`: assert source-root paths are injected and workspace root is not treated as target unless source is `.`.
- Modify `tests/unit/test_polyrepo_target_docs.py`: pin user-facing docs and error examples.

## Task 1: Add Python Workspace Model

**Files:**
- Create: `src/echelon/workspace_model.py`
- Create: `tests/unit/test_workspace_model.py`

- [x] **Step 1: Write failing workspace model tests**

Create `tests/unit/test_workspace_model.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from echelon.workspace_model import discover_workspace, load_workspace_manifest


def _git_dir(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


def test_single_repo_workspace_is_source_root(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.root == tmp_path.resolve()
    assert manifest.workspace.git_present is True
    assert manifest.workspace.git_role == "source"
    assert [source.path for source in manifest.sources] == ["."]
    assert manifest.sources[0].id == "."
    assert manifest.sources[0].git_present is True
    assert "package.json" in manifest.sources[0].project_markers


def test_polyrepo_workspace_uses_child_source_roots(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    for name, marker in [("og-platform", "package.json"), ("pbg-api", "pom.xml")]:
        repo = tmp_path / name
        repo.mkdir()
        _git_dir(repo)
        (repo / marker).write_text("{}", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.id for source in manifest.sources] == ["og-platform", "pbg-api"]
    assert [source.path for source in manifest.sources] == ["og-platform", "pbg-api"]
    assert all(source.git_present for source in manifest.sources)


def test_planning_only_workspace_has_no_sources(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert manifest.workspace.git_present is True
    assert manifest.sources == ()


def test_git_file_counts_as_git_presence_for_worktree_or_submodule(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    source = tmp_path / "source-a"
    source.mkdir()
    (source / ".git").write_text("gitdir: ../.git/modules/source-a\n", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\nname='source-a'\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert len(manifest.sources) == 1
    assert manifest.sources[0].id == "source-a"
    assert manifest.sources[0].git_present is True


def test_manifest_json_round_trips(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    manifest = discover_workspace(tmp_path)
    path = tmp_path / "workspace-manifest.json"
    path.write_text(json.dumps(manifest.to_json_dict(), indent=2), encoding="utf-8")

    loaded = load_workspace_manifest(path)

    assert loaded == manifest
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/unit/test_workspace_model.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.workspace_model'`.

- [x] **Step 3: Implement the workspace model**

Create `src/echelon/workspace_model.py`:

```python
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

GitRole = Literal["orchestration", "source"]

SOURCE_MARKERS = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Package.swift",
    "*.xcodeproj",
    "*.xcworkspace",
    "nx.json",
    "Makefile",
)

IGNORED_SOURCE_DIRS = {
    ".git",
    ".specify",
    ".echelon",
    ".venv",
    "__pycache__",
    "node_modules",
    "runs",
    "specs",
    ".worktrees",
}


@dataclass(frozen=True)
class WorkspaceInfo:
    root: Path
    git_role: GitRole
    git_present: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "git_role": self.git_role,
            "git_present": self.git_present,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "WorkspaceInfo":
        return cls(
            root=Path(str(data["root"])).resolve(),
            git_role=data["git_role"],
            git_present=bool(data["git_present"]),
        )


@dataclass(frozen=True)
class SourceRoot:
    id: str
    path: str
    git_present: bool
    git_role: GitRole = "source"
    project_markers: tuple[str, ...] = ()
    source_file_count: int = 0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "git_role": self.git_role,
            "git_present": self.git_present,
            "project_markers": list(self.project_markers),
            "source_file_count": self.source_file_count,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "SourceRoot":
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            git_role=data.get("git_role", "source"),
            git_present=bool(data.get("git_present", False)),
            project_markers=tuple(str(item) for item in data.get("project_markers", [])),
            source_file_count=int(data.get("source_file_count", 0)),
        )


@dataclass(frozen=True)
class WorkspaceManifest:
    schema_version: int
    workspace: WorkspaceInfo
    sources: tuple[SourceRoot, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace": self.workspace.to_json_dict(),
            "sources": [source.to_json_dict() for source in self.sources],
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "WorkspaceManifest":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            workspace=WorkspaceInfo.from_json_dict(data["workspace"]),
            sources=tuple(SourceRoot.from_json_dict(item) for item in data.get("sources", [])),
        )


def has_git_marker(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def project_markers(path: Path) -> tuple[str, ...]:
    found: list[str] = []
    for marker in SOURCE_MARKERS:
        if "*" in marker:
            if any(path.glob(marker)):
                found.append(marker)
        elif (path / marker).exists():
            found.append(marker)
    return tuple(found)


def count_source_files(path: Path) -> int:
    count = 0
    for child in path.rglob("*"):
        if child.is_file() and ".git" not in child.parts and "node_modules" not in child.parts:
            count += 1
    return count


def _child_source_roots(root: Path) -> tuple[SourceRoot, ...]:
    sources: list[SourceRoot] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name in IGNORED_SOURCE_DIRS:
            continue
        markers = project_markers(child)
        git_present = has_git_marker(child)
        if not markers and not git_present:
            continue
        sources.append(
            SourceRoot(
                id=child.name,
                path=child.name,
                git_present=git_present,
                project_markers=markers,
                source_file_count=count_source_files(child),
            )
        )
    return tuple(sources)


def discover_workspace(root: Path) -> WorkspaceManifest:
    resolved = root.resolve()
    workspace_git_present = has_git_marker(resolved)
    child_sources = _child_source_roots(resolved)
    root_markers = project_markers(resolved)

    if child_sources:
        git_role: GitRole = "orchestration"
        sources = child_sources
    elif root_markers:
        git_role = "source"
        sources = (
            SourceRoot(
                id=".",
                path=".",
                git_present=workspace_git_present,
                project_markers=root_markers,
                source_file_count=count_source_files(resolved),
            ),
        )
    else:
        git_role = "orchestration"
        sources = ()

    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=resolved,
            git_role=git_role,
            git_present=workspace_git_present,
        ),
        sources=sources,
    )


def load_workspace_manifest(path: Path) -> WorkspaceManifest:
    return WorkspaceManifest.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def write_workspace_manifest(root: Path, output: Path) -> WorkspaceManifest:
    manifest = discover_workspace(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write Echelon workspace manifest")
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    write_workspace_manifest(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_workspace_model.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echelon/workspace_model.py tests/unit/test_workspace_model.py
git commit -m "feat: add workspace source roots model"
```

## Task 2: Emit `workspace-manifest.json` From RE Discovery

**Files:**
- Modify: `extension/scripts/bash/re/discover-repos.sh`
- Modify: `tests/integration/re/test-discover-repos.sh`
- Test artifact: sibling `workspace-manifest.json` beside `repos-manifest.json`

- [x] **Step 1: Write failing integration assertions**

In `tests/integration/re/test-discover-repos.sh`, add assertions after the script call that currently writes `repos-manifest.json`:

```bash
workspace_manifest="$(dirname "$manifest")/workspace-manifest.json"
test -f "$workspace_manifest"
jq -e '.schema_version == 1' "$workspace_manifest" >/dev/null
jq -e '.workspace.git_role == "orchestration"' "$workspace_manifest" >/dev/null
jq -e '.sources | length >= 1' "$workspace_manifest" >/dev/null
jq -e '.sources[] | select(.path == "repo-a")' "$workspace_manifest" >/dev/null
```

The existing fixture names are `repo-a`, `repo-b`, and `repo-c`; keep those names in the assertions.

- [x] **Step 2: Run the integration test and verify it fails**

Run:

```bash
bash tests/integration/re/test-discover-repos.sh
```

Expected: FAIL because `workspace-manifest.json` is absent.

- [x] **Step 3: Call Python manifest writer from discovery script**

In `extension/scripts/bash/re/discover-repos.sh`, after the existing `repos-manifest.json` write succeeds, add:

```bash
workspace_manifest="$(dirname "$output_file")/workspace-manifest.json"
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH="${PYTHONPATH:-}:$ECHELON_REPO_ROOT/src" \
    python3 -m echelon.workspace_model "$ROOT_DIR" "$workspace_manifest"
fi
```

Use the script’s existing root variable instead of inventing a new one. If the script names it `PROJECT_ROOT`, use `"$PROJECT_ROOT"`. If there is no `ECHELON_REPO_ROOT`, derive it once near the top:

```bash
ECHELON_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
```

Do not make failure to write `workspace-manifest.json` silent. If Python exists but the module fails, the script should fail because discovery state is incomplete.

- [x] **Step 4: Run the integration test and verify it passes**

Run:

```bash
bash tests/integration/re/test-discover-repos.sh
```

Expected: PASS and both manifests exist.

- [x] **Step 5: Commit**

```bash
git add extension/scripts/bash/re/discover-repos.sh tests/integration/re/test-discover-repos.sh
git commit -m "feat: emit workspace manifest during RE discovery"
```

## Task 3: Make RE Analysis Prefer Workspace Manifest

**Files:**
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `tests/integration/re/test-run-analysis-polyrepo.sh`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`

- [x] **Step 1: Add failing contract checks**

In `tests/kernel/test_codegraph_integration_contract.py`, update the analyzer contract test so it asserts both file names are present and preference is explicit:

```python
assert "workspace-manifest.json" in analyzer
assert "repos-manifest.json" in analyzer
assert "Prefer workspace-manifest.json" in analyzer
```

Add a shell-level assertion in `tests/integration/re/test-run-analysis-polyrepo.sh` after analysis:

```bash
test -f "$RE_OUTPUT_DIR/workspace-manifest.json"
jq -e '.sources | length == 3' "$RE_OUTPUT_DIR/workspace-manifest.json" >/dev/null
test ! -d "$RE_OUTPUT_DIR/.specify"
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/kernel/test_codegraph_integration_contract.py -q
bash tests/integration/re/test-run-analysis-polyrepo.sh
```

Expected: FAIL on missing prompt/script references.

- [x] **Step 3: Update `run-analysis.sh` manifest resolution**

In `extension/scripts/bash/re/run-analysis.sh`, add a helper near argument parsing:

```bash
resolve_workspace_manifest() {
  local repos_manifest="$1"
  local candidate
  candidate="$(dirname "$repos_manifest")/workspace-manifest.json"
  if [[ -f "$candidate" ]]; then
    printf '%s\n' "$candidate"
  else
    printf '%s\n' ""
  fi
}
```

Use it before per-repo iteration:

```bash
WORKSPACE_MANIFEST="$(resolve_workspace_manifest "$REPOS_MANIFEST")"
if [[ -n "$WORKSPACE_MANIFEST" ]]; then
  SOURCE_COUNT="$(jq '.sources | length' "$WORKSPACE_MANIFEST")"
else
  SOURCE_COUNT="$(jq '.repos | length' "$REPOS_MANIFEST")"
fi
```

When iterating repos, prefer source paths from `workspace-manifest.json`:

```bash
if [[ -n "$WORKSPACE_MANIFEST" ]]; then
  jq -r '.sources[].path' "$WORKSPACE_MANIFEST"
else
  jq -r '.repos[].path' "$REPOS_MANIFEST"
fi
```

Keep existing `repos-manifest.json` behavior intact for older run directories.

- [x] **Step 4: Update prompt contracts**

In `extension/agents/re/analyzer.md`, replace `repos-manifest.json`-only instructions with:

```markdown
Prefer `workspace-manifest.json` when present. It defines the workspace root and implementation source roots. Use `repos-manifest.json` only as a compatibility fallback for older runs.
```

Apply the same wording to `extension/agents/re/specifier.md`, `extension/agents/re/verifier.md`, `extension/agents/re/constituter.md`, `extension/agents/re/golddigger.md`, and `extension/agents/exploration/scout.md` wherever they describe polyrepo discovery.

- [x] **Step 5: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/kernel/test_codegraph_integration_contract.py -q
bash tests/integration/re/test-run-analysis-polyrepo.sh
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add extension/scripts/bash/re/run-analysis.sh extension/agents/re/analyzer.md extension/agents/re/specifier.md extension/agents/re/verifier.md extension/agents/re/constituter.md extension/agents/re/golddigger.md extension/agents/exploration/scout.md tests/integration/re/test-run-analysis-polyrepo.sh tests/kernel/test_codegraph_integration_contract.py
git commit -m "feat: prefer workspace manifest in reverse engineering"
```

## Task 4: Add Workspace Git Preflight

**Files:**
- Modify: `src/echelon/cli.py`
- Create: `tests/unit/test_workspace_git_preflight.py`

- [x] **Step 1: Write failing preflight tests**

Create `tests/unit/test_workspace_git_preflight.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from echelon.cli import _workspace_git_preflight


def test_branchless_polyrepo_workspace_blocks_with_init_recipe(tmp_path: Path) -> None:
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _workspace_git_preflight(tmp_path, command_name="echelon harness run")

    assert exc.value.code == 2


def test_git_backed_polyrepo_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    _workspace_git_preflight(tmp_path, command_name="echelon harness run")


def test_single_repo_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    _workspace_git_preflight(tmp_path, command_name="echelon run")
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/unit/test_workspace_git_preflight.py -q
```

Expected: FAIL because `_workspace_git_preflight` does not exist.

- [x] **Step 3: Implement preflight helper**

In `src/echelon/cli.py`, add:

```python
from echelon.workspace_model import discover_workspace


def _workspace_git_preflight(project_root: Path, *, command_name: str) -> None:
    manifest = discover_workspace(project_root)
    if manifest.workspace.git_present:
        return

    source_paths = [source.path for source in manifest.sources if source.path != "."]
    ignore_lines = "\n".join(f"/{path}/" for path in source_paths) or "/source-repo/"
    message = f"""✗ Echelon workspace root is not a Git repo.

Echelon requires workspace Git so specs, run state, and recovery metadata have durable version history.

Fix:
  git init
  printf "{ignore_lines}\\n/runs/\\n" >> .gitignore
  git add .gitignore .specify specs
  git commit -m "chore: initialize echelon workspace"

Then rerun:
  {command_name}
"""
    print(message, file=sys.stderr)
    raise SystemExit(2)
```

If `src/echelon/cli.py` already has a central error helper, use that helper to print and exit but keep the exact message content.

- [x] **Step 4: Wire preflight into commands**

Call `_workspace_git_preflight(Path.cwd(), command_name=...)` at the start of:

- `_cmd_run`
- `_cmd_continue`
- `_cmd_harness_run`
- `_cmd_harness_resume`
- `_cmd_harness_status`

Do not run this preflight for pure read-only help/version commands.

- [x] **Step 5: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_workspace_git_preflight.py tests/unit/test_cli_harness_run.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_workspace_git_preflight.py
git commit -m "feat: require git-backed echelon workspace"
```

## Task 5: Make Target Detection Source-Root Aware

**Files:**
- Modify: `src/echelon/target_detection.py`
- Modify: `tests/unit/test_target_detection.py`

- [x] **Step 1: Write failing source-root target tests**

Add to `tests/unit/test_target_detection.py`:

```python
from echelon.workspace_model import discover_workspace


def test_target_detection_uses_single_source_root_without_guessing(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    manifest = discover_workspace(tmp_path)

    result = detect_target(
        spec_dir=tmp_path / "specs" / "001-demo",
        polyrepo_root=tmp_path,
        workspace_manifest=manifest,
    )

    assert result.recommended_target == "og-platform"
    assert result.confidence == 1.0
    assert result.decision == "single_source_root"


def test_target_detection_blocks_multi_source_without_explicit_target(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    for name in ["og-platform", "pbg-api"]:
        source = tmp_path / name
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
    manifest = discover_workspace(tmp_path)

    result = detect_target(
        spec_dir=tmp_path / "specs" / "001-demo",
        polyrepo_root=tmp_path,
        workspace_manifest=manifest,
    )

    assert result.recommended_target is None
    assert result.confidence == 0.0
    assert result.decision == "multiple_source_roots_need_target"
    assert [candidate.repo for candidate in result.candidates] == ["og-platform", "pbg-api"]


def test_target_detection_keeps_single_repo_dot_behavior(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    manifest = discover_workspace(tmp_path)

    result = detect_target(
        spec_dir=tmp_path / "specs" / "001-demo",
        polyrepo_root=tmp_path,
        workspace_manifest=manifest,
    )

    assert result.recommended_target == "."
    assert result.confidence == 1.0
    assert result.decision == "single_source_root"
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/unit/test_target_detection.py -q
```

Expected: FAIL because `detect_target` does not accept `workspace_manifest`.

- [x] **Step 3: Update target detection**

The current public signature is keyword-only with `spec_dir` and `polyrepo_root`. Preserve that compatibility by implementing this concrete signature instead:

```python
def detect_target(
    *,
    spec_dir: Path,
    polyrepo_root: Path,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    workspace_manifest: WorkspaceManifest | None = None,
    explicit_target: str | None = None,
) -> TargetDetectionResult:
```

Implement this order:

1. If `explicit_target` is set, resolve it under `polyrepo_root` and return it only if it matches `.` or one `sources[].path`.
2. If no manifest is supplied, call `discover_workspace(polyrepo_root)`.
3. If `len(sources) == 0`, return reason `no_source_roots`.
4. If `len(sources) == 1`, return that source path.
5. If `len(sources) > 1`, return a blocked result with candidates.

Return the existing `TargetDetectionResult` type:

```python
TargetDetectionResult(recommended_target, confidence, decision, candidates)
```

For source-root decisions, candidates should be `TargetCandidate(repo=source.id, confidence=1.0, evidence=["workspace source root"])`. Do not include `polyrepo_root` as a candidate unless a source path is `.`.

- [x] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_target_detection.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echelon/target_detection.py tests/unit/test_target_detection.py
git commit -m "feat: detect harness targets from workspace sources"
```

## Task 6: Persist Workspace And Source Metadata In Harness State

**Files:**
- Modify: `src/harness/target_state.py`
- Modify: `tests/unit/test_harness_target_state.py`
- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_ralph_outer.py`

- [x] **Step 1: Add failing state round-trip test**

In `tests/unit/test_harness_target_state.py`, add:

```python
def test_target_state_updates_include_workspace_and_source_metadata(tmp_path: Path) -> None:
    target = tmp_path / "og-platform"
    target.mkdir()

    updates = target_state_updates(
        polyrepo_root=tmp_path,
        target_repo=target,
        target_branch="001-demo",
        target_commit="abc123",
        workspace_root=tmp_path,
        workspace_git_role="orchestration",
        source_root=target,
        source_id="og-platform",
        source_git_role="source",
    )

    assert updates["workspace_root"] == str(tmp_path)
    assert updates["workspace_git_role"] == "orchestration"
    assert updates["source_root"] == str(target)
    assert updates["source_id"] == "og-platform"
    assert updates["source_git_role"] == "source"
```

- [x] **Step 2: Run state test and verify it fails**

Run:

```bash
python -m pytest tests/unit/test_harness_target_state.py -q
```

Expected: FAIL on missing fields.

- [x] **Step 3: Add fields to target state**

In `src/harness/target_state.py`, extend `target_state_updates` with optional keyword-only parameters:

```python
workspace_root: Path | None = None
workspace_git_role: str | None = None
source_root: Path | None = None
source_id: str | None = None
source_git_role: str | None = None
```

The returned dictionary must keep existing keys and add these keys:

```python
"workspace_root": str(workspace_root or polyrepo_root),
"workspace_git_role": workspace_git_role,
"source_root": str(source_root or target_repo),
"source_id": source_id or target_repo.name,
"source_git_role": source_git_role,
```

- [x] **Step 4: Add prompt context assertion**

In `tests/unit/test_ralph_outer.py`, add:

```python
def test_harness_context_names_workspace_and_source_roots(self, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "og-platform"
    source.mkdir(parents=True)
    state = {
        "workspace_root": str(workspace),
        "workspace_git_role": "orchestration",
        "source_root": str(source),
        "source_id": "og-platform",
        "source_git_role": "source",
    }

    controller = self._controller(tmp_path)
    prompt = controller._with_harness_context("body", str(source), target_state=state)

    assert f"workspace_root: {workspace}" in prompt
    assert f"source_root: {source}" in prompt
    assert "Do not search for the application repo" in prompt
```

Adapt controller construction to the helpers already used in this test file.

- [x] **Step 5: Implement harness prompt context**

In `src/harness/ralph.py`, extend deterministic harness context:

```text
workspace_root: {workspace_root}
workspace_git_role: {workspace_git_role}
source_root: {source_root}
source_id: {source_id}
source_git_role: {source_git_role}
Do not search for the application repo. Use source_root as the implementation checkout.
```

Preserve existing `HARNESS_SOURCE_DIR` instructions that prevent searching for Ralph/harness code.

- [x] **Step 6: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_harness_target_state.py tests/unit/test_ralph_outer.py -q
```

Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add src/harness/target_state.py src/harness/ralph.py tests/unit/test_harness_target_state.py tests/unit/test_ralph_outer.py
git commit -m "feat: persist workspace source metadata in harness"
```

## Task 7: Wire Harness Run And Resume To Workspace Model

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/orchestrator.py`
- Modify: `tests/unit/test_cli_harness_run.py`
- Modify: `tests/unit/test_harness_single_repo_unchanged.py`
- Modify: `tests/unit/test_polyrepo_target_docs.py`

- [x] **Step 1: Add failing CLI tests**

In `tests/unit/test_cli_harness_run.py`, add:

```python
def test_harness_run_blocks_multi_source_without_target(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    for name in ["og-platform", "pbg-api"]:
        source = tmp_path / name
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("- [ ] T-001 complexity=S phase=1 req=FR-001 depends=[] Demo\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_harness_run(["001-demo", "mode=semi"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "multiple source roots" in err
    assert "og-platform" in err
    assert "pbg-api" in err
    assert "echelon spec target" in err
```

Add a pass-through test for one child source:

```python
def test_harness_run_uses_single_source_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    result = _resolve_harness_workspace_target(tmp_path, explicit_target=None)

    assert result.source_id == "og-platform"
    assert result.source_root == source
```

If `_resolve_harness_workspace_target` does not exist, create it in Step 3.

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py -q
```

Expected: FAIL on missing helper or old target behavior.

- [x] **Step 3: Implement harness workspace target resolver**

In `src/echelon/cli.py`, add:

```python
@dataclass(frozen=True)
class HarnessWorkspaceTarget:
    workspace_root: Path
    workspace_git_role: str
    source_root: Path
    source_id: str
    source_git_role: str


def _resolve_harness_workspace_target(project_root: Path, explicit_target: str | None) -> HarnessWorkspaceTarget:
    manifest = discover_workspace(project_root)
    result = detect_target(project_root, workspace_manifest=manifest, explicit_target=explicit_target)
    if result.reason == "no_source_roots":
        print("✗ no source roots found; harness build needs at least one source root", file=sys.stderr)
        raise SystemExit(2)
    if result.reason == "multiple_source_roots_need_target":
        candidates = "\n".join(f"  - {candidate}" for candidate in result.candidates)
        print(
            "✗ multiple source roots found; choose one before running harness.\n\n"
            f"Candidates:\n{candidates}\n\n"
            "Fix:\n  echelon spec target <spec-id> <source-root>\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    source = next(item for item in manifest.sources if (project_root / item.path).resolve() == result.target_path.resolve())
    return HarnessWorkspaceTarget(
        workspace_root=manifest.workspace.root,
        workspace_git_role=manifest.workspace.git_role,
        source_root=result.target_path.resolve(),
        source_id=source.id,
        source_git_role=source.git_role,
    )
```

Pass this metadata into orchestrator/run state rather than recomputing it inside the build loop.

- [x] **Step 4: Preserve single-repo behavior**

In `tests/unit/test_harness_single_repo_unchanged.py`, assert the single-repo resolver uses `.`:

```python
def test_single_repo_resolver_uses_project_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    target = _resolve_harness_workspace_target(tmp_path, explicit_target=None)

    assert target.workspace_root == tmp_path.resolve()
    assert target.workspace_git_role == "source"
    assert target.source_root == tmp_path.resolve()
    assert target.source_id == "."
```

- [x] **Step 5: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_polyrepo_target_docs.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/echelon/cli.py src/echelon/orchestrator.py tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_polyrepo_target_docs.py
git commit -m "feat: resolve harness targets from workspace sources"
```

## Task 8: Update Spec/Squad Flow For Workspace Git

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`

- [x] **Step 1: Add failing squad continuation test**

In `tests/integration/test_squad_controller.py`, add a test using a branchless polyrepo fixture:

```python
def test_continue_blocks_branchless_workspace_before_new_run(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_continue([])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err
    assert "git init" in err
```

- [x] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/integration/test_squad_controller.py -q
```

Expected: FAIL because continue currently creates a new run in a branchless workspace.

- [x] **Step 3: Use the same preflight before squad run creation**

In `src/echelon/cli.py`, call `_workspace_git_preflight` before `echelon run` starts a new squad run and before `echelon continue` creates or resumes a run.

Important exception: if a command is explicitly repairing an existing branchless legacy run, it may proceed only when an existing run directory has a valid state file. The command must print:

```text
legacy branchless run detected; continuing for recovery only
```

This exception should not create a new branchless run.

- [x] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echelon/cli.py src/harness/squad.py tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py
git commit -m "feat: block new branchless workspace runs"
```

## Task 9: Documentation And Migration Guide

**Files:**
- Create: `docs/workspace-model.md`
- Modify: `docs/re-overview.md`
- Modify: `docs/re-config.md`
- Modify: `README.md`
- Modify: `tests/unit/test_polyrepo_target_docs.py`

- [x] **Step 1: Add failing docs test**

In `tests/unit/test_polyrepo_target_docs.py`, add:

```python
def test_workspace_model_docs_define_single_repo_as_one_source_root() -> None:
    text = Path("docs/workspace-model.md").read_text(encoding="utf-8")
    assert "sources: [.]" in text
    assert "lightweight workspace Git repo" in text
    assert "branchless workspace" in text
    assert "echelon spec target" in text


def test_re_docs_use_workspace_source_roots_not_monorepo_of_monorepos() -> None:
    text = Path("docs/re-overview.md").read_text(encoding="utf-8")
    assert "workspace-manifest.json" in text
    assert "source roots" in text
    assert "monorepo of monorepos" not in text
```

- [x] **Step 2: Run docs test and verify it fails**

Run:

```bash
python -m pytest tests/unit/test_polyrepo_target_docs.py -q
```

Expected: FAIL because docs are not updated.

- [x] **Step 3: Create workspace docs**

Create `docs/workspace-model.md`:

````markdown
# Workspace Model

Echelon treats every project as a workspace with zero or more source roots.

- Single repo: `sources: [.]`
- Polyrepo: `sources: [repo-a, repo-b]`
- Planning-only workspace: `sources: []`

The workspace root owns `.specify/`, `specs/`, `runs/`, and Echelon state. Source roots own implementation files.

For polyrepo work, initialize a lightweight workspace Git repo:

```bash
git init
printf "/og-platform/\n/pbg-api/\n/runs/\n" >> .gitignore
git add .gitignore .specify specs
git commit -m "chore: initialize echelon workspace"
```

Do not use branchless workspaces for new runs. Echelon only allows branchless workspaces for legacy recovery.

When a workspace has multiple source roots, select the implementation target before harness build:

```bash
echelon spec target 001-feature og-platform
echelon harness run 001-feature
```
````

- [x] **Step 4: Update RE docs**

In `docs/re-overview.md`, add:

```markdown
Reverse engineering writes `workspace-manifest.json` and, for compatibility, `repos-manifest.json`. New tooling should read `workspace-manifest.json` first because it distinguishes orchestration workspace files from implementation source roots.
```

In `docs/re-config.md`, add:

```markdown
`re.polyrepo.*` controls source-root discovery inside the workspace. It does not decide whether the workspace root itself is implementation code; that comes from the workspace manifest.
```

In `README.md`, add a short link to `docs/workspace-model.md` near the harness/polyrepo section.

- [x] **Step 5: Run docs test and verify it passes**

Run:

```bash
python -m pytest tests/unit/test_polyrepo_target_docs.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add README.md docs/workspace-model.md docs/re-overview.md docs/re-config.md tests/unit/test_polyrepo_target_docs.py
git commit -m "docs: document workspace source roots"
```

## Task 10: End-To-End Regression Matrix

**Files:**
- Create: `tests/integration/test_workspace_source_roots_e2e.py`

- [x] **Step 1: Write e2e regression tests**

Create `tests/integration/test_workspace_source_roots_e2e.py`:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def test_workspace_manifest_cli_single_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "workspace-manifest.json"

    result = _run(["python", "-m", "echelon.workspace_model", str(tmp_path), str(output)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["workspace"]["git_role"] == "source"
    assert data["sources"][0]["path"] == "."


def test_workspace_manifest_cli_polyrepo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    for name in ["og-platform", "pbg-api"]:
        source = tmp_path / name
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "workspace-manifest.json"

    result = _run(["python", "-m", "echelon.workspace_model", str(tmp_path), str(output)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["workspace"]["git_role"] == "orchestration"
    assert [source["path"] for source in data["sources"]] == ["og-platform", "pbg-api"]
```

- [x] **Step 2: Run e2e tests and verify they pass**

Run:

```bash
python -m pytest tests/integration/test_workspace_source_roots_e2e.py -q
```

Expected: PASS.

- [x] **Step 3: Run focused regression suite**

Run:

```bash
python -m pytest \
  tests/unit/test_workspace_model.py \
  tests/unit/test_workspace_git_preflight.py \
  tests/unit/test_target_detection.py \
  tests/unit/test_cli_harness_run.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/unit/test_harness_target_state.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_polyrepo_target_docs.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/integration/test_workspace_source_roots_e2e.py \
  -q
bash tests/integration/re/test-discover-repos.sh
bash tests/integration/re/test-run-analysis-polyrepo.sh
```

Expected: all PASS.

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_workspace_source_roots_e2e.py
git commit -m "test: cover workspace source roots end to end"
```

## Task 11: Final Verification And Release Notes

**Files:**
- Modify: `docs/superpowers/specs/2026-06-18-workspace-source-roots-design.md`
- Create: `docs/superpowers/reports/2026-06-18-workspace-source-roots-verification.md`

- [x] **Step 1: Run complete verification subset**

Run:

```bash
python -m pytest \
  tests/unit/test_workspace_model.py \
  tests/unit/test_workspace_git_preflight.py \
  tests/unit/test_target_detection.py \
  tests/unit/test_cli_harness_run.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/unit/test_harness_target_state.py \
  tests/unit/test_ralph_outer.py \
  tests/unit/test_polyrepo_target_docs.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/integration/test_squad_controller.py \
  tests/integration/test_workspace_source_roots_e2e.py \
  -q
bash tests/integration/re/test-discover-repos.sh
bash tests/integration/re/test-run-analysis-polyrepo.sh
```

Expected: all PASS.

- [x] **Step 2: Write verification report**

Create `docs/superpowers/reports/2026-06-18-workspace-source-roots-verification.md`:

```markdown
# Workspace Source Roots Verification

## Scope

Implemented deterministic workspace/source-root model across discovery, RE analysis, harness target detection, harness state, and user documentation.

## Verified Commands

- `python -m pytest tests/unit/test_workspace_model.py tests/unit/test_workspace_git_preflight.py tests/unit/test_target_detection.py tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_harness_target_state.py tests/unit/test_ralph_outer.py tests/unit/test_polyrepo_target_docs.py tests/kernel/test_codegraph_integration_contract.py tests/integration/test_squad_controller.py tests/integration/test_workspace_source_roots_e2e.py -q`
- `bash tests/integration/re/test-discover-repos.sh`
- `bash tests/integration/re/test-run-analysis-polyrepo.sh`

## Behavior Guarantees

- Single repo remains `sources: [.]`.
- Polyrepo workspace uses child source roots and does not classify the workspace root as implementation code.
- Branchless polyrepo workspaces are blocked before new squad or harness runs.
- RE prefers `workspace-manifest.json` and keeps `repos-manifest.json` compatibility.
- Harness prompt context includes explicit workspace and source root paths.
```

- [x] **Step 3: Update design status**

Append to `docs/superpowers/specs/2026-06-18-workspace-source-roots-design.md`:

```markdown
## Implementation Status

Implemented on branch `workspace-source-roots-design`. Verification evidence is in `docs/superpowers/reports/2026-06-18-workspace-source-roots-verification.md`.
```

- [x] **Step 4: Commit final docs**

```bash
git add docs/superpowers/specs/2026-06-18-workspace-source-roots-design.md docs/superpowers/reports/2026-06-18-workspace-source-roots-verification.md
git commit -m "docs: record workspace source roots verification"
```

- [x] **Step 5: Push branch**

Run:

```bash
git push origin workspace-source-roots-design
```

Expected: branch pushes successfully.

## Execution Notes

- Do not squash task commits while developing. The risk is in cross-cutting behavior, so granular rollback matters.
- If Task 4 branchless preflight blocks too many legacy tests, keep the helper strict and update tests to explicitly mark legacy recovery paths. Do not silently restore new branchless run creation.
- If `discover-repos.sh` cannot import `echelon.workspace_model` in an installed extension, fix `PYTHONPATH` or call the installed `python -m echelon.workspace_model`; do not duplicate manifest logic in shell.
- Stop after any task that breaks single-repo harness tests. Single repo as `sources: [.]` is the compatibility baseline.

# Polyrepo Target Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make harness build/resume/land deterministically use the correct implementation repo in polyrepo projects by enforcing or inferring `targets:` before build starts.

**Architecture:** Add a Python-owned target detection/preflight layer that runs before single-repo harness setup. Explicit spec frontmatter remains authoritative; missing targets in polyrepos trigger deterministic inference with mode-specific behavior. Harness state, recovery, and land learn target repo metadata so nested repo commits are visible and recoverable.

**Tech Stack:** Python 3.11, pytest, existing `harness.spec_frontmatter`, `echelon.orchestrator`, `echelon.cli`, `harness.recovery`, and `harness.land`/land CLI modules.

---

## File Structure

- Create `src/echelon/target_detection.py`
  - Detect nested git repos under a polyrepo root.
  - Score candidate target repos using spec artifacts and path/name evidence.
  - Return structured recommendation data with confidence, evidence, and ambiguity state.

- Modify `src/echelon/orchestrator.py`
  - Add single-target validation helper for normal implementation specs.
  - Keep `validate_targets()` and `run_multi_target()` behavior for explicit multi-target support.

- Modify `src/echelon/cli.py`
  - Run target preflight in `_cmd_harness_run()` before local harness config checks.
  - In `semi`, print recommendation and stop.
  - In `banzai`, write high-confidence target to frontmatter and continue through target dispatch.
  - Keep `echelon spec target` as the explicit confirmation command.

- Modify `src/harness/spec_frontmatter.py`
  - Reuse existing `write_targets()` and `read_frontmatter()` without changing their public signatures.

- Modify `src/harness/recovery.py`
  - Teach blocked-run recovery to report and inspect recorded target repo metadata.
  - Do not cherry-pick nested target commits into the wrapper repo.

- Create `src/harness/target_state.py`
  - Normalize target metadata passed from polyrepo dispatch into harness state fields.

- Modify `src/harness/state.py`
  - Add optional target metadata parameters to `StateStore.initialize()`.

- Modify `src/harness/coordinator.py`
  - Pass `ECHELON_POLYREPO_ROOT` and `ECHELON_TARGET_REPO_PATH` metadata into `StateStore.initialize()`.

- Modify `src/harness/land.py`
  - Add `resolve_land_repo()` and use it when selecting the repo for git operations.

- Modify `src/echelon/cli.py`
  - Keep land CLI behavior stable while passing the wrapper project directory and spec directory context into land helpers.

- Modify `tests/unit/test_land.py`, `tests/unit/test_land_cli.py`, and `tests/unit/test_land_gitops.py`
  - Ensure land uses target repo metadata when present.

- Create `tests/unit/test_target_detection.py`
  - Unit coverage for scoring, confidence, ambiguity, and no-polyrepo behavior.

- Modify `tests/unit/test_harness_single_repo_unchanged.py`
  - Update the old “no targets falls through” expectation for polyrepo roots.
  - Keep single-repo behavior unchanged.

- Modify `tests/unit/test_orchestrator.py`
  - Add exact-one-target validation tests.

- Modify `tests/unit/test_cli_harness_run.py`
  - Add semi/banzai preflight behavior tests.

- Modify `tests/unit/test_harness_recovery.py`
  - Add target repo preserved-commit reporting tests.

- Modify `tests/unit/test_land.py` and/or `tests/unit/test_land_cli.py`
  - Add target repo land behavior tests.

---

## Task 1: Add Deterministic Target Detection

**Files:**
- Create: `src/echelon/target_detection.py`
- Create: `tests/unit/test_target_detection.py`

- [ ] **Step 1: Write failing tests for nested repo discovery and scoring**

Create `tests/unit/test_target_detection.py`:

```python
from pathlib import Path

import pytest

from echelon.target_detection import detect_target


def _git_marker(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


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
def test_detect_target_returns_not_polyrepo_for_single_repo(tmp_path: Path) -> None:
    root = tmp_path
    _git_marker(root)
    spec_dir = root / "specs" / "001-local"
    spec_dir.mkdir(parents=True)
    _write(spec_dir / "tasks.md", "Fix local code\n")

    result = detect_target(spec_dir=spec_dir, polyrepo_root=root)

    assert result.decision == "not_polyrepo"
    assert result.recommended_target is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_target_detection.py
```

Expected: import failure for `echelon.target_detection`.

- [ ] **Step 3: Implement minimal detector**

Create `src/echelon/target_detection.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


DEFAULT_CONFIDENCE_THRESHOLD = 0.80


@dataclass(frozen=True)
class TargetCandidate:
    repo: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TargetDetectionResult:
    recommended_target: str | None
    confidence: float
    decision: str
    candidates: list[TargetCandidate]


_PATH_RE = re.compile(r"`([^`]+\.[A-Za-z0-9]+)`|((?:src|app|lib|packages|services|tests|__tests__)/[A-Za-z0-9_./-]+)")


def _candidate_repos(polyrepo_root: Path) -> list[Path]:
    repos: list[Path] = []
    for child in sorted(polyrepo_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {".git", ".specify", "specs", "runs", "knowledge-base"}:
            continue
        if (child / ".git").exists():
            repos.append(child)
    return repos


def _spec_text(spec_dir: Path) -> str:
    chunks: list[str] = []
    for name in ["spec.md", "plan.md", "tasks.md", "research.md"]:
        path = spec_dir / name
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    contracts = spec_dir / "contracts"
    if contracts.exists():
        for path in sorted(contracts.rglob("*.md")):
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _referenced_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for match in _PATH_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw:
            paths.add(raw.strip("/"))
    return paths


def detect_target(
    *,
    spec_dir: Path,
    polyrepo_root: Path,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> TargetDetectionResult:
    repos = _candidate_repos(polyrepo_root)
    if len(repos) <= 1:
        return TargetDetectionResult(None, 0.0, "not_polyrepo", [])

    text = _spec_text(spec_dir)
    lowered = text.lower()
    refs = _referenced_paths(text)
    scored: list[TargetCandidate] = []

    for repo in repos:
        points = 0
        evidence: list[str] = []

        if repo.name.lower() in lowered:
            points += 3
            evidence.append(f"spec artifacts mention repo name `{repo.name}`")

        package_json = repo / "package.json"
        if package_json.exists():
            pkg = package_json.read_text(encoding="utf-8", errors="ignore").lower()
            for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", repo.name.lower()):
                if token in lowered or token in pkg:
                    points += 1
                    evidence.append(f"package metadata aligns with `{token}`")

        for ref in sorted(refs):
            if (repo / ref).exists():
                points += 5
                evidence.append(f"referenced path exists: `{ref}`")

        confidence = min(1.0, points / 10.0)
        scored.append(TargetCandidate(repo=repo.name, confidence=confidence, evidence=evidence))

    scored.sort(key=lambda item: item.confidence, reverse=True)
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None

    if top.confidence >= threshold and (second is None or top.confidence - second.confidence >= 0.10):
        return TargetDetectionResult(top.repo, top.confidence, "recommend", scored)

    return TargetDetectionResult(None, top.confidence, "ambiguous", scored)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_target_detection.py
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/target_detection.py tests/unit/test_target_detection.py
git commit -m "feat: detect polyrepo spec target"
```

---

## Task 2: Add Single-Target Validation in Orchestrator

**Files:**
- Modify: `src/echelon/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator tests**

Append to `tests/unit/test_orchestrator.py`:

```python
from echelon.orchestrator import validate_single_target


@pytest.mark.unit
class TestValidateSingleTarget:
    def test_one_target_is_valid(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path, "repo-a")

        result = validate_single_target(["repo-a"], tmp_path)

        assert result == target

    def test_zero_targets_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            validate_single_target([], tmp_path)

        assert exc.value.code == 1

    def test_multiple_targets_exit_for_normal_specs(self, tmp_path: Path) -> None:
        _make_target(tmp_path, "repo-a")
        _make_target(tmp_path, "repo-b")

        with pytest.raises(SystemExit) as exc:
            validate_single_target(["repo-a", "repo-b"], tmp_path)

        assert exc.value.code == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_orchestrator.py
```

Expected: import failure for `validate_single_target`.

- [ ] **Step 3: Implement helper**

In `src/echelon/orchestrator.py`, add after `validate_targets()`:

```python
def validate_single_target(targets_rel: List[str], polyrepo_root: Path) -> Path:
    """Validate that a normal implementation spec has exactly one target repo."""
    if not targets_rel:
        print(
            "✗ No implementation target configured.\n"
            "  Fix: run 'echelon spec target <spec_id> <repo>'.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(targets_rel) > 1:
        print(
            "✗ Multiple targets configured for a single-target harness build.\n"
            "  Fix: keep exactly one target in spec frontmatter, or use explicit multi-target mode.",
            file=sys.stderr,
        )
        sys.exit(1)
    return validate_targets(targets_rel, polyrepo_root)[0]
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_orchestrator.py
```

Expected: all orchestrator tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat: validate single harness target"
```

---

## Task 3: Wire Target Preflight into Harness Run

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_harness_single_repo_unchanged.py`
- Modify: `tests/unit/test_cli_harness_run.py`

- [ ] **Step 1: Write failing test for semi mode recommendation**

Append to `tests/unit/test_cli_harness_run.py`:

```python
class TestHarnessTargetPreflight:
    def test_semi_mode_recommends_detected_target_and_stops(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        root = tmp_path
        echelon_yml = root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = root / "specs" / "001-opta-points-perf-fix"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# OptaPoints\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=complex phase=foundation req=FR-001 depends=none "
            "Fix `src/lib/sdapi/services/shared-promise.ts`\n",
            encoding="utf-8",
        )

        target = root / "rbf-opta-points"
        (target / ".git").mkdir(parents=True)
        (target / "src/lib/sdapi/services").mkdir(parents=True)
        (target / "src/lib/sdapi/services/shared-promise.ts").write_text("export {}\n", encoding="utf-8")
        other = root / "qag-load-testing-framework"
        (other / ".git").mkdir(parents=True)

        monkeypatch.chdir(root)
        from echelon.cli import _cmd_harness_run

        with pytest.raises(SystemExit) as exc:
            _cmd_harness_run(["001", "mode=semi"])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Recommended implementation target: rbf-opta-points" in err
        assert "echelon spec target 001-opta-points-perf-fix rbf-opta-points" in err
```

- [ ] **Step 2: Write failing test for banzai auto-write**

Append to the same class in `tests/unit/test_cli_harness_run.py`:

```python
    def test_banzai_mode_writes_detected_target_and_dispatches(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-opta-points-perf-fix"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# OptaPoints\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "Fix `src/lib/sdapi/services/shared-promise.ts`\n",
            encoding="utf-8",
        )

        target = root / "rbf-opta-points"
        (target / ".git").mkdir(parents=True)
        yml = target / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        yml.parent.mkdir(parents=True)
        yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (target / "src/lib/sdapi/services").mkdir(parents=True)
        (target / "src/lib/sdapi/services/shared-promise.ts").write_text("export {}\n", encoding="utf-8")

        other = root / "qag-load-testing-framework"
        (other / ".git").mkdir(parents=True)

        monkeypatch.chdir(root)
        from echelon.cli import _cmd_harness_run
        from harness.spec_frontmatter import read_frontmatter

        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=banzai"])

        assert exc.value.code == 0
        assert read_frontmatter(spec_dir)["targets"] == ["rbf-opta-points"]
        mock_run.assert_called_once()
```

- [ ] **Step 3: Update old single-repo unchanged test**

In `tests/unit/test_harness_single_repo_unchanged.py`, keep `test_no_targets_in_spec_uses_single_repo_path` unchanged. Replace `test_spec_without_targets_falls_through_to_init_error` with:

```python
    def test_spec_without_targets_in_polyrepo_blocks_before_wrapper_harness(
        self, tmp_path: Path, capsys
    ) -> None:
        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Wrapper spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("Fix `src/service.ts`\n", encoding="utf-8")

        for name in ["repo-a", "repo-b"]:
            repo = tmp_path / name
            (repo / ".git").mkdir(parents=True)

        import os
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_harness_run
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["024"])
            assert exc.value.code == 1
        finally:
            os.chdir(orig)

        err = capsys.readouterr().err
        assert "No implementation target configured" in err
        assert "echelon spec target" in err
```

- [ ] **Step 4: Run focused tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py
```

Expected: failures because `_cmd_harness_run()` does not call target detection yet.

- [ ] **Step 5: Implement preflight in `_cmd_harness_run()`**

In `src/echelon/cli.py`, extend imports in `_cmd_harness_run()`:

```python
    from harness.spec_frontmatter import find_spec_dir, read_frontmatter, write_status as _write_spec_status, write_targets
    from echelon.orchestrator import validate_targets, run_multi_target, validate_single_target
    from echelon.target_detection import detect_target
```

Replace the existing `if spec_dir is not None:` target block with:

```python
    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is not None:
        frontmatter = read_frontmatter(spec_dir)
        targets_rel: list[str] = frontmatter.get("targets") or []
        polyrepo_root = spec_dir.parent.parent
        if targets_rel:
            target = validate_single_target(targets_rel, polyrepo_root)
            sys.exit(run_multi_target(spec_id, [target], args[1:]))

        detection = detect_target(spec_dir=spec_dir, polyrepo_root=polyrepo_root)
        if detection.decision == "recommend":
            if mode == "banzai" and detection.recommended_target:
                write_targets(spec_dir, [detection.recommended_target])
                target = validate_single_target([detection.recommended_target], polyrepo_root)
                print(
                    f"✓ Wrote inferred implementation target: {detection.recommended_target} "
                    f"(confidence {detection.confidence:.2f})"
                )
                sys.exit(run_multi_target(spec_id, [target], args[1:]))
            print(
                f"✗ No implementation target configured.\n"
                f"  Recommended implementation target: {detection.recommended_target} "
                f"(confidence {detection.confidence:.2f})\n"
                "  Evidence:\n"
                + "".join(
                    f"  - {item}\n"
                    for item in (detection.candidates[0].evidence if detection.candidates else [])
                )
                + f"  Confirm with: echelon spec target {spec_id} {detection.recommended_target}\n"
                + f"  Then rerun:  echelon harness run {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        if detection.decision == "ambiguous":
            print(
                "✗ No implementation target configured and target detection was ambiguous.\n"
                f"  Fix: run 'echelon spec target {spec_id} <repo>'.",
                file=sys.stderr,
            )
            sys.exit(1)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_target_detection.py tests/unit/test_orchestrator.py
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_cli_harness_run.py tests/unit/test_harness_single_repo_unchanged.py
git commit -m "feat: preflight polyrepo harness targets"
```

---

## Task 4: Make Missing Target Harness Init Guidance Precise

**Files:**
- Modify: `src/echelon/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write failing assertion for exact init command**

Update `test_uninitialised_target_exits` in `tests/unit/test_orchestrator.py`:

```python
    def test_uninitialised_target_exits(self, tmp_path: Path, capsys) -> None:
        _make_target(tmp_path, "repo-b", initialised=False)
        with pytest.raises(SystemExit) as exc:
            validate_targets(["repo-b"], tmp_path)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "cd repo-b" in err
        assert "echelon harness init ." in err
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_orchestrator.py::TestValidateTargets::test_uninitialised_target_exits
```

Expected: fails because current message does not include the exact command pair.

- [ ] **Step 3: Update error message**

In `src/echelon/orchestrator.py`, change the uninitialised target print block to:

```python
            print(
                f"✗ {rel}: not initialised for harness.\n"
                f"  Fix:\n"
                f"    cd {rel}\n"
                f"    echelon harness init .",
                file=sys.stderr,
            )
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_orchestrator.py
```

Expected: all orchestrator tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "fix: guide target harness initialization"
```

---

## Task 5: Record Target Metadata in Harness Run State

**Files:**
- Modify: `src/echelon/orchestrator.py`
- Create: `src/harness/target_state.py`
- Modify: `src/harness/state.py`
- Modify: `src/harness/coordinator.py`
- Modify: `tests/unit/test_orchestrator.py`
- Create: `tests/unit/test_harness_target_state.py`
- Modify: `tests/unit/test_state_store_logic.py`
- Modify: `tests/unit/test_coordinator.py`

- [ ] **Step 1: Write failing test for target metadata normalization**

Create `tests/unit/test_harness_target_state.py`:

```python
from pathlib import Path

import pytest

from harness.target_state import target_state_updates


@pytest.mark.unit
def test_target_state_updates_include_repo_branch_and_commit(tmp_path: Path) -> None:
    target = tmp_path / "rbf-opta-points"
    target.mkdir()

    updates = target_state_updates(
        polyrepo_root=tmp_path,
        target_repo=target,
        target_branch="001-opta-points-perf-fix",
        target_commit="6132709363bb9f23da5ab9c711638f201885d7d1",
    )

    assert updates == {
        "polyrepo_root": str(tmp_path),
        "target_repo_path": str(target),
        "target_repo_name": "rbf-opta-points",
        "target_branch": "001-opta-points-perf-fix",
        "target_commit": "6132709363bb9f23da5ab9c711638f201885d7d1",
    }
```

- [ ] **Step 2: Write failing test for `StateStore.initialize()` target fields**

Add to `tests/unit/test_state_store_logic.py`:

```python
@pytest.mark.unit
def test_initialize_records_target_metadata(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "001", "default")
    state = store.initialize(
        run_id="run-1",
        mode="banzai",
        target_repo="rbf-opta-points",
        target_path="rbf-opta-points",
    )

    assert state["target_repo"] == "rbf-opta-points"
    assert state["target_path"] == "rbf-opta-points"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_harness_target_state.py tests/unit/test_state_store_logic.py
```

Expected: import failure for `harness.target_state` and unexpected keyword errors for the new state fields.

- [ ] **Step 4: Implement state helper**

Create `src/harness/target_state.py`:

```python
from __future__ import annotations

from pathlib import Path


def target_state_updates(
    *,
    polyrepo_root: Path,
    target_repo: Path,
    target_branch: str | None,
    target_commit: str | None,
) -> dict[str, str | None]:
    return {
        "polyrepo_root": str(polyrepo_root),
        "target_repo_path": str(target_repo),
        "target_repo_name": target_repo.name,
        "target_branch": target_branch,
        "target_commit": target_commit,
    }
```

- [ ] **Step 5: Extend `StateStore.initialize()`**

Modify `src/harness/state.py`:

```python
def initialize(
    self,
    run_id: str,
    mode: str,
    max_outer: int = 5,
    max_inner: int = 3,
    token_budget: int = 0,
    target_repo: str | None = None,
    target_path: str | None = None,
) -> Dict[str, Any]:
```

Add these initial state fields:

```python
"target_repo": target_repo,
"target_path": target_path,
```

- [ ] **Step 6: Wire metadata recording at target dispatch boundary**

In `src/echelon/orchestrator.py`, update `run_multi_target()` to print and pass a stable environment variable set into each target harness process:

```python
        env = os.environ.copy()
        env["ECHELON_POLYREPO_ROOT"] = str(target.parent)
        env["ECHELON_TARGET_REPO_PATH"] = str(target)
        env["ECHELON_TARGET_REPO_NAME"] = target.name
        proc = subprocess.Popen(
            cmd,
            cwd=str(target),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
```

Add `import os` at the top of the file.

In `src/harness/coordinator.py`, read the environment variables immediately before the `state_store.initialize(...)` call:

```python
target_repo_name = os.environ.get("ECHELON_TARGET_REPO_NAME")
target_repo_path = os.environ.get("ECHELON_TARGET_REPO_PATH")
```

Pass `target_repo=target_repo_name` and `target_path=target_repo_path` into `StateStore.initialize()`. Keep both values `None` when the environment variables are absent, preserving single-repo behavior.

- [ ] **Step 7: Run focused tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_orchestrator.py tests/unit/test_harness_target_state.py tests/unit/test_state_store_logic.py tests/unit/test_coordinator.py
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/orchestrator.py src/harness/target_state.py src/harness/state.py src/harness/coordinator.py tests/unit/test_orchestrator.py tests/unit/test_harness_target_state.py tests/unit/test_state_store_logic.py tests/unit/test_coordinator.py
git commit -m "feat: record harness target metadata"
```

---

## Task 6: Teach Resume to Report Preserved Target Repo Commits

**Files:**
- Modify: `src/harness/recovery.py`
- Modify: `tests/unit/test_harness_recovery.py`

- [ ] **Step 1: Write failing recovery test**

Append to `tests/unit/test_harness_recovery.py`:

```python
@pytest.mark.unit
def test_recover_blocked_run_reports_existing_target_repo_commit(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "wrapper"
    _init_repo(wrapper)
    _commit_file(wrapper, "README.md", "wrapper\n", "wrapper base")

    target = wrapper / "rbf-opta-points"
    _init_repo(target)
    _commit_file(target, "README.md", "target\n", "target base")
    _git(target, "checkout", "-b", "001-opta-points-perf-fix")
    recovered = _commit_file(
        target,
        "src/fix.ts",
        "fix\n",
        "fix(perf): OptaPoints performance stabilization",
    )

    result = recover_blocked_run(
        project_dir=wrapper,
        spec_id="001-opta-points-perf-fix",
        strategy_id="default",
        state={
            "termination_reason": "build_incomplete",
            "target_repo_path": str(target),
            "target_branch": "001-opta-points-perf-fix",
            "target_commit": recovered,
        },
        gitops=_make_gitops(wrapper),
    )

    assert result.source == "target_repo"
    assert result.commit == recovered
    assert result.applied is False
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_harness_recovery.py::test_recover_blocked_run_reports_existing_target_repo_commit
```

Expected: failure because recovery does not inspect `target_repo_path`.

- [ ] **Step 3: Implement target repo recovery branch**

In `src/harness/recovery.py`, locate `recover_blocked_run()`. Before wrapper worktree/mirror recovery, add logic:

```python
    target_repo_raw = state.get("target_repo_path")
    target_branch = state.get("target_branch")
    target_commit = state.get("target_commit")
    if target_repo_raw and target_branch and target_commit:
        target_repo = Path(str(target_repo_raw))
        if target_repo.exists():
            current = _git(target_repo, "rev-parse", "HEAD", check=False)
            branch = _git(target_repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
            if current.returncode == 0 and branch.returncode == 0:
                return RecoveryResult(
                    source="target_repo",
                    commit=str(target_commit),
                    applied=False,
                    message=(
                        "Implementation commit preserved in target repo "
                        f"{target_repo.name} on branch {target_branch}: {target_commit}"
                    ),
                )
```

Adapt helper names to the existing `recovery.py` subprocess wrapper and `RecoveryResult` fields.

- [ ] **Step 4: Run focused recovery tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_harness_recovery.py tests/unit/test_cli_harness_resume.py
```

Expected: all focused recovery/resume tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/recovery.py tests/unit/test_harness_recovery.py
git commit -m "feat: report preserved target repo work"
```

---

## Task 7: Land Target Repo Branches

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/land.py` or actual land module found by `rg "def .*land|ready_to_land|target_branch" src/harness src/echelon`
- Modify: `tests/unit/test_land.py`
- Modify: `tests/unit/test_land_cli.py`

- [ ] **Step 1: Locate land entry points**

Run:

```bash
rg -n "def .*land|ready_to_land|merge.*branch|target_branch|branch_name" src/harness src/echelon tests/unit/test_land.py tests/unit/test_land_cli.py
```

Expected: identify the function that chooses repo path and branch for land.

- [ ] **Step 2: Write failing land test**

Add to `tests/unit/test_land.py` near existing branch/merge tests:

```python
def test_land_uses_target_repo_path_when_spec_has_single_target(tmp_path: Path) -> None:
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    target = wrapper / "rbf-opta-points"
    target.mkdir()

    spec_dir = wrapper / "specs" / "001-opta-points-perf-fix"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\n"
        "targets:\n"
        "  - rbf-opta-points\n"
        "status: ready_to_land\n"
        "---\n"
        "# Spec\n",
        encoding="utf-8",
    )

    resolved = _resolve_land_repo_for_test(wrapper, spec_dir)

    assert resolved == target
```

If no helper exists, create a small production helper first in the land module and test that helper:

```python
from harness.land import resolve_land_repo
```

The helper signature should be:

```python
def resolve_land_repo(project_dir: Path, spec_dir: Path) -> Path:
    ...
```

- [ ] **Step 3: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k target_repo_path
```

Expected: failure because land currently resolves wrapper repo.

- [ ] **Step 4: Implement land repo resolver**

In `src/harness/land.py`, add:

```python
from harness.spec_frontmatter import read_frontmatter


def resolve_land_repo(project_dir: Path, spec_dir: Path) -> Path:
    frontmatter = read_frontmatter(spec_dir)
    targets = frontmatter.get("targets") or []
    if not targets:
        return project_dir
    if len(targets) != 1:
        raise LandError("land requires exactly one target repo for normal specs")
    target = (project_dir / str(targets[0])).resolve()
    if not target.exists():
        raise LandError(f"target repo not found: {targets[0]}")
    return target
```

Use the existing land exception type instead of `LandError` if the module already defines one.

Wire land execution to use `resolve_land_repo()` for git operations while still reading the spec from the wrapper spec directory.

- [ ] **Step 5: Add wrapper submodule pointer test**

Add a test that confirms land does not commit wrapper submodule pointer unless a config flag is enabled. If the current land tests use mocked git operations, assert no `git add rbf-opta-points` occurs in wrapper mode by default.

- [ ] **Step 6: Run focused land tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py tests/unit/test_land_cli.py tests/unit/test_land_gitops.py
```

Expected: all focused land tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/harness/land.py src/echelon/cli.py tests/unit/test_land.py tests/unit/test_land_cli.py tests/unit/test_land_gitops.py
git commit -m "feat: land polyrepo target branches"
```

---

## Task 8: Update User-Facing Docs and Run Full Verification

**Files:**
- Modify: `extension/commands/echelon.harness-run.md`
- Modify: `extension/commands/echelon.harness-resume.md`
- Modify: `README.md`

- [ ] **Step 1: Add documentation test**

Create `tests/unit/test_polyrepo_target_docs.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_harness_run_docs_explain_polyrepo_target_preflight() -> None:
    text = (ROOT / "extension" / "commands" / "echelon.harness-run.md").read_text(encoding="utf-8")

    assert "echelon spec target <spec_id> <repo>" in text
    assert "semi mode recommends" in text
    assert "banzai mode writes" in text


def test_readme_mentions_spec_target_for_polyrepos() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "echelon spec target" in text
    assert "polyrepo" in text.lower()
```

- [ ] **Step 2: Run doc tests to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_polyrepo_target_docs.py
```

Expected: fails until docs are updated.

- [ ] **Step 3: Update harness command docs**

In `extension/commands/echelon.harness-run.md`, add a concise section:

```markdown
## Polyrepo Target Preflight

If the spec contains `targets:`, harness runs inside that target repo. Normal implementation specs require exactly one target.

If a polyrepo spec has no `targets:`, harness detects the recommended implementation repo before build:

- semi mode recommends the target and stops for confirmation
- banzai mode writes `targets:` and continues only when confidence is high
- low confidence or tied candidates block with `echelon spec target <spec_id> <repo>` guidance
```

Add equivalent short notes to resume/land docs.

- [ ] **Step 4: Update README**

Add a short user flow:

```markdown
### Polyrepo Targeting

For polyrepo projects, record the implementation repo before harness build:

```bash
echelon spec target 001-feature app-repo
echelon harness run 001-feature
```

In `semi` mode, Echelon recommends a target and waits for confirmation. In `banzai` mode, Echelon writes the target automatically only when confidence is high.
```
```

When editing the README, ensure nested fenced code blocks are valid Markdown.

- [ ] **Step 5: Run focused docs tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_polyrepo_target_docs.py
```

Expected: docs tests pass.

- [ ] **Step 6: Run full unit suite**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit
```

Expected: all unit tests pass.

- [ ] **Step 7: Run final active prompt/path scan**

Run:

```bash
rg -n '(specs/\\.\\.\\.|\\.specify/\\.\\.\\.|specs/\\{feature\\}/|specs/\\{NNN\\}-\\{feature\\}/|active_specialists plus SCIENTIST)' extension --glob '*.md' --glob '*.yaml' --glob '*.yml' --glob '!extension/agents/exploration/sage.md'
```

Expected: only intentional `init.md` lifecycle references if the previous cleanup state is unchanged.

- [ ] **Step 8: Commit docs and final verification**

```bash
git add extension/commands/echelon.harness-run.md extension/commands/echelon.harness-resume.md README.md tests/unit/test_polyrepo_target_docs.py
git commit -m "docs: explain polyrepo target preflight"
```

---

## Self-Review Notes

Spec coverage:

- Explicit `targets:` authority is covered by Tasks 2, 3, and 7.
- Semi recommendation behavior is covered by Task 3.
- Banzai high-confidence auto-write is covered by Task 3.
- Low-confidence/tie blocking is covered by Tasks 1 and 3.
- Harness init guidance is covered by Task 4.
- Target metadata and preserved work recovery are covered by Tasks 5 and 6.
- Target repo land behavior is covered by Task 7.
- User-facing documentation is covered by Task 8.

Deferred wording scan:

- No deferred markers or vague implementation wording are used as plan steps.
- Steps that require code include concrete test or implementation snippets.

Type consistency:

- `TargetDetectionResult`, `TargetCandidate`, `detect_target()`, `validate_single_target()`, `target_state_updates()`, and `resolve_land_repo()` names are consistent across tasks.

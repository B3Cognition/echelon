# GitHub Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build GitHub-only release automation that bumps Echelon to the next minor-boundary version and creates a GitHub Release only after CI is green for the tagged commit.

**Architecture:** Add a local Python release-prep script that owns version parsing, next-minor calculation, metadata updates, and validation. Add a tag-triggered GitHub Actions workflow that validates tag/package metadata, checks existing CI check-runs for the tagged SHA, builds package artifacts, and creates the GitHub Release. Document the maintainer flow in `docs/releasing.md`.

**Tech Stack:** Python 3.11 standard library, PyYAML already present in project dependencies, pytest, GitHub Actions, `actions/create-github-app-token` not required, `actions/create-release` avoided in favor of `gh release create`.

## Global Constraints

- Releases are GitHub-only; do not publish to PyPI.
- Release versions must be the closest higher minor-boundary version.
- A current version with a minor component greater than `9` is invalid release state.
- Release tags must be shaped as `vMAJOR.MINOR.0`.
- The release workflow must verify green GitHub CI for the exact tagged commit before creating a release.
- Do not create commits from GitHub Actions.

---

## File Structure

- `scripts/prepare-release.py`: command-line release prep utility plus testable pure functions.
- `tests/unit/test_prepare_release.py`: unit tests for version calculation, dry-run, metadata update, and validation failures.
- `.github/workflows/release.yml`: tag-triggered GitHub Release workflow with CI gate and artifact upload.
- `docs/releasing.md`: maintainer-facing release instructions.

### Task 1: Release Prep Tests

**Files:**
- Create: `tests/unit/test_prepare_release.py`

**Interfaces:**
- Consumes: future `scripts/prepare-release.py` functions loaded through `importlib.util.spec_from_file_location`.
- Produces: tests for `Version`, `next_minor_version`, `prepare_release`, and `validate_release_metadata`.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_prepare_release.py` with tests that:

```python
def test_next_minor_version_examples():
    assert module.next_minor_version(module.Version.parse("3.0.81")).text == "3.1.0"
    assert module.next_minor_version(module.Version.parse("3.1.5")).text == "3.2.0"
    assert module.next_minor_version(module.Version.parse("3.9.6")).text == "4.0.0"

def test_dry_run_does_not_write_files(tmp_path):
    project = make_project(tmp_path, "3.0.81")
    result = module.prepare_release(project, dry_run=True)
    assert result.old_version == "3.0.81"
    assert result.new_version == "3.1.0"
    assert read_version(project / "pyproject.toml") == "3.0.81"

def test_prepare_release_updates_all_metadata(tmp_path):
    project = make_project(tmp_path, "3.0.81")
    module.prepare_release(project, dry_run=False)
    assert all metadata surfaces contain "3.1.0"

def test_validate_release_metadata_rejects_mismatch(tmp_path):
    project = make_project(tmp_path, "3.0.81")
    corrupt README to "3.0.82"
    with pytest.raises(module.ReleaseError):
        module.validate_release_metadata(project, "3.0.81")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_prepare_release.py -q`

Expected: failure because `scripts/prepare-release.py` does not exist.

### Task 2: Release Prep Script

**Files:**
- Create: `scripts/prepare-release.py`
- Modify if needed: `tests/unit/test_prepare_release.py`

**Interfaces:**
- Produces:
  - `Version.parse(text: str) -> Version`
  - `Version.text -> str`
  - `next_minor_version(version: Version) -> Version`
  - `prepare_release(root: Path, dry_run: bool = False) -> ReleaseResult`
  - `validate_release_metadata(root: Path, expected_version: str) -> None`
  - CLI: `python scripts/prepare-release.py [--dry-run]`

- [ ] **Step 1: Implement minimal script**

Implement dataclasses for `Version` and `ReleaseResult`, regex-based exact replacement helpers, metadata validation, and the CLI.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/unit/test_prepare_release.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run current metadata test**

Run: `pytest tests/unit/test_version_metadata.py -q`

Expected: pass after confirming every version surface matches `pyproject.toml`.

### Task 3: Release Workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes repository metadata and existing CI check-runs for `${{ github.sha }}`.
- Produces a GitHub Release with generated notes and `dist/*` artifacts.

- [ ] **Step 1: Add workflow**

Create a tag-triggered workflow that:

```yaml
on:
  push:
    tags:
      - "v*"
```

Uses Python 3.11, validates tag/package metadata, queries `gh api repos/{owner}/{repo}/commits/{sha}/check-runs`, requires `Shell tests (unit + integration + e2e + validation)` and `Python unit tests` to be successful, builds with `python -m build`, and creates the release with `gh release create`.

- [ ] **Step 2: Check workflow syntax shape**

Run: `python - <<'PY'` with `yaml.safe_load` on `.github/workflows/release.yml`.

Expected: YAML parses successfully.

### Task 4: Release Documentation

**Files:**
- Create: `docs/releasing.md`

**Interfaces:**
- Consumes implemented command names and workflow behavior.
- Produces maintainer instructions for GitHub Releases.

- [ ] **Step 1: Add docs**

Document `python scripts/prepare-release.py --dry-run`, `python scripts/prepare-release.py`, commit, push, wait for CI, tag, and inspect failed release workflow.

- [ ] **Step 2: Run doc sanity checks**

Run: `rg -n "PyPI|prepare-release|git tag|CI" docs/releasing.md`

Expected: docs mention GitHub-only release scope, prep script, tag command, and CI gate.

### Task 5: Final Verification

**Files:**
- Verify all created and modified files.

**Interfaces:**
- Consumes all prior tasks.
- Produces a releasable implementation.

- [ ] **Step 1: Run focused release tests**

Run: `pytest tests/unit/test_prepare_release.py tests/unit/test_version_metadata.py -q`

Expected: all pass.

- [ ] **Step 2: Run dry-run on repository**

Run: `python scripts/prepare-release.py --dry-run`

Expected: prints current version and computed next release version, with no file changes.

- [ ] **Step 3: Build package**

Run: `python -m build`

Expected: `dist/echelon-*.tar.gz` and `dist/echelon-*.whl` are produced.

## Self-Review

Spec coverage:

- Next-minor version policy: Task 1 and Task 2.
- Metadata surface updates: Task 1 and Task 2.
- GitHub-only release workflow: Task 3.
- CI-green gate for exact tagged commit: Task 3.
- Maintainer docs: Task 4.
- Verification: Task 5.

Placeholder scan: no pending placeholders remain.

Type consistency: task interfaces consistently use `Version`, `ReleaseResult`, `next_minor_version`, `prepare_release`, and `validate_release_metadata`.

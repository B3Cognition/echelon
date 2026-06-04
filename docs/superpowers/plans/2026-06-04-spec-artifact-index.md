# Spec Artifact Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a deterministic `{spec_dir}/ARTIFACTS.md` map so humans can quickly understand Echelon spec-folder outputs without spending LLM tokens.

**Architecture:** Add a Python-owned artifact-index generator, expose it as `echelon artifacts <spec_id>`, and refresh it from deterministic harness success paths. Prompts may call the command, but agents must not hand-author the generated file.

**Tech Stack:** Python 3.11+, `pathlib`, `dataclasses`, existing `harness.spec_frontmatter`, pytest, Markdown prompt/docs tests.

---

## File Structure

- Create `src/echelon/artifact_index.py`: static registry, lifecycle inference, Markdown rendering, write helper.
- Create `tests/unit/test_artifact_index.py`: generator behavior.
- Create `tests/unit/test_cli_artifacts.py`: `echelon artifacts <spec_id>` behavior.
- Modify `src/echelon/cli.py`: usage, `_cmd_artifacts`, main dispatch.
- Modify `src/harness/ralph.py`: refresh index after `ready_to_land` status/run-history update.
- Modify `extension/workflow/phases/phase4-document.md`: call deterministic command after `finalize-run.sh`.
- Modify `extension/workflow/phases/build-8-finalize.md`: call deterministic command before final build summary.
- Modify `tests/unit/test_phase_output_paths.py`: prompt-surface assertions.
- Modify `README.md`: short human guide and command reference.
- Create `tests/unit/test_artifact_index_docs.py`: README coverage.

## Artifact Registry Contract

`src/echelon/artifact_index.py` will define:

```python
@dataclass(frozen=True)
class ArtifactDefinition:
    path: str
    title: str
    purpose: str
    phase: str
    owner: str
    updated_when: str
    audience: str
    required_stage: str | None = None
```

Use this lifecycle order:

```python
STAGE_ORDER = {"phase_a": 1, "build": 2, "verified": 3, "landed": 4}
```

The initial registry must include these known outputs. `required_stage` is only set for files expected by that lifecycle stage; all others are optional unless present.

| Path | Title | Required Stage |
| --- | --- | --- |
| `spec.md` | Feature contract | `phase_a` |
| `plan.md` | Implementation plan | `phase_a` |
| `tasks.md` | Task ledger | `phase_a` |
| `research.md` | Research notes | |
| `data-model.md` | Data model | |
| `contracts` | Contracts | |
| `checklists` | Checklists | |
| `constitution.md` | Constitution snapshot | |
| `strategic-overview.md` | Strategic overview | |
| `feasibility.md` | Feasibility report | |
| `prioritization.md` | Prioritization | |
| `estimates.md` | Estimates | |
| `mvp-scope.md` | MVP scope | |
| `risk-matrix.md` | Risk matrix | |
| `dependencies.md` | Dependencies | |
| `critical-path.md` | Critical path | |
| `implementability-report.md` | Implementability report | |
| `test-strategy.md` | Test strategy | |
| `test-architecture.md` | Test architecture | |
| `coverage-map.md` | Coverage map | |
| `quality-gates.md` | Quality gates | |
| `issues.md` | Issues | |
| `spec-diagram.svg` | Spec diagram SVG | |
| `spec-diagram.png` | Spec diagram PNG | |
| `progress-report.md` | Progress report | `build` |
| `spec-compliance-report.md` | Spec compliance report | `build` |
| `code-review-report.md` | Code review report | `build` |
| `test-quality-report.md` | Test quality report | `build` |
| `integration-report.md` | Integration report | `build` |
| `gap-report.md` | Gap report | `verified` |
| `excess-report.md` | Excess report | |
| `traceability-matrix.md` | Traceability matrix | `verified` |
| `verification-summary.md` | Verification summary | `verified` |
| `fulfillment-report.md` | Fulfillment report | `verified` |
| `run-history.json` | Run history | `build` |

For each definition, fill concise `purpose`, `phase`, `owner`, `updated_when`, and `audience` strings in code. Keep each string one sentence or shorter.

## Task 1: Generator

- [ ] **Step 1: Write failing tests**

Create tests covering:

```python
def test_render_lists_present_known_artifacts(tmp_path: Path) -> None: ...
def test_phase_a_stage_reports_missing_required_files(tmp_path: Path) -> None: ...
def test_optional_missing_files_do_not_appear_as_required_gaps(tmp_path: Path) -> None: ...
def test_unclassified_top_level_files_are_listed(tmp_path: Path) -> None: ...
def test_verified_stage_detected_from_verification_summary(tmp_path: Path) -> None: ...
def test_landed_stage_detected_from_frontmatter_status(tmp_path: Path) -> None: ...
def test_write_artifact_index_overwrites_only_artifacts_md(tmp_path: Path) -> None: ...
```

Use `generated_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)` in render/write tests so output assertions are stable.

Assert these exact output fragments:

```python
assert "# Artifact Map" in text
assert "This file is generated by Echelon." in text
assert "Lifecycle stage: phase_a" in text
assert "`tasks.md`" in text
assert "`plan.md`" in text
assert "| `spec-diagram.png` | Optional missing |" in text
assert "## Unclassified Files" in text
assert "`surprise-notes.md`" in text
assert "Generated at: 2026-06-04T12:00:00+00:00" in text
```

- [ ] **Step 2: Verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_artifact_index.py -q
```

Expected: `ModuleNotFoundError: No module named 'echelon.artifact_index'`.

- [ ] **Step 3: Implement `src/echelon/artifact_index.py`**

Expose these functions:

```python
def infer_lifecycle_stage(spec_dir: Path) -> str:
    ...

def render_artifact_index(
    spec_dir: Path,
    generated_at: datetime | None = None,
) -> str:
    ...

def write_artifact_index(
    spec_dir: Path,
    generated_at: datetime | None = None,
) -> Path:
    ...
```

Stage inference rules:

```python
if read_frontmatter(spec_dir).get("status", "").lower() == "landed":
    return "landed"
if (spec_dir / "verification-summary.md").exists() or (spec_dir / "fulfillment-report.md").exists():
    return "verified"
if any((spec_dir / p).exists() for p in BUILD_MARKERS):
    return "build"
return "phase_a"
```

`BUILD_MARKERS`:

```python
("progress-report.md", "spec-compliance-report.md", "code-review-report.md",
 "test-quality-report.md", "integration-report.md", "run-history.json")
```

Render sections in this order:

```markdown
# Artifact Map
> This file is generated by Echelon. Regenerate it with `echelon artifacts <spec_id>`; do not hand-edit it.
## Start Here
## Current State
## Artifact Table
## Missing Expected Files
## Unclassified Files
## Generated
```

Statuses must be exactly `Present`, `Missing`, or `Optional missing`. `write_artifact_index()` writes only `{spec_dir}/ARTIFACTS.md`.

- [ ] **Step 4: Verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_artifact_index.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/artifact_index.py tests/unit/test_artifact_index.py
git commit -m "feat: generate spec artifact index"
```

## Task 2: CLI Command

- [ ] **Step 1: Write failing tests**

Create tests for:

```python
def test_artifacts_command_writes_index(tmp_path: Path, capsys) -> None: ...
def test_artifacts_command_requires_spec_id(tmp_path: Path, capsys) -> None: ...
def test_artifacts_command_reports_missing_spec(tmp_path: Path, capsys) -> None: ...
```

Assertions:

```python
assert (spec_dir / "ARTIFACTS.md").exists()
assert "Wrote artifact map" in capsys.readouterr().out
assert "missing spec_id" in capsys.readouterr().err
assert "Spec not found" in capsys.readouterr().err
```

- [ ] **Step 2: Verify failure**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_artifacts.py -q
```

Expected: `_cmd_artifacts` import fails.

- [ ] **Step 3: Implement CLI**

In `USAGE`, add:

```text
  artifacts <spec_id>                       Generate specs/<id>/ARTIFACTS.md
```

Near `_cmd_spec_target`, add:

```python
def _cmd_artifacts(args: list[str]) -> None:
    if not args:
        print("echelon artifacts: missing spec_id", file=sys.stderr)
        sys.exit(1)

    from echelon.artifact_index import write_artifact_index
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(args[0], Path.cwd())
    if spec_dir is None:
        print(f"✗ Spec not found: {args[0]}", file=sys.stderr)
        sys.exit(1)

    path = write_artifact_index(spec_dir)
    print(f"✓ Wrote artifact map: {path}")
```

In `main()`, after `spec` dispatch:

```python
    if command == "artifacts":
        _cmd_artifacts(args[1:])
        return
```

- [ ] **Step 4: Verify pass and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_artifacts.py -q
git add src/echelon/cli.py tests/unit/test_cli_artifacts.py
git commit -m "feat: add artifact index command"
```

## Task 3: Harness Hook

- [ ] **Step 1: Extend focused test**

In `test_convergence_writes_ready_to_land_status`, assert:

```python
artifacts = spec_dir / "ARTIFACTS.md"
assert artifacts.exists()
text = artifacts.read_text(encoding="utf-8")
assert "Lifecycle stage: verified" in text
assert "`run-history.json`" in text
```

- [ ] **Step 2: Verify failure**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py::TestRalphOuterLoop::test_convergence_writes_ready_to_land_status -q
```

Expected: `ARTIFACTS.md` missing.

- [ ] **Step 3: Implement hook**

In `src/harness/ralph.py`, import:

```python
from echelon.artifact_index import write_artifact_index
```

In `_mark_spec_ready_to_land()`, after `append_implementation_run(...)`:

```python
write_artifact_index(spec_dir)
```

- [ ] **Step 4: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_ralph_outer.py::TestRalphOuterLoop::test_convergence_writes_ready_to_land_status -q
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: refresh artifact index on harness convergence"
```

## Task 4: Prompt Hooks

- [ ] **Step 1: Add failing prompt tests**

Add:

```python
def test_phase4_document_generates_artifact_index_deterministically(self) -> None:
    text = (ROOT / "extension" / "workflow" / "phases" / "phase4-document.md").read_text(encoding="utf-8")
    assert "echelon artifacts" in text
    assert "NEVER hand-author `ARTIFACTS.md`" in text

def test_build_finalize_generates_artifact_index_deterministically(self) -> None:
    text = (ROOT / "extension" / "workflow" / "phases" / "build-8-finalize.md").read_text(encoding="utf-8")
    assert "echelon artifacts" in text
    assert "NEVER hand-author `ARTIFACTS.md`" in text
```

- [ ] **Step 2: Verify failure**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_phase_output_paths.py -q
```

- [ ] **Step 3: Update `phase4-document.md`**

After `finalize-run.sh` succeeds, add:

```markdown
After `finalize-run.sh` succeeds, refresh the human artifact map deterministically:

```bash
echelon artifacts "${SPEC_ID}"
```

ALWAYS use `echelon artifacts` to generate `{spec_dir}/ARTIFACTS.md` after finalization. NEVER hand-author `ARTIFACTS.md`; it is Python-owned and overwritten on regeneration.
```

- [ ] **Step 4: Update `build-8-finalize.md`**

Before the final build summary, add:

```markdown
Before printing the final build summary, refresh the human artifact map deterministically:

```bash
echelon artifacts "${SPEC_ID}"
```

ALWAYS use `echelon artifacts` to generate `{spec_dir}/ARTIFACTS.md` after build finalization. NEVER hand-author `ARTIFACTS.md`; it is Python-owned and overwritten on regeneration.
```

- [ ] **Step 5: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_phase_output_paths.py -q
git add extension/workflow/phases/phase4-document.md extension/workflow/phases/build-8-finalize.md tests/unit/test_phase_output_paths.py
git commit -m "docs: require deterministic artifact index refresh"
```

## Task 5: README

- [ ] **Step 1: Add failing README tests**

Create:

```python
"""README coverage for spec artifact index UX."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

def test_readme_points_humans_to_artifacts_md() -> None:
    text = README.read_text(encoding="utf-8")
    assert "ARTIFACTS.md" in text
    assert "How to read a spec folder" in text

def test_readme_documents_artifacts_command() -> None:
    text = README.read_text(encoding="utf-8")
    assert "echelon artifacts <id>" in text
    assert "Generate or refresh" in text
```

- [ ] **Step 2: Verify failure**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_artifact_index_docs.py -q
```

- [ ] **Step 3: Add concise README text**

Add to quick commands:

```markdown
echelon artifacts 001                      # generate specs/001-*/ARTIFACTS.md
```

Add near the `specs/` tree:

```markdown
### How to read a spec folder

Start with `specs/<id>-*/ARTIFACTS.md`. Echelon generates this file deterministically, without LLM tokens, as a concise map of known spec artifacts, what each file is for, when it is updated, and which expected files are missing for the current lifecycle stage.

Refresh it manually with:

```bash
echelon artifacts <id>
```
```

Add to command reference:

```markdown
| `echelon artifacts <id>` | — | Generate or refresh `specs/<id>-*/ARTIFACTS.md`, the deterministic human map of spec-folder outputs |
```

- [ ] **Step 4: Verify and commit**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_artifact_index_docs.py -q
git add README.md tests/unit/test_artifact_index_docs.py
git commit -m "docs: explain spec artifact map"
```

## Task 6: Full Verification

- [ ] **Step 1: Run focused tests**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest \
  tests/unit/test_artifact_index.py \
  tests/unit/test_cli_artifacts.py \
  tests/unit/test_ralph_outer.py::TestRalphOuterLoop::test_convergence_writes_ready_to_land_status \
  tests/unit/test_phase_output_paths.py \
  tests/unit/test_artifact_index_docs.py \
  -q
```

- [ ] **Step 2: Run full unit suite**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit
```

Expected baseline before this plan: `975 passed`.

- [ ] **Step 3: Confirm status**

```bash
git status --short --branch
```

Expected: clean after final commit.

## Self-Review

- Spec coverage: generator, manual CLI, harness refresh, prompt-surface refresh, and README guidance are all covered.
- Placeholder scan: The plan uses concrete files, function names, commands, snippets, and test assertions.
- Type consistency: Public API is consistently `infer_lifecycle_stage`, `render_artifact_index`, and `write_artifact_index`.
- Token economy: The implementation plan is intentionally compact; the generated artifact map is Python-owned and does not add LLM prompt tokens.

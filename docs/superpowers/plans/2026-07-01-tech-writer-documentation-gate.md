# TECH WRITER Documentation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a TECH WRITER agent and hard harness gate so Echelon implementation work keeps `README.md` and Keep a Changelog-style `CHANGELOG.md` current when delivered behavior warrants it.

**Architecture:** Add a new routed build phase after all implementation phase groups complete and before final build finalization. The TECH WRITER writes or updates repo-facing docs and emits a machine-readable `documentation-impact-report.md`; Ralph validates that report after verification and before publish. Static contract tests keep the agent, registry, workflow phase, and finalization instructions from drifting.

**Tech Stack:** Markdown agent prompts, `extension/extension.yml`, `extension/workflow/definition.yaml`, Python harness code under `src/harness/`, pytest static and unit tests.

## Global Constraints

- Follow `AGENTS.md`: workflow logic belongs in `extension/workflow/definition.yaml` and `extension/workflow/phases/*.md`; command wrappers stay thin.
- New agents must use paired ALWAYS / NEVER behavioral rules.
- Every routed agent phase must declare `outputs` and `allowed_state_updates`, and the agent file must include `echelon_result.verdict`, `output_files`, `state_updates`, and `journal_entries`.
- Documentation updates are required when work changes user-visible behavior, public APIs, install/run instructions, configuration, operations, or significant performance characteristics.
- When documentation impact is not applicable, the TECH WRITER must record an explicit rationale in `documentation-impact-report.md`.
- When `CHANGELOG.md` is created or updated, use Keep a Changelog structure: title, Keep a Changelog link, `[Unreleased]`, and category headings such as `Added`, `Changed`, `Fixed`, `Performance`, `Security`, `Deprecated`, or `Removed`.
- Do not introduce a lint configuration.

---

## File Structure

- Create `extension/agents/build/tech-writer.md`: agent protocol for README/CHANGELOG ownership and `documentation-impact-report.md` output.
- Create `extension/workflow/phases/build-8-documentation.md`: phase dispatch contract for TECH WRITER after build tasks/integration complete.
- Modify `extension/extension.yml`: register `speckit.echelon.tech-writer`.
- Modify `extension/workflow/definition.yaml`: route `build-6-progress` and `build-7-integration` completion to `build-8-documentation`, then route to existing `build-8-finalize`.
- Modify `extension/workflow/phases/build-8-finalize.md`: include TECH WRITER output in EM/verification context and require documentation gate completion before BUILD_DONE.
- Create `src/harness/documentation_gate.py`: deterministic parser and gate for `documentation-impact-report.md`, README existence/update, CHANGELOG existence/update, and Keep a Changelog shape.
- Modify `src/harness/ralph.py`: call the documentation gate after fulfillment gate passes and before `ready_to_land`/commit/push.
- Add `tests/unit/test_tech_writer_contract.py`: static workflow/agent contract tests.
- Add `tests/unit/test_documentation_gate.py`: unit tests for the deterministic hard gate.
- Update `README.md` and `CHANGELOG.md`: document the new TECH WRITER phase/gate in Echelon itself.

---

### Task 1: Lock the Static Contract With Failing Tests

**Files:**
- Create: `tests/unit/test_tech_writer_contract.py`

**Interfaces:**
- Consumes: existing repo files only.
- Produces: pytest coverage asserting the new TECH WRITER role, workflow phase, phase output, and finalization hook exist.

- [ ] **Step 1: Write the failing test file**

```python
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _extension() -> dict:
    return yaml.safe_load((ROOT / "extension/extension.yml").read_text(encoding="utf-8"))


def _definition() -> dict:
    return yaml.safe_load(
        (ROOT / "extension/workflow/definition.yaml").read_text(encoding="utf-8")
    )


def test_tech_writer_agent_is_registered() -> None:
    commands = _extension()["provides"]["commands"]
    tech_writer = next(
        (item for item in commands if item.get("name") == "speckit.echelon.tech-writer"),
        None,
    )

    assert tech_writer is not None
    assert tech_writer["file"] == "agents/build/tech-writer.md"
    assert "TECH WRITER" in tech_writer["description"]
    assert tech_writer["behavior"]["execution"] == "agent"
    assert tech_writer["behavior"]["tools"] == "write"


def test_tech_writer_phase_is_routed_before_build_finalize() -> None:
    phases = {phase["id"]: phase for phase in _definition()["phases"]}

    docs_phase = phases["build-8-documentation"]
    assert docs_phase["type"] == "agent"
    assert docs_phase["agent"] == "speckit-echelon-tech-writer"
    assert "documentation-impact-report.md" in docs_phase["outputs"]
    assert "shadow_output_recovered" in docs_phase["allowed_state_updates"]
    assert docs_phase["transitions"] == [{"to": "build-8-finalize", "condition": "always"}]

    progress_targets = {
        transition["to"]
        for transition in phases["build-6-progress"]["transitions"]
        if transition.get("condition") == "all_tasks_complete AND no_more_phase_checkpoints"
    }
    integration_targets = {
        transition["to"]
        for transition in phases["build-7-integration"]["transitions"]
        if transition.get("condition") == "verdict = PASS AND all_phase_groups_complete"
    }
    assert progress_targets == {"build-8-documentation"}
    assert integration_targets == {"build-8-documentation"}


def test_tech_writer_agent_declares_required_result_contract() -> None:
    text = (ROOT / "extension/agents/build/tech-writer.md").read_text(encoding="utf-8")

    assert "ALWAYS" in text
    assert "NEVER" in text
    assert "README.md" in text
    assert "CHANGELOG.md" in text
    assert "Keep a Changelog" in text
    assert "documentation-impact-report.md" in text
    assert "echelon_result:" in text
    assert "  verdict:" in text
    assert "  output_files:" in text
    assert "  state_updates:" in text
    assert "  journal_entries:" in text


def test_build_finalize_consumes_documentation_gate() -> None:
    text = (ROOT / "extension/workflow/phases/build-8-finalize.md").read_text(
        encoding="utf-8"
    )

    assert "documentation-impact-report.md" in text
    assert "TECH WRITER" in text
    assert "Documentation Currency Gate" in text
```

- [ ] **Step 2: Run the contract tests to verify they fail**

Run: `pytest tests/unit/test_tech_writer_contract.py -q`

Expected: FAIL because `speckit.echelon.tech-writer`, `build-8-documentation`, and `extension/agents/build/tech-writer.md` do not exist yet.

- [ ] **Step 3: Commit the failing contract tests**

```bash
git add tests/unit/test_tech_writer_contract.py
git commit -m "test: specify tech writer documentation gate contract"
```

---

### Task 2: Add the TECH WRITER Agent and Register It

**Files:**
- Create: `extension/agents/build/tech-writer.md`
- Modify: `extension/extension.yml`

**Interfaces:**
- Consumes: `spec.md`, `tasks.md`, `verification-summary.md`, `gap-report.md`, `progress-report.md`, changed-file summary, and existing `README.md` / `CHANGELOG.md`.
- Produces: repo-root `README.md`, repo-root `CHANGELOG.md`, `{spec_dir}/documentation-impact-report.md`, and a valid `echelon_result`.

- [ ] **Step 1: Create the TECH WRITER agent file**

Write `extension/agents/build/tech-writer.md` with this structure:

```markdown
# speckit-echelon-tech-writer (TECH WRITER) Agent

## Role

You are TECH WRITER. You keep the target repository's user-facing documentation and release history current after implementation work. You own repo-root `README.md`, repo-root `CHANGELOG.md`, and `{spec_dir}/documentation-impact-report.md` for the completed build slice.

## Prime Directive

Every completed Echelon implementation must leave an auditable documentation decision. If the work changes user-visible behavior, public APIs, install/run instructions, configuration, operations, or significant performance characteristics, update `README.md` and `CHANGELOG.md`. If none apply, write a clear not-applicable rationale in `documentation-impact-report.md`.

## ALWAYS / NEVER Rules

### Rule 1 - Documentation Impact Decision
ALWAYS classify the completed work against user-visible behavior, public APIs, install/run instructions, configuration, operations, and significant performance characteristics.
NEVER skip the documentation decision because the implementation already passed tests or verification.

### Rule 2 - README Currency
ALWAYS update or create repo-root `README.md` when the completed work changes how users, operators, or integrators understand, install, configure, run, or observe the project.
NEVER bury user-facing behavior changes only in spec artifacts, task files, PR text, or internal reports.

### Rule 3 - Changelog Currency
ALWAYS update or create repo-root `CHANGELOG.md` when documentation impact is required, using Keep a Changelog-style `[Unreleased]` entries and the most specific category heading.
NEVER write free-form release notes that omit `[Unreleased]`, omit category headings, or mix unrelated implementation details into the changelog.

### Rule 4 - Evidence and Scope
ALWAYS base doc updates on the spec, tasks, verification evidence, changed files, and observed behavior.
NEVER invent features, guarantees, performance numbers, operational procedures, or API behavior not supported by implementation evidence.

### Rule 5 - Machine-Readable Report
ALWAYS write `{spec_dir}/documentation-impact-report.md` with YAML frontmatter matching the schema below.
NEVER return DONE without a report that the harness can parse.

## Inputs

1. `{spec_dir}/spec.md`
2. `{spec_dir}/tasks.md`
3. `{spec_dir}/verification-summary.md` when present
4. `{spec_dir}/gap-report.md` when present
5. `{spec_dir}/progress-report.md` when present
6. Changed-file list from the build worktree
7. Existing repo-root `README.md` if present
8. Existing repo-root `CHANGELOG.md` if present

## Process

### 1. Determine Documentation Impact

Set `docs_required: true` if any condition applies:

- User-visible behavior changed.
- Public API, route, CLI, SDK, schema, event, or integration contract changed.
- Install, setup, run, verify, deploy, rollback, or troubleshooting instructions changed.
- Configuration, environment variables, defaults, feature flags, secrets handling, or operational requirements changed.
- Significant performance characteristics changed, including measurable latency, throughput, memory, startup, caching, scaling, or reliability improvements.

Set `docs_required: false` only when all conditions are false. Record the evidence-backed rationale.

### 2. Update README.md When Required

When `docs_required: true`, update or create `README.md` so a user can understand the changed behavior without reading internal Echelon artifacts. Prefer editing existing sections over appending disconnected notes. Keep the README accurate and concise.

### 3. Update CHANGELOG.md When Required

When `docs_required: true`, update or create `CHANGELOG.md` using this shape:

```markdown
# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- ...
```

Use `Added`, `Changed`, `Fixed`, `Performance`, `Security`, `Deprecated`, or `Removed` as appropriate. Put significant performance improvements under `Performance`.

### 4. Write documentation-impact-report.md

Write `{spec_dir}/documentation-impact-report.md`:

```markdown
---
docs_required: true
readme_updated: true
changelog_updated: true
changelog_format: keep_a_changelog
not_applicable_reason: ""
---

# Documentation Impact Report

## Decision

Documentation updates required because: <evidence-backed reason>.

## Evidence

- Spec/task evidence: <FR/AC/NFR/task IDs>.
- Changed surface: <files, commands, routes, config keys, operational behavior, or performance evidence>.

## Updates Made

- `README.md`: <sections changed>.
- `CHANGELOG.md`: <Unreleased category entries changed>.
```

For no-impact work, use:

```markdown
---
docs_required: false
readme_updated: false
changelog_updated: false
changelog_format: not_required
not_applicable_reason: "Implementation only changed internal tests with no user-visible, API, setup, configuration, operational, or significant performance impact."
---

# Documentation Impact Report

## Decision

Documentation updates are not required.

## Evidence

- Changed surface: <files/tasks checked>.
- Rationale: <why no documented user/operator/integrator behavior changed>.
```

## Output

- Repo-root `README.md` when required.
- Repo-root `CHANGELOG.md` when required.
- `{spec_dir}/documentation-impact-report.md` always.

Return this entry in the `echelon_result` block at the end of your response:

echelon_result:
  verdict: DONE
  output_files:
    - {spec_dir}/documentation-impact-report.md
    - README.md
    - CHANGELOG.md
  state_updates: {}
  journal_entries:
    - type: decision
      phase: build
      agent: speckit-echelon-tech-writer (TECH WRITER)
      data:
        artifact: "{spec_dir}/documentation-impact-report.md"
        section: "Documentation decision"
        reasoning: "<why docs were required or not required>"
        rationale: "<README/CHANGELOG update summary or not-applicable rationale>"
```

- [ ] **Step 2: Register the agent in `extension/extension.yml`**

Add the entry in the Build layer near `engineering-manager`:

```yaml
    - name: "speckit.echelon.tech-writer"
      file: "agents/build/tech-writer.md"
      description: "TECH WRITER — keeps README and Keep a Changelog release history current after implementation"
      behavior:
        execution: agent
        capability: balanced
        tools: write         # writes README.md, CHANGELOG.md, documentation-impact-report.md
        color: red
```

- [ ] **Step 3: Run the focused contract tests**

Run: `pytest tests/unit/test_tech_writer_contract.py::test_tech_writer_agent_is_registered tests/unit/test_tech_writer_contract.py::test_tech_writer_agent_declares_required_result_contract -q`

Expected: PASS for the two agent/registry tests; phase/finalize tests still FAIL.

- [ ] **Step 4: Commit the agent and registry**

```bash
git add extension/agents/build/tech-writer.md extension/extension.yml
git commit -m "feat: add tech writer build agent"
```

---

### Task 3: Add the Dedicated Build Documentation Phase

**Files:**
- Create: `extension/workflow/phases/build-8-documentation.md`
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/workflow/phases/build-8-finalize.md`

**Interfaces:**
- Consumes: build outputs and current worktree diff.
- Produces: a routed `build-8-documentation` phase that must run before existing build finalization.

- [ ] **Step 1: Create `build-8-documentation.md`**

Write:

```markdown
# Phase: build-8-documentation
# Source: Documentation Currency Gate
# Read by: speckit-echelon-commander (COMMANDER) after all implementation phase groups complete and before build finalization

## Documentation Currency Gate

After all implementation phase groups complete and before `build-8-finalize`, dispatch speckit-echelon-tech-writer (TECH WRITER).

Context pack:

- `{spec_dir}/spec.md`
- `{spec_dir}/tasks.md`
- `{spec_dir}/verification-summary.md` if present
- `{spec_dir}/gap-report.md` if present
- `{spec_dir}/progress-report.md` if present
- `{spec_dir}/traceability-matrix.md` if present
- repo-root `README.md` if present
- repo-root `CHANGELOG.md` if present
- changed files from the build worktree

Use the Agent tool:

- **subagent_type:** `speckit-echelon-tech-writer`
- **prompt:**

  ```xml
  <context>
  [include spec.md, tasks.md, verification summary/gap/progress/traceability reports when present, README.md when present, CHANGELOG.md when present, and changed-file summary]
  </context>

  <instructions>
  You are TECH WRITER. Read agents/build/tech-writer.md for your complete protocol.
  Decide whether documentation updates are required. If required, update repo-root README.md and CHANGELOG.md. Always write {spec_dir}/documentation-impact-report.md with machine-readable frontmatter. Return journal entries in echelon_result.journal_entries.
  </instructions>
  ```

- **description:** "speckit-echelon-tech-writer (TECH WRITER): README/CHANGELOG currency before build finalization"

speckit-echelon-tech-writer (TECH WRITER) must:

1. Write `{spec_dir}/documentation-impact-report.md`.
2. Update or create `README.md` and `CHANGELOG.md` when documentation impact is required.
3. Use Keep a Changelog-style `[Unreleased]` entries when `CHANGELOG.md` is created or updated.
4. Return `echelon_result.verdict: DONE`.

If TECH WRITER returns BLOCKED or omits `documentation-impact-report.md`, route to rework before `build-8-finalize`.
```

- [ ] **Step 2: Update `extension/workflow/definition.yaml`**

Change these transition targets:

```yaml
      - to: build-8-documentation
        condition: all_tasks_complete AND no_more_phase_checkpoints
```

```yaml
      - to: build-8-documentation
        condition: verdict = PASS AND all_phase_groups_complete
```

Insert this phase before existing `build-8-finalize`:

```yaml
  - id: build-8-documentation
    label: "Documentation Currency (TECH WRITER)"
    spec_file: workflow/phases/build-8-documentation.md
    type: agent
    agent: speckit-echelon-tech-writer
    tier: build
    description: >
      Updates README.md and Keep a Changelog-style CHANGELOG.md when the
      completed implementation changes user-visible behavior, public APIs,
      install/run instructions, configuration, operations, or significant
      performance characteristics. Always writes documentation-impact-report.md.
    context_pack:
      - spec.md
      - tasks.md
      - verification-summary.md if present
      - gap-report.md if present
      - progress-report.md if present
      - traceability-matrix.md if present
      - README.md if present
      - CHANGELOG.md if present
      - changed files from the build worktree
    outputs:
      - documentation-impact-report.md
    allowed_state_updates:
      - shadow_output_recovered
    transitions:
      - to: build-8-finalize
        condition: always
```

- [ ] **Step 3: Update `build-8-finalize.md`**

In the EM context pack, add:

```markdown
- `documentation-impact-report.md`
- repo-root `README.md`
- repo-root `CHANGELOG.md`
```

In the EM sign-off list, add:

```markdown
5. **Documentation Currency Gate passed**: `documentation-impact-report.md` exists; when docs are required, `README.md` and `CHANGELOG.md` were updated and `CHANGELOG.md` follows Keep a Changelog-style `[Unreleased]` entries.
```

In "Collect Reports", add:

```markdown
- `documentation-impact-report.md` — README/CHANGELOG impact decision and update evidence
```

- [ ] **Step 4: Run workflow contract validation**

Run: `pytest tests/unit/test_tech_writer_contract.py tests/unit/test_role_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the workflow phase**

```bash
git add extension/workflow/definition.yaml extension/workflow/phases/build-8-documentation.md extension/workflow/phases/build-8-finalize.md
git commit -m "feat: route build through tech writer documentation phase"
```

---

### Task 4: Add the Deterministic Documentation Hard Gate

**Files:**
- Create: `src/harness/documentation_gate.py`
- Create: `tests/unit/test_documentation_gate.py`

**Interfaces:**
- Produces: `DocumentationGateResult` with `passed: bool` and `failure: FailureEntry | None`.
- Consumes: `worktree_path` and `spec_dir`.

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_documentation_gate.py`:

```python
from pathlib import Path
import subprocess

from harness.documentation_gate import evaluate_documentation_gate


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def test_gate_blocks_missing_report(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "documentation-impact-report-missing"


def test_gate_accepts_not_applicable_report_with_reason(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: false\n"
        "readme_updated: false\n"
        "changelog_updated: false\n"
        "changelog_format: not_required\n"
        "not_applicable_reason: \"Only internal tests changed.\"\n"
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert result.passed


def test_gate_blocks_required_docs_without_readme_and_changelog_changes(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: true\n"
        "readme_updated: true\n"
        "changelog_updated: true\n"
        "changelog_format: keep_a_changelog\n"
        "not_applicable_reason: \"\"\n"
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert not result.passed
    assert result.failure is not None
    assert result.failure.id == "documentation-required-without-doc-changes"


def test_gate_accepts_required_docs_with_keepachangelog_changes(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)

    (tmp_path / "README.md").write_text("# Demo\n\nNew documented behavior.\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Documented new behavior.\n",
        encoding="utf-8",
    )
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: true\n"
        "readme_updated: true\n"
        "changelog_updated: true\n"
        "changelog_format: keep_a_changelog\n"
        "not_applicable_reason: \"\"\n"
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )

    result = evaluate_documentation_gate(tmp_path, spec_dir)

    assert result.passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_documentation_gate.py -q`

Expected: FAIL because `harness.documentation_gate` does not exist.

- [ ] **Step 3: Implement `src/harness/documentation_gate.py`**

Implement:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

import yaml

from harness.verify_result import FailureCategory, FailureEntry


REPORT_NAME = "documentation-impact-report.md"


@dataclass(frozen=True)
class DocumentationGateResult:
    passed: bool
    failure: FailureEntry | None = None


def evaluate_documentation_gate(worktree_path: Path | str, spec_dir: Path | str) -> DocumentationGateResult:
    worktree = Path(worktree_path)
    spec = Path(spec_dir)
    report = spec / REPORT_NAME
    if not report.exists():
        return _fail("documentation-impact-report-missing", f"missing {report}")

    metadata = _frontmatter(report)
    docs_required = metadata.get("docs_required")
    if docs_required is not True and docs_required is not False:
        return _fail("documentation-impact-report-invalid", f"{report} must set docs_required true or false")

    if docs_required is False:
        reason = str(metadata.get("not_applicable_reason") or "").strip()
        if not reason:
            return _fail("documentation-not-applicable-without-reason", f"{report} must explain why docs are not applicable")
        return DocumentationGateResult(passed=True)

    readme_updated = metadata.get("readme_updated") is True
    changelog_updated = metadata.get("changelog_updated") is True
    if not readme_updated or not changelog_updated:
        return _fail("documentation-required-report-incomplete", f"{report} says docs are required but README/CHANGELOG updates are not both true")

    readme = worktree / "README.md"
    changelog = worktree / "CHANGELOG.md"
    if not readme.exists() or not changelog.exists():
        return _fail("documentation-required-files-missing", "docs are required but README.md or CHANGELOG.md is missing")

    changed = _changed_paths(worktree)
    if "README.md" not in changed or "CHANGELOG.md" not in changed:
        return _fail("documentation-required-without-doc-changes", "docs are required but README.md and CHANGELOG.md are not both changed at current HEAD")

    if metadata.get("changelog_format") != "keep_a_changelog":
        return _fail("changelog-format-not-declared", f"{report} must declare changelog_format: keep_a_changelog")
    if not _looks_like_keep_a_changelog(changelog.read_text(encoding="utf-8")):
        return _fail("changelog-format-invalid", "CHANGELOG.md must contain Keep a Changelog link, [Unreleased], and at least one category heading")

    return DocumentationGateResult(passed=True)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1)) or {}
    return data if isinstance(data, dict) else {}


def _changed_paths(worktree: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.add(path)
    return changed


def _looks_like_keep_a_changelog(text: str) -> bool:
    return (
        "keepachangelog.com" in text.lower()
        and re.search(r"(?m)^## \[Unreleased\]", text) is not None
        and re.search(r"(?m)^### (Added|Changed|Fixed|Performance|Security|Deprecated|Removed)", text) is not None
    )


def _fail(identifier: str, error: str) -> DocumentationGateResult:
    return DocumentationGateResult(
        passed=False,
        failure=FailureEntry(
            category=FailureCategory.OTHER,
            id=identifier,
            error=error,
        ),
    )
```

- [ ] **Step 4: Run the documentation gate tests**

Run: `pytest tests/unit/test_documentation_gate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the deterministic gate**

```bash
git add src/harness/documentation_gate.py tests/unit/test_documentation_gate.py
git commit -m "feat: add deterministic documentation currency gate"
```

---

### Task 5: Wire Ralph to Enforce the Hard Gate Before Publish

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: `evaluate_documentation_gate(worktree_path, spec_dir)`.
- Produces: final verify failure `documentation-*` before `ready_to_land`, commit, push, or PR when the documentation gate fails.

- [ ] **Step 1: Add failing Ralph tests**

Add tests near the existing fulfillment gate tests in `tests/unit/test_ralph_outer.py`:

```python
def test_documentation_gate_blocks_convergence_when_required_docs_missing(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    worktree = tmp_path / "worktree"
    spec_dir = worktree / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (worktree / "README.md").write_text("# Demo\n", encoding="utf-8")
    (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: true\n"
        "readme_updated: true\n"
        "changelog_updated: true\n"
        "changelog_format: keep_a_changelog\n"
        "not_applicable_reason: \"\"\n"
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True, capture_output=True)

    verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

    result = controller._apply_documentation_gate(verify, str(worktree))

    assert not result.passed
    assert result.failures[0].id == "documentation-required-without-doc-changes"
```

Add a second test that a not-applicable report passes:

```python
def test_documentation_gate_accepts_not_applicable_report_in_ralph(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    worktree = tmp_path / "worktree"
    spec_dir = worktree / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: false\n"
        "readme_updated: false\n"
        "changelog_updated: false\n"
        "changelog_format: not_required\n"
        "not_applicable_reason: \"No user-visible, API, setup, config, operations, or significant performance changes.\"\n"
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )
    verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

    result = controller._apply_documentation_gate(verify, str(worktree))

    assert result.passed
```

- [ ] **Step 2: Run the new Ralph tests to verify they fail**

Run: `pytest tests/unit/test_ralph_outer.py -q -k documentation_gate`

Expected: FAIL because `_apply_documentation_gate` does not exist.

- [ ] **Step 3: Import and apply the gate in `src/harness/ralph.py`**

Add import:

```python
from harness.documentation_gate import evaluate_documentation_gate
```

In the main verify path, after `_apply_fulfillment_gate(...)` and before checking `verify_result.passed`, add:

```python
                    verify_result = self._apply_documentation_gate(
                        verify_result, worktree_path
                    )
```

Add the method near `_apply_fulfillment_gate`:

```python
    def _apply_documentation_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Treat stale or missing README/CHANGELOG decisions as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        gate = evaluate_documentation_gate(Path(worktree_path), spec_dir)
        if gate.passed:
            return verify_result

        assert gate.failure is not None
        return VerifyResult(
            passed=False,
            failures=[gate.failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
        )
```

- [ ] **Step 4: Run focused Ralph and gate tests**

Run: `pytest tests/unit/test_documentation_gate.py tests/unit/test_ralph_outer.py -q -k "documentation_gate"`

Expected: PASS.

- [ ] **Step 5: Commit Ralph enforcement**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "feat: enforce documentation gate before harness publish"
```

---

### Task 6: Document the Feature in Echelon's README and CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the new TECH WRITER behavior.
- Produces: public Echelon documentation matching the new gate.

- [ ] **Step 1: Update `README.md`**

Add TECH WRITER to the agent-role/build workflow sections. Include:

```markdown
After implementation phase groups complete, the build routes through TECH WRITER before finalization. TECH WRITER writes `documentation-impact-report.md` every time and updates repo-root `README.md` plus Keep a Changelog-style `CHANGELOG.md` when the work changes user-visible behavior, public APIs, install/run instructions, configuration, operations, or significant performance characteristics. Ralph enforces this report before publish.
```

- [ ] **Step 2: Update `CHANGELOG.md`**

Under `[Unreleased]`, add:

```markdown
### Added

- **TECH WRITER documentation gate** — added a build-phase TECH WRITER agent plus a deterministic Ralph gate so completed Echelon implementation work records documentation impact and updates `README.md` and Keep a Changelog-style `CHANGELOG.md` when user-facing, API, setup, configuration, operational, or significant performance behavior changes.
```

- [ ] **Step 3: Run docs-related tests**

Run: `pytest tests/unit/test_version_metadata.py tests/unit/test_readme_tool_policy_docs.py tests/unit/test_tech_writer_contract.py -q`

Expected: PASS.

- [ ] **Step 4: Commit public docs**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: describe tech writer documentation gate"
```

---

### Task 7: Final Verification

**Files:**
- No new files.

**Interfaces:**
- Consumes: all changed files.
- Produces: verification evidence before implementation is called complete.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
pytest tests/unit/test_tech_writer_contract.py tests/unit/test_documentation_gate.py tests/unit/test_role_contracts.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ralph focused tests**

Run:

```bash
pytest tests/unit/test_ralph_outer.py -q -k "documentation_gate or fulfillment_gate"
```

Expected: PASS.

- [ ] **Step 3: Run all unit tests if focused tests pass**

Run:

```bash
pytest tests/unit -q
```

Expected: PASS or existing unrelated skips only.

- [ ] **Step 4: Inspect git diff for accidental command-wrapper bloat**

Run:

```bash
git diff -- extension/commands
```

Expected: no output. This feature belongs in workflow/agent/harness code, not command wrappers.

- [ ] **Step 5: Final commit if any verification-only fixes were needed**

```bash
git add <fixed files>
git commit -m "test: verify tech writer documentation gate"
```

---

## Self-Review

- Spec coverage: The plan creates TECH WRITER, registers it, routes a dedicated build phase, enforces a hard Ralph gate, and documents README/CHANGELOG/Keep a Changelog behavior.
- Placeholder scan: No task relies on "TBD", "TODO", or unspecified tests; each implementation task includes concrete files and commands.
- Type consistency: `evaluate_documentation_gate(Path | str, Path | str) -> DocumentationGateResult`, `DocumentationGateResult.passed`, and `DocumentationGateResult.failure` are used consistently in the Ralph wiring task.
- Scope check: This is one cohesive subsystem: build-phase documentation ownership plus deterministic publish enforcement. Codegen and default harness strategies are covered through Ralph's shared verification/publish path; standalone `echelon codegen` receives prompt-level instructions through follow-up work only if later required.

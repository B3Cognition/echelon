# Remove Retired SOAR Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the already-disabled SOAR/codegen execution product while preserving the MemPalace, knowledge-base validation, and secret-scrubbing utilities used by active Echelon workflows.

**Architecture:** Retain a deliberately small `codegen` compatibility namespace containing only active shared utilities. Remove every execution controller, command, prompt, installer branch, strategy guard, package asset, and execution-only test. A static boundary test prevents deleted execution packages from returning.

**Tech Stack:** Python 3.11+, Typer, pytest, Bash installer, Prosaic Markdown runtime bundle.

**Spec:** `docs/superpowers/specs/2026-09-21-harness-simplification-control-design.md`

## Global Constraints

- Preserve `codegen.memory.collision`, `codegen.memory.context`, `codegen.memory.kb_schema_validator`, `codegen.memory.mempalace_reader`, and `codegen.memory.mempalace_writer` with their existing public interfaces.
- Preserve `codegen.security.secret_scrubber.scrub_secrets` and its current matching behavior.
- Do not rename the retained `codegen.memory` package in S1; namespace migration belongs to a later CLI/control-plane milestone.
- Historical specifications, findings, plans, and changelog entries remain historical records and are not rewritten merely because they mention SOAR.
- A user-supplied delivery strategy remains an opaque command; S1 removes Echelon's built-in SOAR knowledge and executable implementation, not the general custom-strategy facility.
- Use `.venv/bin/python -m pytest`, not the system `pytest`, because the system interpreter lacks project dependencies.

---

### Task 1: Seal the retained shared-utility boundary

**Files:**

- Create: `src/codegen/security/credential_patterns.py`
- Modify: `src/codegen/security/secret_scrubber.py`
- Create: `tests/unit/test_codegen_shared_boundary.py`
- Test: `tests/unit/test_spec_memory_miner.py`
- Test: `tests/unit/test_mempalace_collision.py`
- Test: `tests/unit/test_mempalace_context.py`
- Test: `tests/unit/test_mempalace_reader.py`
- Test: `tests/unit/test_mempalace_writer.py`
- Test: `tests/unit/test_kb_schema_validator.py`

**Interfaces:**

- Consumes: the five active `codegen.memory` modules and `scrub_secrets(text: str) -> str`.
- Produces: `CREDENTIAL_DENY_PATTERNS: tuple[re.Pattern[str], ...]` as the independent security source used by `secret_scrubber`.

- [ ] **Step 1: Write the failing credential-pattern ownership test**

Add to `tests/unit/test_codegen_shared_boundary.py`:

```python
from codegen.security.credential_patterns import CREDENTIAL_DENY_PATTERNS
from codegen.security.secret_scrubber import scrub_secrets


def test_secret_scrubber_owns_patterns_without_soar_import() -> None:
    assert CREDENTIAL_DENY_PATTERNS
    assert scrub_secrets("token=abcdefghijklmnopqrstuvwxyz123456") == "[REDACTED]"
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_codegen_shared_boundary.py
```

Expected: collection fails because `codegen.security.credential_patterns` does not exist.

- [ ] **Step 3: Move the shared patterns out of the SOAR writer**

Create `src/codegen/security/credential_patterns.py` with the six existing regular expressions from `src/codegen/soar/smem_writer.py`, exported as an immutable tuple:

```python
"""Credential patterns shared by active persistent-memory writers."""
from __future__ import annotations

import re

CREDENTIAL_DENY_PATTERNS = (
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"C:\\\\[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"),
    re.compile(r"(?i)(password|secret|token)\s*[:=]\s*\S+"),
)
```

Change `secret_scrubber.py` to import `CREDENTIAL_DENY_PATTERNS` from this module and build `_ALL_PATTERNS` from it. Remove all `codegen.soar` imports and update the module comments to call the security module—not the SOAR writer—the canonical source.

- [ ] **Step 4: Add the post-deletion package boundary test**

Add this test to `tests/unit/test_codegen_shared_boundary.py`. It is expected to fail until Task 3 performs the deletion:

```python
from pathlib import Path


def test_codegen_package_contains_only_active_shared_utilities() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "codegen"
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert actual == {
        "memory/__init__.py",
        "memory/collision.py",
        "memory/context.py",
        "memory/kb_schema_validator.py",
        "memory/mempalace_reader.py",
        "memory/mempalace_writer.py",
        "security/__init__.py",
        "security/credential_patterns.py",
        "security/secret_scrubber.py",
    }
```

- [ ] **Step 5: Verify behavior while accepting the expected boundary failure**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_codegen_shared_boundary.py \
  tests/unit/test_spec_memory_miner.py \
  tests/unit/test_mempalace_collision.py \
  tests/unit/test_mempalace_context.py \
  tests/unit/test_mempalace_reader.py \
  tests/unit/test_mempalace_writer.py \
  tests/unit/test_kb_schema_validator.py
```

Expected: all existing behavior tests and the ownership test pass; only `test_codegen_package_contains_only_active_shared_utilities` fails and lists the execution files awaiting Task 3.

- [ ] **Step 6: Commit the independent security boundary**

```bash
git add src/codegen/security/credential_patterns.py \
  src/codegen/security/secret_scrubber.py \
  tests/unit/test_codegen_shared_boundary.py
git commit -m "refactor: decouple memory scrubbing from SOAR"
```

### Task 2: Remove user-facing and installer execution routes

**Files:**

- Modify: `scripts/install.sh`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/harness/skill_loader.py`
- Modify: `src/harness/strategy_loader.py`
- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_optional_codegen_install.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_strategy_loader.py`
- Modify: `tests/unit/test_run_intent.py`
- Delete: `tests/unit/test_soar_disabled.py`

**Interfaces:**

- Consumes: the existing Typer root command registry, default delivery strategy, and installer help contract.
- Produces: an installer with no SOAR option and a CLI with no `codegen` command or built-in codegen strategy knowledge.

- [ ] **Step 1: Update tests to describe the removed surface**

In `tests/unit/test_optional_codegen_install.py`:

- change installer usage assertions to `Usage: bash scripts/install.sh [--help]`;
- assert `--with-codegen`, `SOAR_VERSION`, `SOAR_DIR`, and `CODEGEN_LAUNCHER` are absent;
- replace the launcher-mode test with an assertion that no `codegen` launcher text exists;
- retain the unconditional MemPalace installation assertions.

In `tests/unit/test_cli_typer_app.py`, replace the codegen help test with:

```python
def test_retired_codegen_command_is_absent() -> None:
    result = runner.invoke(app, ["codegen", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output
```

Change delivery passthrough fixtures using the arbitrary strategy name `codegen` to `alternate`; those tests exercise argument forwarding, not SOAR behavior.

In `tests/unit/test_strategy_loader.py`, remove retirement-specific expectations and use `alternate` wherever a non-default strategy filename is required. In `tests/unit/test_run_intent.py`, likewise replace `strategies=codegen` with `strategies=alternate`.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_optional_codegen_install.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_strategy_loader.py \
  tests/unit/test_run_intent.py
```

Expected: failures identify the still-present installer option, CLI command, and SOAR-specific strategy checks.

- [ ] **Step 3: Remove the installer branch**

In `scripts/install.sh`:

- change usage to accept only `--help`;
- remove `WITH_CODEGEN`, `SOAR_VERSION`, `SOAR_DIR`, and `CODEGEN_LAUNCHER`;
- remove `_download_soar`, platform detection, SOAR PATH mutation, launcher creation, and codegen status output;
- retain venv installation, MemPalace setup, Node runtimes, Prosaic, and normal PATH setup unchanged.

- [ ] **Step 4: Remove the root CLI compatibility command**

In `src/echelon/cli.py`:

- remove `"codegen": "echelon.codegen"` from `SKILL_MAP`;
- remove `codegen` from `_skill_required_capability`;
- remove the `command == "codegen"` branch from `_dispatch_skill_command`;
- delete `_require_codegen_installation`.

In `src/echelon/cli_app.py`, delete the hidden `root_codegen` command. In `src/harness/skill_loader.py`, delete the `codegen` command mapping and its example.

- [ ] **Step 5: Remove SOAR-specific strategy knowledge**

In `src/harness/strategy_loader.py`, remove the retirement import, special strategy-name rejection, post-load command rejection, and SOAR examples. Preserve parsing of arbitrary custom strategy files.

In `src/harness/ralph.py`, remove `reject_soar_command(build_command)` and update docstrings that present `echelon codegen` as an example. No SOAR executable remains after Task 3, and custom strategy commands remain an explicit user-controlled facility.

- [ ] **Step 6: Remove the obsolete retirement-only test**

Delete `tests/unit/test_soar_disabled.py`; it tests code paths removed by this task and Task 3. Do not replace it with another fail-closed compatibility layer.

- [ ] **Step 7: Run the focused tests**

Run the Step 2 command again.

Expected: all tests pass.

- [ ] **Step 8: Commit the surface removal**

```bash
git add scripts/install.sh src/echelon/cli.py src/echelon/cli_app.py \
  src/harness/skill_loader.py src/harness/strategy_loader.py \
  src/harness/ralph.py tests/unit/test_optional_codegen_install.py \
  tests/unit/test_cli_typer_app.py tests/unit/test_strategy_loader.py \
  tests/unit/test_run_intent.py tests/unit/test_soar_disabled.py
git commit -m "refactor: remove retired SOAR entry points"
```

### Task 3: Delete the retired execution implementation and runtime prose

**Files:**

- Modify: `pyproject.toml`
- Delete: `src/codegen/analysis/`
- Delete: `src/codegen/anchor/`
- Delete: `src/codegen/audit/`
- Delete: `src/codegen/authoring/`
- Delete: `src/codegen/bridge/`
- Delete: `src/codegen/ci/`
- Delete: `src/codegen/cli/`
- Delete: `src/codegen/decompose/`
- Delete: `src/codegen/delivery/`
- Delete: `src/codegen/epmem/`
- Delete: `src/codegen/extract/`
- Delete: `src/codegen/greenfield/`
- Delete: `src/codegen/hooks/`
- Delete: `src/codegen/impasse/`
- Delete: `src/codegen/implement/`
- Delete: `src/codegen/library/`
- Delete: `src/codegen/lsp/`
- Delete: `src/codegen/metrics/`
- Delete: `src/codegen/pipeline/`
- Delete: `src/codegen/runner/`
- Delete: `src/codegen/schema/`
- Delete: `src/codegen/soar/`
- Delete: `src/codegen/testing/`
- Delete: `src/codegen/tests/`
- Delete: `src/codegen/retirement.py`
- Delete: `src/codegen/memory/config.py`
- Delete: `src/codegen/memory/pid_lock.py`
- Delete: `src/codegen/memory/repair.py`
- Delete: `src/codegen/memory/requirements_miner.py`
- Delete: `src/codegen/memory/run_index.py`
- Delete: `src/codegen/memory/smem_accumulator.py`
- Delete: `src/codegen/memory/smem_types.py`
- Delete: all `src/codegen/**/__pycache__/` directories if present in the working tree
- Delete: `prosaic/commands/echelon.codegen.md`
- Delete: `prosaic/commands/echelon.codegenlight.md`
- Delete: `runtime/workflow/phases/codegen-A-preamble.md`
- Delete: `runtime/workflow/phases/codegen-0-preflight.md`
- Delete: `runtime/workflow/phases/codegen-1-re.md`
- Delete: `runtime/workflow/phases/codegen-2-decompose.md`
- Delete: `runtime/workflow/phases/codegen-3-implement.md`
- Delete: `runtime/workflow/phases/codegen-4-gate.md`
- Delete: `runtime/workflow/phases/codegen-5-impasse.md`
- Delete: `runtime/workflow/phases/codegen-6-test.md`
- Delete: `runtime/workflow/phases/codegen-6b-security.md`
- Delete: `runtime/workflow/phases/codegen-6c-runnable.md`
- Delete: `runtime/workflow/phases/codegen-7-deliver.md`
- Delete: `runtime/workflow/phases/codegen-resume.md`
- Delete: `runtime/workflow/phases/codegenlight-0-preflight.md`
- Delete: `runtime/workflow/phases/codegenlight-1-re.md`
- Delete: `runtime/workflow/phases/codegenlight-7-deliver.md`
- Delete: `runtime/workflow/phases/codegenlight-resume.md`
- Delete: `tests/e2e/test_mempalace_e2e.py`
- Delete: `tests/unit/test_codegen_cli_wing.py`
- Delete: `tests/unit/test_compose_task.py`
- Delete: `tests/unit/test_element_ids.py`
- Delete: `tests/unit/test_pipeline_engine_wing.py`
- Delete: `tests/unit/test_runnable_contract.py`
- Delete: `tests/unit/test_runnable_gate.py`
- Delete: `tests/unit/test_runnable_gate_integration.py`
- Delete: `tests/unit/test_soar_seed_rules.py`
- Delete: `tests/unit/test_verification_manifest.py`

**Interfaces:**

- Consumes: the retained boundary fixed by Task 1.
- Produces: a `src/codegen` tree containing exactly the nine allowlisted active utility files.

- [ ] **Step 1: Delete execution packages, prompts, phases, and execution-only tests**

Use `git rm -r` for the exact tracked directories and files above. Remove ignored `__pycache__` directories separately without staging them. Do not remove the five retained memory modules, their package initializer, or the three retained security files.

- [ ] **Step 2: Remove retired package assets**

Delete this stanza from `pyproject.toml`:

```toml
"codegen" = ["soar/*.soar", "library/packs/**/*.yaml"]
```

Keep package discovery unchanged because `codegen.memory` and `codegen.security` remain installed shared utilities.

- [ ] **Step 3: Run the boundary test**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_codegen_shared_boundary.py
```

Expected: both tests pass and the exact retained-file set matches.

- [ ] **Step 4: Prove no active production import targets a deleted package**

Run:

```bash
rg -n 'from (src\.)?codegen|import (src\.)?codegen' src/echelon src/harness src/kernel
```

Expected: every result names only `codegen.memory.*` or `codegen.security.secret_scrubber`; there are no `codegen.retirement`, execution, pipeline, schema, runner, bridge, or SOAR imports.

- [ ] **Step 5: Run retained utility tests**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_codegen_shared_boundary.py \
  tests/unit/test_spec_memory_miner.py \
  tests/unit/test_mempalace_collision.py \
  tests/unit/test_mempalace_context.py \
  tests/unit/test_mempalace_reader.py \
  tests/unit/test_mempalace_writer.py \
  tests/unit/test_kb_schema_validator.py \
  tests/unit/test_kb_proposal_templates.py \
  tests/integration/test_mempalace_mine_search.py \
  tests/integration/test_squad_context_memory.py
```

Expected: all pass.

- [ ] **Step 6: Commit the implementation deletion**

```bash
git add -A src/codegen prosaic/commands runtime/workflow/phases tests pyproject.toml
git commit -m "refactor: delete retired SOAR execution"
```

### Task 4: Remove active documentation and test-suite references

**Files:**

- Modify: `README.md`
- Modify: `INSTALLATION.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/pipeline-matrix.md`
- Delete: `docs/soar-delivery.md`
- Modify: `runtime/workflow/phases/bugfix-5-finalize.md`
- Modify: `tests/kernel/test_prompt_references.py`
- Modify: `tests/unit/test_gitops_worktree.py`
- Modify: `tests/unit/test_runtime_config_resolver.py`
- Modify: `tests/unit/test_prosaic_runtime_state_paths.py`

**Interfaces:**

- Consumes: the supported CLI and delivery surface after Tasks 2–3.
- Produces: current operator documentation and static tests that describe only supported behavior. Historical documents under `docs/superpowers`, `docs/findings`, `specs`, and old changelog entries remain untouched.

- [ ] **Step 1: Update current operator documentation**

In `README.md`, `INSTALLATION.md`, `AGENTS.md`, and `CLAUDE.md`:

- remove the disabled codegen command and strategy rows;
- remove `--with-codegen`, SOAR download/removal, launcher, and troubleshooting instructions;
- describe `src/codegen/memory` and `src/codegen/security` as retained shared utility namespaces, not a pipeline;
- remove codegen/codegenlight from active command-wrapper lists;
- state that default delivery is the only supported delivery strategy.

Remove the retired row from `docs/pipeline-matrix.md` and delete `docs/soar-delivery.md`.

- [ ] **Step 2: Remove current runtime guidance that recommends codegen**

Delete the Codegen alternative from `runtime/workflow/phases/bugfix-5-finalize.md`. The finalization prompt must recommend only the supported default delivery command.

- [ ] **Step 3: Update static tests that enumerate the retired surface**

- Remove the codegen prompt assertion from `tests/kernel/test_prompt_references.py`.
- Remove codegen phase filenames from `tests/unit/test_gitops_worktree.py`; retain the assertion that target runtime sync excludes Phase A-only content.
- Remove the deleted phase fixture from `tests/unit/test_runtime_config_resolver.py`.
- Keep the `src/codegen/memory/context.py` state-path assertion in `tests/unit/test_prosaic_runtime_state_paths.py`, but rename any test or comment that calls it a pipeline surface.

- [ ] **Step 4: Check current-surface references**

Run:

```bash
rg -n -i '\bsoar\b|echelon[ .]codegen|codegenlight|--with-codegen' \
  README.md INSTALLATION.md AGENTS.md CLAUDE.md src runtime prosaic scripts \
  tests/kernel tests/unit tests/integration \
  --glob '!src/codegen/memory/**' \
  --glob '!src/codegen/security/**'
```

Expected: no active execution, command, installer, or runtime-prose reference remains. References inside historical `docs/superpowers`, `docs/findings`, `specs`, and `CHANGELOG.md` are intentionally outside this check.

- [ ] **Step 5: Run documentation and static-contract tests**

```bash
.venv/bin/python -m pytest -q \
  tests/kernel/test_prompt_references.py \
  tests/unit/test_gitops_worktree.py \
  tests/unit/test_runtime_config_resolver.py \
  tests/unit/test_prosaic_runtime_state_paths.py \
  tests/unit/test_polyrepo_target_docs.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_optional_codegen_install.py
```

Expected: all pass.

- [ ] **Step 6: Commit the supported-surface documentation**

```bash
git add README.md INSTALLATION.md AGENTS.md CLAUDE.md docs/pipeline-matrix.md \
  docs/soar-delivery.md runtime/workflow/phases/bugfix-5-finalize.md \
  tests/kernel/test_prompt_references.py tests/unit/test_gitops_worktree.py \
  tests/unit/test_runtime_config_resolver.py \
  tests/unit/test_prosaic_runtime_state_paths.py
git commit -m "docs: remove retired SOAR workflow guidance"
```

### Task 5: Verify S1 and close the tracker milestone

**Files:**

- Modify: `docs/simplification-control.md`

**Interfaces:**

- Consumes: Tasks 1–4 and their commits.
- Produces: recorded verification evidence, S1=`DONE`, and S2=`ACTIVE` only after every exit check succeeds.

- [ ] **Step 1: Run the complete focused S1 suite**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_codegen_shared_boundary.py \
  tests/unit/test_spec_memory_miner.py \
  tests/unit/test_mempalace_collision.py \
  tests/unit/test_mempalace_context.py \
  tests/unit/test_mempalace_reader.py \
  tests/unit/test_mempalace_writer.py \
  tests/unit/test_kb_schema_validator.py \
  tests/unit/test_kb_proposal_templates.py \
  tests/unit/test_squad_completion.py \
  tests/unit/test_coordinator.py \
  tests/unit/test_strategy_loader.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_optional_codegen_install.py \
  tests/integration/test_mempalace_mine_search.py \
  tests/integration/test_squad_context_memory.py
```

Expected: all pass.

- [ ] **Step 2: Run merge verification from the control baseline**

```bash
.venv/bin/python scripts/merge_verification.py plan --base 51dbfdc0
.venv/bin/python scripts/merge_verification.py run --base 51dbfdc0
```

Expected: the selected verification plan completes successfully and writes a receipt under `tests/reports/merge-verification/`.

- [ ] **Step 3: Record quantitative deletion evidence**

Run:

```bash
git diff --stat 51dbfdc0..HEAD
find src/codegen -type f -not -path '*/__pycache__/*' | sort
```

Record the deleted file/line totals, exact nine-file retained tree, focused test count, and merge-verification receipt in `docs/simplification-control.md`.

- [ ] **Step 4: Close S1 and activate S2**

In `docs/simplification-control.md`:

- mark every S1 checklist row complete;
- set S1 to `DONE` only if Steps 1–3 succeeded;
- set S2 to `ACTIVE` and change `Current milestone` to S2;
- add a dated evidence-log row with commands, counts, and receipt path.

If verification fails, leave S1 `ACTIVE` or mark it `BLOCKED`; do not activate S2.

- [ ] **Step 5: Commit the verified milestone transition**

```bash
git add docs/simplification-control.md
git commit -m "docs: close SOAR removal milestone"
```

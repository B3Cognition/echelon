# Optional SOAR and Codegen Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SOAR and the usable codegen pipeline opt-in through `scripts/install.sh --with-codegen`, while retaining MemPalace for all installations.

**Architecture:** The Python package keeps codegen implementation and MemPalace integration, but no longer publishes an unconditional `codegen` console script. The installer parses a deterministic opt-in flag, installs core dependencies and warms MemPalace in both modes, and conditionally installs SOAR plus an installer-owned launcher. The `echelon codegen` entry path treats the sibling launcher as the installation capability marker and fails before dispatch when absent.

**Tech Stack:** Bash, Python 3.11+, setuptools `pyproject.toml`, pytest.

## Global Constraints

- Plain `bash scripts/install.sh` must not download SOAR, change PATH for SOAR, or leave `~/.echelon/venv/bin/codegen` installed.
- `bash scripts/install.sh --with-codegen` must retain the pinned SOAR 9.6.4 behavior and expose `codegen`.
- MemPalace remains a base dependency and its shared memory/model warm-up runs in both modes.
- Default reinstall removes no SOAR binaries, MemPalace data, caches, or user state.
- The installer is non-interactive; unknown arguments fail before mutation and `--help` is read-only.
- Preserve unrelated worktree changes.

---

### Task 1: Installer mode contract

**Files:**
- Create: `tests/unit/test_optional_codegen_install.py`
- Modify: `scripts/install.sh`

**Interfaces:**
- Produces: `bash scripts/install.sh [--with-codegen|--help]`; `WITH_CODEGEN` internal mode; `~/.echelon/venv/bin/codegen` capability marker.

- [ ] **Step 1: Write failing static contract tests**

Add tests that read `scripts/install.sh` and assert it recognizes `--with-codegen` and `--help`, rejects unknown arguments before the `uv` check, keeps memory setup and warm-up outside the opt-in block, gates `_download_soar` and SOAR PATH mutation, creates a launcher containing `from codegen.cli.codegen_cli import main`, removes that launcher in default mode, and emits the exact opt-in command in the default summary.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/unit/test_optional_codegen_install.py -q`

Expected: failures because the installer has no argument parser or conditional launcher behavior.

- [ ] **Step 3: Implement early argument parsing**

At the top of `scripts/install.sh`, add a `_usage` function and a `case` loop accepting only no arguments, `--with-codegen`, and `--help`. Set `WITH_CODEGEN=1` only for the opt-in form. Exit `2` on unknown arguments before checking `uv`, platform, or creating directories.

- [ ] **Step 4: Gate SOAR and manage the launcher**

Move platform detection, SOAR download, and SOAR PATH mutation into `if [ "$WITH_CODEGEN" = "1" ]`. Remove the unconditional codegen entry point from packaging in Task 2. After installing the editable project, create `~/.echelon/venv/bin/codegen` as a Python shebang launcher only in opt-in mode; otherwise remove that exact venv-owned path. Keep memory creation and model warm-up unconditional. Make completion output state `not installed (rerun with --with-codegen)` in default mode.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_optional_codegen_install.py -q`

Expected: all tests pass.

### Task 2: Packaging and CLI availability gate

**Files:**
- Modify: `tests/unit/test_optional_codegen_install.py`
- Modify: `pyproject.toml`
- Modify: `src/echelon/cli.py`

**Interfaces:**
- Consumes: sibling launcher at `Path(sys.executable).with_name("codegen")` as the opt-in capability marker.
- Produces: `_require_codegen_installation() -> None`, exiting with status 2 and the command `bash scripts/install.sh --with-codegen` when unavailable.

- [ ] **Step 1: Write failing packaging and CLI tests**

Add tests parsing `pyproject.toml` with `tomllib` to assert `mempalace` remains in base `project.dependencies` and `project.scripts` has no `codegen`. Add a CLI unit test that monkeypatches `sys.executable` to an isolated venv path, calls `_require_codegen_installation()`, and asserts `SystemExit(2)` plus the exact opt-in instruction; add the passing case with an executable sibling launcher.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/test_optional_codegen_install.py -q`

Expected: packaging test finds the unconditional entry point and the helper is absent.

- [ ] **Step 3: Implement packaging and dispatch guard**

Delete only `codegen = "codegen.cli.codegen_cli:main"` from `[project.scripts]`. Add `_require_codegen_installation()` near CLI dispatch helpers. Call it before handling the `codegen` skill command, so both direct `echelon codegen` and harness `strategy=codegen` fail before LLM dispatch when the installer-owned sibling launcher is absent.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_optional_codegen_install.py tests/unit/test_cli_delivery.py tests/unit/test_cli_typer_app.py -q`

Expected: all selected tests pass.

### Task 3: User-facing installation documentation

**Files:**
- Modify: `tests/unit/test_optional_codegen_install.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `scripts/install.sh`

**Interfaces:**
- Produces: one canonical opt-in command, `bash scripts/install.sh --with-codegen`, across installer help and documentation.

- [ ] **Step 1: Write failing documentation assertions**

Add focused assertions that the README installation section describes the default three-tool/core installation, documents `--with-codegen`, and no longer states that SOAR and codegen are bundled unconditionally. Assert repository guidance no longer says the installer reinstalls four CLIs.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/test_optional_codegen_install.py -q`

Expected: documentation assertions fail on existing unconditional-install wording.

- [ ] **Step 3: Update documentation and installer labels**

Revise the README quick start, CLI table, maintenance command, SOAR/codegen section, and installation inventory. Update AGENTS.md and CLAUDE.md install guidance to distinguish core and opt-in installs. Ensure the installer header and summary do not claim all four CLIs in default mode.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_optional_codegen_install.py -q`

Expected: all tests pass.

### Task 4: Regression verification

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: completed installer, packaging, CLI, and documentation changes.
- Produces: fresh verification evidence.

- [ ] **Step 1: Run shell syntax and focused tests**

Run: `bash -n scripts/install.sh && pytest tests/unit/test_optional_codegen_install.py tests/unit/test_cli_delivery.py tests/unit/test_cli_typer_app.py tests/integration/test_squad_context_memory.py tests/integration/test_squad_context_generation.py -q`

Expected: shell syntax succeeds and all selected tests pass.

- [ ] **Step 2: Run broader unit regression suite**

Run: `pytest -m unit -q`

Expected: all unit tests pass. If unrelated pre-existing failures occur, record their exact tests and output without modifying unrelated user work.

- [ ] **Step 3: Inspect scope and contract**

Run: `git diff --check && git diff -- scripts/install.sh pyproject.toml src/echelon/cli.py README.md AGENTS.md CLAUDE.md tests/unit/test_optional_codegen_install.py`

Expected: no whitespace errors; diff contains only the approved optional-install behavior in the named files.

- [ ] **Step 4: Commit implementation files**

Stage only the plan-owned files and commit with `feat: make codegen installation optional`. Do not stage unrelated modified or untracked files.

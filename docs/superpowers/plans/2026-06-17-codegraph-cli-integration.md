# CodeGraph CLI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer upstream `codegraph` CLI evidence when available, keep the vendored bridge fallback, and add optional installer support without MCP setup.

**Architecture:** `src/harness/codegraph_evidence.py` owns provider selection and artifact generation. The upstream CLI provider writes Echelon's existing analysis JSON contract through `codegraph export --format echelon --output <path>` when that command exists; otherwise it records failure and falls back to the vendored bridge. `scripts/install.sh` remains deterministic and only installs upstream CodeGraph CLI when `ECHELON_INSTALL_CODEGRAPH_CLI=1` is set.

**Tech Stack:** Python 3.11, pytest, Bash installer, Node/npm for optional upstream CLI and existing vendored bridge.

---

### Task 1: CLI Provider Preference And Fallback

**Files:**
- Modify: `src/harness/codegraph_evidence.py`
- Test: `tests/unit/test_harness_main_codegraph_evidence.py`

- [x] **Step 1: Write the failing tests**

Add tests that create fake `codegraph`, `node`, and bridge executables in a temporary `PATH`. Cover CLI success, CLI failure with bridge fallback, and total failure writing `codegraph-error.txt`.

```python
def test_write_codegraph_evidence_prefers_codegraph_cli_when_available(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_codegraph_cli(tmp_path / "bin", success=True)
    _write_fake_bridge(project_root)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(["write-codegraph-evidence", str(project_root), str(verify_run_dir), str(spec_dir)])

    assert result.returncode == 0, result.stderr
    analysis = json.loads((verify_run_dir / "codegraph-analysis.json").read_text())
    assert analysis["provider"] == "codegraph-cli"
    assert not (verify_run_dir / "codegraph-error.txt").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/unit/test_harness_main_codegraph_evidence.py -q
```

Observed: FAIL because production code ignored the CLI provider.

- [x] **Step 3: Write minimal implementation**

Add provider helpers in `src/harness/codegraph_evidence.py`:

```python
def _run_codegraph_cli(codegraph: str, project_root: Path, analysis_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            codegraph,
            "export",
            "--format",
            "echelon",
            "--path",
            str(project_root),
            "--output",
            str(analysis_path),
        ],
        cwd=str(project_root),
        text=True,
        capture_output=True,
        check=False,
    )
```

Call this before the vendored bridge when `shutil.which("codegraph")` returns a path. Validate that the command exits 0 and writes usable JSON; otherwise capture diagnostics and try the bridge.

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/unit/test_harness_main_codegraph_evidence.py -q
```

Observed: PASS, `5 passed`.

### Task 2: Installer Optional Upstream CLI Support

**Files:**
- Modify: `scripts/install.sh`
- Test: `tests/kernel/test_codegraph_integration_contract.py`

- [x] **Step 1: Write the failing contract tests**

Add tests asserting that the installer checks for `ECHELON_INSTALL_CODEGRAPH_CLI`, installs `@colbymchenry/codegraph` only behind that flag, and never calls `codegraph install`.

```python
def test_install_script_supports_optional_codegraph_cli_without_mcp_install():
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert "ECHELON_INSTALL_CODEGRAPH_CLI" in install_script
    assert "@colbymchenry/codegraph" in install_script
    assert "codegraph install" not in install_script
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/kernel/test_codegraph_integration_contract.py -q
```

Observed: FAIL because installer support was absent.

- [x] **Step 3: Write minimal implementation**

Add a section after vendored bridge dependency install:

```bash
echo "▶ Checking upstream CodeGraph CLI..."
if command -v codegraph &>/dev/null; then
  CODEGRAPH_CLI_VER="$(codegraph version 2>/dev/null || codegraph --version 2>/dev/null || echo "installed")"
  echo "  ✓ CodeGraph CLI found ($CODEGRAPH_CLI_VER)"
elif [ "${ECHELON_INSTALL_CODEGRAPH_CLI:-0}" = "1" ]; then
  if command -v npm &>/dev/null; then
    npm install -g @colbymchenry/codegraph --silent
    echo "  ✓ CodeGraph CLI installed"
  else
    echo "  ⚠ npm not found; cannot install CodeGraph CLI."
  fi
else
  echo "  ℹ CodeGraph CLI not found; optional install:"
  echo "    ECHELON_INSTALL_CODEGRAPH_CLI=1 bash scripts/install.sh"
fi
```

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/kernel/test_codegraph_integration_contract.py -q
```

Observed: PASS, `9 passed`.

### Task 3: Verification And Commit

**Files:**
- Verify: `src/harness/codegraph_evidence.py`
- Verify: `scripts/install.sh`
- Verify: CodeGraph tests

- [x] **Step 1: Run focused test suite**

Run:

```bash
python -m pytest tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_codegraph_evidence_mapper.py tests/unit/test_verify_spec_codegraph_prompt.py
```

Observed: PASS, `25 passed`.

- [x] **Step 2: Inspect git diff**

Run:

```bash
git diff -- src/harness/codegraph_evidence.py scripts/install.sh tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py docs/superpowers/plans/2026-06-17-codegraph-cli-integration.md
```

Observed: only planned files changed.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add src/harness/codegraph_evidence.py scripts/install.sh tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py docs/superpowers/plans/2026-06-17-codegraph-cli-integration.md
git commit -m "feat: prefer codegraph cli evidence provider"
```

# Container CLI Podman Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `echelon harness init` and subsequent harness sandbox operations use Podman via `ECHELON_CONTAINER_CLI=podman`, then persist `harness.container_cli: podman` in config.

**Architecture:** Keep the existing `docker` provider name for compatibility, but add a separate `container_cli` setting that controls which Docker-compatible CLI binary is executed. Init resolves the CLI from `ECHELON_CONTAINER_CLI` or defaults to Docker, verifies it with `<cli> info`, writes the selected CLI to `echelon-config.yml`, and run/resume paths pass the configured CLI into `DockerWorktreeProvider`.

**Tech Stack:** Python dataclasses/config parsing, subprocess CLI invocation, pytest with mocks.

---

### Task 1: Config Field

**Files:**
- Modify: `src/harness/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
def test_container_cli_defaults_to_docker() -> None:
    config = _parse_config(MINIMAL)
    assert config.container_cli == "docker"


def test_container_cli_accepts_podman() -> None:
    config = _parse_config({**MINIMAL, "container_cli": "podman"})
    assert config.container_cli == "podman"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/unit/test_config.py::TestParseConfigValid::test_container_cli_defaults_to_docker tests/unit/test_config.py::TestParseConfigValid::test_container_cli_accepts_podman -q`
Expected: FAIL because `HarnessConfig` has no `container_cli`.

- [ ] **Step 3: Write minimal implementation**

Add `container_cli: str = "docker"` to `HarnessConfig`, validate `docker|podman`, and parse `data.get("container_cli", "docker")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/unit/test_config.py::TestParseConfigValid::test_container_cli_defaults_to_docker tests/unit/test_config.py::TestParseConfigValid::test_container_cli_accepts_podman -q`
Expected: PASS.

### Task 2: Init Resolution And Persistence

**Files:**
- Modify: `src/harness/init.py`
- Test: `tests/unit/test_init.py`

- [ ] **Step 1: Write the failing test**

```python
def test_init_persists_container_cli_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHELON_CONTAINER_CLI", "podman")
    # existing init fixture setup
    config = init_harness(str(tmp_path), base_dir=str(tmp_path))
    raw = yaml.safe_load((tmp_path / ".specify/extensions/echelon/echelon-config.yml").read_text())
    assert config.container_cli == "podman"
    assert raw["harness"]["container_cli"] == "podman"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/unit/test_init.py::test_init_persists_container_cli_from_env -q`
Expected: FAIL because init ignores `ECHELON_CONTAINER_CLI`.

- [ ] **Step 3: Write minimal implementation**

Resolve `ECHELON_CONTAINER_CLI`, validate it, use `<cli> info` in the health check, and include `container_cli` in `HarnessConfig` and `harness_data`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/unit/test_init.py::test_init_persists_container_cli_from_env -q`
Expected: PASS.

### Task 3: Provider Command Selection

**Files:**
- Modify: `src/harness/docker_provider.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/integration/test_docker_provider.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_docker_uses_configured_container_cli() -> None:
    with patch("harness.docker_provider.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_docker(["info"], cli="podman")
    assert run.call_args.args[0] == ["podman", "info"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/integration/test_docker_provider.py::TestDockerProviderInit::test_run_docker_uses_configured_container_cli -q`
Expected: FAIL because `_run_docker` always uses `docker`.

- [ ] **Step 3: Write minimal implementation**

Add a `container_cli` constructor parameter to `DockerWorktreeProvider`, store it, and route all `_run_docker` helper calls and direct subprocess calls through it. Update CLI run/resume/status construction to pass `config.container_cli`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/integration/test_docker_provider.py::TestDockerProviderInit::test_run_docker_uses_configured_container_cli -q`
Expected: PASS.

### Task 4: Focused Regression

**Files:**
- No source edits unless tests reveal a missed call site.

- [ ] **Step 1: Run focused test set**

Run: `PYTHONPATH=src pytest tests/unit/test_config.py tests/unit/test_init.py tests/integration/test_docker_provider.py -q`
Expected: PASS, with Docker-marked tests skipped if no daemon is available.

- [ ] **Step 2: Inspect changed files**

Run: `git diff -- src/harness/config.py src/harness/init.py src/harness/docker_provider.py src/echelon/cli.py tests/unit/test_config.py tests/unit/test_init.py tests/integration/test_docker_provider.py`
Expected: Changes are limited to container CLI selection and tests.
